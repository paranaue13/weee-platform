"""Μεταφορά των «ΔΙΑΦΟΡΕΣ» (και κάθε ποσότητας ΕΚΤΟΣ ημερομηνιών) των καρτελών 3, 4, 5 των μηνιαίων Excel στη γραμμή «Διορθώσεις» των Υλικών.
Μέχρι τώρα οι ΔΙΑΦΟΡΕΣ είχαν περαστεί ως ημερήσιες εγγραφές παραγωγής («Διόρθωση μηνός (ΔΙΑΦΟΡΕΣ)») στην τελευταία ημέρα του μήνα.
Τώρα:
 1. κάθε τέτοια εγγραφή (Ιαν–Αυγ 2026) γίνεται κίνηση διόρθωσης (ίδια ημερομηνία, ίδια ετικέτα, ίδια κιλά) και η εγγραφή παραγωγής απενεργοποιείται (active=0, δεν σβήνεται),
 2. αν το Excel έχει ΔΙΑΦΟΡΕΣ που δεν υπάρχουν στη βάση → προστίθενται ως διόρθωση,
 3. αν το «ΕΚ ΜΕΤΑΦΟΡΑΣ» ενός μήνα διαφέρει από το «ΑΠΟΘΕΜΑ» του προηγούμενου → η διαφορά μπαίνει ως διόρθωση (1η του μήνα).
Σεπτέμβριος: δεν αγγίζεται (οι διαφορές του είναι ήδη ενσωματωμένες στις ημερήσιες τιμές). Η Πρέσα (καρτέλα 6) δεν αλλάζει.
Χρήση:  python xl_corrections_move.py <βάση> [--apply] [--real-approved]   (χωρίς --apply: δοκιμαστική εκτέλεση, rollback)"""
import os, sys, re, glob, json, uuid, sqlite3, collections
from datetime import datetime, timezone
import calendar
sys.stdout.reconfigure(encoding='utf-8')
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
DB = sys.argv[1]
APPLY = '--apply' in sys.argv
os.environ['DATABASE_URL'] = 'sqlite:///' + DB.replace(chr(92), '/')
from app.mat_warehouse import _fold_key
import openpyxl
FOLDER = r'C:\Users\paran\Desktop\HER app\Files\Εισερχομενα - επεξεργασμένα 1-8 2026'
MON = {'ΙΑΝΟΥΑΡΙΟΣ': 1, 'ΦΕΒΡΟΥΑΡΙΟΣ': 2, 'ΜΑΡΤΙΟΣ': 3, 'ΑΠΡΙΛΙΟΣ': 4, 'ΜΑΪΟΣ': 5, 'ΙΟΥΝΙΟΣ': 6, 'ΙΟΥΛΙΟΣ': 7, 'ΑΥΓΟΥΣΤΟΣ': 8}
GROUP = {'3': 'AXIOPOIISIMA', '4': 'EIDIKIS_DIACHEIRISIS', '5': 'APORRIPSI'}
ADMIN = 'a448f4d4-b94d-4287-87f2-144e85113901'
NOTE = 'Διόρθωση μηνός (ΔΙΑΦΟΡΕΣ)'
cl = lambda v: re.sub(r'\s+', ' ', str(v or '')).strip()
num = lambda v: float(v) if isinstance(v, (int, float)) else 0.0

