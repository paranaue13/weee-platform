"""V1: Παραλαβές ΑΗΗΕ που λείπουν από τη βάση ενώ υπάρχουν στα αρχεία «Απόθεμα ΑΗΗΕ 2026» (Ιανουάριος–Οκτώβριος· ο Νοέμβριος ΔΕΝ περνιέται).

Πηγή (ΜΟΝΟ ανάγνωση, από αντίγραφο): ημερήσια φύλλα, μία στήλη ανά φορτίο, γραμμές ανά κατηγορία/υποκατηγορία.
Για κάθε φορτίο του Excel:
  1. αν υπάρχει ήδη ενεργό φορτίο στη βάση με τα ίδια βάρη → δεν γίνεται τίποτα (δεν δημιουργούνται διπλότυπα)·
  2. αλλιώς, ενεργό φορτίο της ίδιας ημέρας/προμηθευτή χωρίς εγγραφές (καθαρό 0) → συμπληρώνεται·
  3. αλλιώς, ΔΙΑΓΡΑΜΜΕΝΟ φορτίο της ίδιας ημέρας/προμηθευτή/κιλών → ξαναενεργοποιείται και συμπληρώνεται (ένα από κάθε ζεύγος διπλών)·
  4. αλλιώς δημιουργείται νέο φορτίο (προμηθευτής/μεταφορέας ΜΟΝΟ από υπάρχοντες οργανισμούς).
Εξαιρέσεις: 19/10 ΟΤΕ 8.830 kg (διπλότυπο που διαγράφηκε)· οτιδήποτε αμφίσημο παραλείπεται και αναφέρεται.
Μόνο υποκατηγορίες που ΥΠΑΡΧΟΥΝ στο μητρώο (weee_categories με parent_code)· ό,τι δεν αντιστοιχεί μένει στην κατηγορία («Χωρίς υποκατηγορία»).
Χρήση: python v1_missing_receipts.py <db> [--apply]"""
import sys, os, re, glob, shutil, uuid, json, unicodedata, sqlite3, collections
from datetime import datetime, timezone
sys.stdout.reconfigure(encoding='utf-8')
import openpyxl

DBF = sys.argv[1]; APPLY = '--apply' in sys.argv
SRC = r'C:\Users\paran\Desktop\HER app\Files\Απόθεμα ΑΗΗΕ 2026'
MONTHS = ['%02d' % k for k in range(1, 11)]
LOOK = dict(zip('ΑΒΕΖΗΙΚΜΝΟΡΤΥΧ', 'ABEZHIKMNOPTYX'))
ADMIN = 'a448f4d4-b94d-4287-87f2-144e85113901'
EXCLUDE = {('2026-10-19', 'ΟΤΕ', 8830.0)}   # διπλότυπο που διαγράφηκε


def nm(s):
    t = unicodedata.normalize('NFD', str(s or '').upper()); t = ''.join(c for c in t if not unicodedata.combining(c))
    t = ''.join(LOOK.get(c, c) for c in t)
    return re.sub(r'[^0-9A-Z]', '', t)


c = sqlite3.connect(DBF, timeout=60); c.row_factory = sqlite3.Row
cats = {r['id']: dict(r) for r in c.execute('select id,code,description_el,parent_code from weee_categories')}
cat_id = {r['code']: r['id'] for r in cats.values()}
code_set = set(cat_id)
by_parent = collections.defaultdict(list)
for r in cats.values():
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


def read_month(mm):
    f = [x for x in glob.glob(SRC + f'\\ΑΠΟΘΕΜΑ ΤΡΕΧOΝ {mm}.2026*.xlsx') if '~$' not in x][0]
    t = os.path.join(os.environ['TEMP'], f'v1_{mm}.xlsx'); shutil.copy(f, t)
    wb = openpyxl.load_workbook(t, read_only=True, data_only=True); days = {}
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
            kg = rows[4][ci + 1] if len(rows[4]) > ci + 1 else None; sup = rows[1][ci + 1]
            if sup is None and kg in (None, 0, ''): continue
            vec = collections.defaultdict(float); pcs = collections.defaultdict(int); unk = []
            for group, code, label, r in lines:
                w = r[ci] if ci < len(r) else None
                if not isinstance(w, (int, float)) or not w: continue
                pc = r[ci + 1] if ci + 1 < len(r) and isinstance(r[ci + 1], (int, float)) else 0
                s = sub_for(group, label)
                key = s['code'] if s else (code if code in code_set else None)
                if key is None:
                    if code in code_set or code: key = code if code in code_set else None
                if key is None: unk.append((label, float(w))); continue
                vec[key] += float(w); pcs[key] += int(pc)
            loads.append(dict(day=iso, k=k, sup=sup, car=rows[2][ci + 1], bin=rows[3][ci + 1], kg=float(kg) if isinstance(kg, (int, float)) else 0.0, vec=dict(vec), pcs=dict(pcs), unk=unk))
        days[iso] = loads
    return days


