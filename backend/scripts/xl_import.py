"""ΠΡΟΣΩΡΙΝΟ εργαλείο εισαγωγής ποσοτήτων από τα μηνιαία Excel (Υλικά/Πρέσα) με βάση τις αποθηκευμένες αντιστοιχίσεις ετικετών.
Χρήση:
  python xl_import.py --db <αρχείο βάσης> --preview <έξοδος.xlsx>     προεπισκόπηση (μόνο ανάγνωση, δεν αλλάζει τίποτα)
  python xl_import.py --db <αντίγραφο βάσης> --apply                   εισαγωγή (ΠΑΝΤΑ πρώτα σε αντίγραφο· στην πραγματική μόνο με έγκριση και backup)
Κανόνες:
 * Εισάγονται ΜΟΝΟ ετικέτες με ρητή αντιστοίχιση (εκτός «Δεν είναι υλικό», «Άθροισμα/ετικέτα» και «Από παραλαβές» που δεν εισάγουν ποσότητες).
 * Όπως και στην αρχική εισαγωγή, η γραμμή «ΔΙΑΦΟΡΕΣ» του Excel προστίθεται στην τελευταία ημερομηνία του μήνα.
 * Εγγραφή προστίθεται μόνο όταν η αναμενόμενη τιμή (κελί + ΔΙΑΦΟΡΕΣ) είναι μεγαλύτερη από αυτή που υπάρχει ήδη στη βάση για την ίδια ετικέτα/ημέρα· ό,τι διαφέρει αλλιώς ΔΕΝ αγγίζεται αλλά αναφέρεται (απαιτεί απόφαση).
 * Ξαναεκτέλεση: εισάγονται μόνο όσα λείπουν (νέες αντιστοιχίσεις, νέες ημέρες). Δεδομένα Οκτωβρίου και μετά είναι δοκιμαστικά και αγνοούνται.
"""
import os, sys, re, glob, sqlite3, argparse, collections
from datetime import datetime
# ΑΣΦΑΛΕΙΑ: η βάση που θα χρησιμοποιήσουν οι εισαγωγές των modules της εφαρμογής ορίζεται από το --db ΠΡΙΝ φορτωθεί οποιοδήποτε module (αλλιώς θα χρησιμοποιούσε την πραγματική)
if '--db' in sys.argv:
    os.environ['DATABASE_URL'] = 'sqlite:///' + sys.argv[sys.argv.index('--db') + 1].replace('\\', '/')
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
from app.mat_warehouse import _fold_key
from app.excel_labels_tool import PRESS_KG_COLS

FOLDER = r'C:\Users\paran\Desktop\HER app\Files\Εισερχομενα - επεξεργασμένα 1-8 2026'
CUTOFF = '2026-10'                      # από εδώ και μετά: δοκιμαστικά δεδομένα
SKIP = re.compile(r'ΣΥΝΟΛΟ|ΑΠΟΘΕΜΑ|ΗΜΕΡΟΜΗΝΙΑ|ΜΕΡΙΚΟ', re.I)
SHEETS = [('3 (', 'AXIOPOIISIMA'), ('4 (', 'EIDIKIS_DIACHEIRISIS'), ('5 (', 'APORRIPSI'), ('ΥΛΙΚΑ ΑΠΟ ΕΜΠΟΡΙΟ', 'COMMERCIAL')]
TABNAME = {'AXIOPOIISIMA': 'Αξιοποιήσιμα Υλικά', 'EIDIKIS_DIACHEIRISIS': 'Υλικά Ειδικής Διαχείρισης', 'PLAKETES': 'Πλακέτες', 'APORRIPSI': 'Υλικά προς Απόρριψη', 'PRESS': 'Πρέσα', 'COMMERCIAL': 'Εμπορικά'}
cl = lambda v: re.sub(r'\s+', ' ', str(v or '')).strip()


def _num(v):
    try: return float(v)
    except (TypeError, ValueError): return 0.0


