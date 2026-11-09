import os,sys,sqlite3,collections,pickle,uuid,json,datetime,calendar
sys.path.insert(0,os.environ['TEMP'])
sys.stdout.reconfigure(encoding='utf-8')
from x33 import norm
SP=os.path.dirname(os.path.abspath(__file__))
dbp=sys.argv[1]; apply=len(sys.argv)>2 and sys.argv[2]=='apply'
data=pickle.load(open(SP+'/xmat.pkl','rb'))
db=sqlite3.connect(dbp); db.row_factory=sqlite3.Row
OPEN=collections.defaultdict(float); OUT=collections.defaultdict(float); SH=collections.defaultdict(float); CO=collections.defaultdict(float); LAB={}
for r in db.execute("select category_group g,material_label l,kg k from material_opening_stocks where active=1"): OPEN[(r['g'],norm(r['l']))]+=r['k']; LAB[(r['g'],norm(r['l']))]=r['l']
for r in db.execute("select cast(substr(work_date,6,2) as int) m,category_group g,material_label l,weight_kg k from material_output_entries where active=1"): OUT[(r['m'],r['g'],norm(r['l']))]+=r['k']; LAB.setdefault((r['g'],norm(r['l'])),r['l'])
for r in db.execute("select cast(substr(work_date,6,2) as int) m,category_group g,material_label l,weight_kg k from material_shipment_entries where active=1"): SH[(r['m'],r['g'],norm(r['l']))]+=r['k']; LAB.setdefault((r['g'],norm(r['l'])),r['l'])
for r in db.execute("select cast(substr(work_date,6,2) as int) m,material_label l,weight_kg_delta k from material_correction_entries"): CO[(r['m'],norm(r['l']))]+=r['k']
EXC={ (m,g,nl):v for m in range(1,10) for (g,key,nl),(lab,v) in data[m].items() if key=='sales'}
STK={ (m,g,nl):v for m in range(1,10) for (g,key,nl),(lab,v) in data[m].items() if key=='stock'}
cand={k:v for k,v in EXC.items() if v>0 and SH.get(k,0)==0}      # λείπει εντελώς από την εφαρμογή
def stock(m,g,nl,sh):
    s=OPEN.get((g,nl),0)
    for mm in range(1,m+1): s+=OUT.get((mm,g,nl),0)-sh.get((mm,g,nl),0)+CO.get((mm,nl),0)
    return s
after=dict(SH); after.update(cand)
mats=sorted({(g,nl) for (m,g,nl) in cand})
ok=[];skip=[]
for g,nl in mats:
    good=True
    for m in range(1,10):
        if (m,g,nl) in STK and abs(stock(m,g,nl,after)-STK[(m,g,nl)])>0.5: good=False
    (ok if good else skip).append((g,nl))
print('υλικά με ελλιπείς πωλήσεις:',len(mats),'· ταιριάζουν με το Excel (απόθεμα όλων των μηνών) μετά την προσθήκη:',len(ok))
print('ΔΕΝ εφαρμόζονται (το απόθεμα δεν ταιριάζει):',[LAB.get(k,k[1]) for k in skip])
now=datetime.datetime.now().isoformat(sep=' ')
new=[]
for (m,g,nl),v in sorted(cand.items()):
    if (g,nl) not in ok: continue
    d=datetime.date(2026,m,calendar.monthrange(2026,m)[1])
    new.append((d.isoformat()+' 00:00:00.000000',g,LAB[(g,nl)],v))
tpl=dict(db.execute("select * from material_shipment_entries where source='HISTORICAL_2026_SALES' limit 1").fetchone())
for wd,g,l,v in new:
    r=dict(tpl); r.update(id=str(uuid.uuid4()),work_date=wd,category_group=g,material_label=l,weight_kg=v,source='HISTORICAL_2026_SALES',notes='Αποστολή από Excel (ΠΩΛΗΣΕΙΣ ΚΙΛΑ μήνα)',active=1,created_at=now,updated_at=now)
    cols=list(r); db.execute(f"insert into material_shipment_entries ({','.join(cols)}) values ({','.join('?'*len(cols))})",[r[c] for c in cols])
print('νέες εγγραφές αποστολών:',len(new),'· σύνολο kg:',round(sum(x[3] for x in new)))
bym=collections.defaultdict(float)
for wd,g,l,v in new: bym[wd[:7]]+=v
print('ανά μήνα:',{k:round(v) for k,v in sorted(bym.items())})
# έλεγχος: Excel έναντι εφαρμογής για τα υλικά που προστέθηκαν
SH2=collections.defaultdict(float)
for r in db.execute("select cast(substr(work_date,6,2) as int) m,category_group g,material_label l,weight_kg k from material_shipment_entries where active=1"): SH2[(r['m'],r['g'],norm(r['l']))]+=r['k']
bad=[(k,EXC[k],SH2.get(k,0)) for k in EXC if (k[1],k[2]) in ok and abs(EXC[k]-SH2.get(k,0))>0.05]
print('ασυμφωνίες πωλήσεων για τα υλικά που προστέθηκαν:',len(bad))
leftover=[(k,EXC.get(k,0),round(SH2.get(k,0),1)) for k in set(EXC)|set(SH2) if abs(EXC.get(k,0)-SH2.get(k,0))>0.05]
print('υπόλοιπες διαφορές πωλήσεων Excel/εφαρμογής (δεν αλλάζουν):',len(leftover))
if apply and not bad:
    db.execute("insert into audit_events(id,user_id,entity_type,entity_id,action,old_values,new_values,reason,created_at) values(?,?,?,?,?,?,?,?,?)",(str(uuid.uuid4()),None,'material_shipment_entry','','IMPORT_MISSING_SALES_AUG_SEP_20261109',None,json.dumps({'rows':len(new),'kg':round(sum(x[3] for x in new))}),'Πωλήσεις υλικών Αυγ–Σεπ που έλειπαν (από το Excel)',now)); db.commit(); print('ΕΦΑΡΜΟΣΤΗΚΕ')
else: db.rollback(); print('ΔΕΝ εφαρμόστηκε (rollback)')
for k,e,a in sorted(leftover)[:30]: print('   διαφορά',k[0],k[1],LAB.get((k[1],k[2]),k[2]),'Excel',e,'εφαρμογή',a)
