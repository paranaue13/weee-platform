"""Συμπλήρωση Σεπτεμβρίου 2026 από τις ημερήσιες αναφορές (μορφή ΔΠΠ).

Συμπληρώνει τα φορτία που υπήρχαν «άδεια» (καθαρό 0, χωρίς εγγραφές ταξινόμησης) και προσθέτει τα φορτία που λείπουν.
Δεν αγγίζει φορτία που βρίσκονται σε εξέλιξη στην εφαρμογή (ΕΤΟΙΜΟ/ΣΕ ΤΑΞΙΝΟΜΗΣΗ κλπ).
Είσοδος: %TEMP%\\lm_test\\m09\\parsed.json (το φτιάχνει το mparse.py). Χρήση: python import_september_2026.py <db> [--apply]
"""
import os, sys, json, sqlite3, uuid, collections, re
from datetime import datetime, timezone
sys.stdout.reconfigure(encoding='utf-8')
DBF = sys.argv[1]; APPLY = '--apply' in sys.argv
T = os.path.join(os.environ['TEMP'], 'lm_test')
P = json.load(open(os.path.join(T, 'm09', 'parsed.json'), encoding='utf-8'))
ADMIN = 'a448f4d4-b94d-4287-87f2-144e85113901'
c = sqlite3.connect(DBF, timeout=60); c.row_factory = sqlite3.Row
def norm(s):
    t = str(s or '').upper()
    for a, b in (('Ϊ', 'Ι'), ('Ί', 'Ι'), ('Ή', 'Η'), ('Ά', 'Α'), ('Ό', 'Ο'), ('Έ', 'Ε'), ('Ύ', 'Υ'), ('Ώ', 'Ω'), ('Ϋ', 'Υ')): t = t.replace(a, b)
    return re.sub(r'[^0-9A-ZΑ-Ω]', '', t)
def fx(v):
    t = str(v if v is not None else '').split('.')[0].strip()
    return None if t in ('', '-', 'None') else t
# αντιστοίχιση ονομάτων αρχείου → οργανισμός, από φορτία που ήδη ταιριάζουν (όλοι οι μήνες)
sup_map = collections.defaultdict(collections.Counter); car_map = collections.defaultdict(collections.Counter)
db_by_order = {r['order_number']: r for r in c.execute("select l.order_number,l.supplier_id,t.carrier_id,t.receipt_type from inbound_loads l join inbound_trips t on t.id=l.trip_id")}
for m in ('02', '03', '04', '05', '06', '07', '08', '09'):
    pj = os.path.join(T, 'm' + m, 'parsed.json')
    if not os.path.exists(pj): continue
    for day, lst in json.load(open(pj, encoding='utf-8')).items():
        for r in lst:
            d = db_by_order.get(fx(r['order']))
            if d:
                sup_map[norm(r['supplier'])][d['supplier_id']] += 1; car_map[norm(r['carrier'])][d['carrier_id']] += 1
jp = os.path.join(T, 'jan', 'jan_parsed.json')
for day, lst in json.load(open(jp, encoding='utf-8')).items():
    for r in lst:
        d = db_by_order.get(fx(r['order']))
        if d: sup_map[norm(r['supplier'])][d['supplier_id']] += 1; car_map[norm(r['carrier'])][d['carrier_id']] += 1
orgs = {}
for o in c.execute('select id,legal_name,trade_name from organizations'):
    orgs.setdefault(norm(o['legal_name']), o['id']); orgs.setdefault(norm(o['trade_name']), o['id'])
sup_type = collections.defaultdict(collections.Counter)
for r in c.execute("select l.supplier_id,t.receipt_type from inbound_loads l join inbound_trips t on t.id=l.trip_id where l.incoming_container_number is null or l.incoming_container_number=''"):
    sup_type[r[0]][r[1]] += 1
def find_org(name, mp):
    k = norm(name)
    if k in mp: return mp[k].most_common(1)[0][0]
    return orgs.get(k)
