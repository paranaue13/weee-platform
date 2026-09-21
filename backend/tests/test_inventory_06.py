from decimal import Decimal
from fastapi.testclient import TestClient
from app.main import app

def auth(c):
    r=c.post('/auth/token',json={'username':'admin','password':'testpass'})
    assert r.status_code==200, r.text
    return {'Authorization':'Bearer '+r.json()['access_token']}

def test_closed_sorting_materializes_stock_and_moves_to_production():
    with TestClient(app) as c:
        h=auth(c)
        supplier=c.post('/master/organizations',headers=h,json={'legal_name':'Supplier Build06','roles':['SUPPLIER']}).json()
        cats=c.get('/master/weee-categories',headers=h).json(); cat=next(x for x in cats if x['code']=='4Δ0000')
        mts=c.get('/master/medium-types',headers=h).json(); mt=next(x for x in mts if x['code']=='BASKET_SMALL')
        units=c.get('/master/org-units',headers=h).json(); unit=next(x for x in units if x['code']=='BENCH')
        m=c.post('/master/media',headers=h,json={'type_id':mt['id'],'code':'K-0601','tare_weight':'80'}); assert m.status_code==200,m.text
        mid=m.json()['id']
        rec=c.post('/receipts',headers=h,json={'receipt_type':'CURTAIN_TRAILER','receipt_date':'2026-08-25T09:00:00+03:00','loads':[{'supplier_id':supplier['id'],'gross_weight':'1000','tare_weight':'500'}]}); assert rec.status_code==200,rec.text
        lid=rec.json()['loads'][0]['id']; rid=rec.json()['id']
        assert c.post(f'/receipts/{rid}/ready-for-sorting',headers=h).status_code==200
        assert c.post(f'/sorting/{lid}/start',headers=h).status_code==200
        assert c.post(f'/sorting/{lid}/entries',headers=h,json={'weee_category_id':cat['id'],'collection_medium_id':mid,'raw_weight':'300'}).status_code==200
        assert c.post(f'/sorting/{lid}/entries',headers=h,json={'weee_category_id':cat['id'],'collection_medium_id':mid,'raw_weight':'200'}).status_code==200
        assert c.post(f'/sorting/{lid}/confirm',headers=h).status_code==200
        close=c.post(f'/sorting/{lid}/logistics-review',headers=h,json={'requires_management_approval':False}); assert close.status_code==200,close.text
        stock=c.get('/inventory/weee',headers=h); assert stock.status_code==200,stock.text
        rows=[x for x in stock.json() if x['inbound_load_id']==lid]
        assert len(rows)==2
        assert sum(Decimal(x['available_weight']) for x in rows)==Decimal('500.000')
        first=rows[0]
        move=c.post('/production/transfers',headers=h,json={'destination_org_unit_id':unit['id'],'items':[{'stock_lot_id':first['id'],'weight':'100'}]}); assert move.status_code==200,move.text
        stock2=c.get('/inventory/weee',headers=h).json(); changed=next(x for x in stock2 if x['id']==first['id'])
        assert Decimal(changed['available_weight'])==Decimal(first['available_weight'])-Decimal('100')
