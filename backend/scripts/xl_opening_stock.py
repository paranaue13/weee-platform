"""Απογραφή 31/12/2025 των Υλικών: διόρθωση με βάση το «ΕΚ ΜΕΤΑΦΟΡΑΣ» του Ιανουαρίου των καρτελών 3, 4, 5 του Excel (αυτό θεωρείται η σωστή αρχική κατάσταση).
Χρήση: python xl_opening_stock.py <βάση> [--apply] [--real-approved] [--list <αρχείο.csv>]
Χωρίς --apply: μόνο η λίστα (ετικέτα, Excel, εφαρμογή, διαφορά) και rollback. Ό,τι δεν διαφέρει δεν αγγίζεται."""
import os, sys, re, glob, json, uuid, sqlite3, collections
from datetime import datetime, timezone
sys.stdout.reconfigure(encoding='utf-8')
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
DB = sys.argv[1]; APPLY = '--apply' in sys.argv
os.environ['DATABASE_URL'] = 'sqlite:///' + DB.replace(chr(92), '/')
from app.mat_warehouse import _fold_key
import openpyxl
FOLDER = r'C:\Users\paran\Desktop\HER app\Files\Εισερχομενα - επεξεργασμένα 1-8 2026'
GROUP = {'3': 'AXIOPOIISIMA', '4': 'EIDIKIS_DIACHEIRISIS', '5': 'APORRIPSI'}
ADMIN = 'a448f4d4-b94d-4287-87f2-144e85113901'
cl = lambda v: re.sub(r'\s+', ' ', str(v or '')).strip()
num = lambda v: float(v) if isinstance(v, (int, float)) else 0.0
f = [x for x in glob.glob(FOLDER + '/*ΙΑΝΟΥΑΡΙΟΣ 2026*.xlsx') if not os.path.basename(x).startswith('~$')][0]
wb = openpyxl.load_workbook(f, data_only=True, read_only=True)
xl = {}                                            # (ομάδα, key) -> (ετικέτα, ΕΚ ΜΕΤΑΦΟΡΑΣ)
for sn in wb.sheetnames:
    if not re.match(r'[345] \(', sn): continue
    rows = list(wb[sn].iter_rows(values_only=True))
    first = next(i for i, r in enumerate(rows) if r and isinstance(r[0], datetime))
    hdr = rows[1:first]; tail = {cl(r[0]).upper(): r for r in rows[first:] if r and isinstance(r[0], str) and cl(r[0])}
    for j in range(1, max(len(r) for r in rows[:first + 1])):
        cs = [cl(r[j]) for r in hdr if j < len(r) and cl(r[j])]
        if not cs or re.search('ΣΥΝΟΛΟ|ΑΠΟΘΕΜΑ|ΗΜΕΡΟΜΗΝΙΑ|ΜΕΡΙΚΟ', cs[-1], re.I): continue
        r = tail.get('ΕΚ ΜΕΤΑΦΟΡΑΣ'); xl[(GROUP[sn[:1]], _fold_key(cs[-1]))] = (cs[-1], num(r[j]) if r is not None and j < len(r) else 0.0)
c = sqlite3.connect(DB, timeout=60); c.row_factory = sqlite3.Row
maps = {r['label_key']: r['material_id'] for r in c.execute("select label_key, material_id from material_label_maps where source='EXCEL' and kind='MATERIAL'")}
op = c.execute("select * from material_opening_stocks where active=1").fetchall()
byk = collections.defaultdict(list)
for r in op: byk[(r['category_group'], _fold_key(r['material_label']))].append(r)
# ετικέτες που φαίνονται στις καρτέλες (για νέες γραμμές απογραφής)
lab_db = collections.Counter((r[0], r[1]) for r in c.execute("select category_group, material_label from material_output_entries where active=1"))
lines = []; used = set()
for (grp, key), (xlab, kg) in sorted(xl.items(), key=lambda x: (x[0][0], x[1][0])):
    rows = byk.get((grp, key), [])
    if not rows and key in maps:                   # ίδιο υλικό με άλλο όνομα ετικέτας
        for (g2, k2), rr in byk.items():
            if g2 == grp and maps.get(k2) == maps[key] and (g2, k2) not in used: rows = rr; used.add((g2, k2)); break
    used.add((grp, key))
    app = sum(float(r['kg']) for r in rows)
    lines.append({'grp': grp, 'label': xlab, 'xl': kg, 'app': app, 'diff': round(kg - app, 3), 'rows': rows})
