"""Z1: Διορθώσεις παραγωγής από τα Excel «ΕΙΣΕΡΧΟΜΕΝΑ-ΕΠΕΞΕΡΓΑΣΜΕΝΑ ΥΛΙΚΑ-ΠΡΕΣΑ» (Ιανουάριος–Οκτώβριος 2026, καρτέλες 1 και 2).

Κανόνες: ημερομηνία στη στήλη Α πάνω από τη γραμμή HERMES = Λοιποί (OTHER)· ημερομηνία κάτω από τη γραμμή HERMES = HERMES·
αριθμός σε γραμμή ΧΩΡΙΣ ημερομηνία (κενή στήλη Α ή «ΔΙΟΡΘΩΣΗ») = ΔΙΟΡΘΩΣΗ των ΛΟΙΠΩΝ (και αρνητικοί) — ΠΟΤΕ του HERMES.
Οι ημερήσιες εγγραφές ταιριάζουν ήδη με το Excel (ελέγχεται)· αντικαθίστανται ΜΟΝΟ οι εγγραφές «Διόρθωση αρχείου παραγωγής» των ιστορικών πηγών, ανά μήνα, με μία εγγραφή ανά κατηγορία (ΛΟΙΠΟΙ, τελευταία ημέρα του μήνα).
Δεν αγγίζονται εγγραφές που δεν προέρχονται από τα αρχεία. Χρήση: python z1_production_corrections.py <db> [--apply]"""
import sys, os, re, glob, shutil, json, uuid, collections, sqlite3, calendar
from datetime import datetime, timezone
sys.stdout.reconfigure(encoding='utf-8')
import openpyxl

DBF = sys.argv[1]; APPLY = '--apply' in sys.argv
SRC = r'C:\Users\paran\Desktop\HER app\Files\Εισερχομενα - επεξεργασμένα 1-8 2026'
NAMES = {'01': 'ΙΑΝΟΥΑΡΙΟΣ', '02': 'ΦΕΒΡΟΥΑΡΙΟΣ', '03': 'ΜΑΡΤΙΟΣ', '04': 'ΑΠΡΙΛΙΟΣ', '05': 'ΜΑΪΟΣ', '06': 'ΙΟΥΝΙΟΣ', '07': 'ΙΟΥΛΙΟΣ', '08': 'ΑΥΓΟΥΣΤΟΣ', '09': 'ΣΕΠΤΕΜΒΡΙΟΣ', '10': 'ΟΚΤΩΒΡΙΟΣ'}
SOURCE = {m: ('HISTORICAL_2026_SEP' if m == '09' else 'HISTORICAL_2026_OCT' if m == '10' else 'HISTORICAL_2026') for m in NAMES}
CORR = 'Διόρθωση αρχείου παραγωγής'
HEADER_MAP_JSON = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'z1_header_map.json')   # (ομάδα|τίτλος στήλης) → κωδικός κατηγορίας ΑΗΗΕ
HEADER_MAP = {tuple(k.split('|')): v for k, v in json.load(open(HEADER_MAP_JSON, encoding='utf-8')).items()}


def hkey(rows, c):
    g = ''
    for j in range(c, -1, -1):
        if rows[0][j] not in (None, ''): g = str(rows[0][j]).split('\n')[0]; break
    return (g.strip().upper(), re.sub(r'\s+', ' ', str(rows[1][c] or '')).strip().upper())


def parse_month(mm):
    f = [x for x in glob.glob(SRC + f'\\*({NAMES[mm]} 2026).xlsx') if '~$' not in x][0]
    t = os.path.join(os.environ['TEMP'], f'z1_{mm}.xlsx'); shutil.copy(f, t)   # αντίγραφο: το αρχικό δεν αγγίζεται
    wb = openpyxl.load_workbook(t, read_only=True, data_only=True)
    dated = collections.defaultdict(float); corr = collections.defaultdict(float); unknown = []; tots = collections.defaultdict(float)
    for si in (0, 1):
        rows = list(wb.worksheets[si].iter_rows(values_only=True))
        hm = [i for i, r in enumerate(rows) if any(isinstance(v, str) and 'HERMES' in v.upper() for v in r)][0]
        for i, r in enumerate(rows[2:], 2):
            if i > 70: break
            a = r[0]; lab = re.sub(r'\s+', ' ', str(a)).strip().upper() if a is not None and not hasattr(a, 'year') else None
            for c in range(1, len(r)):
                v = r[c]
                if not isinstance(v, (int, float)) or not v: continue
                k = hkey(rows, c)
                if 'ΣΥΝΟΛΟ ΗΜΕΡΑΣ' in k[1] or k[1] == '': continue
                if hasattr(a, 'year'): kind = 'dated'
                elif lab is None or lab.startswith('ΔΙΟΡΘΩΣΗ'): kind = 'corr'
                elif lab.startswith('ΣΥΝΟΛΟ') and 'ΧΕΡΜΕΣ' not in lab and not lab.startswith(('ΣΥΝΟΛΟ 20', 'ΣΥΝΟΛΟ ΕΤΟΣ')):
                    if k in HEADER_MAP: tots[HEADER_MAP[k]] += float(v)   # «ΣΥΝΟΛΟ ΜΗΝΑ» του Excel (έλεγχος)
                    continue
                else: continue
                if k not in HEADER_MAP: unknown.append((mm, k, kind, v)); continue
                code = HEADER_MAP[k]
                if kind == 'dated': dated[(a.strftime('%Y-%m-%d'), code, 'OTHER' if i < hm else 'HERMES')] += float(v)
                else: corr[code] += float(v)
    return dated, corr, unknown, tots


