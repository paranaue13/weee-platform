"""Consolidated, version-agnostic regression checks.

This file replaces a long tail of per-build test files that pinned an exact
version string (e.g. `assert c.get('/health').json()['version']=='2.5.31'`)
alongside otherwise-real functional assertions. The version pins guaranteed
the file would go red on every subsequent release; the checks below keep the
underlying behavioral/business-rule assertions (folded in from those files)
without re-introducing a version pin.

Sources for the "mandatory historical checks" section: docs/TESTING_AND_RELEASE.md
and docs/BUSINESS_RULES.md (handoff_docs/).
"""
from pathlib import Path
from fastapi.testclient import TestClient
from app.main import app

ROOT = Path(__file__).resolve().parents[1]


def auth(c):
    r = c.post('/auth/token', json={'username': 'admin', 'password': 'testpass'})
    assert r.status_code == 200, r.text
    return {'Authorization': 'Bearer ' + r.json()['access_token']}


# ---- Receipts / sorting historical counts (TESTING_AND_RELEASE.md) ----
def test_mandatory_receipts_and_sorting_counts():
    with TestClient(app) as c:
        h = auth(c)
        receipts = c.get('/receipts', headers=h).json()
        sorting = c.get('/sorting/review-queue', headers=h).json()
        assert len(receipts) == 1077
        assert len(sorting) == 1077
        assert sum(1 for x in receipts if x['receipt_date'].startswith('2026-08')) == 65
        assert sum(1 for x in sorting if x['receipt_date'].startswith('2026-08')) == 65
        assert max(x['receipt_date'] for x in receipts)[:10] == '2026-08-31'


# ---- Production historical totals (TESTING_AND_RELEASE.md / BUSINESS_RULES.md #3) ----
def test_mandatory_august_production_totals():
    with TestClient(app) as c:
        h = auth(c)
        prod = c.get('/production/work-entries', headers=h, params={'start': '2026-08-01', 'end': '2026-08-31'}).json()
        assert prod and any(x['supplier_group'] == 'HERMES' for x in prod)
        groups = {}
        for x in prod:
            groups[x['supplier_group']] = groups.get(x['supplier_group'], 0) + float(x['weight_kg'])
        # Negative corrections always reduce OTHER, never HERMES (BUSINESS_RULES.md #3).
        assert all(not (float(x['weight_kg']) < 0 and x['supplier_group'] == 'HERMES') for x in prod)
        assert round(sum(groups.values())) == 130442
        assert round(groups['HERMES']) == 7134
        assert round(groups['OTHER']) == 123308
        assert c.get('/sorting/month-report', headers=h, params={'month': '2026-08'}).status_code == 200


# ---- Warehouse arithmetic (BUSINESS_RULES.md #2, TESTING_AND_RELEASE.md) ----
def test_mandatory_warehouse_no_negative_stock():
    with TestClient(app) as c:
        h = auth(c)
        d = c.get('/inventory/weee-dashboard', headers=h, params={'month': '2026-08'}).json()
        assert d['kpis']['processed_month'] == 130442.0
        assert d['kpis']['inferred_carry_in'] >= 0
        # Internal-subcategory rows intentionally report no individual balance (None,
        # shown as '-') once stock is pooled per official family -- see
        # test_mandatory_warehouse_family_level_carry_in below. Only rows that do
        # carry a balance must never be negative.
        rows = d['to_process'] + d['to_ship']
        assert all(float(x['current_stock']) >= -1e-6 for x in rows if x['current_stock'] is not None)


# ---- Warehouse stock pooled per official family, not per internal subcategory ----
# Regression for the 2.5.34 "negative WEEE stock" bug: historical receipts/sorting
# classified electronics only at the official parent code (e.g. 6Α0000), while
# historical production consumed the finer internal company subcategories of that
# same code (INT-6A-TELCO, INT-6A-PRINT, ...). Treated as independent per-category
# ledgers this inflated `inferred_carry_in` to ~281,732 kg system-wide. Pooling the
# stock balance per family (official code + its internal subcategories) instead of
# per individual code should collapse most of that -- see KNOWN_ISSUES_AND_NEXT_WORK.md.
def test_mandatory_warehouse_family_level_carry_in():
    with TestClient(app) as c:
        h = auth(c)
        d = c.get('/inventory/weee-dashboard', headers=h, params={'month': '2026-01'}).json()
        rows = {x['internal_code']: x for x in d['to_process'] + d['to_ship']}
        # Internal-subcategory rows no longer carry an individual stock balance --
        # the family total lives on the official parent row instead.
        for code in ('INT-6A-TELCO', 'INT-6A-PRINT', 'INT-6A-PCSERVER', 'INT-4L-COPY', 'INT-5D-AV'):
            assert rows[code]['previous_stock'] is None
            assert rows[code]['current_stock'] is None
        # Their own period classification/production figures stay real and unpooled.
        assert rows['INT-6A-TELCO']['processed_period'] > 0
        # The pooled carry-in requirement should be far below the pre-fix ~281,732 kg
        # (the mismatch between the two largest families alone was ~215,000 kg).
        assert d['kpis']['inferred_carry_in'] < 150000