def extract(folder=FOLDER):
    """Επιστρέφει {'cells': [...], 'press': [...], 'files': [...]}· cells: dict με sheet,label,date,kg (κελί), diff (ΔΙΑΦΟΡΕΣ στην τελευταία ημερομηνία), plak, file."""
    import openpyxl
    cells, press, files = [], [], []
    for f in sorted(glob.glob(os.path.join(folder, '*.xlsx'))):
        if os.path.basename(f).startswith('~$'): continue          # αρχεία κλειδώματος του Excel (το αρχείο είναι ανοιχτό στον χρήστη)
        fname = os.path.basename(f); files.append(fname)
        wb = openpyxl.load_workbook(f, read_only=True, data_only=True)
        for sn in wb.sheetnames:
            grp = next((g for p, g in SHEETS if sn.startswith(p)), None)
            is_press = sn.startswith('6 (')
            if not grp and not is_press: continue
            rows = list(wb[sn].iter_rows(values_only=True))
            first = next((i for i, r in enumerate(rows) if r and isinstance(r[0], datetime)), None)
            if first is None: continue
            data = [r for r in rows[first:] if r and isinstance(r[0], datetime)]
            if is_press:
                for c, name in PRESS_KG_COLS.items():
                    for r in data:
                        kg = _num(r[c]) if c < len(r) else 0.0; n = _num(r[c - 1]) if (c - 1) < len(r) and c != 11 else 0.0
                        if kg: press.append({'label': name, 'date': r[0].date().isoformat(), 'kg': kg, 'bales': int(n), 'file': fname})
                continue
            hdr = rows[1:first]
            import calendar
            md = max(r[0] for r in data)                  # η γραμμή ΔΙΑΦΟΡΕΣ μπαίνει στην τελευταία ημέρα του ΜΗΝΑ (όπως στην αρχική εισαγωγή)
            last_date = md.replace(day=calendar.monthrange(md.year, md.month)[1]).date().isoformat()
            diff_row = next((r for r in rows[first:] if r and isinstance(r[0], str) and cl(r[0]).upper().startswith('ΔΙΑΦΟΡΕΣ')), None)
            r2 = rows[1]; plak_from = plak_to = None
            if sn.startswith('4 ('):
                plak_from = next((j for j, v in enumerate(r2) if cl(v) == 'ΠΛΑΚΕΤΕΣ'), None)
                if plak_from is not None:
                    plak_to = next((j for j in range(plak_from + 1, len(r2)) if cl(r2[j])), len(r2))
            for j in range(1, max(len(r) for r in rows[:first + 1])):
                cs = [cl(r[j]) for r in hdr if j < len(r) and cl(r[j])]
                if not cs or SKIP.search(cs[-1]): continue
                lab = cs[-1]; plak = plak_from is not None and plak_from <= j < plak_to
                per = {}
                for r in data:
                    kg = _num(r[j]) if j < len(r) else 0.0
                    if kg: per[r[0].date().isoformat()] = per.get(r[0].date().isoformat(), 0.0) + kg
                dv = _num(diff_row[j]) if (diff_row is not None and j < len(diff_row) and grp != 'COMMERCIAL') else 0.0
                if dv: per[last_date] = per.get(last_date, 0.0) + 0.0   # ώστε να υπάρχει η ημερομηνία
                for d, kg in per.items():
                    cells.append({'sheet': grp, 'label': lab, 'date': d, 'kg': kg, 'diff': dv if d == last_date else 0.0, 'plak': plak, 'file': fname})
    return {'cells': cells, 'press': press, 'files': files}


def db_state(db):
    """Υπάρχοντα στοιχεία της βάσης: αποθηκευμένες αντιστοιχίσεις, υλικά, παραγωγή ανά (ετικέτα,ημέρα), πρέσα ανά (στήλη,ημέρα)."""
    maps = {}
    for src, label, key, kind, mid, wid, gname, sheet in db.execute('select source,label,label_key,kind,material_id,weee_category_id,group_name,sheet from material_label_maps'):
        maps[(src, key)] = {'label': label, 'kind': kind, 'material_id': mid, 'weee_id': wid, 'group': gname, 'sheet': sheet}
    mats = {i: (erp, off or inn, bool(act), bool(com)) for i, erp, off, inn, act, com in db.execute('select id,galaxy_code,official_description,internal_name,active,is_commercial from materials')}
    prod = collections.defaultdict(float); labels = {}; groups = {}
    for lab, d, kg, g in db.execute('select material_label, work_date, weight_kg, category_group from material_output_entries where active=1'):
        k = _fold_key(lab); prod[(k, str(d)[:10])] += float(kg); labels.setdefault(k, lab); groups.setdefault(k, g)
    bales_m = collections.defaultdict(lambda: [0.0, 0])
    for g, d, w, seq, cnt in db.execute('select material_group, period, weight_kg, bale_seq, bale_count from bale_entries where active=1'):
        b = bales_m[(_fold_key(g), str(d)[:7])]; b[0] += float(w or 0); b[1] += 1 if seq is not None else int(cnt or 0)
    return {'maps': maps, 'mats': mats, 'prod': prod, 'labels': labels, 'groups': groups, 'bales_m': bales_m}


