"""U1: Υποκατηγορίες ΑΗΗΕ — ανάλυση ανά υποκατηγορία των παραλαβών Οκτωβρίου 2026 που είχαν περαστεί μόνο στον κωδικό της κατηγορίας.

Πηγή (ΜΟΝΟ ανάγνωση): «Απόθεμα ΑΗΗΕ 2026\\ΑΠΟΘΕΜΑ ΤΡΕΧOΝ 10.2026 - ΕΝΤΥΠΟ 9.xlsx» (ημερήσια φύλλα, στήλη ανά φορτίο, γραμμές ανά κατηγορία/υποκατηγορία).
Για κάθε φορτίο της βάσης με εγγραφή ταξινόμησης στον κωδικό οικογένειας (4Δ0000, 4Ι0000, 4Λ0000, 5Δ0000, 5Ι2000, 6Α0000) βρίσκεται η στήλη του Excel με το ίδιο φορτίο
(ίδια ημέρα, ίδια βάρη οικογένειας, πλησιέστερο καθαρό βάρος) και η εγγραφή σπάει σε υποκατηγορίες που ΥΠΑΡΧΟΥΝ ΗΔΗ στο μητρώο (weee_categories με parent_code).
Το σύνολο της κατηγορίας ΔΕΝ αλλάζει (το άθροισμα των νέων εγγραφών = το παλιό βάρος). Ό,τι δεν αντιστοιχεί σε υπάρχουσα υποκατηγορία μένει στην κατηγορία («Χωρίς υποκατηγορία»).
Δεν δημιουργεί ποτέ νέες υποκατηγορίες. Χρήση: python u1_subcategories_oct.py <db> [--apply]"""
import sys, os, re, shutil, glob, uuid, unicodedata, sqlite3, collections, json
from datetime import datetime, timezone
sys.stdout.reconfigure(encoding='utf-8')
import openpyxl

DBF = sys.argv[1]; APPLY = '--apply' in sys.argv
SRC = r'C:\Users\paran\Desktop\HER app\Files\Απόθεμα ΑΗΗΕ 2026'
MONTH = '10'
FAM = ('4Δ0000', '4Ι0000', '4Λ0000', '5Δ0000', '5Ι2000', '6Α0000')
LOOK = dict(zip('ΑΒΕΖΗΙΚΜΝΟΡΤΥΧ', 'ABEZHIKMNOPTYX'))


def nm(s):
    t = unicodedata.normalize('NFD', str(s or '').upper()); t = ''.join(c for c in t if not unicodedata.combining(c))
    t = ''.join(LOOK.get(c, c) for c in t)
    return re.sub(r'[^0-9A-Z]', '', t)


c = sqlite3.connect(DBF, timeout=60); c.row_factory = sqlite3.Row
cats = {r['id']: dict(r) for r in c.execute('select id,code,description_el,parent_code from weee_categories')}
cat_id = {r['code']: r['id'] for r in cats.values()}
subs = [r for r in cats.values() if r['parent_code']]
by_parent = collections.defaultdict(list)
for r in subs: by_parent[r['parent_code']].append(r)


def sub_for(group, label):
    n = nm(label)
    if len(n) < 3: return None
    for p, lst in by_parent.items():
        if p[0] != group: continue
        for r in lst:
            nn = nm(r['description_el'])
            if n == nn or nn.startswith(n[:14]) or n.startswith(nn[:14]): return r
    return None


def read_excel():
    f = [x for x in glob.glob(SRC + f'\\ΑΠΟΘΕΜΑ ΤΡΕΧOΝ {MONTH}.2026*.xlsx') if '~$' not in x][0]
    t = os.path.join(os.environ['TEMP'], f'u1_{MONTH}.xlsx'); shutil.copy(f, t)   # αντίγραφο: το αρχικό δεν αγγίζεται
    wb = openpyxl.load_workbook(t, read_only=True, data_only=True)
    days = {}
    for ws in wb.worksheets:
        m = re.match(r'^(\d\d)\.(\d\d)', ws.title)
        if not m: continue
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
        for k, ci in enumerate(cols):
            kg = rows[4][ci + 1] if len(rows[4]) > ci + 1 else None
            if rows[1][ci + 1] is None and kg in (None, 0, ''): continue
            if not isinstance(kg, (int, float)): kg = 0
            fam = collections.defaultdict(dict)   # οικογένεια -> {sub_code: (βάρος, τεμ)}
            for group, code, label, r in lines:
                w = r[ci] if ci < len(r) else None
                if not isinstance(w, (int, float)) or not w: continue
                pc = r[ci + 1] if ci + 1 < len(r) and isinstance(r[ci + 1], (int, float)) else None
                s = sub_for(group, label)
                if s is not None:
                    d = fam[s['parent_code']]; o = d.get(s['code'], (0.0, 0)); d[s['code']] = (o[0] + float(w), o[1] + int(pc or 0))
                elif code in FAM:
                    fam[code]['?' + label] = (float(w), int(pc or 0))   # δεν αντιστοιχεί σε υπάρχουσα υποκατηγορία
            loads.append(dict(k=k, kg=float(kg or 0), sup=rows[1][ci + 1], bin=rows[3][ci + 1], fam=dict(fam)))
        days[iso] = loads
    return days