# ---- Excel: ΔΙΑΦΟΡΕΣ / ΕΚ ΜΕΤΑΦΟΡΑΣ / ΑΠΟΘΕΜΑ ανά ετικέτα και μήνα (καρτέλες 3,4,5)
xl = collections.defaultdict(dict)
for f in sorted(glob.glob(FOLDER + '/ΕΙΣ*.xlsx')):
    if os.path.basename(f).startswith('~$'): continue
    mo = MON.get(re.search(r'\((\S+) 2026\)', f).group(1))
    if not mo: continue
    wb = openpyxl.load_workbook(f, data_only=True, read_only=True)
    for sn in wb.sheetnames:
        if not re.match(r'[345] \(', sn): continue
        rows = list(wb[sn].iter_rows(values_only=True))
        first = next(i for i, r in enumerate(rows) if r and isinstance(r[0], datetime))
        hdr = rows[1:first]; tail = {}
        for r in rows[first:]:
            if r and isinstance(r[0], str) and cl(r[0]): tail[cl(r[0]).upper()] = r
        for j in range(1, max(len(r) for r in rows[:first + 1])):
            cs = [cl(r[j]) for r in hdr if j < len(r) and cl(r[j])]
            if not cs or re.search('ΣΥΝΟΛΟ|ΑΠΟΘΕΜΑ|ΗΜΕΡΟΜΗΝΙΑ|ΜΕΡΙΚΟ', cs[-1], re.I): continue
            g = lambda k: num(tail[k][j]) if k in tail and j < len(tail[k]) else 0.0
            xl[(sn[:1], _fold_key(cs[-1]))][mo] = {'label': cs[-1], 'diff': g('ΔΙΑΦΟΡΕΣ'), 'carry': g('ΕΚ ΜΕΤΑΦΟΡΑΣ'), 'stock': g('ΑΠΟΘΕΜΑ ΚΙΛΑ')}

c = sqlite3.connect(DB, timeout=60); c.row_factory = sqlite3.Row
maps = {r['label_key']: dict(r) for r in c.execute("select label_key, kind, material_id, sheet from material_label_maps where source='EXCEL'")}
ent = c.execute("select * from material_output_entries where active=1 and notes like 'Διόρθωση μηνός%'").fetchall()
labels_db = collections.Counter((r['category_group'], r['material_label']) for r in c.execute("select category_group, material_label from material_output_entries where active=1"))


def db_label(sheet, key, xl_label):
    """Η ετικέτα με την οποία φαίνεται η στήλη στις καρτέλες Υλικών (ίδια ετικέτα που έχουν οι εγγραφές παραγωγής)."""
    grp = GROUP[sheet]; m = maps.get(key)
    cand = [lab for (g, lab), n in labels_db.items() if g == grp and _fold_key(lab) == key]
    if cand: return max(cand, key=lambda l: labels_db[(grp, l)])
    if m and m['kind'] == 'MATERIAL':
        cand = [lab for (g, lab), n in labels_db.items() if g == grp and maps.get(_fold_key(lab), {}).get('material_id') == m['material_id']]
        if cand: return max(cand, key=lambda l: labels_db[(grp, l)])
    return None


c.execute('begin')
now = datetime.now(timezone.utc).isoformat(sep=' ')
stats = collections.Counter(); problems = []; moved = collections.defaultdict(float); added = []


def add_corr(date, label, kg, reason):
    c.execute('insert into material_correction_entries (id, work_date, material_label, weight_kg_delta, piece_delta, reason, created_by_user_id, created_at, updated_at) values (?,?,?,?,?,?,?,?,?)',
              (str(uuid.uuid4()), date, label, kg, 0, reason, ADMIN, now, now))


have = collections.defaultdict(float)
G2S = {v: k for k, v in GROUP.items()}
for e in ent:
    mo = int(str(e['work_date'])[5:7])
    if mo > 8: stats['Σεπτέμβριος (δεν αγγίχτηκε)'] += 1; continue
    kg = float(e['weight_kg'])
    add_corr(e['work_date'], e['material_label'], kg, 'Διαφορές μήνα (από το Excel «ΔΙΑΦΟΡΕΣ»)')
    c.execute('update material_output_entries set active=0, updated_at=?, notes=? where id=?', (now, (e['notes'] or '') + ' · μεταφέρθηκε στις Διορθώσεις', e['id']))
    have[(G2S.get(e['category_group'], e['category_group']), _fold_key(e['material_label']), mo)] += kg
    stats['εγγραφές που μεταφέρθηκαν'] += 1; moved[mo] += kg

