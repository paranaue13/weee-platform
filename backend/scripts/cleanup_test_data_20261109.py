import sqlite3,sys,os,json,uuid,datetime,collections,shutil
sys.stdout.reconfigure(encoding='utf-8')
dbp=sys.argv[1]; apply=len(sys.argv)>2 and sys.argv[2]=='apply'
db=sqlite3.connect(dbp); db.execute('pragma foreign_keys=OFF'); db.row_factory=sqlite3.Row
q=lambda s,*a:db.execute(s,a).fetchall()
now=datetime.datetime.now().isoformat(sep=' ')
tables=[r[0] for r in q("select name from sqlite_master where type='table' and name not like 'sqlite_%'")]
fks=collections.defaultdict(list)   # parent -> [(child,childcol,parentcol)]
for t in tables:
    for r in q(f"pragma foreign_key_list({t})"): fks[r['table']].append((t,r['from'],r['to'] or 'id'))
fkc_before=len(q("pragma foreign_key_check"))
deleted=collections.Counter()
def purge(table,ids,seen=None):
    """σβήνει γραμμές του table με αυτά τα id και (αναδρομικά) τις εξαρτημένες γραμμές των παιδιών"""
    ids=[i for i in ids if i is not None]
    if not ids: return
    pk='id'
    for child,ccol,pcol in fks.get(table,[]):
        if child=='sqlite_sequence' : continue
        # τιμές του parent column
        vals=[r[0] for r in q(f"select {pcol} from {table} where id in ({','.join('?'*len(ids))})",*ids)] if pcol!='id' else ids
        cids=[r[0] for r in q(f"select id from {child} where {ccol} in ({','.join('?'*len(vals))})",*vals)] if vals and 'id' in [c[1] for c in q(f"pragma table_info({child})")] else None
        if cids is None:
            n=db.execute(f"delete from {child} where {ccol} in ({','.join('?'*len(vals))})",vals).rowcount; deleted[child]+=n
        else: purge(child,cids)
    n=db.execute(f"delete from {table} where id in ({','.join('?'*len(ids))})",ids).rowcount; deleted[table]+=n
sept_before=q("select round(sum(weight_kg),1) s from production_work_entries where active=1 and work_date>='2026-09-01' and work_date<'2026-10-01'")[0]['s']
# ---- α. ΑΠΕΝΕΡΓΟΠΟΙΗΣΗ
old_inactive_win=[x['id'] for x in q("select id from production_work_entries where source='WINDOWS' and (active=0 or notes like 'TEST-%')")]
r=db.execute("update production_work_entries set active=0,updated_at=? where source='WINDOWS' and active=1",(now,)).rowcount; print('α1 απενεργοποίηση παραγωγής WINDOWS:',r)
trips=[x['id'] for x in q("select id from inbound_trips where receipt_number in ('REC-2026-000009','REC-2026-000010','REC-2026-000011','REC-2026-000012','REC-2026-000013') and deleted_at is null")]
r=db.execute(f"update inbound_trips set deleted_at=?,updated_at=? where id in ({','.join('?'*len(trips))})",(now,now,*trips)).rowcount; print('α2 απενεργοποίηση παραλαβών REC-9..13:',r)
# ---- β. ΔΙΑΓΡΑΦΗ Android / δοκιμές Code
purge('production_transfers',[x['id'] for x in q("select id from production_transfers")])
n=db.execute("delete from production_work_entries where source='ANDROID'").rowcount+(db.execute(f"delete from production_work_entries where id in ({','.join('?'*len(old_inactive_win))})",old_inactive_win).rowcount if old_inactive_win else 0); deleted['production_work_entries(ANDROID/TEST)']+=n
purge('stock_movements',[x['id'] for x in q("select id from stock_movements where movement_type in ('TO_PRODUCTION','CANCEL_TO_PRODUCTION')")])
purge('loading_orders',[x['id'] for x in q("select id from loading_orders")])
purge('ready_material_lots',[x['id'] for x in q("select id from ready_material_lots")])
db.execute("delete from ready_material_movements"); 
purge('inbound_trips',[x['id'] for x in q("select id from inbound_trips where receipt_number in ('REC-2026-000001','REC-2026-000006','REC-2026-000007','REC-2026-000008')")])
db.execute("delete from visitor_logs where driver_name like 'TEST%' or 1=1") if False else None
n=db.execute("delete from visitor_logs where full_name='TEST-DRIVER'").rowcount; deleted['visitor_logs']+=n
purge('collection_media',[x['id'] for x in q("select id from collection_media where created_at>='2026-11-09'")])
n=db.execute("delete from action_history").rowcount; deleted['action_history']+=n
n=db.execute("delete from idempotency_keys").rowcount; deleted['idempotency_keys']+=n
# ---- γ. παρουσίες/γεγονότα παρουσίας, φωτογραφίες
n=db.execute("delete from production_attendance_events").rowcount; deleted['production_attendance_events']+=n
n=db.execute("delete from production_attendance").rowcount; deleted['production_attendance']+=n
photos=[dict(x) for x in q("select * from file_attachments")]
n=db.execute("delete from file_attachments").rowcount; deleted['file_attachments']+=n
print('διαγράφηκαν:',dict(deleted))
sept_after=q("select round(sum(weight_kg),1) s from production_work_entries where active=1 and work_date>='2026-09-01' and work_date<'2026-10-01'")[0]['s']
print('παραγωγή Σεπτεμβρίου πριν/μετά:',sept_before,sept_after,'διαφορά',round(sept_after-sept_before,1))
fkc_after=len(q("pragma foreign_key_check")); print('παραβιάσεις ξένων κλειδιών πριν/μετά:',fkc_before,fkc_after)
print('ακεραιότητα:',q("pragma integrity_check")[0][0])
print('εργαζόμενοι:',q("select count(*) c from employees")[0]['c'],'· τμήματα:',q("select count(*) c from organizational_units")[0]['c'])
if apply and fkc_after<=fkc_before:
    db.execute("insert into audit_events(id,user_id,entity_type,entity_id,action,old_values,new_values,reason,created_at) values(?,?,?,?,?,?,?,?,?)",(str(uuid.uuid4()),None,'cleanup','','CLEANUP_TEST_DATA_20261109',None,json.dumps(dict(deleted),ensure_ascii=False),'Καθαρισμός δοκιμαστικών/Android εγγραφών (εντολή χρήστη)',now))
    db.commit(); print('ΕΦΑΡΜΟΣΤΗΚΕ'); json.dump(photos,open(os.path.join(os.path.dirname(os.path.abspath(__file__)),'photos_to_move.json'),'w',encoding='utf-8'),ensure_ascii=False,default=str)
else: db.rollback(); print('ΔΕΝ εφαρμόστηκε (rollback)')