def plan(xl, st):
    new, diff, unmapped, skipped, comm, octo = [], [], collections.Counter(), collections.Counter(), [], []
    agg = collections.defaultdict(lambda: {'kg': 0.0, 'diff': 0.0, 'plak': False, 'sheet': None, 'label': None, 'file': None})
    for c in xl['cells']:
        a = agg[(c['sheet'], _fold_key(c['label']), c['date'])]
        a['kg'] += c['kg']; a['diff'] += c['diff']; a['plak'] = a['plak'] or c['plak']; a['sheet'] = c['sheet']; a['label'] = c['label']; a['file'] = c['file']
    # Σύγκριση ανά ΟΜΑΔΑ (καρτέλα + υλικό): δύο ετικέτες της ίδιας καρτέλας που ανήκουν στο ίδιο υλικό (π.χ. «ΚΑΤΗΓΟΡΙΑΣ D» στη βάση και «ΠΛΑΚΕΤΕΣ ΚΑΤΗΓΟΡΙΑΣ D» στο Excel)
    # είναι το ίδιο υλικό: το Excel συγκρίνεται με το ΑΘΡΟΙΣΜΑ όσων υπάρχουν ήδη στη βάση, ώστε να μη διπλομετρηθεί ό,τι έχει ήδη περαστεί με άλλο όνομα.
    EXC = ('NONE', 'SUM', 'RECEIPTS')
    gkey = lambda tab, m, key: ('M', tab, m['material_id']) if m['kind'] == 'MATERIAL' else ('L', tab, key)
    exp = collections.defaultdict(lambda: collections.defaultdict(float)); dsum = collections.defaultdict(lambda: collections.defaultdict(float)); ginfo = {}
    for (sheet, key, d), a in sorted(agg.items(), key=lambda x: (x[0][2], x[0][0], x[0][1])):
        if d[:7] >= CUTOFF:
            octo.append((sheet, a['label'], d, a['kg'])); continue
        tab = 'PLAKETES' if (sheet == 'EIDIKIS_DIACHEIRISIS' and a['plak']) else sheet
        m = st['maps'].get(('COMMERCIAL' if sheet == 'COMMERCIAL' else 'EXCEL', key))
        if sheet == 'COMMERCIAL':
            comm.append((a['label'], d, a['kg'], m)); continue
        if not m:
            unmapped[(TABNAME[tab], a['label'])] += 1; continue
        if m['kind'] in EXC:
            skipped[(TABNAME[tab], a['label'], m['kind'])] += 1; continue
        if m.get('sheet') and m['sheet'] != tab:
            # η ίδια ετικέτα υπάρχει σε στήλες διαφορετικής καρτέλας (π.χ. TABLETS στις Πλακέτες και στις Συσκευές επαναχρησιμοποίησης)· η αντιστοίχιση του χρήστη ισχύει για άλλη καρτέλα → ΔΕΝ εισάγεται, θέλει απόφαση
            skipped[(TABNAME[tab], a['label'], f"ΑΜΦΙΒΟΛΙΑ: αντιστοιχίστηκε στις «{TABNAME.get(m['sheet'], m['sheet'])}», οι ποσότητες είναι στήλη των «{TABNAME[tab]}»")] += 1; continue
        gk = gkey(tab, m, key)
        exp[gk][d] += a['kg'] + a['diff']; dsum[gk][d] += a['diff']
        g = ginfo.setdefault(gk, {'tab': tab, 'sheet': sheet, 'm': m, 'labels': [], 'file': a['file']})
        if a['label'] not in g['labels']: g['labels'].append(a['label'])
    have_g = collections.defaultdict(lambda: collections.defaultdict(float)); db_lbl = collections.defaultdict(list)
    for (key, d), v in st['prod'].items():
        m = st['maps'].get(('EXCEL', key))
        if not m or m['kind'] in EXC or not m.get('sheet'): continue
        gk = gkey(m['sheet'], m, key); have_g[gk][d] += v
        if st['labels'].get(key) not in db_lbl[gk]: db_lbl[gk].append(st['labels'].get(key))
    for gk, days in exp.items():
        g = ginfo[gk]; m = g['m']; mat = st['mats'].get(m['material_id'])
        for d, expected in sorted(days.items()):
            have = have_g[gk].get(d, 0.0); delta = round(expected - have, 3)
            if abs(delta) < 0.6: continue
            row = {'tab': TABNAME[g['tab']], 'sheet': g['sheet'], 'month': d[:7], 'date': d, 'label': ' + '.join(g['labels']), 'db_label': (db_lbl.get(gk) or [None])[0], 'use_label': (db_lbl.get(gk) or [g['labels'][0]])[0],
                   'erp': mat[0] if mat else '', 'material': mat[1] if mat else '', 'kind': m['kind'], 'excel_kg': round(expected - dsum[gk][d], 3), 'diff': dsum[gk][d], 'expected': round(expected, 3), 'in_db': round(have, 3), 'delta': delta, 'file': g['file']}
            if have == 0 or (dsum[gk][d] and abs(have - dsum[gk][d]) < 0.6):
                row['add'] = delta; new.append(row)          # τίποτα στη βάση για αυτή την ημέρα (ή μόνο η ΔΙΑΦΟΡΕΣ που μπήκε νωρίτερα): προστίθεται η διαφορά
            else:
                diff.append(row)                             # υπάρχει ήδη διαφορετική τιμή: ΔΕΝ αγγίζεται, θέλει απόφαση
    # πρέσα: το Excel (καρτέλα 6) δίνει την ΠΑΡΑΓΩΓΗ μπαλών ανά ημέρα· η βάση κρατά ΜΟΝΟ τη λίστα μπαλών του Σεπτεμβρίου (φύλλο ΜΠΑΛΕΣ) και καμία άλλη χρονιά.
    # Δεν είναι το ίδιο μέγεθος, γι' αυτό η Πρέσα ΔΕΝ μπαίνει αυτόματα: δίνεται μηνιαίος πίνακας για απόφαση.
    pnew, pdiff = [], []
    pm = collections.defaultdict(lambda: [0.0, 0, None])
    for p in xl['press']:
        if p['date'][:7] >= CUTOFF: continue
        a = pm[(_fold_key(p['label']), p['date'][:7])]; a[0] += p['kg']; a[1] += p['bales']; a[2] = p['label']
    for (k, mo), (kg, n, lab) in sorted(pm.items(), key=lambda x: (x[0][1], x[0][0])):
        m = st['maps'].get(('PRESS', k)); have = st['bales_m'].get((k, mo), [0.0, 0])
        mat = st['mats'].get(m['material_id']) if m else None
        if not m: unmapped[('Πρέσα', lab)] += 1
        pdiff.append({'month': mo, 'label': lab, 'erp': mat[0] if mat else '', 'material': mat[1] if mat else '', 'excel_kg': kg, 'excel_bales': n, 'in_db_kg': round(have[0], 3), 'in_db_bales': have[1], 'date': mo})
    return {'new': new, 'diff': diff, 'unmapped': unmapped, 'skipped': skipped, 'commercial': comm, 'october': octo, 'press_new': pnew, 'press_diff': pdiff}


