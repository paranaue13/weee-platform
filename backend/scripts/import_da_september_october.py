import sqlite3,sys,collections,uuid,json,datetime,os,openpyxl
sys.stdout.reconfigure(encoding='utf-8')
dbp=sys.argv[1]; apply=len(sys.argv)>2 and sys.argv[2]=='apply'
F=r"C:\Users\paran\Desktop\HER app\Files\Εισερχομενα - επεξεργασμένα 1-8 2026\ΠΩΛΗΣΕΙΣ ΥΛΙΚΩΝ & ΑΠΟΣΤΟΛΕΣ Α.Η.Η.Ε. ΣΕ ΑΛΛΕΣ ΜΟΝΑΔΕΣ - ΕΤΟΣ 2026.xlsx"
LO,HI=datetime.datetime(2026,9,1),datetime.datetime(2026,10,31)
wb=openpyxl.load_workbook(F,read_only=True,data_only=True)
def cl(x):
    return None if x is None or str(x).strip()=='' else ' '.join(str(x).split())
R=[]
for sheet,kind in (('Δ.Α.','MATERIAL'),('Δ.Α. (ΛΕΥΚΕΣ)','WEEE_TO_UNIT')):
    for r in wb[sheet].iter_rows(min_row=3,values_only=True):
        if isinstance(r[0],datetime.datetime) and LO<=r[0]<=HI and r[1] is not None and isinstance(r[6],(int,float)):
            R.append(dict(kind=kind,date=r[0].strftime('%Y-%m-%d'),da=str(r[1]).strip(),zyg=(' & '.join(x.strip() for x in str(r[2]).splitlines() if x.strip()) if r[2] is not None else None),
              transporter=cl(r[3]),recipient=cl(r[4]),desc=cl(r[5]),kg=float(r[6]),eka=cl(r[7]),rep=cl(r[8])))
db=sqlite3.connect(dbp); db.row_factory=sqlite3.Row
have=collections.Counter()
for h in db.execute("select da_number,description,weight_kg from shipment_history_entries where active=1 and work_date>='2026-09-01'"): have[(h['da_number'],h['description'],float(h['weight_kg']))]+=1
cat={r['code']:dict(r) for r in db.execute('select id,code,her_description,description_el from weee_categories')}
replot={}
for r in db.execute("select c.code,(select l.id from weee_stock_lots l where l.weee_category_id=c.id order by l.created_at limit 1) lid from weee_categories c"):
    if r['lid']: replot[r['code']]=r['lid']
user=db.execute("select user_id from stock_movements where movement_type='SHIPPED_OUT' limit 1").fetchone()[0]
loc=db.execute("select from_location_id from stock_movements where movement_type='SHIPPED_OUT' limit 1").fetchone()[0]
now=datetime.datetime.now().isoformat(sep=' ')
newH=[];seen=collections.Counter()
for x in R:
    k=(x['da'],x['desc'],x['kg']); seen[k]+=1
    if seen[k]<=have.get(k,0): continue
    newH.append(x)
print('Excel γραμμές Σεπτ–Οκτ:',len(R),'· ήδη στην εφαρμογή:',len(R)-len(newH),'· νέες:',len(newH))
ops=collections.Counter(); skip=[]
tpl_h=dict(db.execute("select * from shipment_history_entries where source='DA_LOG_2026' limit 1").fetchone())
def addH(x):
    d=dict(tpl_h); d.update(id=str(uuid.uuid4()),work_date=x['date']+' 12:00:00.000000',da_number=x['da'],weighbridge_number=x['zyg'],transporter=x['transporter'],recipient=x['recipient'],description=x['desc'],weight_kg=x['kg'],eka_code=x['eka'],reptool_code=x['rep'],kind=x['kind'],source='DA_LOG_2026',active=1,created_at=now,updated_at=now,first_recipient=None,mgmt_operation=None,tracking_document=None,destination_country=None,container_number=None,gr_notification_no=None,bill_of_lading=None)
    cols=list(d); db.execute(f"insert into shipment_history_entries ({','.join(cols)}) values ({','.join('?'*len(cols))})",[d[c] for c in cols]); ops['νέες γραμμές Ιστορικού Δ.Α.']+=1
