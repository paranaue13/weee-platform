import sqlite3,sys,uuid,json,datetime
sys.stdout.reconfigure(encoding='utf-8')
dbp=sys.argv[1]; apply=len(sys.argv)>2 and sys.argv[2]=='apply'
db=sqlite3.connect(dbp); now=datetime.datetime.now().isoformat(sep=' ')
loose=db.execute("select id,kg from material_opening_stocks where material_label='ΜΕΤΑΛΛΟ ΣΙΔΗΡΟΥΧΟ' and active=1").fetchone()
assert loose and loose[1]==12232, loose
assert not db.execute("select 1 from material_opening_stocks where material_label='ΜΕΤΑΛΛΟ ΣΙΔΗΡΟΥΧΟ (ΜΠΑΛΕΣ)'").fetchone()
BALES_KG=18725; BALES_PC=23; LOOSE=12232-BALES_KG
db.execute("update material_opening_stocks set kg=?,notes=?,updated_at=? where id=?",(LOOSE,'ΕΚ ΜΕΤΑΦΟΡΑΣ Ιανουαρίου: χύμα σίδηρος (ΑΠΟΘΕΜΑ Δεκεμβρίου 2025 ΠΡΕΣΑ: χύμα −6.493 kg)· οι μπάλες 18.725 kg είναι στη γραμμή (ΜΠΑΛΕΣ)· ολικό σίδηρος 12.232 kg όπως πριν',now,loose[0]))
db.execute("insert into material_opening_stocks (id,as_of_date,category_group,material_label,kg,reptool_code,her_description,source,notes,active,created_at,updated_at) values (?,?,?,?,?,?,?,?,?,1,?,?)",
 (str(uuid.uuid4()),'2025-12-31 00:00:00.000000','AXIOPOIISIMA','ΜΕΤΑΛΛΟ ΣΙΔΗΡΟΥΧΟ (ΜΠΑΛΕΣ)',BALES_KG,'19 12 03 / 02-1','Μέταλλο μη σιδηρούχο','HISTORICAL_2025','Αρχικό απόθεμα πρέσας: γραμμή ΑΠΟΘΕΜΑ φύλλου ΠΡΕΣΑ Δεκεμβρίου 2025 (23 μπάλες σιδήρου, 18.725 kg)',now,now))
uid=db.execute("select created_by_user_id from material_correction_entries where created_by_user_id is not null limit 1").fetchone()[0]
db.execute("insert into material_correction_entries (id,work_date,material_label,weight_kg_delta,piece_delta,reason,created_by_user_id,created_at,updated_at) values (?,?,?,?,?,?,?,?,?)",
 (str(uuid.uuid4()),'2025-12-31 12:00:00.000000','ΜΕΤΑΛΛΟ ΣΙΔΗΡΟΥΧΟ (ΜΠΑΛΕΣ)',0,BALES_PC,'Αρχικό απόθεμα πρέσας: 23 μπάλες σιδήρου (ΑΠΟΘΕΜΑ Δεκεμβρίου 2025)',uid,now,now))
if apply:
    db.execute("insert into audit_events(id,user_id,entity_type,entity_id,action,old_values,new_values,reason,created_at) values(?,?,?,?,?,?,?,?,?)",(str(uuid.uuid4()),None,'material_stock','','K2_PRESS_OPENING_20261110',json.dumps({'loose':12232}),json.dumps({'loose':LOOSE,'bales_kg':BALES_KG,'bales_pc':BALES_PC}),'Αρχικό απόθεμα μπαλών πρέσας (σίδηρος)',now)); db.commit(); print('ΕΦΑΡΜΟΣΤΗΚΕ')
else: db.rollback(); print('rollback')