cat_id = {r['code']: r['id'] for r in c.execute('select id,code from weee_categories')}
loc = c.execute("select id from inventory_locations where code='WEEE_MAIN'").fetchone()['id']
tpl_load = c.execute("select l.* from inbound_loads l where order_number='812304'").fetchone()
tpl_trip = c.execute('select * from inbound_trips where id=?', (tpl_load['trip_id'],)).fetchone()
tpl_ses = c.execute('select * from sorting_sessions where inbound_load_id=?', (tpl_load['id'],)).fetchone()
tpl_ent = c.execute('select * from sorting_entries where session_id=? limit 1', (tpl_ses['id'],)).fetchone()
tpl_lot = c.execute('select * from weee_stock_lots where source_sorting_entry_id=?', (tpl_ent['id'],)).fetchone()
tpl_mv = c.execute('select * from stock_movements where lot_id=? limit 1', (tpl_lot['id'],)).fetchone()
def clone(table, row, **over):
    d = dict(row); d.update(over)
    cols = list(d); c.execute(f'insert into {table} ({",".join(cols)}) values ({",".join("?" * len(cols))})', [d[k] for k in cols])
stats = collections.Counter(); problems = []
c.execute('begin')
def add_entries(ses_id, load_id, dt, cats):
    for code, (w, pc) in cats.items():
        if code not in cat_id: problems.append(('άγνωστη κατηγορία', code)); continue
        w = float(w); pcv = int(pc) if pc is not None else None
        e = str(uuid.uuid4()); l = str(uuid.uuid4())
        clone('sorting_entries', tpl_ent, id=e, session_id=ses_id, weee_category_id=cat_id[code], raw_weight=w, approved_weight=w, piece_count=pcv, created_at=dt, updated_at=dt, created_by=ADMIN)
        clone('weee_stock_lots', tpl_lot, id=l, source_sorting_entry_id=e, inbound_load_id=load_id, weee_category_id=cat_id[code], original_weight=w, available_weight=w, piece_count=pcv, created_at=dt, updated_at=dt)
        clone('stock_movements', tpl_mv, id=str(uuid.uuid4()), lot_id=l, weight=w, created_at=dt)
        stats['εγγραφές ταξινόμησης'] += 1