# ---- Warehouse opening stock is the documented 31/12/2025 physical count, not a
# guess (BUSINESS_RULES.md #2: "do not fabricate a prior stock value"). The
# family-level fix above collapsed the *code-mismatch* portion of the carry-in;
# this checks the *real inventory* portion: previous_stock for January must be
# grounded in the user-supplied count (app/data/opening_stock_2025_12_31.json),
# and any remaining shortfall must be reported separately (opening_stock_gap),
# never silently absorbed into the same number.
def test_mandatory_warehouse_opening_stock_is_documented_not_guessed():
    with TestClient(app) as c:
        h = auth(c)
        d = c.get('/inventory/weee-dashboard', headers=h, params={'month': '2026-01'}).json()
        k = d['kpis']
        # Documented total matches the supplied sheet (49,103 + 5,558 kg, mapped codes).
        assert round(k['opening_stock_documented_total']) == 54657
        # Remaining gap (recorded 2026 consumption the documented count doesn't
        # explain) shrank sharply once real data replaced the inferred minimum,
        # but a genuine residual is expected and must stay visible, not hidden.
        assert 0 < k['opening_stock_gap_total'] < 25000
        # Per explicit user direction (Σεπτέμβριος 2026 session), the gap no longer pads
        # carry_in/previous_stock -- that silently kept current_stock from ever going negative,
        # which doesn't match the company's own real ledger (its "Απόθεμα Τρέχον" column is allowed
        # to go negative, e.g. when processing draws down more than was ever documented/received).
        # inferred_carry_in is now just the documented total; the gap stays a separate diagnostic
        # and any real shortfall shows up directly as a negative current_stock instead.
        assert round(k['inferred_carry_in']) == round(k['opening_stock_documented_total'])
        rows = {x['internal_code']: x for x in d['to_process'] + d['to_ship']}
        # A code with a large documented count (real physical stock) should use it directly.
        assert rows['5Α0000']['opening_stock_documented'] == 6221.0
        # 1Β1210 was blank on the supplied sheet (no documented count) yet 2026
        # production consumed ~10,850 kg under it -- must surface as a gap, not
        # get silently folded into a bigger "previous_stock" number.
        assert rows['1Β1210']['opening_stock_documented'] == 0.0
        assert rows['1Β1210']['opening_stock_gap'] > 10000


# ---- Production hierarchy (BUSINESS_RULES.md #4) ----
def test_mandatory_production_hierarchy_and_category1_label():
    with TestClient(app) as c:
        h = auth(c)
        disp = c.get('/master/weee-display', headers=h, params={'include_inactive': 'true'}).json()
        assert any(x.get('is_internal_subcategory') and x.get('parent_code') == '4Δ0000' for x in disp)
        # Expand/collapse of the hierarchy in the UI must not change the reported total.
        prod = c.get('/production/work-entries', headers=h, params={'start': '2026-08-01', 'end': '2026-08-31'}).json()
        assert round(sum(float(x['weight_kg']) for x in prod)) == 130442
        # Major-group 1 display label is frontend-only (no backend row uses bare code "1").
        html = c.get('/desktop').text
        assert "'1':'Κλιματιστικά'" in html