orphans = [r for (g, k), rr in byk.items() if (g, k) not in used for r in rr]
chg = [l for l in lines if abs(l['diff']) > 0.5]
print('ετικέτες Excel:', len(lines), '· διαφορετικές:', len(chg), '· σύνολο Excel', round(sum(l['xl'] for l in lines)), '· εφαρμογή', round(sum(l['app'] for l in lines)))
for l in chg: print(f"  {l['grp'][:4]} | {l['label'][:36]:36} | Excel {l['xl']:>9.1f} | εφαρμογή {l['app']:>9.1f} | διαφορά {l['diff']:>+9.1f}")
print('γραμμές απογραφής εφαρμογής χωρίς αντίστοιχη στήλη Excel (δεν αγγίζονται):', [(r['material_label'], float(r['kg'])) for r in orphans])
if '--list' in sys.argv:
    import csv
    with open(sys.argv[sys.argv.index('--list') + 1], 'w', encoding='utf-8-sig', newline='') as fh:
        w = csv.writer(fh, delimiter=';'); w.writerow(['Ομάδα', 'Ετικέτα', 'Excel', 'Εφαρμογή', 'Διαφορά'])
        for l in chg: w.writerow([l['grp'], l['label'], l['xl'], l['app'], l['diff']])
c.execute('begin'); now = datetime.now(timezone.utc).isoformat(sep=' '); n_upd = n_new = 0
tpl = op[0] if op else None
for l in chg:
    rows = l['rows']
    if rows:
        main = max(rows, key=lambda r: float(r['kg']))
        rest = [r for r in rows if r['id'] != main['id']]
        for r in rest: c.execute('update material_opening_stocks set active=0, updated_at=?, notes=? where id=?', (now, 'Μηδενίστηκε: απογραφή από το ΕΚ ΜΕΤΑΦΟΡΑΣ Ιανουαρίου Excel', r['id']))
        c.execute('update material_opening_stocks set kg=?, updated_at=?, notes=? where id=?', (l['xl'], now, f"Διόρθωση από ΕΚ ΜΕΤΑΦΟΡΑΣ Ιανουαρίου Excel: πριν {sum(float(r['kg']) for r in rows):g} kg", main['id'])); n_upd += 1
    elif l['xl'] > 0:
        lab = max([x for (g, x), n in lab_db.items() if g == l['grp'] and _fold_key(x) == _fold_key(l['label'])] or [l['label']], key=lambda x: 0)
        d = dict(tpl); d.update(id=str(uuid.uuid4()), category_group=l['grp'], material_label=lab, kg=l['xl'], reptool_code=None, her_description=None, source='XL_OPENING_2026', notes='Από ΕΚ ΜΕΤΑΦΟΡΑΣ Ιανουαρίου Excel', created_at=now, updated_at=now)
        c.execute(f"insert into material_opening_stocks ({','.join(d)}) values ({','.join('?' * len(d))})", list(d.values())); n_new += 1
print('ενημερώσεις:', n_upd, '· νέες γραμμές:', n_new)
if APPLY:
    if os.path.normcase(os.path.abspath(DB)) == os.path.normcase(os.path.abspath(os.path.join(os.environ['LOCALAPPDATA'], 'WEEE Platform', 'data', 'weee_dev.db'))) and '--real-approved' not in sys.argv:
        c.rollback(); raise SystemExit('ΑΚΥΡΩΘΗΚΕ: πραγματική βάση μόνο με --real-approved')
    c.execute('insert into audit_events (id,user_id,entity_type,entity_id,action,old_values,new_values,reason,created_at) values (?,?,?,?,?,?,?,?,?)',
              (str(uuid.uuid4()), ADMIN, 'material_opening_stock', '', 'IMPORT_OPENING', '', json.dumps({'updated': n_upd, 'new': n_new}), 'Απογραφή 31/12/2025 από ΕΚ ΜΕΤΑΦΟΡΑΣ Ιανουαρίου', now))
    c.commit(); print('ΕΦΑΡΜΟΣΤΗΚΕ')
else:
    c.rollback(); print('ΔΕΝ εφαρμόστηκε (rollback)')
