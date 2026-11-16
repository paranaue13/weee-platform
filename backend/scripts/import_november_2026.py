"""Νοέμβριος 2026 (1–9/11): παραλαβές και ταξινομήσεις από τα ημερήσια φύλλα ΔΠΠ + υποκατηγορίες από «Απόθεμα ΑΗΗΕ 2026».

Πηγές (ΜΟΝΟ ανάγνωση):
  - Files/2026/2026/11.ΝΟΕΜΒΡΙΟΣ/ηη.11.2026.xlsx — ένα φύλλο ανά ΔΠΠ (φόρμα «ΑΝΑΦΟΡΑ ΚΑΤΑΓΡΑΦΗΣ ΠΑΡΑΛΗΦΘΕΝΤΩΝ Α.Η.Η.Ε.»):
    B2 προμηθευτής, B3 μεταφορική, D2 εντολή, D3 σφραγίδα, B5 container, B6 ζυγολόγιο, B8 δελτίο, B9 ΔΠΠ, D9 όχημα,
    D4 καθαρό ΑΗΗΕ, D5/D6 ξένα, D7/D8 ειδικής διαχείρισης, γραμμή 12 έλεγχοι, γραμμές 15+ : D κωδικός, O βάρος, P τεμάχια.
  - Files/Απόθεμα ΑΗΗΕ 2026/ΑΠΟΘΕΜΑ ΤΡΕΧOΝ 11.2026*.xlsx — μία στήλη ανά φορτίο με υποκατηγορίες (όπως το v1_missing_receipts.py).
Κανόνες (ίδιοι με Οκτώβριο/B10):
  - καθαρό βάρος φορτίου = ΑΗΗΕ + ξένα· τα ξένα μπαίνουν στην 119999 (ΜΗ ΑΗΗΕ) με παρτίδα + κίνηση SORTING_IN·
  - υποκατηγορίες από το «Απόθεμα» μόνο όταν το φορτίο ταιριάζει (ίδια ημέρα, ίδια κιλά, ίδια σύνολα ανά κατηγορία)· αλλιώς οι κωδικοί του φύλλου ΔΠΠ·
  - προμηθευτής/μεταφορέας ΜΟΝΟ από υπάρχοντες οργανισμούς (ταύτιση από προηγούμενους μήνες με τον ίδιο αριθμό εντολής ή ίδιο όνομα)· νέοι ΔΕΝ δημιουργούνται·
  - αριθμός εντολής που υπάρχει ήδη → εκτός (δεν εφευρίσκεται νέος)·
  - ό,τι είναι αμφίσημο μένει εκτός και αναφέρεται.
Χρήση: python import_november_2026.py <βάση> [--apply]"""
import sys, os, re, glob, shutil, uuid, json, unicodedata, sqlite3, collections
from datetime import datetime, timezone
import openpyxl
sys.stdout.reconfigure(encoding='utf-8')

DBF = sys.argv[1]; APPLY = '--apply' in sys.argv
ROOT = r'C:/Users/paran/Desktop/HER app/Files/2026/2026'
STOCK = r'C:/Users/paran/Desktop/HER app/Files/Απόθεμα ΑΗΗΕ 2026'
DAYS = ['%02d' % d for d in range(1, 10)]
ADMIN = 'a448f4d4-b94d-4287-87f2-144e85113901'
SRC_TAG = 'HISTORICAL_2026_NOV_REC'
LOOK = dict(zip('ΑΒΕΖΗΙΚΜΝΟΡΤΥΧ', 'ABEZHIKMNOPTYX'))


def nm(s):
    t = unicodedata.normalize('NFD', str(s or '').upper()); t = ''.join(ch for ch in t if not unicodedata.combining(ch))
    t = ''.join(LOOK.get(ch, ch) for ch in t)
    return re.sub(r'[^0-9A-Z]', '', t)


def fx(v):
    if v is None: return None
    if isinstance(v, float) and v.is_integer(): v = int(v)
    t = str(v).strip()
    return None if t in ('', '-', '--', 'None') else t


def num(v):
    if v in (None, '', '-'): return 0.0
    if isinstance(v, (int, float)): return float(v)
    try: return float(str(v).replace(',', '.'))
    except ValueError: return None


def yes(v): return str(v or '').strip().upper().startswith('Ν')


