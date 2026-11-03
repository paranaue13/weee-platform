import os, sys, json, sqlite3, uuid, collections
from datetime import datetime, timezone
sys.stdout.reconfigure(encoding='utf-8')
D = os.path.join(os.environ['TEMP'], 'lm_test', 'jan')
DBF = sys.argv[1]
APPLY = '--apply' in sys.argv
SUB = json.load(open(os.path.join(D, 'sub_parsed.json'), encoding='utf-8'))
c = sqlite3.connect(DBF, timeout=60)
c.row_factory = sqlite3.Row
ADMIN = 'a448f4d4-b94d-4287-87f2-144e85113901'
cat_id = {r['code']: r['id'] for r in c.execute('select id,code from weee_categories')}
def totals():
    t = {}
    for r in c.execute("""select lo.order_number,cat.code,coalesce(e.approved_weight,e.raw_weight) as raw_weight,e.piece_count from sorting_entries e join sorting_sessions s on s.id=e.session_id join inbound_loads lo on lo.id=s.inbound_load_id
        join inbound_trips tr on tr.id=lo.trip_id join weee_categories cat on cat.id=e.weee_category_id where tr.receipt_date>='2026-01-01' and tr.receipt_date<'2026-02-01'"""):
        t.setdefault(r['order_number'], []).append((r['code'], r['raw_weight'], r['piece_count']))
    return t
before = totals()
def clone(table, row, **over):
    d = dict(row); d.update(over)
    cols = list(d); c.execute(f'insert into {table} ({",".join(cols)}) values ({",".join("?" * len(cols))})', [d[k] for k in cols])
now = datetime.now(timezone.utc).isoformat(sep=' ')
stats = collections.Counter(); problems = []
c.execute('begin')
for day, lst in SUB.items():
    for rec in lst:
        load = c.execute('select id from inbound_loads where order_number=?', (rec['order'],)).fetchone()
        if not load: problems.append(('δεν βρέθηκε φορτίο', rec['order'])); continue
        ses = c.execute('select id from sorting_sessions where inbound_load_id=?', (load['id'],)).fetchone()
        for parent, lines in rec['parents'].items():
            lines = [l for l in lines if l[2]]
            if not lines: continue
            ents = c.execute('select * from sorting_entries where session_id=? and weee_category_id=?', (ses['id'], cat_id[parent])).fetchall()
            if len(ents) != 1: problems.append(('εγγραφές γονέα', rec['order'], parent, len(ents))); continue
            e = ents[0]
            if abs(float(e['approved_weight'] if e['approved_weight'] is not None else e['raw_weight']) - sum(l[2] for l in lines)) > 0.5: problems.append(('άθροισμα', rec['order'], parent)); continue
            lot = c.execute('select * from weee_stock_lots where source_sorting_entry_id=?', (e['id'],)).fetchone()
            mv = c.execute('select * from stock_movements where lot_id=?', (lot['id'],)).fetchall() if lot else []
            if lot and abs(float(lot['original_weight']) - float(lot['available_weight'])) > 0.001: problems.append(('καταναλωμένη παρτίδα', rec['order'], parent)); continue
            for i, (scode, sid, w, pc, nm) in enumerate(lines):
                if i == 0:
                    c.execute('update sorting_entries set weee_category_id=?,raw_weight=?,approved_weight=?,piece_count=?,updated_at=? where id=?', (sid, w, (w if e['approved_weight'] is not None else None), pc, now, e['id']))
                    if lot:
                        c.execute('update weee_stock_lots set weee_category_id=?,original_weight=?,available_weight=?,piece_count=?,updated_at=? where id=?', (sid, w, w, pc, now, lot['id']))
                        c.execute('update stock_movements set weight=? where lot_id=?', (w, lot['id']))
                else:
                    ne = str(uuid.uuid4()); clone('sorting_entries', e, id=ne, weee_category_id=sid, raw_weight=w, approved_weight=(w if e['approved_weight'] is not None else None), piece_count=pc, updated_at=now)
                    if lot:
                        nl = str(uuid.uuid4()); clone('weee_stock_lots', lot, id=nl, source_sorting_entry_id=ne, weee_category_id=sid, original_weight=w, available_weight=w, piece_count=pc, updated_at=now)
                        for m in mv: clone('stock_movements', m, id=str(uuid.uuid4()), lot_id=nl, weight=w)
                    stats['νέες εγγραφές'] += 1
            stats['γονείς που σπάστηκαν'] += 1; stats['γραμμές υποκατηγοριών'] += len(lines)
after = totals()
bad = [o for o in before if abs(sum(x[1] for x in before[o]) - sum(x[1] for x in after.get(o, []))) > 0.001 or abs(sum(x[2] or 0 for x in before[o]) - sum(x[2] or 0 for x in after.get(o, []))) > 0.001 and False]
fam_before = collections.Counter(); fam_after = collections.Counter()
par = {r['code']: r['parent_code'] for r in c.execute('select code,parent_code from weee_categories where is_internal_subcategory=1')}
for o, xs in before.items():
    for code, w, _ in xs: fam_before[(o, par.get(code, code))] += w
for o, xs in after.items():
    for code, w, _ in xs: fam_after[(o, par.get(code, code))] += w
famdiff = [k for k in set(fam_before) | set(fam_after) if abs(fam_before[k] - fam_after[k]) > 0.001]
print('στατιστικά:', dict(stats), '· προβλήματα:', len(problems), problems[:5])
print('φορτία με διαφορά στο σύνολο kg:', len(bad), '· οικογένειες κατηγοριών με διαφορά:', len(famdiff))
print('εγγραφές πριν:', sum(len(v) for v in before.values()), '· μετά:', sum(len(v) for v in after.values()))
if APPLY and not problems and not bad and not famdiff:
    c.execute('insert into audit_events (id,user_id,entity_type,entity_id,action,old_values,new_values,reason,created_at) values (?,?,?,?,?,?,?,?,?)',
              (str(uuid.uuid4()), ADMIN, 'sorting_session', '', 'IMPORT_SUBCATEGORIES', '', json.dumps(dict(stats), ensure_ascii=False), 'Ιανουάριος 2026: υποκατηγορίες από το αρχείο αποθέματος', now))
    c.commit(); print('ΕΦΑΡΜΟΣΤΗΚΕ')
else:
    c.rollback(); print('ΔΕΝ εφαρμόστηκε (rollback)' + ('' if APPLY else ' — δοκιμαστική εκτέλεση'))
