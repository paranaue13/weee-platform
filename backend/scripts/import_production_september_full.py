import sqlite3,sys,pickle,collections,uuid,json,datetime,os
sys.stdout.reconfigure(encoding='utf-8')
SP=os.path.dirname(os.path.abspath(__file__))
dbp=sys.argv[1]; apply=len(sys.argv)>2 and sys.argv[2]=='apply'
X=pickle.load(open(SP+'/xsep.pkl','rb'))
db=sqlite3.connect(dbp); db.row_factory=sqlite3.Row
cat={r['code']:r['id'] for r in db.execute('select id,code from weee_categories')}
E=collections.defaultdict(float)
for d,code,g,kg,*_ in X: E[(d or '2026-09-30',code,'corr' if d is None else 'date')+(g,)]+=kg
want=collections.defaultdict(dict)   # (date,code,kind)->{group:kg}
for (d,code,kind,g),v in E.items(): want[(d,code,kind)][g]=v
have=collections.defaultdict(list)
for r in db.execute("select w.*,c.code from production_work_entries w join weee_categories c on c.id=w.weee_category_id where w.source='HISTORICAL_2026_SEP' and w.active=1"):
    k=(r['work_date'][:10],r['code'],'corr' if r['notes']=='Διόρθωση αρχείου παραγωγής' else 'date'); have[k].append(r)
tpl=db.execute("select * from production_work_entries where source='HISTORICAL_2026_SEP' and notes='Εισαγωγή Σεπτεμβρίου 2026' limit 1").fetchone()
now=datetime.datetime.now().isoformat(sep=' ')
ops=collections.Counter(); problems=[]; log=[]
def ins(k,g,kg):
    d=dict(tpl); d.update(id=str(uuid.uuid4()),work_date=k[0]+' 12:00:00.000000',weee_category_id=cat[k[1]],weight_kg=kg,supplier_group=g,created_at=now,updated_at=now,active=1,
        notes=('Διόρθωση αρχείου παραγωγής' if k[2]=='corr' else 'Εισαγωγή Σεπτεμβρίου 2026'))
    cols=list(d); db.execute(f"insert into production_work_entries ({','.join(cols)}) values ({','.join('?'*len(cols))})",[d[c] for c in cols]); ops['νέες γραμμές']+=1
for k in sorted(set(want)|set(have)):
    w=want.get(k,{}); h=have.get(k,[])
    if k[1] not in cat: problems.append(('άγνωστη κατηγορία',k)); continue
    if not w:
        problems.append(('γραμμή εφαρμογής χωρίς Excel',k,[x['weight_kg'] for x in h])); continue
    groups=sorted(w)
    same=(len(h)==len(groups) and all(any(abs(x['weight_kg']-w[g])<0.001 and x['supplier_group']==g for x in h) for g in groups))
    if same: continue
    for r in h:
        db.execute("update production_work_entries set active=0,updated_at=? where id=?",(now,r['id'])); ops['απενεργοποιήθηκαν παλιές γραμμές']+=1
    for g in groups: ins(k,g,w[g])
print('πράξεις',dict(ops),'προβλήματα',len(problems)); [print('  ',x) for x in problems[:15]]
tot=db.execute("select round(sum(weight_kg),3) from production_work_entries where active=1 and source='HISTORICAL_2026_SEP'").fetchone()[0]
print('σύνολο Σεπτεμβρίου (πηγή εισαγωγής) μετά:',tot,'· Excel:',sum(x[3] for x in X))
# επαλήθευση ανά (ημερομηνία,κωδικός,ομάδα,είδος)
D=collections.defaultdict(float)
for r in db.execute("select substr(w.work_date,1,10) d,c.code,w.supplier_group g,w.weight_kg kg,w.notes from production_work_entries w join weee_categories c on c.id=w.weee_category_id where w.source='HISTORICAL_2026_SEP' and w.active=1"):
    D[(r['d'],r['code'],'corr' if r['notes']=='Διόρθωση αρχείου παραγωγής' else 'date',r['g'])]+=r['kg']
bad=[k for k in set(E)|set(D) if abs(E.get(k,0)-D.get(k,0))>0.5]
print('κλειδιά που ΔΕΝ ταιριάζουν με το Excel μετά την εισαγωγή:',len(bad),bad[:5])
if apply and not problems and not bad:
    db.execute("insert into audit_events(id,user_id,entity_type,entity_id,action,old_values,new_values,reason,created_at) values(?,?,?,?,?,?,?,?,?)",(str(uuid.uuid4()),None,'production_work_entry','','IMPORT_PRODUCTION_SEPTEMBER_FULL_20261109',None,json.dumps(dict(ops),ensure_ascii=False),'Σεπτέμβριος 2026: πλήρης παραγωγή από το Excel (ημέρες 16-30, ομάδα HERMES, διορθώσεις)',now))
    db.commit(); print('ΕΦΑΡΜΟΣΤΗΚΕ')
else:
    db.rollback(); print('ΔΕΝ εφαρμόστηκε (rollback)')