def copy_tmp(f):
    t = os.path.join(os.environ['TEMP'], 'nov_' + re.sub(r'[^0-9A-Za-z.]', '_', os.path.basename(f)))
    shutil.copy(f, t); return t


def read_daily(mm, days):
    out = []
    for f in sorted(glob.glob(f'{ROOT}/*/*.{mm}.2026.xlsx')):
        b = os.path.basename(f)
        if not re.fullmatch(r'\d\d\.\d\d\.2026\.xlsx', b) or b[:2] not in days: continue
        iso = f'2026-{mm}-{b[:2]}'
        wb = openpyxl.load_workbook(copy_tmp(f), data_only=True, read_only=True)
        for sh in wb.sheetnames:
            if not sh.strip().isdigit(): continue
            rows = list(wb[sh].iter_rows(min_row=1, max_row=110, max_col=16, values_only=True))
            g = lambda a1: (lambda c, r: rows[r - 1][c] if r - 1 < len(rows) and c < len(rows[r - 1]) else None)(ord(a1[0]) - 65, int(a1[1:]))
            if not (isinstance(g('C4'), str) and 'Καθαρό' in g('C4')): continue
            if g('B2') in (None, '') and num(g('D4')) == 0: continue
            cats, pcs = collections.defaultdict(float), collections.defaultdict(int)
            for r in rows[14:]:
                code = fx(r[3]) if len(r) > 3 else None
                if not code or not re.match(r'^\d[Α-ΩA-Z0-9]\d{4}$', code): continue
                w = num(r[14]) if len(r) > 14 else 0
                if w: cats[code] += w; pcs[code] += int(num(r[15]) or 0) if len(r) > 15 else 0
            out.append(dict(day=iso, file=b, sheet=sh, sup=g('B2'), car=g('B3'), order=fx(g('D2')), seal=fx(g('D3')), cont=fx(g('B5')), zyg=fx(g('B6')),
                            dn=fx(g('B8')), dpp=fx(g('B9')), vehicle=fx(g('D9')), aee=num(g('D4')), fyn=g('D5'), fkg=num(g('D6')), syn=g('D7'), skg=num(g('D8')),
                            chk=dict(special=yes(rows[11][6]), kday=yes(rows[11][8]), nonint=yes(rows[11][11]), pure=yes(rows[11][14])),
                            cats=dict(cats), pcs=dict(pcs)))
        wb.close()
    return out


c = sqlite3.connect(DBF, timeout=60); c.row_factory = sqlite3.Row
cats_db = {r['id']: dict(r) for r in c.execute('select id,code,description_el,parent_code from weee_categories')}
cat_id = {r['code']: r['id'] for r in cats_db.values()}
by_parent = collections.defaultdict(list)
for r in cats_db.values():
    if r['parent_code']: by_parent[r['parent_code']].append(r)


def sub_for(group, label):
    n = nm(label)
    if len(n) < 3: return None
    for p, lst in by_parent.items():
        if p[0] != group: continue
        for r in lst:
            nn = nm(r['description_el'])
            if n == nn or nn.startswith(n[:14]) or n.startswith(nn[:14]): return r
    return None