def fam(v):
    o = collections.defaultdict(float)
    for k, w in v.items():
        p = cats[cat_id[k]]['parent_code'] if k in cat_id else None
        o[p or k] += w
    return dict(o)


def eq(a, b): return all(abs(a.get(k, 0) - b.get(k, 0)) <= 1.0 for k in set(a) | set(b))


def db_loads(day):
    out = []
    for l in c.execute("select l.id lid,l.order_number,l.net_weight,l.supplier_id,l.incoming_container_number cont,l.status,t.id tid,t.deleted_at,t.carrier_id,s.id sid,t.receipt_date from inbound_loads l join inbound_trips t on t.id=l.trip_id left join sorting_sessions s on s.inbound_load_id=l.id where substr(t.receipt_date,1,10)=?", (day,)):
        vec = collections.defaultdict(float)
        if l['sid']:
            for e in c.execute("select cc.code,coalesce(e.approved_weight,e.raw_weight,0) w from sorting_entries e join weee_categories cc on cc.id=e.weee_category_id where e.session_id=?", (l['sid'],)): vec[e['code']] += float(e['w'])
        out.append(dict(l, vec=dict(vec)))
    return out


# --- οργανισμοί: όνομα αρχείου → id (από ήδη ταιριασμένα φορτία + ονόματα Μητρώων)· ΔΕΝ δημιουργούνται νέοι ---
orgs = {}
for o in c.execute('select id,legal_name,trade_name from organizations'):
    orgs.setdefault(nm(o['legal_name']), o['id']); orgs.setdefault(nm(o['trade_name']), o['id'])
sup_map = collections.defaultdict(collections.Counter); car_map = collections.defaultdict(collections.Counter)

xl = {}
for mm in MONTHS: xl.update(read_month(mm))
unmatched = []; stats = collections.Counter(); problems = []; plan = []
for iso, loads in sorted(xl.items()):
    dbl = db_loads(iso); act = [x for x in dbl if not x['deleted_at']]; used = set()
    for X in loads:
        sx = sum(X['vec'].values()); m = None
        for i, L in enumerate(act):
            if i in used or float(L['net_weight'] or 0) == 0 and not L['vec']: continue
            sl = sum(L['vec'].values())
            if (abs(float(L['net_weight'] or 0) - X['kg']) <= 15 or abs(sl - sx) <= 1) and (eq(L['vec'], X['vec']) or eq(fam(L['vec']), fam(X['vec']))):
                m = i; break
        if m is not None:
            used.add(m); L = act[m]
            if L['carrier_id']: car_map[nm(X['car'])][L['carrier_id']] += 1
            sup_map[nm(X['sup'])][L['supplier_id']] += 1
        else: unmatched.append((iso, X, dbl, act, used))


org_raw = {o['id']: (str(o['legal_name']).upper(), str(o['trade_name']).upper()) for o in c.execute('select id,legal_name,trade_name from organizations')}
org_nm = {o['id']: (nm(o['legal_name']), nm(o['trade_name'])) for o in c.execute('select id,legal_name,trade_name from organizations')}


def same_org(oid, name):
    k = nm(name)
    if 'METRO' in str(name).upper() and any('ΜΕΤΡΟ' in (o or '') for o in org_raw.get(oid, ())): return True   # ίδια εταιρεία: «METRO Α.Ε.Β.Ε.» (λατινικά) = «ΜΕΤΡΟ ΑΕΒΕ» (ελληνικά)
    return any(x and (x == k or (len(k) >= 8 and (x.startswith(k[:14]) or k.startswith(x[:14])))) for x in org_nm.get(oid, ()))


def org_for(name, mp):
    k = nm(name)
    if k in mp: return mp[k].most_common(1)[0][0]
    if k in orgs: return orgs[k]
    for kk, v in orgs.items():
        if len(k) >= 8 and (kk.startswith(k[:14]) or k.startswith(kk[:14])): return v
    return None


