from decimal import Decimal
from fastapi.testclient import TestClient
from app.main import app

def auth(c):
    r=c.post('/auth/token',json={'username':'admin','password':'testpass'})
    assert r.status_code==200, r.text
    return {'Authorization':'Bearer '+r.json()['access_token']}

def test_loading_reserved_and_complete():
    with TestClient(app) as c:
        h=auth(c)
        customer=c.post('/master/organizations',headers=h,json={'legal_name':'Customer 08','roles':['CUSTOMER']}).json()
        mats=c.get('/master/materials',headers=h).json(); mat=next(x for x in mats if x['internal_code']=='Α00001')
        units=c.get('/master/org-units',headers=h).json(); source=next(x for x in units if x['code']=='LARGE')
        out=c.post('/production/outputs',headers=h,json={'material_id':mat['id'],'output_form':'BALE','source_org_unit_id':source['id'],'net_weight':'800'}); assert out.status_code==200,out.text
        lot=out.json()
        order=c.post('/loading/orders',headers=h,json={'customer_id':customer['id'],'max_allowed_weight':'1000','selection_mode':'OFFICE_RESERVED','vehicle_registration':'ABC-123'}); assert order.status_code==200,order.text
        oid=order.json()['id']
        res=c.post(f'/loading/orders/{oid}/reserve',headers=h,json={'ready_material_lot_id':lot['id']}); assert res.status_code==200,res.text
        assert Decimal(res.json()['reserved_weight'])==Decimal('800.000')
        load=c.post(f'/loading/orders/{oid}/load',headers=h,json={'ready_material_lot_id':lot['id']}); assert load.status_code==200,load.text
        done=c.post(f'/loading/orders/{oid}/complete',headers=h); assert done.status_code==200,done.text
        assert done.json()['status']=='COMPLETED'
        ready=c.get('/inventory/ready-materials',headers=h).json()
        assert not any(x['id']==lot['id'] for x in ready)

def test_loading_respects_max_weight():
    with TestClient(app) as c:
        h=auth(c)
        customer=c.post('/master/organizations',headers=h,json={'legal_name':'Customer 08B','roles':['CUSTOMER']}).json()
        mats=c.get('/master/materials',headers=h).json(); mat=next(x for x in mats if x['internal_code']=='Α00008')
        out=c.post('/production/outputs',headers=h,json={'material_id':mat['id'],'output_form':'BIG_BAG','net_weight':'600'}).json()
        order=c.post('/loading/orders',headers=h,json={'customer_id':customer['id'],'max_allowed_weight':'500','selection_mode':'OFFICE_RESERVED'}).json()
        r=c.post(f"/loading/orders/{order['id']}/reserve",headers=h,json={'ready_material_lot_id':out['id']})
        assert r.status_code==422