def read_stock(mm, days):
    f = [x for x in glob.glob(STOCK + f'/ΑΠΟΘΕΜΑ ΤΡΕΧOΝ {mm}.2026*.xlsx') if '~$' not in x][0]
    wb = openpyxl.load_workbook(copy_tmp(f), read_only=True, data_only=True); res = {}
    for ws in wb.worksheets:
        m = re.match(r'^(\d\d)\.(\d\d)', ws.title)
        if not m or m.group(1) not in days: continue
        rows = list(ws.iter_rows(values_only=True))
        if len(rows) < 90: continue
        iso = f'2026-{m.group(2)}-{m.group(1)}'
        hdr = rows[1]; cols = [i for i in range(15, len(hdr), 3) if hdr[i] == 'Προμηθευτής']
        group = None; lines = []
        for ri in range(7, 88):
            r = rows[ri]
            if r[0] not in (None, '') and str(r[0]).strip().isdigit(): group = str(r[0]).strip()
            code = str(r[1]).strip() if r[1] not in (None, '') and re.match(r'^\d[Α-ΩA-Z]\d{4}$', str(r[1]).strip()) else None
            lab = [v for v in (r[2], r[3], r[4]) if v not in (None, '') and not isinstance(v, (int, float))]
            if not lab and not code: continue
            lines.append((group, code, str(lab[0]).strip() if lab else '', r))
        loads = []
        for ci in cols:
            kg = rows[4][ci + 1] if len(rows[4]) > ci + 1 else None; sup = rows[1][ci + 1]
            if sup is None and kg in (None, 0, ''): continue
            vec = collections.defaultdict(float); pcs = collections.defaultdict(int); unk = []
            for group, code, label, r in lines:
                w = r[ci] if ci < len(r) else None
                if not isinstance(w, (int, float)) or not w: continue
                pc = r[ci + 1] if ci + 1 < len(r) and isinstance(r[ci + 1], (int, float)) else 0
                s = sub_for(group, label)
                key = s['code'] if s else (code if code in cat_id else None)
                if key is None: unk.append((label, float(w))); continue
                vec[key] += float(w); pcs[key] += int(pc)
            loads.append(dict(sup=sup, kg=float(kg) if isinstance(kg, (int, float)) else 0.0, vec=dict(vec), pcs=dict(pcs), unk=unk))
        res[iso] = loads
    return res


def fam(v):
    o = collections.defaultdict(float)
    for k, w in v.items():
        p = cats_db[cat_id[k]]['parent_code'] if k in cat_id else None
        o[p or k] += w
    return dict(o)


def eq(a, b): return all(abs(a.get(k, 0) - b.get(k, 0)) <= 0.5 for k in set(a) | set(b))


# --- οργανισμοί: ονόματα προηγούμενων ημερήσιων φύλλων (Σεπ/Οκτ) ↔ φορτία της βάσης με τον ίδιο αριθμό εντολής ---
db_by_order = {str(r['order_number']): r for r in c.execute("select l.order_number,l.supplier_id,t.carrier_id from inbound_loads l join inbound_trips t on t.id=l.trip_id where t.deleted_at is null and l.order_number is not null")}
sup_map = collections.defaultdict(collections.Counter); car_map = collections.defaultdict(collections.Counter)
for mm in ('09', '10'):
    for x in read_daily(mm, ['%02d' % d for d in range(1, 32)]):
        d = db_by_order.get(str(x['order']))
        if d:
            sup_map[nm(x['sup'])][d['supplier_id']] += 1
            if d['carrier_id']: car_map[nm(x['car'])][d['carrier_id']] += 1
orgs = {}
for o in c.execute('select id,legal_name,trade_name from organizations'):
    for k in (nm(o['legal_name']), nm(o['trade_name'])):
        if k: orgs.setdefault(k, set()).add(o['id'])


# ταυτίσεις με υπάρχουσες εγγραφές Μητρώων (όχι νέοι οργανισμοί):
#  ΤΟΛΛΙΑΣ: δύο εγγραφές με τον ίδιο ΑΦΜ 999680591 → αυτή που έχει ήδη παραλαβή· AVDIAJ SHKELQLM (λάθος γραφής στο Excel) = «AVDIAJ SHKELQIM του ABIL» (ΑΦΜ 049491053)
MANUAL = {nm('ΤΟΛΛΙΑΣ ΑΝΑΚΥΚΛΩΣΗ Ι.Κ.Ε.'): '56fde173-16c1-4867-8f2e-7f44d7574077', nm('AVDIAJ SHKELQLM'): 'ac6cd86b-938a-4f90-a4c7-5bf8644ab0a7'}


def org_for(name, mp):
    k = nm(name)
    if not k: return None, 'κενό όνομα'
    if mp is sup_map and k in MANUAL: return MANUAL[k], 'ταύτιση (ίδιος ΑΦΜ / λάθος γραφής)'
    if k in mp:
        (best, n1), *rest = mp[k].most_common(2)
        if rest and rest[0][1] == n1: return None, 'αμφίσημο (2 οργανισμοί με ίδιο πλήθος)'
        return best, 'από προηγούμενους μήνες'
    if k in orgs:
        if len(orgs[k]) > 1: return None, 'αμφίσημο (πολλοί οργανισμοί με ίδιο όνομα)'
        return next(iter(orgs[k])), 'ίδιο όνομα στα Μητρώα'
    return None, 'δεν βρέθηκε στα Μητρώα'