for iso, X, dbl, act, used in unmatched:
    sup_id = org_for(X['sup'], sup_map)
    if iso == '2026-10-19' and abs(X['kg'] - 8830) < 1 and 'ΤΗΛΕΠΙΚΟΙΝΩΝΙΩΝ' in str(X['sup']).upper():
        stats['εξαιρέθηκε (διπλότυπο)'] += 1; print(f'ΕΞΑΙΡΕΣΗ  {iso} {str(X["sup"])[:30]} {X["kg"]} (διπλότυπο που διαγράφηκε)'); continue
    if not X['vec']: problems.append((iso, X['sup'], X['kg'], 'χωρίς γραμμές ΑΗΗΕ')); continue
    if sup_id is None: problems.append((iso, X['sup'], X['kg'], 'άγνωστος προμηθευτής (δεν δημιουργείται)')); continue
    # 2. κενό ενεργό φορτίο ίδιου προμηθευτή
    empty = [L for i, L in enumerate(act) if i not in used and (L['supplier_id'] == sup_id or same_org(L['supplier_id'], X['sup'])) and not L['vec'] and float(L['net_weight'] or 0) <= 15]
    if len(empty) == 1:
        plan.append(('fill', iso, X, empty[0])); used.add(act.index(empty[0])); continue
    if len(empty) > 1:
        problems.append((iso, X['sup'], X['kg'], f'αμφίσημο: {len(empty)} κενά φορτία του ίδιου προμηθευτή')); continue
    # 3. διαγραμμένο φορτίο ίδιου προμηθευτή/κιλών
    dele = [L for L in dbl if L['deleted_at'] and (L['supplier_id'] == sup_id or same_org(L['supplier_id'], X['sup'])) and abs(float(L['net_weight'] or 0) - X['kg']) <= 15]
    taken = {p[3]['lid'] for p in plan if p[0] == 'restore'}
    dele = [L for L in dele if L['lid'] not in taken]
    if dele:
        dele.sort(key=lambda L: str(L['deleted_at']), reverse=True)                       # πιο πρόσφατα διαγραμμένο πρώτο
        dele.sort(key=lambda L: (abs(float(L['net_weight'] or 0) - X['kg']), 0 if L['sid'] else 1))   # ίδια κιλά, με συνεδρία ταξινόμησης (σταθερή ταξινόμηση)
        best = dele[0]
        same = [L for L in dele if abs(float(L['net_weight'] or 0) - X['kg']) == abs(float(best['net_weight'] or 0) - X['kg'])]
        plan.append(('restore', iso, X, best, len(same))); continue
    # ίδια ημέρα και ίδια κιλά με διαγραμμένο φορτίο ΑΛΛΟΥ προμηθευτή: αμφίσημο, δεν περνιέται (μπορεί να είναι το ίδιο φορτίο με άλλο όνομα)
    amb = [L for L in dbl if L['deleted_at'] and abs(float(L['net_weight'] or 0) - X['kg']) <= 15 and not any(p[0] == 'restore' and p[3]['lid'] == L['lid'] for p in plan)]
    if amb:
        problems.append((iso, X['sup'], X['kg'], 'αμφίσημο: υπάρχει διαγραμμένο φορτίο ίδιας ημέρας/κιλών με ΑΛΛΟ προμηθευτή (' + ', '.join(f"{L['order_number']}/{(c.execute('select legal_name from organizations where id=?', (L['supplier_id'],)).fetchone() or ['?'])[0][:30]}" for L in amb) + ')')); continue
    # 4. νέο φορτίο
    car_id = org_for(X['car'], car_map)
    plan.append(('create', iso, X, sup_id, car_id))

print('Σχέδιο:', collections.Counter(p[0] for p in plan))
for p in plan:
    X = p[2]
    extra = ''
    if p[0] == 'restore': extra = f" ← διαγραμμένο {p[3]['order_number']} ({p[3]['net_weight']} kg, διαγρ. {str(p[3]['deleted_at'])[:10]}){' [διπλό ζεύγος]' if p[4] > 1 else ''}"
    if p[0] == 'fill': extra = f" ← κενό φορτίο {p[3]['order_number']}"
    if p[0] == 'create': extra = f" · μεταφορέας {'OK' if p[4] else 'ΧΩΡΙΣ (κενός)'}"
    print(f'  {p[0].upper():8s} {p[1]} {str(X["sup"])[:32]:32s} κάδος {X["bin"]} · {X["kg"]:.0f} kg · ΑΗΗΕ {sum(X["vec"].values()):.0f}{extra}')