def mvExists(da,code):
    return db.execute("select coalesce(sum(m.weight),0) from stock_movements m join weee_stock_lots l on l.id=m.lot_id join weee_categories c on c.id=l.weee_category_id where m.movement_type='SHIPPED_OUT' and m.reason like ? and c.code=?",('%ΔΑ - '+da.zfill(6)+'%',code)).fetchone()[0]
def addM(x,code,kg):
    c=cat[code]; lot=replot.get(code)
    if not lot: skip.append(('χωρίς παρτίδα — δεν υπάρχει κίνηση',x['da'],code,kg)); return
    desc=c['her_description'] or c['description_el']
    db.execute("insert into stock_movements(id,domain,lot_id,movement_type,from_location_id,to_location_id,weight,org_unit_id,user_id,reason,created_at,transfer_id) values(?,?,?,?,?,?,?,?,?,?,?,?)",
      (str(uuid.uuid4()),'WEEE',lot,'SHIPPED_OUT',loc,None,kg,None,user,f"Πώληση/Αποστολή προς ΑΝΑΚΥΚΛΩΣΗ ΣΥΣΚΕΥΩΝ ΜΟΝ. Α.Ε. · 2100 - ΔΑ - {x['da'].zfill(6)} · {desc}",x['date']+' 12:00:00.000000',None)); ops['νέες κινήσεις αποθέματος']+=1
for x in newH:
    addH(x)
# κινήσεις για ΚΑΤΗΓΟΡΙΑ-γραμμές ΛΕΥΚΕΣ (και για υπάρχοντα Δ.Α. χωρίς κίνηση)
allcat=[x for x in R if x['kind']=='WEEE_TO_UNIT' and (x['desc'] or '').startswith('ΚΑΤΗΓΟΡΙΑ ')]
bycode=collections.defaultdict(float)
for x in allcat: bycode[(x['da'],x['desc'][len('ΚΑΤΗΓΟΡΙΑ '):].strip(),x['date'])]+=x['kg']
for (da,code,date),kg in sorted(bycode.items()):
    if code not in cat: skip.append(('άγνωστη κατηγορία',da,code,kg)); continue
    ex=mvExists(da,code)
    if abs(ex-kg)<0.5: continue
    if ex>0.5: skip.append(('ασυμφωνία υπάρχουσας κίνησης',da,code,'κίνηση',ex,'Excel',kg)); continue
    addM(dict(da=da,date=date),code,kg)
print('πράξεις',dict(ops)); print('παραλείψεις/ζητήματα:',len(skip)); [print('  ',s) for s in skip[:25]]
# έλεγχος ανά μήνα/είδος: Excel έναντι Ιστορικού
E=collections.defaultdict(float); Dd=collections.defaultdict(float)
for x in R: E[(x['date'][:7],x['kind'])]+=x['kg']
for r in db.execute("select substr(work_date,1,7) m,kind,sum(weight_kg) s from shipment_history_entries where active=1 and work_date>='2026-09-01' and work_date<'2026-11-01' group by 1,2"): Dd[(r['m'],r['kind'])]=r['s']
bad=[(k,E[k],Dd.get(k,0)) for k in sorted(set(E)|set(Dd)) if abs(E.get(k,0)-Dd.get(k,0))>0.5]
print('Σύνολα Excel έναντι Ιστορικού μετά:',{k:(round(E[k]),round(Dd.get(k,0))) for k in sorted(E)}); print('ασυμφωνίες:',bad)
if apply and not bad and not [s for s in skip if s[0]!='χωρίς παρτίδα — δεν υπάρχει κίνηση']:
    db.execute("insert into audit_events(id,user_id,entity_type,entity_id,action,old_values,new_values,reason,created_at) values(?,?,?,?,?,?,?,?,?)",(str(uuid.uuid4()),None,'shipment_history','','IMPORT_DA_SEP_OCT_20261109',None,json.dumps(dict(ops),ensure_ascii=False),'Δ.Α. Σεπτεμβρίου–Οκτωβρίου 2026 από το Excel',now))
    db.commit(); print('ΕΦΑΡΜΟΣΤΗΚΕ')
else: db.rollback(); print('ΔΕΝ εφαρμόστηκε (rollback)')