sup_type = collections.defaultdict(collections.Counter)
for r in c.execute("select l.supplier_id,t.receipt_type from inbound_loads l join inbound_trips t on t.id=l.trip_id where t.deleted_at is null and (l.incoming_container_number is null or l.incoming_container_number='')"):
    sup_type[r[0]][r[1]] += 1

X = read_daily('11', DAYS)
ST = read_stock('11', DAYS)
used_rn = {str(x[0]) for x in c.execute('select receipt_number from inbound_trips')} | {str(x[0]) for x in c.execute('select order_number from inbound_loads where order_number is not null')}
used_dpp = {x[0] for x in c.execute('select dpp_number from inbound_loads where dpp_number is not null')}

plan, skipped, problems = [], [], []
st_used = collections.defaultdict(set)
for x in X:
    tag = f"{x['day']} ΔΠΠ {x['dpp']} εντολή {x['order']} {str(x['sup'])[:34]}"
    catsum = sum(x['cats'].values())
    if abs(catsum - x['aee']) > 0.5: problems.append((tag, f'άθροισμα κατηγοριών {catsum:g} ≠ καθαρό ΑΗΗΕ {x["aee"]:g}')); continue
    if not x['order']: problems.append((tag, 'χωρίς αριθμό εντολής')); continue
    if str(x['order']) in used_rn: skipped.append((tag, 'ο αριθμός εντολής υπάρχει ήδη στη βάση')); continue
    if x['dpp'] and x['dpp'].isdigit() and int(x['dpp']) in used_dpp: skipped.append((tag, 'ο ΔΠΠ υπάρχει ήδη στη βάση')); continue
    sup, why_s = org_for(x['sup'], sup_map); car, why_c = org_for(x['car'], car_map)
    if not sup: skipped.append((tag, f'προμηθευτής «{" ".join(str(x["sup"]).split())}»: {why_s}')); continue
    if not car: skipped.append((tag, f'μεταφορέας «{" ".join(str(x["car"]).split())}»: {why_c}')); continue
    # υποκατηγορίες από το «Απόθεμα»: ίδια ημέρα, κιλά = ΑΗΗΕ + ξένα, ίδια σύνολα ανά κατηγορία
    vec, pcs, src = x['cats'], x['pcs'], 'ΔΠΠ'
    cand = [i for i, s in enumerate(ST.get(x['day'], [])) if i not in st_used[x['day']] and abs(s['kg'] - (x['aee'] + x['fkg'])) <= 0.5 and not s['unk'] and eq(fam(s['vec']), fam(x['cats']))]
    if cand:
        s = ST[x['day']][cand[0]]; st_used[x['day']].add(cand[0]); vec, pcs, src = s['vec'], s['pcs'], 'Απόθεμα (υποκατηγορίες)'
    unknown = [k for k in vec if k not in cat_id]
    if unknown: problems.append((tag, f'άγνωστοι κωδικοί {unknown}')); continue
    used_rn.add(str(x['order']))
    if x['dpp'] and x['dpp'].isdigit(): used_dpp.add(int(x['dpp']))
    plan.append(dict(x=x, sup=sup, car=car, vec=vec, pcs=pcs, src=src, why=(why_s, why_c)))

loc = c.execute("select id from inventory_locations where code='WEEE_MAIN'").fetchone()['id']
x999 = cat_id['119999']
tpl_load = c.execute("select l.* from inbound_loads l where order_number='812304'").fetchone()
tpl_trip = c.execute('select * from inbound_trips where id=?', (tpl_load['trip_id'],)).fetchone()
tpl_ses = c.execute('select * from sorting_sessions where inbound_load_id=?', (tpl_load['id'],)).fetchone()
tpl_ent = c.execute('select * from sorting_entries where session_id=? limit 1', (tpl_ses['id'],)).fetchone()
tpl_lot = c.execute('select * from weee_stock_lots where source_sorting_entry_id=?', (tpl_ent['id'],)).fetchone()
tpl_mv = c.execute('select * from stock_movements where lot_id=? limit 1', (tpl_lot['id'],)).fetchone()