for pr in problems: print('ΠΡΟΒΛΗΜΑ/ΠΑΡΑΛΕΙΨΗ:', pr)

# --- εκτέλεση ---
loc = c.execute("select id from inventory_locations where code='WEEE_MAIN'").fetchone()['id']
tpl_load = c.execute("select l.* from inbound_loads l where order_number='812304'").fetchone()
tpl_trip = c.execute('select * from inbound_trips where id=?', (tpl_load['trip_id'],)).fetchone()
tpl_ses = c.execute('select * from sorting_sessions where inbound_load_id=?', (tpl_load['id'],)).fetchone()
tpl_ent = c.execute('select * from sorting_entries where session_id=? limit 1', (tpl_ses['id'],)).fetchone()
tpl_lot = c.execute('select * from weee_stock_lots where source_sorting_entry_id=?', (tpl_ent['id'],)).fetchone()
tpl_mv = c.execute('select * from stock_movements where lot_id=? limit 1', (tpl_lot['id'],)).fetchone()
now = datetime.now(timezone.utc).isoformat(sep=' ')


def clone(table, row, **over):
    d = dict(row); d.update(over); cols = list(d)
    c.execute(f'insert into {table} ({",".join(cols)}) values ({",".join("?" * len(cols))})', [d[k] for k in cols])


def snap_month():
    out = collections.defaultdict(float)
    for r in c.execute("select substr(t.receipt_date,1,7) m,cc.code,sum(coalesce(e.approved_weight,e.raw_weight,0)) w from sorting_entries e join weee_categories cc on cc.id=e.weee_category_id join sorting_sessions s on s.id=e.session_id join inbound_loads l on l.id=s.inbound_load_id join inbound_trips t on t.id=l.trip_id where t.deleted_at is null group by 1,2"): out[(r['m'], r['code'])] += r['w']
    return out


def add_entries(sid, lid, dt, X):
    for code, w in sorted(X['vec'].items()):
        eid, lotid, mid = str(uuid.uuid4()), str(uuid.uuid4()), str(uuid.uuid4()); pcv = X['pcs'].get(code) or None
        clone('sorting_entries', tpl_ent, id=eid, session_id=sid, weee_category_id=cat_id[code], collection_medium_id=None, entry_type='HISTORICAL', raw_weight=w, approved_weight=w, piece_count=pcv,
              notes='Εισαγωγή από «Απόθεμα ΑΗΗΕ 2026» (xlsx)', created_at=dt, updated_at=dt)
        clone('weee_stock_lots', tpl_lot, id=lotid, source_sorting_entry_id=eid, inbound_load_id=lid, weee_category_id=cat_id[code], collection_medium_id=None, location_id=loc, original_weight=w, available_weight=w,
              piece_count=pcv, status='AVAILABLE', created_at=dt, updated_at=dt)
        clone('stock_movements', tpl_mv, id=mid, lot_id=lotid, weight=w, reason='Ιστορική εισαγωγή από «Απόθεμα ΑΗΗΕ 2026» (xlsx)', created_at=dt, transfer_id=None)


def clear_load(sid):
    """Σβήνει τις παλιές εγγραφές (ΜΟΝΟ φορτίου που ξαναενεργοποιείται· δεν έχουν χρησιμοποιηθεί πουθενά) πριν μπουν οι σωστές από το Excel."""
    for e in c.execute('select id from sorting_entries where session_id=?', (sid,)).fetchall():
        for lt in c.execute('select id from weee_stock_lots where source_sorting_entry_id=?', (e['id'],)).fetchall():
            if c.execute('select count(*) from production_transfer_items where stock_lot_id=?', (lt['id'],)).fetchone()[0]: raise RuntimeError('παρτίδα σε μεταφορά παραγωγής')
            c.execute('delete from stock_movements where lot_id=?', (lt['id'],)); c.execute('delete from weee_stock_lots where id=?', (lt['id'],))
        c.execute('delete from sorting_adjustments where sorting_entry_id=?', (e['id'],)); c.execute('delete from sorting_entries where id=?', (e['id'],))


