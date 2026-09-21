from fastapi.testclient import TestClient
from app.main import app


def auth(c):
    r=c.post('/auth/token',json={'username':'admin','password':'testpass'})
    assert r.status_code==200
    return {'Authorization':'Bearer '+r.json()['access_token']}


def test_receipt_flows():
    with TestClient(app) as c:
        h=auth(c)
        supplier=c.post('/master/organizations',headers=h,json={'legal_name':'Supplier A','roles':['SUPPLIER']}).json()
        carrier=c.post('/master/organizations',headers=h,json={'legal_name':'Carrier A','roles':['CARRIER']}).json()
        ctr=c.post('/master/containers',headers=h,json={'container_number':'CTR-OUT-1','tare_weight':2200}).json()
        # Hooklift: net = gross1 - gross2 - incoming ctr tare + outgoing ctr tare
        rec=c.post('/receipts',headers=h,json={
            'receipt_type':'CONTAINER','receipt_date':'2026-08-25T09:00:00+03:00','carrier_id':carrier['id'],
            'vehicle_registration':'ABC-1234','loads':[{'supplier_id':supplier['id'],'incoming_container_number':'CTR-IN-9',
            'incoming_container_tare':2000,'outgoing_container_id':ctr['id'],'gross_weight':30000,'tare_weight':22000}]
        })
        assert rec.status_code==200, rec.text
        assert float(rec.json()['loads'][0]['net_weight'])==8200.0
        ready=c.post(f"/receipts/{rec.json()['id']}/ready-for-sorting",headers=h)
        assert ready.status_code==200
        assert ready.json()['status']=='READY_FOR_SORTING'
        # small points allows multiple loads and requires an order on ready
        sp=c.post('/receipts',headers=h,json={'receipt_type':'SMALL_POINTS','receipt_date':'2026-08-25T10:00:00+03:00','carrier_id':carrier['id'],'loads':[
            {'supplier_id':supplier['id'],'order_number':'ORD-1','gross_weight':12000,'tare_weight':11000},
            {'supplier_id':supplier['id'],'order_number':'ORD-2','gross_weight':11000,'tare_weight':10200}]})
        assert sp.status_code==200, sp.text
        assert len(sp.json()['loads'])==2
        assert c.post(f"/receipts/{sp.json()['id']}/ready-for-sorting",headers=h).status_code==200