def db_unmapped_columns(db, st):
    """Ετικέτες που φαίνονται ήδη στις καρτέλες από τη βάση αλλά δεν έχουν ρητή αντιστοίχιση."""
    out = []
    for k, lab in st['labels'].items():
        if ('EXCEL', k) not in st['maps']:
            n = db.execute('select count(*), coalesce(sum(weight_kg),0) from material_output_entries where active=1 and material_label=?', (lab,)).fetchone()
            out.append((TABNAME.get(st['groups'].get(k), st['groups'].get(k)), lab, n[0], round(n[1], 1)))
    return sorted(out)


def write_preview(path, p, unm_cols, xl):
    from openpyxl import Workbook
    from openpyxl.styles import Font, PatternFill, Alignment
    wb = Workbook()
    def sheet(title, headers, rows, first=False):
        ws = wb.active if first else wb.create_sheet()
        ws.title = title[:31]; ws.append(headers)
        for c in ws[1]: c.font = Font(bold=True); c.fill = PatternFill('solid', fgColor='DDE6F0'); c.alignment = Alignment(wrap_text=True, vertical='top')
        for r in rows: ws.append(r)
        ws.freeze_panes = 'A2'
        for i, h in enumerate(headers): ws.column_dimensions[chr(65 + i)].width = max(14, min(46, len(str(h)) + 4))
        return ws
    # σύνοψη ανά καρτέλα και μήνα
    sm = collections.defaultdict(lambda: [0, 0.0, 0, 0.0])
    for r in p['new']: s = sm[(r['tab'], r['month'])]; s[0] += 1; s[1] += r['add']
    for r in p['diff']: s = sm[(r['tab'], r['month'])]; s[2] += 1; s[3] += r['delta']
    sheet('Σύνοψη', ['Καρτέλα', 'Μήνας', 'Νέες εγγραφές (πλήθος)', 'Νέα κιλά που θα μπουν', 'Διαφορές που θέλουν απόφαση (πλήθος)', 'Άθροισμα διαφορών (kg)'],
          [[t, m, a, round(b, 1), c, round(d, 1)] for (t, m), (a, b, c, d) in sorted(sm.items())], first=True)
    sheet('Νέες εγγραφές', ['Καρτέλα', 'Μήνας', 'Ημερομηνία', 'Ετικέτα Excel', 'Ετικέτα στη βάση', 'ERP', 'Υλικό', 'Είδος αντιστοίχισης', 'Κελί Excel (kg)', 'ΔΙΑΦΟΡΕΣ (kg)', 'Αναμενόμενο (kg)', 'Ήδη στη βάση (kg)', 'ΝΑ ΜΠΕΙ (kg)', 'Αρχείο'],
          [[r['tab'], r['month'], r['date'], r['label'], r['db_label'] or '(νέα ετικέτα)', r['erp'], r['material'], r['kind'], r['excel_kg'], r['diff'], r['expected'], r['in_db'], r['add'], r['file']] for r in p['new']])
    sheet('Διαφορές (απόφαση)', ['Καρτέλα', 'Μήνας', 'Ημερομηνία', 'Ετικέτα Excel', 'ERP', 'Υλικό', 'Κελί Excel (kg)', 'ΔΙΑΦΟΡΕΣ (kg)', 'Αναμενόμενο (kg)', 'Στη βάση (kg)', 'Διαφορά (kg)', 'Αρχείο'],
          [[r['tab'], r['month'], r['date'], r['label'], r['erp'], r['material'], r['excel_kg'], r['diff'], r['expected'], r['in_db'], r['delta'], r['file']] for r in p['diff']])
    sheet('Δεν αντιστοιχίστηκαν', ['Καρτέλα', 'Ετικέτα Excel', 'Ημέρες με ποσότητα'], [[t, l, n] for (t, l), n in sorted(p['unmapped'].items())])
    sheet('Στήλες βάσης χωρίς αντιστοίχιση', ['Καρτέλα (βάσης)', 'Ετικέτα', 'Εγγραφές στη βάση', 'Άθροισμα kg στη βάση'], [list(x) for x in unm_cols])
    sheet('Παραλείπονται (σκόπιμα)', ['Καρτέλα', 'Ετικέτα Excel', 'Είδος', 'Ημέρες με ποσότητα'], [[t, l, k, n] for (t, l, k), n in sorted(p['skipped'].items())])
    sheet('Εμπορικά (σε αναμονή)', ['Ετικέτα Excel', 'Ημερομηνία', 'kg', 'Αντιστοίχιση', 'Σημείωση'],
          [[l, d, kg, (m or {}).get('kind', 'ΧΩΡΙΣ'), 'Δεν εισάγεται: η καρτέλα Εμπορικά παίρνει αρχικό απόθεμα/κινήσεις από το Excel μηνιαίου αποθέματος της χρονιάς'] for l, d, kg, m in p['commercial']])
    sheet('Πρέσα (σε αναμονή)', ['Μήνας', 'Στήλη Πρέσας', 'ERP', 'Υλικό', 'Παραγωγή Excel (kg)', 'Παραγωγή Excel (μπάλες)', 'Στη βάση σήμερα (kg)', 'Στη βάση σήμερα (μπάλες)', 'Σημείωση'],
          [[r['month'], r['label'], r['erp'], r['material'], r['excel_kg'], r['excel_bales'], r['in_db_kg'], r['in_db_bales'],
            'Η βάση έχει μόνο τη λίστα μπαλών Σεπτεμβρίου (απόθεμα)· δεν είναι η μηνιαία παραγωγή του Excel' if r['in_db_kg'] else 'Δεν υπάρχει στη βάση'] for r in p['press_diff']])
    sheet('Οκτώβριος+ (αγνοούνται)', ['Καρτέλα Excel', 'Ετικέτα', 'Ημερομηνία', 'kg'], [[TABNAME.get(s, s), l, d, kg] for s, l, d, kg in p['october']])
    wb.save(path)


