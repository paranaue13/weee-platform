from fastapi.testclient import TestClient
from app.main import app

def test_build_23_master_drivers_visitors():
    with TestClient(app) as c:
        t=c.post('/auth/token',json={'username':'admin','password':'testpass'}).json()['access_token']; h={'Authorization':'Bearer '+t}
        s=c.post('/master/organizations',headers=h,json={'legal_name':'TEST SUP 23','roles':['SUPPLIER']}); assert s.status_code==200
        cr=c.post('/master/organizations',headers=h,json={'legal_name':'TEST CARRIER 23','roles':['CARRIER']}); assert cr.status_code==200
        cid=cr.json()['id']; sid=s.json()['id']
        d=c.post(f'/master/carriers/{cid}/drivers',headers=h,json={'full_name':'Test Driver','active':True}); assert d.status_code==200
        r=c.post('/receipts',headers=h,json={'receipt_type':'CURTAIN_TRAILER','receipt_date':'2026-08-27T10:00:00','carrier_id':cid,'driver_name':'Test Driver','vehicle_registration':'TEST','loads':[{'supplier_id':sid,'gross_weight':1000,'tare_weight':500}]}); assert r.status_code==200, r.text
        v=c.get('/visitor-log',headers=h); assert v.status_code==200
        row=next(x for x in v.json() if x.get('source_id')==r.json()['id']); assert row['full_name']=='Test Driver' and row['arrival_at'] and row['departure_at']
        c.delete('/master/organizations/'+sid,headers=h)
        active=c.get('/master/organizations?role=SUPPLIER',headers=h).json(); assert not any(x['id']==sid for x in active)
        allrows=c.get('/master/organizations?role=SUPPLIER&include_inactive=true',headers=h).json(); assert any(x['id']==sid and not x['active'] for x in allrows)