xl = read_excel()
unknown = collections.Counter()
for iso, loads in xl.items():
    for L in loads:
        for p, d in L['fam'].items():
            for k, (w, pc) in d.items():
                if k.startswith('?'): unknown[(p, k[1:])] += w

# --- φορτία βάσης με εγγραφές στον κωδικό οικογένειας ---
q = """select substr(t.receipt_date,1,10) d, l.id lid, l.order_number, l.net_weight, s.id sid, t.receipt_date from inbound_loads l join inbound_trips t on t.id=l.trip_id
       join sorting_sessions s on s.inbound_load_id=l.id where t.deleted_at is null and t.receipt_date>=? and t.receipt_date<?"""
loads_db = []
for r in c.execute(q, (f'2026-{MONTH}-01', f'2026-{int(MONTH)+1:02d}-01' if MONTH != '12' else '2027-01-01')):
    ents = {}
    for e in c.execute("select e.*,c.code from sorting_entries e join weee_categories c on c.id=e.weee_category_id where e.session_id=? and c.code in (%s)" % ','.join('?' * len(FAM)), (r['sid'],) + FAM):
        d_ = dict(e); d_.pop('code', None); ents[e['code']] = d_
    if ents: loads_db.append(dict(r, ents=ents))
print('φορτία με εγγραφές στον κωδικό οικογένειας:', len(loads_db), '· εγγραφές:', sum(len(x['ents']) for x in loads_db))

# --- αντιστοίχιση ανά ημέρα ---
plan = []; unmatched = []; ties = 0
byday = collections.defaultdict(list)
for L in loads_db: byday[L['d']].append(L)
for d, lst in sorted(byday.items()):
    used = set(); cand = []
    for i, L in enumerate(lst):
        for j, X in enumerate(xl.get(d, [])):
            ok = True
            for p, e in L['ents'].items():
                w = float(e['approved_weight'] if e['approved_weight'] is not None else e['raw_weight'] or 0)
                sx = sum(v[0] for v in X['fam'].get(p, {}).values())
                if abs(sx - w) > 1.0: ok = False; break
            if ok:
                for p, dd in X['fam'].items():   # η στήλη δεν πρέπει να έχει οικογένειες που λείπουν από το φορτίο
                    if p not in L['ents'] and sum(v[0] for v in dd.values()) > 0.5: ok = False; break
            if ok: cand.append((abs(X['kg'] - float(L['net_weight'] or 0)), i, j))
    cand.sort(); usedL = set(); usedX = set(); pairs = {}
    for cost, i, j in cand:
        if i in usedL or j in usedX: continue
        same = [x for x in cand if x[1] == i and x[0] == cost and x[2] not in usedX]
        if len(same) > 1: ties += 1
        pairs[i] = j; usedL.add(i); usedX.add(j)
    for i, L in enumerate(lst):
        if i in pairs: plan.append((L, xl[d][pairs[i]]))
        else: unmatched.append(L)
print('αντιστοιχίστηκαν', len(plan), '· χωρίς αντιστοίχιση', len(unmatched), '· ισοπαλίες (ίδια βάρη)', ties)
for L in unmatched[:20]: print('  χωρίς αντιστοίχιση:', L['d'], L['order_number'], L['net_weight'], {p: round(float(e['approved_weight'] or e['raw_weight'] or 0)) for p, e in L['ents'].items()})
print('υποκατηγορίες του Excel που ΔΕΝ υπάρχουν στο μητρώο (μένουν στην κατηγορία):', dict(unknown))

# --- εκτέλεση ---
loc_cols = None
stats = collections.Counter(); before = {}
def snap():
    out = collections.defaultdict(float)
    for r in c.execute("select substr(t.receipt_date,1,7) m,cc.code,sum(coalesce(e.approved_weight,e.raw_weight,0)) w from sorting_entries e join weee_categories cc on cc.id=e.weee_category_id join sorting_sessions s on s.id=e.session_id join inbound_loads l on l.id=s.inbound_load_id join inbound_trips t on t.id=l.trip_id where t.deleted_at is null and t.receipt_date>='2026-10-01' group by 1,2"):
        p = cats[cat_id[r['code']]]['parent_code'] or r['code']; out[(r['m'], p)] += r['w']
    return out
before = snap()
c.execute('begin')
now = datetime.now(timezone.utc).isoformat(sep=' ')
def clone(table, row, **over):
    d = dict(row); d.update(over); cols = list(d)
    c.execute(f'insert into {table} ({",".join(cols)}) values ({",".join("?" * len(cols))})', [d[k] for k in cols])