def apply(dbpath, p, user_note='Εισαγωγή από Excel 1-9/2026'):
    """Προσθέτει τις «νέες εγγραφές» στη βάση (ΜΟΝΟ προσθήκες, τίποτα δεν αλλάζει/διαγράφεται). Επιστρέφει πλήθος."""
    from app.db import SessionLocal, engine
    from app import models
    from decimal import Decimal
    target = os.path.normcase(os.path.abspath(str(engine.url.database or '')))
    if target != os.path.normcase(os.path.abspath(dbpath)):
        raise SystemExit(f'ΑΚΥΡΩΘΗΚΕ: ο κώδικας θα έγραφε σε άλλη βάση ({target}) από την ζητούμενη ({dbpath})')
    real = os.path.normcase(os.path.abspath(os.path.join(os.environ.get('LOCALAPPDATA', ''), 'WEEE Platform', 'data', 'weee_dev.db')))
    if target == real and '--real-approved' not in sys.argv:
        raise SystemExit('ΑΚΥΡΩΘΗΚΕ: εισαγωγή στην ΠΡΑΓΜΑΤΙΚΗ βάση μόνο με έγκριση του χρήστη και backup (--real-approved)')
    n = 0
    with SessionLocal() as s:
        for r in p['new']:
            grp = 'EIDIKIS_DIACHEIRISIS' if r['sheet'] == 'EIDIKIS_DIACHEIRISIS' else r['sheet']
            s.add(models.MaterialOutputEntry(work_date=datetime.fromisoformat(r['date'] + 'T12:00:00'), category_group=grp, material_label=r['use_label'], weight_kg=Decimal(str(r['add'])),
                                             source='XL_IMPORT_2026', notes=f"{user_note} · {r['file']}"))
            n += 1
        s.commit()                                   # η Πρέσα ΔΕΝ εισάγεται (βλ. plan): σε αναμονή για απόφαση του χρήστη
    return n