for day, lst in P.items():
    dd, mm, yy = day[:10].split('.'); iso = f'{yy}-{mm}-{dd}'; dt = iso + ' 12:00:00.000000'
    for r in lst:
        o = fx(r['order']); net = float(r['net'] or 0); catsum = sum(float(w) for w, _ in r['cats'].values())
        ex = db_by_order.get(o)
        if abs(catsum - net) > 0.5: problems.append(('άθροισμα κατηγοριών ≠ καθαρό', o, catsum, net)); continue
        fm = 'ΝΑΙ' if str(r['foreign_flag'] or '').strip().upper().startswith('Ν') else 'ΟΧΙ'
        sw = 'ΝΑΙ' if str(r['special'] or '').strip().upper().startswith('Ν') else 'ΟΧΙ'
        fw = float(r['foreign_w'] or 0); sww = float(r['special_w'] or 0)
        if ex:
            ld = c.execute('select l.*, (select count(*) from sorting_entries e join sorting_sessions s on s.id=e.session_id where s.inbound_load_id=l.id) as n from inbound_loads l where order_number=?', (o,)).fetchone()
            if not (ld['status'] == 'CLOSED' and not float(ld['net_weight'] or 0) and ld['n'] == 0): continue
            ses = c.execute('select * from sorting_sessions where inbound_load_id=?', (ld['id'],)).fetchone()
            c.execute('update inbound_loads set net_weight=? where id=?', (net, ld['id']))
            c.execute('update sorting_sessions set final_sorting_weight=?,foreign_materials=?,foreign_weight=?,special_waste=?,special_waste_weight=? where id=?', (net, fm, fw, sw, sww, ses['id']))
            add_entries(ses['id'], ld['id'], dt, r['cats']); stats['φορτία που συμπληρώθηκαν'] += 1; continue
        sup = find_org(r['supplier'], sup_map); car = find_org(r['carrier'], car_map)
        if not sup and norm(r['supplier']):
            tpl_org = c.execute("select * from organizations o where exists(select 1 from organization_roles r where r.organization_id=o.id and r.role='SUPPLIER') limit 1").fetchone()
            sup = str(uuid.uuid4()); nm = ' '.join(str(r['supplier']).split())
            clone('organizations', tpl_org, id=sup, legal_name=nm, trade_name=nm, tax_id=None, email=None, phone=None, galaxy_id=None, permit_number=None, permit_ada=None, active=1, created_at=dt, updated_at=dt)
            c.execute("insert into organization_roles (organization_id,role) values (?,'SUPPLIER')", (sup,))
            sup_map[norm(r['supplier'])][sup] += 1; stats['νέοι προμηθευτές'] += 1
        if not sup: problems.append(('άγνωστος προμηθευτής', o, r['supplier'])); continue
        if not car: problems.append(('άγνωστος μεταφορέας', o, r['carrier'])); continue
        cont = fx(r['container'])
        rtype = 'CONTAINER' if cont else (sup_type[sup].most_common(1)[0][0] if sup_type.get(sup) else 'SMALL_POINTS')
        if not cont and sup not in sup_type: stats['προμηθευτής χωρίς ιστορικό (μικρά σημεία)'] += 1
        extras = {'sealNo': fx(r['seal']) or '', 'weighbridgeNo': fx(r['zyg']) or '', 'reportDate': iso, 'dispatchNo': fx(r['dn']) or '', 'foreignMaterials': fm, 'foreignWeight': fw,
                  'specialWaste': sw, 'specialWasteWeight': sww, 'dppNo': fx(r['dpp']) or '', 'checkSpecial': False, 'checkKday': False, 'checkNonInteger': False, 'loadPure': False,
                  'sourceTimeKnown': False, 'sourceFile': day[:10] + '.xlsx', 'sourceSheet': str(r['sheet'])}
        tid, lid, sid = str(uuid.uuid4()), str(uuid.uuid4()), str(uuid.uuid4())
        clone('inbound_trips', tpl_trip, id=tid, receipt_number=o, receipt_type=rtype, receipt_date=dt, carrier_id=car, vehicle_registration=r['vehicle'], status='CLOSED', created_by=ADMIN,
              notes='__EXTRA__' + json.dumps(extras, ensure_ascii=False, separators=(',', ':')) + '\n', created_at=dt, updated_at=dt, deleted_at=None)
        clone('inbound_loads', tpl_load, id=lid, trip_id=tid, supplier_id=sup, order_number=o, incoming_container_number=cont, net_weight=net, status='CLOSED', ready_for_sorting_at=dt,
              dpp_number=int(fx(r['dpp'])) if fx(r['dpp']) else None, weighbridge_number=fx(r['zyg']), dispatch_note_number=fx(r['dn']), seal_number=fx(r['seal']), created_at=dt, updated_at=dt)
        clone('sorting_sessions', tpl_ses, id=sid, inbound_load_id=lid, status='CLOSED', started_at=dt, sorting_confirmed_at=dt, logistics_confirmed_at=dt, final_sorting_weight=net, final_difference=0,
              foreign_materials=fm, foreign_weight=fw, special_waste=sw, special_waste_weight=sww, created_at=dt, updated_at=dt)
        add_entries(sid, lid, dt, r['cats']); stats['νέα φορτία'] += 1
        if sup not in sup_type: pass
print('στατιστικά:', dict(stats), '· προβλήματα:', len(problems), problems[:8])
tot = c.execute("select count(*),round(sum(l.net_weight)),round((select sum(coalesce(e.approved_weight,e.raw_weight)) from sorting_entries e join sorting_sessions s on s.id=e.session_id join inbound_loads l2 on l2.id=s.inbound_load_id join inbound_trips t2 on t2.id=l2.trip_id where t2.receipt_date>='2026-09-01' and t2.receipt_date<'2026-10-01')) from inbound_loads l join inbound_trips t on t.id=l.trip_id where t.receipt_date>='2026-09-01' and t.receipt_date<'2026-10-01' and t.deleted_at is null").fetchone()
print('Σεπτέμβριος μετά: φορτία', tot[0], '· καθαρό', tot[1], '· σύνολο ταξινόμησης', tot[2])
if APPLY and not problems:
    now = datetime.now(timezone.utc).isoformat(sep=' ')
    c.execute('insert into audit_events (id,user_id,entity_type,entity_id,action,old_values,new_values,reason,created_at) values (?,?,?,?,?,?,?,?,?)',
              (str(uuid.uuid4()), ADMIN, 'inbound_load', '', 'IMPORT_SEPTEMBER', '', json.dumps(dict(stats), ensure_ascii=False), 'Σεπτέμβριος 2026: συμπλήρωση από ημερήσιες αναφορές', now))
    c.commit(); print('ΕΦΑΡΜΟΣΤΗΚΕ')
else:
    c.rollback(); print('ΔΕΝ εφαρμόστηκε (rollback)' + ('' if APPLY else ' — δοκιμαστική εκτέλεση'))
