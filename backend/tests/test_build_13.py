from fastapi.testclient import TestClient
from app.main import app

def auth(c):
    r=c.post('/auth/token',json={'username':'admin','password':'testpass'}); assert r.status_code==200
    return {'Authorization':'Bearer '+r.json()['access_token']}

def test_org_roles_edit_deactivate_and_receipt_edit():
    with TestClient(app) as c:
        h=auth(c)
        s=c.post('/master/organizations',headers=h,json={'legal_name':'Supplier Only','roles':['SUPPLIER']}); assert s.status_code==200
        carrier=c.post('/master/organizations',headers=h,json={'legal_name':'Carrier Supplier','roles':['CARRIER','SUPPLIER']}); assert carrier.status_code==200
        partner=c.post('/master/organizations',headers=h,json={'legal_name':'Partner Only','roles':['PARTNER']}); assert partner.status_code==200
        suppliers=c.get('/master/organizations?role=SUPPLIER',headers=h).json(); assert any(x['id']==s.json()['id'] for x in suppliers); assert any(x['id']==carrier.json()['id'] for x in suppliers)
        carriers=c.get('/master/organizations?role=CARRIER',headers=h).json(); assert any(x['id']==carrier.json()['id'] for x in carriers); assert not any(x['id']==s.json()['id'] for x in carriers)
        partners=c.get('/master/organizations?role=PARTNER',headers=h).json(); assert any(x['id']==partner.json()['id'] for x in partners)
        oid=carrier.json()['id']
        u=c.put('/master/organizations/'+oid,headers=h,json={'legal_name':'Carrier Supplier Edited','trade_name':'CSE','roles':['CARRIER','SUPPLIER']}); assert u.status_code==200; assert u.json()['legal_name']=='Carrier Supplier Edited'
        d=c.delete('/master/organizations/'+partner.json()['id'],headers=h); assert d.status_code==200
        assert not any(x['id']==partner.json()['id'] for x in c.get('/master/organizations?role=PARTNER',headers=h).json())
        # basic curtain receipt, then read and edit before sorting starts
        payload={'receipt_type':'CURTAIN_TRAILER','receipt_date':'2026-08-26T10:00:00Z','carrier_id':oid,'driver_name':'Driver','vehicle_registration':'ABC123','notes':'first','loads':[{'supplier_id':s.json()['id'],'gross_weight':1000,'tare_weight':500}]}
        r=c.post('/receipts',headers=h,json=payload); assert r.status_code==200
        rid=r.json()['id']; assert c.get('/receipts/'+rid,headers=h).status_code==200
        payload['notes']='edited'; payload['vehicle_registration']='XYZ987'; payload['loads'][0]['gross_weight']=1100
        e=c.put('/receipts/'+rid,headers=h,json=payload); assert e.status_code==200; assert e.json()['notes']=='edited'; assert e.json()['vehicle_registration']=='XYZ987'; assert float(e.json()['loads'][0]['net_weight'])==600