if __name__ == '__main__':
    ap = argparse.ArgumentParser(); ap.add_argument('--db', required=True); ap.add_argument('--preview'); ap.add_argument('--apply', action='store_true'); ap.add_argument('--real-approved', action='store_true')
    a = ap.parse_args(); sys.stdout.reconfigure(encoding='utf-8')
    ro = sqlite3.connect('file:' + a.db.replace('\\', '/') + '?mode=ro', uri=True)
    xl = extract(); st = db_state(ro); p = plan(xl, st)
    print('αρχεία Excel:', len(xl['files']), '| νέες εγγραφές:', len(p['new']), f"({sum(r['add'] for r in p['new']):.0f} kg) | διαφορές για απόφαση:", len(p['diff']), '| δεν αντιστοιχίστηκαν:', len(p['unmapped']),
          '| παραλείπονται:', len(p['skipped']), '| εμπορικά σε αναμονή:', len(p['commercial']), '| Πρέσα (σε αναμονή) μήνες×στήλες:', len(p['press_diff']), '| Οκτώβριος+ αγνοούνται:', len(p['october']))
    if a.preview:
        write_preview(a.preview, p, db_unmapped_columns(ro, st), xl); print('προεπισκόπηση:', a.preview)
    if a.apply:
        print('εισήχθησαν:', apply(a.db, p), 'εγγραφές')