def clone(table, row, **over):
    d = dict(row); d.update(over); cols = list(d)
    c.execute(f'insert into {table} ({",".join(cols)}) values ({",".join("?" * len(cols))})', [d[k] for k in cols])


def entry(sid, lid, dt, code, w, pc, note, reason):
    eid, lot = str(uuid.uuid4()), str(uuid.uuid4())
    clone('sorting_entries', tpl_ent, id=eid, session_id=sid, weee_category_id=cat_id[code], collection_medium_id=None, entry_type='HISTORICAL', raw_weight=w, approved_weight=w,
          piece_count=pc or None, created_by=ADMIN, notes=note, created_at=dt, updated_at=dt, source=None)
    clone('weee_stock_lots', tpl_lot, id=lot, source_sorting_entry_id=eid, inbound_load_id=lid, weee_category_id=cat_id[code], collection_medium_id=None, location_id=loc,
          original_weight=w, available_weight=w, piece_count=pc or None, status='AVAILABLE', created_at=dt, updated_at=dt)
    clone('stock_movements', tpl_mv, id=str(uuid.uuid4()), domain='WEEE', lot_id=lot, movement_type='SORTING_IN', from_location_id=None, to_location_id=loc, weight=w,
          org_unit_id=None, user_id=ADMIN, reason=reason, created_at=dt, transfer_id=None)


stats = collections.Counter()
c.execute('begin')
for p in plan:
    x = p['x']; iso = x['day']; dt = iso + ' 12:00:00.000000'
    net = round(x['aee'] + x['fkg'], 3)
    fm = 'ΝΑΙ' if (yes(x['fyn']) or x['fkg'] > 0) else 'ΟΧΙ'; sw = 'ΝΑΙ' if (yes(x['syn']) or x['skg'] > 0) else 'ΟΧΙ'
    cont = x['cont'] if x['cont'] and re.fullmatch(r'\d{4,}', x['cont']) else None
    rtype = 'CONTAINER' if cont else (sup_type[p['sup']].most_common(1)[0][0] if sup_type.get(p['sup']) else 'SMALL_POINTS')
    extras = {'sealNo': x['seal'] or '', 'weighbridgeNo': x['zyg'] or '', 'reportDate': iso, 'dispatchNo': x['dn'] or '', 'foreignMaterials': fm, 'foreignWeight': x['fkg'],
              'specialWaste': sw, 'specialWasteWeight': x['skg'], 'dppNo': x['dpp'] or '', 'checkSpecial': x['chk']['special'], 'checkKday': x['chk']['kday'],
              'checkNonInteger': x['chk']['nonint'], 'loadPure': x['chk']['pure'], 'sourceTimeKnown': False, 'sourceFile': x['file'], 'sourceSheet': x['sheet'], 'importSource': SRC_TAG}
    tid, lid, sid = str(uuid.uuid4()), str(uuid.uuid4()), str(uuid.uuid4())
    clone('inbound_trips', tpl_trip, id=tid, receipt_number=str(x['order']), receipt_type=rtype, receipt_date=dt, carrier_id=p['car'], driver_name=None, vehicle_registration=x['vehicle'],
          status='CLOSED', created_by=ADMIN, notes='__EXTRA__' + json.dumps(extras, ensure_ascii=False, separators=(',', ':')) + '\n', created_at=dt, updated_at=dt, deleted_at=None,
          aggregate_weighbridge_number=None, cancelled_at=None, cancel_reason=None, cancelled_by=None, cancel_snapshot=None)
    clone('inbound_loads', tpl_load, id=lid, trip_id=tid, load_sequence=1, supplier_id=p['sup'], order_number=str(x['order']), incoming_container_number=cont, incoming_container_tare=None,
          outgoing_container_id=None, gross_weight=None, tare_weight=None, net_weight=net, status='CLOSED', ready_for_sorting_at=dt, notes=None, created_at=dt, updated_at=dt,
          dpp_number=int(x['dpp']) if x['dpp'] and x['dpp'].isdigit() else None, outgoing_container_tare=None, weighbridge_number=x['zyg'], dispatch_note_number=x['dn'], seal_number=x['seal'])
    clone('sorting_sessions', tpl_ses, id=sid, inbound_load_id=lid, status='CLOSED', started_at=dt, sorting_confirmed_at=dt, logistics_confirmed_at=dt, final_sorting_weight=net, final_difference=0,
          foreign_materials=fm, foreign_weight=x['fkg'], special_waste=sw, special_waste_weight=x['skg'], load_pure=int(x['chk']['pure']), check_special=int(x['chk']['special']),
          check_kday=int(x['chk']['kday']), check_non_integer=int(x['chk']['nonint']), created_at=dt, updated_at=dt)
    note = f'Εισαγωγή Νοεμβρίου 2026 ({x["file"]} φύλλο {x["sheet"]}' + (' + υποκατηγορίες από «Απόθεμα ΑΗΗΕ 2026»)' if p['src'] != 'ΔΠΠ' else ')')
    for code, w in sorted(p['vec'].items()):
        entry(sid, lid, dt, code, w, p['pcs'].get(code), note, 'Ιστορική εισαγωγή Νοεμβρίου 2026 (xlsx)'); stats['εγγραφές ταξινόμησης'] += 1
    if x['fkg'] > 0:
        entry(sid, lid, dt, '119999', x['fkg'], None, 'Ξένα υλικά (Μη ΑΗΗΕ) από το Excel ' + x['file'], 'Ξένα υλικά από Excel'); stats['ξένα (119999)'] += 1
    stats['νέες παραλαβές'] += 1; stats['με υποκατηγορίες' if p['src'] != 'ΔΠΠ' else 'χωρίς αντιστοίχιση στο Απόθεμα'] += 1

