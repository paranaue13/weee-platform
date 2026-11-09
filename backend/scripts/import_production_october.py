import sqlite3,sys,pickle,collections,uuid,json,datetime,os,openpyxl
sys.stdout.reconfigure(encoding='utf-8')
SP=os.path.dirname(os.path.abspath(__file__))
dbp=sys.argv[1]; apply=len(sys.argv)>2 and sys.argv[2]=='apply'
X=pickle.load(open(SP+'/xoct.pkl','rb')); mapping=pickle.load(open(SP+'/xmap.pkl','rb'))
F=r"C:\Users\paran\Desktop\HER app\Files\Εισερχομενα - επεξεργασμένα 1-8 2026\ΕΙΣΕΡΧΟΜΕΝΑ-ΕΠΕΞΕΡΓΑΣΜΕΝΑ ΥΛΙΚΑ-ΠΡΕΣΑ (ΟΚΤΩΒΡΙΟΣ 2026).xlsx"
# έλεγχος έναντι της γραμμής «ΣΥΝΟΛΟ ΟΚΤΩΒΡΙΟΣ» του ίδιου του Excel (ανά στήλη)
wb=openpyxl.load_workbook(F,read_only=True,data_only=True); xl_tot=0; per_col={}
for si in (0,1):
    for r in wb.worksheets[si].iter_rows(values_only=True):
        if r[0] and str(r[0]).replace('\n',' ').strip().upper().startswith(('ΣΥΝΟΛΟ ΟΚΤΩΒΡΙΟΣ','ΣΥΝΟΛΟ ΜΗΝΑ')):
            for c in range(1,len(r)):
                if (si,c) in mapping and isinstance(r[c],(int,float)): per_col[(si,c)]=r[c]; xl_tot+=r[c]
            break
mine=collections.defaultdict(float)
for d,code,g,kg,sh,row,col in X: mine[(sh-1,col)]+=kg
badcols=[(k,per_col.get(k,0),round(mine.get(k,0),1)) for k in set(per_col)|set(mine) if abs(per_col.get(k,0)-mine.get(k,0))>0.5]
print('σύνολο Excel (γραμμή ΣΥΝΟΛΟ ΟΚΤΩΒΡΙΟΥ):',xl_tot,'· δικό μου:',sum(x[3] for x in X),'· στήλες με διαφορά:',len(badcols),badcols[:5])
db=sqlite3.connect(dbp); db.row_factory=sqlite3.Row
cat={r['code']:r['id'] for r in db.execute('select id,code from weee_categories')}
exist=db.execute("select count(*) c from production_work_entries where active=1 and work_date>='2026-10-01' and work_date<'2026-11-01' and source like 'HISTORICAL%'").fetchone()['c']
print('ήδη υπάρχουσες ιστορικές εγγραφές Οκτωβρίου:',exist)
tpl=dict(db.execute("select * from production_work_entries where source='HISTORICAL_2026_SEP' and notes='Εισαγωγή Σεπτεμβρίου 2026' limit 1").fetchone())
now=datetime.datetime.now().isoformat(sep=' ')
E=collections.defaultdict(float)
for d,code,g,kg,*_ in X: E[(d or '2026-10-31',code,g,'corr' if d is None else 'date')]+=kg
n=0; probs=[]
if not exist:
    for (d,code,g,kind),v in sorted(E.items()):
        if code not in cat: probs.append(code); continue
        r=dict(tpl); r.update(id=str(uuid.uuid4()),work_date=d+' 12:00:00.000000',weee_category_id=cat[code],weight_kg=v,supplier_group=g,source='HISTORICAL_2026_OCT',created_at=now,updated_at=now,active=1,notes=('Διόρθωση αρχείου παραγωγής' if kind=='corr' else 'Εισαγωγή Οκτωβρίου 2026'))
        cols=list(r); db.execute(f"insert into production_work_entries ({','.join(cols)}) values ({','.join('?'*len(cols))})",[r[c] for c in cols]); n+=1
tot=db.execute("select round(sum(weight_kg),1) s,count(*) c from production_work_entries where active=1 and work_date>='2026-10-01' and work_date<'2026-11-01'").fetchone()
print('νέες γραμμές:',n,'· άγνωστες κατηγορίες:',probs,'· Οκτώβριος μετά:',tot['c'],'γραμμές',tot['s'],'kg')
ok=(not probs) and abs(tot['s']-sum(x[3] for x in X))<0.5 and abs(xl_tot-sum(x[3] for x in X))<0.5 and not exist
if apply and ok:
    db.execute("insert into audit_events(id,user_id,entity_type,entity_id,action,old_values,new_values,reason,created_at) values(?,?,?,?,?,?,?,?,?)",(str(uuid.uuid4()),None,'production_work_entry','','IMPORT_PRODUCTION_OCTOBER_20261109',None,json.dumps({'rows':n,'kg':tot['s']}),'Παραγωγή Οκτωβρίου 2026 από το Excel',now)); db.commit(); print('ΕΦΑΡΜΟΣΤΗΚΕ')
else: db.rollback(); print('ΔΕΝ εφαρμόστηκε (rollback)' + ('' if ok else ' — ΔΕΝ ταιριάζει'))