# ΔΙΑΦΟΡΕΣ του Excel που δεν υπήρχαν στη βάση
for (sh, key), ms in xl.items():
    for mo, v in ms.items():
        if not v['diff']: continue
        h = have.get((sh, key, mo), 0.0)
        # ζεύγη ΣΙΔΗΡΟΥ/ΜΠΑΛΩΝ (σχάση σιδήρου από την Πρέσα) έχουν περαστεί με άλλο όνομα· συγκρίνεται το σύνολο της ετικέτας
        if abs(h - v['diff']) > 0.6:
            lab = db_label(sh, key, v['label'])
            miss = round(v['diff'] - h, 3)
            if not lab: problems.append((sh, v['label'], mo, 'δεν βρέθηκε στήλη στη βάση', miss)); continue
            if h: problems.append((sh, v['label'], mo, 'διαφορετικό ποσό στη βάση', v['diff'], h)); continue
            d = f'2026-{mo:02d}-{calendar.monthrange(2026, mo)[1]:02d} 12:00:00.000000'
            add_corr(d, lab, miss, 'Διαφορές μήνα (από το Excel «ΔΙΑΦΟΡΕΣ»)'); added.append((sh, lab, mo, miss)); stats['ΔΙΑΦΟΡΕΣ που έλειπαν'] += 1

# ΕΚ ΜΕΤΑΦΟΡΑΣ ≠ ΑΠΟΘΕΜΑ προηγούμενου μήνα
carry = []
for (sh, key), ms in xl.items():
    for mo, v in ms.items():
        if mo - 1 in ms and abs(ms[mo - 1]['stock'] - v['carry']) > 1.5:
            lab = db_label(sh, key, v['label']); delta = round(v['carry'] - ms[mo - 1]['stock'], 3)
            if not lab: problems.append((sh, v['label'], mo, 'μεταφορά: δεν βρέθηκε στήλη', delta)); continue
            add_corr(f'2026-{mo:02d}-01 12:00:00.000000', lab, delta, 'Η μεταφορά από τον προηγούμενο μήνα διαφέρει στο Excel (ΕΚ ΜΕΤΑΦΟΡΑΣ ≠ ΑΠΟΘΕΜΑ)'); carry.append((sh, lab, mo, delta)); stats['διαφορές μεταφοράς'] += 1

print('στατιστικά:', dict(stats)); print('ποσά που μεταφέρθηκαν ανά μήνα:', {k: round(v) for k, v in sorted(moved.items())}, '· σύνολο', round(sum(moved.values())))
print('ΔΙΑΦΟΡΕΣ που έλειπαν:', added); print('διαφορές μεταφοράς:', carry); print('προβλήματα:', problems)
# έλεγχος: το απόθεμα (παραγωγή + διορθώσεις) ανά ετικέτα δεν αλλάζει
chk = c.execute("select (select coalesce(sum(weight_kg),0) from material_output_entries where active=1), (select coalesce(sum(weight_kg_delta),0) from material_correction_entries)").fetchone()
print('παραγωγή (active) + διορθώσεις μετά:', round(chk[0] + chk[1], 3))
if APPLY and not problems:
    if os.path.normcase(os.path.abspath(DB)) == os.path.normcase(os.path.abspath(os.path.join(os.environ['LOCALAPPDATA'], 'WEEE Platform', 'data', 'weee_dev.db'))) and '--real-approved' not in sys.argv:
        c.rollback(); raise SystemExit('ΑΚΥΡΩΘΗΚΕ: πραγματική βάση μόνο με --real-approved')
    c.execute('insert into audit_events (id,user_id,entity_type,entity_id,action,old_values,new_values,reason,created_at) values (?,?,?,?,?,?,?,?,?)',
              (str(uuid.uuid4()), ADMIN, 'material_correction', '', 'IMPORT_CORRECTIONS', '', json.dumps(dict(stats), ensure_ascii=False), 'ΔΙΑΦΟΡΕΣ Excel (καρτέλες 3,4,5) → Διορθώσεις Υλικών', now))
    c.commit(); print('ΕΦΑΡΜΟΣΤΗΚΕ')
else:
    c.rollback(); print('ΔΕΝ εφαρμόστηκε (rollback)' + ('' if APPLY else ' — δοκιμαστική εκτέλεση'))