for L, X in plan:
    for p, e in L['ents'].items():
        w = float(e['approved_weight'] if e['approved_weight'] is not None else e['raw_weight'] or 0)
        parts = {k: v for k, v in X['fam'].get(p, {}).items() if not k.startswith('?') and v[0] > 0}
        if not parts: continue
        sw = sum(v[0] for v in parts.values()); rest = round(w - sw, 3)
        if rest < -1.0: stats['παραλείφθηκε (Excel > βάρος)'] += 1; continue
        pcs_total = int(e['piece_count'] or 0); lot = c.execute('select * from weee_stock_lots where source_sorting_entry_id=?', (e['id'],)).fetchone()
        mv = c.execute("select * from stock_movements where lot_id=? and movement_type='SORTING_IN'", (lot['id'],)).fetchone()
        items = sorted(parts.items())
        # τεμάχια: από το Excel όταν το άθροισμα ταιριάζει, αλλιώς αναλογικά στο βάρος
        px = [v[1] for _, v in items]
        if sum(px) != pcs_total: px = [round(pcs_total * v[0] / sw) for _, v in items]
        first = True
        for (sc, (sw_i, _)), pc_i in zip(items, px):
            wi = round(sw_i, 3)
            if first:   # η υπάρχουσα εγγραφή γίνεται η πρώτη υποκατηγορία
                c.execute('update sorting_entries set weee_category_id=?,raw_weight=?,approved_weight=?,piece_count=?,notes=?,updated_at=? where id=?',
                          (cat_id[sc], wi, wi, pc_i, (e['notes'] or '') + ' · ανάλυση υποκατηγορίας από «Απόθεμα ΑΗΗΕ 2026»', now, e['id']))
                c.execute('update weee_stock_lots set weee_category_id=?,original_weight=?,available_weight=?,piece_count=?,updated_at=? where id=?', (cat_id[sc], wi, wi, pc_i, now, lot['id']))
                c.execute('update stock_movements set weight=? where id=?', (wi, mv['id']))
                first = False
            else:
                eid, lid, mid = str(uuid.uuid4()), str(uuid.uuid4()), str(uuid.uuid4())
                clone('sorting_entries', e, id=eid, weee_category_id=cat_id[sc], raw_weight=wi, approved_weight=wi, piece_count=pc_i, updated_at=now)
                clone('weee_stock_lots', lot, id=lid, source_sorting_entry_id=eid, weee_category_id=cat_id[sc], original_weight=wi, available_weight=wi, piece_count=pc_i, updated_at=now)
                clone('stock_movements', mv, id=mid, lot_id=lid, weight=wi)
        if rest > 0.5:   # υπόλοιπο που δεν ανήκει σε γνωστή υποκατηγορία: μένει στην κατηγορία («Χωρίς υποκατηγορία»)
            eid, lid, mid = str(uuid.uuid4()), str(uuid.uuid4()), str(uuid.uuid4()); pr = max(0, pcs_total - sum(px))
            clone('sorting_entries', e, id=eid, weee_category_id=cat_id[p], raw_weight=rest, approved_weight=rest, piece_count=pr, updated_at=now)
            clone('weee_stock_lots', lot, id=lid, source_sorting_entry_id=eid, weee_category_id=cat_id[p], original_weight=rest, available_weight=rest, piece_count=pr, updated_at=now)
            clone('stock_movements', mv, id=mid, lot_id=lid, weight=rest)
            stats['υπόλοιπο στην κατηγορία'] += 1
        stats['εγγραφές που σπάστηκαν'] += 1; stats['νέες γραμμές υποκατηγοριών'] += len(items)
after = snap()
bad = [(k, round(before[k], 3), round(after.get(k, 0), 3)) for k in before if abs(before[k] - after.get(k, 0)) > 0.01]
print('στατιστικά:', dict(stats)); print('σύνολα οικογένειας που άλλαξαν (πρέπει να είναι κενό):', bad)
left = c.execute(f"select count(*) from sorting_entries e join weee_categories cc on cc.id=e.weee_category_id join sorting_sessions s on s.id=e.session_id join inbound_loads l on l.id=s.inbound_load_id join inbound_trips t on t.id=l.trip_id where t.deleted_at is null and cc.code in ({','.join('?' * len(FAM))}) and t.receipt_date>='2026-10-01'", FAM).fetchone()[0]
print('εγγραφές που έμειναν στον κωδικό οικογένειας (Οκτώβριος+):', left)
if APPLY and not bad:
    c.execute('insert into audit_events (id,user_id,entity_type,entity_id,action,old_values,new_values,reason,created_at) values (?,?,?,?,?,?,?,?,?)',
              (str(uuid.uuid4()), 'a448f4d4-b94d-4287-87f2-144e85113901', 'sorting_entry', '', 'SPLIT_SUBCATEGORIES', '', json.dumps(dict(stats), ensure_ascii=False), 'Οκτώβριος 2026: ανάλυση ανά υποκατηγορία από «Απόθεμα ΑΗΗΕ 2026»', now))
    c.commit(); print('ΕΦΑΡΜΟΣΤΗΚΕ')
else:
    c.rollback(); print('ΔΕΝ εφαρμόστηκε (rollback)' + ('' if APPLY else ' — δοκιμαστική εκτέλεση'))