# ---- Materials canonical profile / active + precious rules (BUSINESS_RULES.md #6) ----
def test_mandatory_materials_active_and_precious_rules():
    with TestClient(app) as c:
        h = auth(c)
        mats = c.get('/master/materials', headers=h, params={'include_inactive': 'true'}).json()
        active = [m for m in mats if m['active']]
        assert active and all((m.get('galaxy_code') or '').strip() for m in active)
        assert any(m['is_precious'] and float(m['export_step_kg']) == 0.05 for m in active)
        assert any((not m['is_precious']) and float(m['export_step_kg']) == 0.5 for m in active)
        # A material without an ERP code is created inactive and can't be force-activated.
        r = c.post('/master/materials', headers=h, json={'internal_code': 'NOERP-MANDATORY', 'internal_name': 'Χωρίς ERP'})
        assert r.status_code == 200 and r.json()['active'] is False
        assert c.post(f"/master/materials/{r.json()['id']}/activate", headers=h).status_code == 409


# ---- Legacy medium types must not silently come back (BUSINESS_RULES.md #8, seed.py) ----
def test_mandatory_legacy_medium_types_stay_inactive():
    with TestClient(app) as c:
        h = auth(c)
        active_codes = {x['code'] for x in c.get('/master/medium-types', headers=h).json()}
        assert 'METAL_BASKET' not in active_codes
        assert 'BIG_BAG' not in active_codes
        assert 'SACK_2KG' not in active_codes  # legacy duplicate of SACK_2KG_UN


# ---- Build 1.6 mistaken WEEE-category rows must stay hidden (seed.py comment / regression) ----
def test_mandatory_legacy_bulk_categories_stay_inactive():
    with TestClient(app) as c:
        h = auth(c)
        cats = c.get('/master/weee-categories', headers=h).json()  # endpoint always returns all rows, active or not
        for legacy in ('INT-BULK-FRIDGE', 'INT-BULK-FREEZER'):
            row = next((x for x in cats if x['code'] == legacy), None)
            assert row is None or row['active'] is False


# ---- Container registry (README / DATA_AND_IMPORTS.md) ----
def test_mandatory_reference_registry_counts():
    root = ROOT
    import json
    ctr = json.loads((root / 'app/data/container_registry.json').read_text(encoding='utf-8'))
    i2 = json.loads((root / 'app/data/infocycle2_registry.json').read_text(encoding='utf-8'))
    assert len(ctr) == 595
    assert len(i2) == 372
    assert all(x['type'] == 'Καλάθι Infocycle 2' for x in i2)


# ---- Release packaging (PROJECT_HANDOFF.md #4) ----
def test_mandatory_launcher_does_not_depend_on_activate_bat():
    start = (root_project() / 'START_WEEE_PLATFORM.cmd').read_text(encoding='utf-8')
    assert 'activate.bat' not in start
    assert '".venv\\Scripts\\python.exe" -m uvicorn' in start
    assert 'if not exist ".venv\\Scripts\\python.exe"' in start


def root_project() -> Path:
    return ROOT.parent


# ---- Registry first-click regression (KNOWN_ISSUES_AND_NEXT_WORK.md #7) ----
def test_mandatory_registry_tab_state_is_not_reset_on_first_click():
    with TestClient(app) as c:
        html = c.get('/desktop').text
    # The 2.5.35 fix: initial master-tab render no longer races a duplicate
    # navigation loader that used to snap the UI back to the first subtab.
    assert 'duplicate master nav loader removed' in html
    assert 'masterTab(currentMasterTab);requestAnimationFrame' in html


# ---- Tab performance / caching (KNOWN_ISSUES_AND_NEXT_WORK.md #6) ----
def test_mandatory_get_cache_present():
    with TestClient(app) as c:
        html = c.get('/desktop').text
    assert 'API_CACHE_MS=30000' in html
    # The "τεκμαρτό αρχικό απόθεμα" note (warehouseCarryNote) was removed per explicit user
    # direction (Σεπτέμβριος 2026 session): the WEEE dashboard no longer pads previous_stock with
    # an inferred gap to avoid negative current_stock, so the note's premise no longer applies.
    # Asserting its absence catches an accidental reintroduction of the old padding behavior.
    assert 'warehouseCarryNote' not in html
    assert 'duplicate receipts nav loader removed' in html


# ---- Receipts daily column contract (UI_UX_SPEC.md #5) ----
def test_mandatory_receipts_column_contract():
    with TestClient(app) as c:
        html = c.get('/desktop').text
    assert 'Αριθμός Εντολής</th><th>Προμηθευτής</th><th>Τύπος φορτίου</th><th>Μεταφορέας</th><th>Καθαρό Βάρος (kg)' in html