print('Φύλλα ΔΠΠ 1–9/11:', len(X), '· φορτία στο «Απόθεμα» 1–9/11:', sum(len(v) for v in ST.values()))
for p in plan:
    x = p['x']; print(f"  {x['day']} ΔΠΠ {x['dpp']} εντολή {x['order']} {str(x['sup'])[:30]:30s} ΑΗΗΕ {x['aee']:>7g} + ξένα {x['fkg']:>4g} · {p['src']} · {p['why'][0]}")
for s in skipped: print('ΕΚΤΟΣ:', *s)
for pr in problems: print('ΠΡΟΒΛΗΜΑ:', *pr)
day_x = collections.defaultdict(float); day_st = {d: sum(s['kg'] for s in v) for d, v in ST.items()}
for x in X: day_x[x['day']] += x['aee'] + x['fkg']
print('Σύνολα ανά ημέρα (ΔΠΠ ↔ Απόθεμα):', {d: (round(day_x[d]), round(day_st.get(d, 0))) for d in sorted(set(day_x) | set(day_st))})
tot = c.execute("select count(*),round(sum(l.net_weight)) from inbound_loads l join inbound_trips t on t.id=l.trip_id where t.receipt_date>='2026-11-01' and t.receipt_date<'2026-11-10' and t.deleted_at is null").fetchone()
srt = c.execute("select round(sum(coalesce(e.approved_weight,e.raw_weight))) from sorting_entries e join sorting_sessions s on s.id=e.session_id join inbound_loads l on l.id=s.inbound_load_id join inbound_trips t on t.id=l.trip_id where t.receipt_date>='2026-11-01' and t.receipt_date<'2026-11-10' and t.deleted_at is null").fetchone()
print('στατιστικά:', dict(stats), f'· 1–9/11 μετά: παραλαβές {tot[0]} · καθαρό {tot[1]} kg · ταξινόμηση {srt[0]} kg')
if APPLY and not problems:
    now = datetime.now(timezone.utc).isoformat(sep=' ')
    c.execute('insert into audit_events (id,user_id,entity_type,entity_id,action,old_values,new_values,reason,created_at) values (?,?,?,?,?,?,?,?,?)',
              (str(uuid.uuid4()), ADMIN, 'inbound_load', '', 'IMPORT_NOVEMBER', '', json.dumps(dict(stats), ensure_ascii=False), 'Νοέμβριος 2026 (1–9/11): εισαγωγή από ημερήσιες αναφορές ΔΠΠ + «Απόθεμα ΑΗΗΕ 2026»', now))
    c.commit(); print('ΕΦΑΡΜΟΣΤΗΚΕ')
else:
    c.rollback(); print('ΔΕΝ εφαρμόστηκε (rollback)' + ('' if APPLY else ' — δοκιμαστική εκτέλεση') + (' — υπάρχουν προβλήματα' if problems else ''))
