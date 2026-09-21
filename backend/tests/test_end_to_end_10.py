from decimal import Decimal
from fastapi.testclient import TestClient
from app.main import app

def auth(c):
    r=c.post('/auth/token',json={'username':'admin','password':'testpass'})
    assert r.status_code==200, r.text
    return {'Authorization':'Bearer '+r.json()['access_token']}

def test_full_operational_flow_receipt_to_dispatch_and_queue():
    with TestClient(app) as c:
        h=auth(c)
        supplier=c.post('/master/organizations',headers=h,json={'legal_name':'Supplier E2E','roles':['SUPPLIER']}).json()
        customer=c.post('/master/organizations',headers=h,json={'legal_name':'Customer E2E','roles':['CUSTOMER']}).json()
        cats=c.get('/master/weee-categories',headers=h).json(); cat=next(x for x in cats if x['code']=='4Δ0000')
        mats=c.get('/master/materials',headers=h).json(); iron=next(x for x in mats if x['internal_code']=='Α00001')
        units=c.get('/master/org-units',headers=h).json(); bench=next(x for x in units if x['code']=='BENCH')
        mts=c.get('/master/medium-types',headers=h).json(); basket=next(x for x in mts if x['code']=='BASKET_SMALL')
        medium=c.post('/master/media',headers=h,json={'type_id':basket['id'],'code':'K-E2E-001','tare_weight':'80'}).json()

        rec=c.post('/receipts',headers=h,json={'receipt_type':'CURTAIN_TRAILER','receipt_date':'2026-08-25T08:30:00+03:00','loads':[{'supplier_id':supplier['id'],'gross_weight':'1500','tare_weight':'1000'}]}); assert rec.status_code==200,rec.text
        rid=rec.json()['id']; lid=rec.json()['loads'][0]['id']
        assert c.post(f'/receipts/{rid}/ready-for-sorting',headers=h).status_code==200
        assert c.post(f'/sorting/{lid}/start',headers=h).status_code==200
        assert c.post(f'/sorting/{lid}/entries',headers=h,json={'weee_category_id':cat['id'],'collection_medium_id':medium['id'],'raw_weight':'500'}).status_code==200
        assert c.post(f'/sorting/{lid}/confirm',headers=h).status_code==200
        assert c.post(f'/sorting/{lid}/logistics-review',headers=h,json={'requires_management_approval':False}).status_code==200

        stock=[x for x in c.get('/inventory/weee',headers=h).json() if x['inbound_load_id']==lid]
        assert len(stock)==1 and Decimal(stock[0]['available_weight'])==Decimal('500.000')
        transfer=c.post('/production/transfers',headers=h,json={'destination_org_unit_id':bench['id'],'items':[{'stock_lot_id':stock[0]['id']}]}); assert transfer.status_code==200,transfer.text
        balances=c.get('/production/balances',headers=h).json(); bal=next(x for x in balances if x['org_unit_id']==bench['id'] and x['weee_code']=='4Δ0000' and Decimal(x['initial_weight'])==Decimal('500.000'))
        rem=c.post('/production/remainders',headers=h,json={'balance_id':bal['id'],'remaining_weight':'100'}); assert rem.status_code==200,rem.text
        assert Decimal(rem.json()['processed_since_previous'])==Decimal('400.000')

        output=c.post('/production/outputs',headers=h,json={'material_id':iron['id'],'output_form':'BALE','source_org_unit_id':bench['id'],'net_weight':'400'}); assert output.status_code==200,output.text
        ready=output.json(); assert Decimal(ready['net_weight'])==Decimal('400.000')
        order=c.post('/loading/orders',headers=h,json={'customer_id':customer['id'],'max_allowed_weight':'1000','selection_mode':'OFFICE_RESERVED','vehicle_registration':'E2E-100'}); assert order.status_code==200,order.text
        oid=order.json()['id']
        assert c.post(f'/loading/orders/{oid}/reserve',headers=h,json={'ready_material_lot_id':ready['id']}).status_code==200
        assert c.post(f'/loading/orders/{oid}/load',headers=h,json={'ready_material_lot_id':ready['id']}).status_code==200
        done=c.post(f'/loading/orders/{oid}/complete',headers=h); assert done.status_code==200,done.text
        assert done.json()['status']=='COMPLETED'

        queue=c.get('/integration/galaxy/queue',headers=h); assert queue.status_code==200,queue.text
        assert any(x['entity_type']=='LOADING_ORDER' and x['entity_id']==oid and x['status']=='PENDING' for x in queue.json())
        dash=c.get('/dashboard/operations',headers=h); assert dash.status_code==200,dash.text
        assert Decimal(dash.json()['production_open_kg'])>=Decimal('100.000')
        assert dash.json()['galaxy_pending']>=1