c = sqlite3.connect(DBF, timeout=60); c.row_factory = sqlite3.Row
cat = {r['code']: r['id'] for r in c.execute('select id,code from weee_categories')}; code_of = {v: k for k, v in cat.items()}
now = datetime.now(timezone.utc).isoformat(sep=' ')
tpl = dict(c.execute("select * from production_work_entries where source='HISTORICAL_2026_SEP' and notes=? limit 1", (CORR,)).fetchone())
problems = []; plan = {}; mapped = set(HEADER_MAP.values())
for mm in NAMES:
    dated, corr, unknown, tots = parse_month(mm)
    if unknown: problems.append(('επικεφαλίδα χωρίς αντιστοίχιση', unknown[:3]))
    db_d = collections.defaultdict(float)
    for r in c.execute("select weee_category_id,substr(work_date,1,10) d,weight_kg,supplier_group from production_work_entries where substr(work_date,1,7)=? and active=1 and source like 'HISTORICAL%' and (notes is null or notes<>?)", ('2026-' + mm, CORR)):
        db_d[(r['d'], code_of[r['weee_category_id']], r['supplier_group'])] += float(r['weight_kg'])
    bad = [(k, round(dated.get(k, 0), 1), round(db_d.get(k, 0), 1)) for k in set(dated) | set(db_d) if abs(dated.get(k, 0) - db_d.get(k, 0)) > 0.5 and k[1] in mapped]
    if bad: problems.append((mm, 'ημερήσιες διαφορές', bad[:4]))
    plan[mm] = (corr, dated, tots)

c.execute('begin')
stats = collections.Counter(); chg = {}; chk = []
for mm, (corr, dated, tots) in plan.items():
    ym = '2026-' + mm; last = calendar.monthrange(2026, int(mm))[1]
    old = c.execute("select e.* from production_work_entries e where substr(e.work_date,1,7)=? and e.active=1 and e.source like 'HISTORICAL%' and e.notes=?", (ym, CORR)).fetchall()
    old_tot = collections.defaultdict(float)
    for r in old:
        if code_of[r['weee_category_id']] in mapped:
            old_tot[code_of[r['weee_category_id']]] += float(r['weight_kg'])
            c.execute('delete from production_work_entries where id=?', (r['id'],)); stats['διαγράφηκαν παλιές διορθώσεις'] += 1
    for code, v in sorted(corr.items()):
        if abs(v) < 0.0005: continue
        r = dict(tpl); r.update(id=str(uuid.uuid4()), work_date=f'{ym}-{last:02d} 12:00:00.000000', weee_category_id=cat[code], weight_kg=round(v, 3), supplier_group='OTHER', source=SOURCE[mm], notes=CORR, created_at=now, updated_at=now, active=1)
        cols = list(r); c.execute(f'insert into production_work_entries ({",".join(cols)}) values ({",".join("?" * len(cols))})', [r[x] for x in cols]); stats['νέες διορθώσεις (Λοιποί)'] += 1
    for code in set(old_tot) | set(corr):
        d = corr.get(code, 0) - old_tot.get(code, 0)
        if abs(d) > 0.5: chg[(mm, code)] = (round(old_tot.get(code, 0), 1), round(corr.get(code, 0), 1))
    # έλεγχος με τη γραμμή «ΣΥΝΟΛΟ ΜΗΝΑ» του Excel: ημερήσια (Λοιποί+HERMES) + διορθώσεις = ΣΥΝΟΛΟ ΜΗΝΑ ανά κατηγορία
    for code, tv in tots.items():
        mine = sum(v for (d, cd, g), v in dated.items() if cd == code) + corr.get(code, 0)
        if abs(mine - tv) > 0.5: chk.append((mm, code, round(tv, 1), round(mine, 1)))
print('στατιστικά:', dict(stats)); print('προβλήματα:', problems)
print('κατηγορίες όπου το ΣΥΝΟΛΟ διορθώσεων αλλάζει (παλιό, Excel):', sorted(chg.items()))
print('διαφορές από τη γραμμή ΣΥΝΟΛΟ ΜΗΝΑ του Excel (μήνας, κατηγορία, Excel, δικό μου):', chk)
if APPLY and not problems:
    c.execute('insert into audit_events (id,user_id,entity_type,entity_id,action,old_values,new_values,reason,created_at) values (?,?,?,?,?,?,?,?,?)',
              (str(uuid.uuid4()), 'a448f4d4-b94d-4287-87f2-144e85113901', 'production_work_entry', '', 'FIX_FILE_CORRECTIONS', '', json.dumps(dict(stats), ensure_ascii=False), 'Παραγωγή Ιαν–Οκτ: οι διορθώσεις αρχείου περνούν στους Λοιπούς', now))
    c.commit(); print('ΕΦΑΡΜΟΣΤΗΚΕ')
else:
    c.rollback(); print('ΔΕΝ εφαρμόστηκε (rollback)' + ('' if APPLY else ' — δοκιμαστική εκτέλεση'))