before = snap_month()
c.execute('begin')
n_seq = 0
for p in plan:
    kind, iso, X = p[0], p[1], p[2]
    dt = f'{iso} 12:00:00.000000'; net = round(sum(X['vec'].values()), 3)
    if kind in ('fill', 'restore'):
        L = p[3]
        if kind == 'restore':
            c.execute('update inbound_trips set deleted_at=NULL,status=?,updated_at=? where id=?', ('CLOSED', now, L['tid']))
        c.execute('update inbound_loads set net_weight=?,status=?,updated_at=? where id=?', (net, 'CLOSED', now, L['lid']))
        sid = L['sid']
        if sid:
            clear_load(sid)
            c.execute('update sorting_sessions set status=?,final_sorting_weight=?,final_difference=0,updated_at=? where id=?', ('CLOSED', net, now, sid))
        else:
            sid = str(uuid.uuid4())
            clone('sorting_sessions', tpl_ses, id=sid, inbound_load_id=L['lid'], status='CLOSED', started_at=dt, sorting_confirmed_at=dt, logistics_confirmed_at=dt, final_sorting_weight=net, final_difference=0,
                  foreign_materials=0, foreign_weight=0, special_waste=0, special_waste_weight=0, created_at=dt, updated_at=dt)
        add_entries(sid, L['lid'], dt, X); stats[kind] += 1
    else:
        sup_id, car_id = p[3], p[4]
        n_seq += 1; rn = f'XL-{iso.replace("-", "")}-{n_seq:02d}'
        cont = str(int(X['bin'])) if isinstance(X['bin'], (int, float)) and X['bin'] >= 10000 else None
        extras = {'sealNo': '', 'weighbridgeNo': '', 'reportDate': iso, 'dispatchNo': '', 'foreignMaterials': False, 'foreignWeight': 0, 'specialWaste': False, 'specialWasteWeight': 0, 'dppNo': '',
                  'checkSpecial': False, 'checkKday': False, 'checkNonInteger': False, 'loadPure': False, 'sourceTimeKnown': False, 'sourceFile': 'Απόθεμα ΑΗΗΕ 2026', 'sourceSheet': iso[8:10] + '.' + iso[5:7]}
        tid, lid, sid = str(uuid.uuid4()), str(uuid.uuid4()), str(uuid.uuid4())
        clone('inbound_trips', tpl_trip, id=tid, receipt_number=rn, receipt_type='CONTAINER' if cont else tpl_trip['receipt_type'], receipt_date=dt, carrier_id=car_id, vehicle_registration=None, status='CLOSED',
              created_by=ADMIN, notes='__EXTRA__' + json.dumps(extras, ensure_ascii=False, separators=(',', ':')) + '\n', created_at=dt, updated_at=dt, deleted_at=None)
        clone('inbound_loads', tpl_load, id=lid, trip_id=tid, supplier_id=sup_id, order_number=None, incoming_container_number=cont, net_weight=net, status='CLOSED', ready_for_sorting_at=dt,
              dpp_number=None, weighbridge_number=None, dispatch_note_number=None, seal_number=None, created_at=dt, updated_at=dt)
        clone('sorting_sessions', tpl_ses, id=sid, inbound_load_id=lid, status='CLOSED', started_at=dt, sorting_confirmed_at=dt, logistics_confirmed_at=dt, final_sorting_weight=net, final_difference=0,
              foreign_materials=0, foreign_weight=0, special_waste=0, special_waste_weight=0, created_at=dt, updated_at=dt)
        add_entries(sid, lid, dt, X); stats['create'] += 1
after = snap_month()
print('στατιστικά:', dict(stats), '· προβλήματα:', len(problems))
chg = collections.defaultdict(float)
for k in set(before) | set(after): chg[k[0]] += after.get(k, 0) - before.get(k, 0)
print('μεταβολή kg ανά μήνα:', {m: round(v) for m, v in sorted(chg.items()) if abs(v) > 0.5})
if APPLY:
    c.execute('insert into audit_events (id,user_id,entity_type,entity_id,action,old_values,new_values,reason,created_at) values (?,?,?,?,?,?,?,?,?)',
              (str(uuid.uuid4()), ADMIN, 'inbound_load', '', 'IMPORT_MISSING_RECEIPTS', '', json.dumps(dict(stats), ensure_ascii=False), 'Παραλαβές που έλειπαν από το «Απόθεμα ΑΗΗΕ 2026» (Ιαν–Οκτ)', now))
    c.commit(); print('ΕΦΑΡΜΟΣΤΗΚΕ')
else:
    c.rollback(); print('ΔΕΝ εφαρμόστηκε (rollback) — δοκιμαστική εκτέλεση')
