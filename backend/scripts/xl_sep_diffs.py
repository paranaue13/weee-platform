"""ΔΙΑΦΟΡΕΣ Σεπτεμβρίου 2026 (καρτέλες 3, 4, 5) → γραμμή «Διορθώσεις». Οι 11 διορθώσεις που υπάρχουν ήδη ΔΕΝ αγγίζονται.
Για τις ετικέτες με ΔΙΑΦΟΡΕΣ στο Excel που είχαν περαστεί μέσα στην τιμή της 30/9 (άρα θα μετριόντουσαν διπλά αν προστίθεντο ως διόρθωση):
  η εγγραφή παραγωγής της 30/9 μειώνεται κατά τη διαφορά και η διαφορά μπαίνει ως διόρθωση → το απόθεμα της ετικέτας δεν αλλάζει.
Χρήση: python xl_sep_diffs.py <βάση> [--apply] [--real-approved]"""
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
f = [x for x in glob.glob(FOLDER + '/*ΣΕΠΤΕΜΒΡΙΟΣ 2026*.xlsx') if not os.path.basename(x).startswith('~$')][0]
wb = openpyxl.load_workbook(f, data_only=True, read_only=True)
xl = {}
for sn in wb.sheetnames:
    if not re.match(r'[345] \(', sn): continue
    rows = list(wb[sn].iter_rows(values_only=True))
    first = next(i for i, r in enumerate(rows) if r and isinstance(r[0], datetime))
    hdr = rows[1:first]; tail = {cl(r[0]).upper(): r for r in rows[first:] if r and isinstance(r[0], str) and cl(r[0])}
    days = [r for r in rows[first:] if r and isinstance(r[0], datetime)]
    for j in range(1, max(len(r) for r in rows[:first + 1])):
        cs = [cl(r[j]) for r in hdr if j < len(r) and cl(r[j])]
        if not cs or re.search('ΣΥΝΟΛΟ|ΑΠΟΘΕΜΑ|ΗΜΕΡΟΜΗΝΙΑ|ΜΕΡΙΚΟ', cs[-1], re.I): continue
        d = tail.get('ΔΙΑΦΟΡΕΣ'); diff = num(d[j]) if d is not None and j < len(d) else 0.0
        if diff: xl[(sn[:1], _fold_key(cs[-1]))] = {'label': cs[-1], 'diff': diff, 'days': sum(num(r[j]) for r in days if j < len(r))}
c = sqlite3.connect(DB, timeout=60); c.row_factory = sqlite3.Row
maps = {r['label_key']: r['material_id'] for r in c.execute("select label_key, material_id from material_label_maps where source='EXCEL' and kind='MATERIAL'")}
ents = c.execute("select * from material_output_entries where active=1 and work_date>='2026-09-01' and work_date<'2026-10-01'").fetchall()


def entries_of(grp, key):
    out = [e for e in ents if e['category_group'] == grp and _fold_key(e['material_label']) == key]
    if not out and key in maps:
        out = [e for e in ents if e['category_group'] == grp and maps.get(_fold_key(e['material_label'])) == maps[key]]
    return out


c.execute('begin'); now = datetime.now(timezone.utc).isoformat(sep=' '); stats = collections.Counter(); problems = []; plan = []
for (sh, key), v in sorted(xl.items()):
    grp = GROUP[sh]; es = entries_of(grp, key)
    existing = sum(float(e['weight_kg']) for e in es if (e['notes'] or '').startswith('Διόρθωση μηνός'))
    if abs(existing - v['diff']) < 0.6 and existing:
        stats['υπάρχουν ήδη (δεν αγγίχτηκαν)'] += 1; continue
    total = sum(float(e['weight_kg']) for e in es)
    if not es: problems.append((v['label'], 'δεν βρέθηκαν εγγραφές Σεπτεμβρίου', v['diff'])); continue
    label = es[0]['material_label']
    folded = abs(total - (v['days'] + v['diff'])) < 0.6
    plain = abs(total - v['days']) < 0.6
    if folded:
        e = max([x for x in es if str(x['work_date'])[:10] == '2026-09-30' and x['source'] == 'XL_IMPORT_2026'] or [None], key=lambda x: float(x['weight_kg']) if x else 0)
        if e is None: problems.append((v['label'], 'η διαφορά είναι μέσα στην τιμή αλλά όχι σε εγγραφή 30/9', v['diff'])); continue
        neww = round(float(e['weight_kg']) - v['diff'], 3)
        if neww < -0.001: problems.append((v['label'], 'αρνητική τιμή 30/9 μετά τον διαχωρισμό', neww)); continue
        if neww <= 0.001: c.execute('update material_output_entries set active=0, updated_at=?, notes=? where id=?', (now, (e['notes'] or '') + ' · η τιμή ήταν μόνο ΔΙΑΦΟΡΕΣ: μεταφέρθηκε στις Διορθώσεις', e['id']))
        else: c.execute('update material_output_entries set weight_kg=?, updated_at=?, notes=? where id=?', (neww, now, (e['notes'] or '') + f" · οι ΔΙΑΦΟΡΕΣ ({v['diff']:g}) μεταφέρθηκαν στις Διορθώσεις", e['id']))
        plan.append((v['label'], 'από την τιμή 30/9', float(e['weight_kg']), neww, v['diff']))
    elif plain:
        plan.append((v['label'], 'μόνο διόρθωση', total, total, v['diff']))
    else: problems.append((v['label'], 'το σύνολο Σεπτεμβρίου δεν ταιριάζει με το Excel', total, v['days'], v['diff'])); continue
    c.execute('insert into material_correction_entries (id, work_date, material_label, weight_kg_delta, piece_delta, reason, created_by_user_id, created_at, updated_at) values (?,?,?,?,?,?,?,?,?)',
              (str(uuid.uuid4()), '2026-09-30 12:00:00.000000', label, v['diff'], 0, 'Διαφορές μήνα (από το Excel «ΔΙΑΦΟΡΕΣ»)', ADMIN, now, now)); stats['νέες διορθώσεις'] += 1
print('στατιστικά:', dict(stats))
for p in plan: print('  ', p)
print('προβλήματα:', problems)
if APPLY and not problems:
    if os.path.normcase(os.path.abspath(DB)) == os.path.normcase(os.path.abspath(os.path.join(os.environ['LOCALAPPDATA'], 'WEEE Platform', 'data', 'weee_dev.db'))) and '--real-approved' not in sys.argv:
        c.rollback(); raise SystemExit('ΑΚΥΡΩΘΗΚΕ: πραγματική βάση μόνο με --real-approved')
    c.execute('insert into audit_events (id,user_id,entity_type,entity_id,action,old_values,new_values,reason,created_at) values (?,?,?,?,?,?,?,?,?)',
              (str(uuid.uuid4()), ADMIN, 'material_correction', '', 'IMPORT_CORRECTIONS_SEP', '', json.dumps(dict(stats), ensure_ascii=False), 'ΔΙΑΦΟΡΕΣ Σεπτεμβρίου Excel → Διορθώσεις Υλικών', now))
    c.commit(); print('ΕΦΑΡΜΟΣΤΗΚΕ')
else:
    c.rollback(); print('ΔΕΝ εφαρμόστηκε (rollback)')
