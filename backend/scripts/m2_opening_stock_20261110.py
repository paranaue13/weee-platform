import json,os,sys,sqlite3,uuid,datetime,openpyxl
sys.stdout.reconfigure(encoding='utf-8')
dbp=sys.argv[1]; apply=len(sys.argv)>2 and sys.argv[2]=='apply'
FILE=r"C:\Users\paran\Desktop\HER app\Files\Αποθέματα_1-1-2026_εφαρμογή (διορθωμένο).xlsx"
plan=json.load(open(os.path.join(os.environ['TEMP'],'m2plan.json'),encoding='utf-8'))['plan']
ws=openpyxl.load_workbook(FILE,data_only=True).active
press={r[1]:(int(r[4] or 0),float(r[5] or 0)) for r in ws.iter_rows(min_row=2,values_only=True) if r[0]=='Πρέσα'}
bp,bk=press['ΣΙΔΗΡΟΣ ΜΠΑΛΕΣ']; print('μπάλες σιδήρου από το αρχείο:',bp,bk)
db=sqlite3.connect(dbp); now=datetime.datetime.now().isoformat(sep=' ')
cols={r[1] for r in db.execute('pragma table_info(material_opening_stocks)')}
if 'pieces' not in cols: db.execute("alter table material_opening_stocks add column pieces integer default 0")
db.execute("update material_opening_stocks set pieces=0 where pieces is null")
n=0
for p in plan:
    if not p['db']: continue
    db.execute("update material_opening_stocks set kg=?,pieces=?,updated_at=? where id=?",(p['kg'],p['pieces'],now,p['db'][0])); n+=1
# σίδηρος: το σύνολο του αρχείου (ΣΙΔΗΡΟΣ ΧΥΜΑ) περιέχει τις μπάλες (υποσύνολο): χύμα = σύνολο − μπάλες, μπάλες στη δική τους ετικέτα (χωρίς διπλομέτρηση)
loose=db.execute("select id,kg,pieces,category_group,reptool_code,her_description from material_opening_stocks where material_label='ΜΕΤΑΛΛΟ ΣΙΔΗΡΟΥΧΟ' and active=1").fetchone()
tot_k,tot_p=loose[1],loose[2]
assert abs(tot_k-12232)<.01 and tot_p==12,(tot_k,tot_p)
db.execute("update material_opening_stocks set kg=?,pieces=?,notes=? where id=?",(tot_k-bk,tot_p-bp,'Σίδηρος: σύνολο αρχείου 12.232 kg / 12 τεμ., από τα οποία μπάλες '+str(bp)+' τεμ. / '+str(bk)+' kg (ξεχωριστή γραμμή (ΜΠΑΛΕΣ))',loose[0]))
if not db.execute("select 1 from material_opening_stocks where material_label='ΜΕΤΑΛΛΟ ΣΙΔΗΡΟΥΧΟ (ΜΠΑΛΕΣ)' and active=1").fetchone():
    asof=db.execute("select as_of_date from material_opening_stocks where id=?",(loose[0],)).fetchone()[0]
    db.execute("insert into material_opening_stocks (id,as_of_date,category_group,material_label,kg,pieces,reptool_code,her_description,source,notes,active,created_at,updated_at) values (?,?,?,?,?,?,?,?,?,?,1,?,?)",
      (str(uuid.uuid4()),asof,loose[3],'ΜΕΤΑΛΛΟ ΣΙΔΗΡΟΥΧΟ (ΜΠΑΛΕΣ)',bk,bp,loose[4],loose[5],'HISTORICAL_2025','Μπάλες σιδήρου του αρχικού αποθέματος (υποσύνολο του ΣΙΔΗΡΟΣ ΧΥΜΑ του αρχείου)',now,now))
# η προσωρινή διόρθωση τεμαχίων του K2 (23 μπάλες) αντικαθίσταται από τα τεμάχια του αρχικού αποθέματος
d=db.execute("delete from material_correction_entries where work_date<'2026-01-01' and material_label='ΜΕΤΑΛΛΟ ΣΙΔΗΡΟΥΧΟ (ΜΠΑΛΕΣ)' and reason like 'Αρχικό απόθεμα πρέσας%'").rowcount
print('ενημερώθηκαν γραμμές:',n,'· διαγράφηκε προσωρινή διόρθωση K2:',d)
if apply:
    db.execute("insert into audit_events(id,user_id,entity_type,entity_id,action,old_values,new_values,reason,created_at) values(?,?,?,?,?,?,?,?,?)",(str(uuid.uuid4()),None,'material_stock','','M2_OPENING_20261110',None,json.dumps({'rows':n}),'Αρχικά αποθέματα 1/1/2026 από το αρχείο του χρήστη (τεμάχια και κιλά)',now)); db.commit(); print('ΕΦΑΡΜΟΣΤΗΚΕ')
else: db.rollback(); print('rollback')
