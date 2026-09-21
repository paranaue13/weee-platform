from fastapi.testclient import TestClient
from app.main import app

def auth(c):
    r=c.post('/auth/token',json={'username':'admin','password':'testpass'}); assert r.status_code==200
    return {'Authorization':'Bearer '+r.json()['access_token']}

def test_build14_mobile_and_scale_gross_edit_delete():
    with TestClient(app) as c:
        h=auth(c)
        page=c.get('/mobile').text
        assert 'ΧΥΜΑ ΠΛΥΝΤΗΡΙΑ / ΚΟΥΖΙΝΕΣ' in page and 'ΧΥΜΑ ΨΥΓΕΙΑ' in page
        supplier=c.post('/master/organizations',headers=h,json={'legal_name':'Supplier 14','roles':['SUPPLIER']}).json()
        rec=c.post('/receipts',headers=h,json={'receipt_type':'CURTAIN_TRAILER','receipt_date':'2026-08-27T07:00:00+03:00','loads':[{'supplier_id':supplier['id'],'gross_weight':1000,'tare_weight':500}]}).json()
        c.post(f"/receipts/{rec['id']}/ready-for-sorting",headers=h)
        load=rec['loads'][0]; c.post(f"/sorting/{load['id']}/start",headers=h)
        mt=next(x for x in c.get('/master/medium-types',headers=h).json() if x['code']=='BASKET_LARGE')
        med=c.post('/master/media',headers=h,json={'type_id':mt['id'],'code':'TEST-BASKET-14','tare_weight':20}).json()
        cat=next(x for x in c.get('/master/weee-categories',headers=h).json() if x['code']=='4Δ0000')
        e=c.post(f"/sorting/{load['id']}/entries",headers=h,json={'weee_category_id':cat['id'],'collection_medium_id':med['id'],'entry_type':'SCALE_GROSS','raw_weight':70})
        assert e.status_code==200, e.text
        assert float(e.json()['raw_weight'])==50.0
        sug=c.get(f"/sorting/{load['id']}/medium-suggestions",headers=h,params={'weee_category_id':cat['id']})
        assert sug.status_code==200 and sug.json()[0]['id']==med['id'] and sug.json()[0]['used_by_me']
        upd=c.put(f"/sorting/entries/{e.json()['id']}",headers=h,json={'weee_category_id':cat['id'],'collection_medium_id':med['id'],'entry_type':'MEDIUM','raw_weight':55})
        assert upd.status_code==200 and float(upd.json()['raw_weight'])==55
        assert c.delete(f"/sorting/entries/{e.json()['id']}",headers=h).status_code==200
