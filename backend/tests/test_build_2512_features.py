from fastapi.testclient import TestClient
from app.main import app


def auth(c):
    r=c.post('/auth/token',json={'username':'admin','password':'testpass'})
    assert r.status_code==200, r.text
    return {'Authorization':'Bearer '+r.json()['access_token']}


def test_small_points_get_distinct_dpp_and_sorting_metadata_export():
    with TestClient(app) as c:
        h=auth(c)
        supplier=c.post('/master/organizations',headers=h,json={'legal_name':'Supplier DPP','roles':['SUPPLIER']}).json()
        carrier=c.post('/master/organizations',headers=h,json={'legal_name':'Carrier DPP','roles':['CARRIER']}).json()
        rec=c.post('/receipts',headers=h,json={'receipt_type':'SMALL_POINTS','receipt_date':'2027-01-03T10:00:00+03:00','carrier_id':carrier['id'],'vehicle_registration':'TEST-12','loads':[
            {'supplier_id':supplier['id'],'order_number':'SP-A','gross_weight':5000,'tare_weight':4500},
            {'supplier_id':supplier['id'],'order_number':'SP-B','gross_weight':4500,'tare_weight':4000},
            {'supplier_id':supplier['id'],'order_number':'SP-C','gross_weight':4000,'tare_weight':3500}]})
        assert rec.status_code==200, rec.text
        dpps=[x['dpp_number'] for x in rec.json()['loads']]
        assert dpps==[1,2,3]
        load_id=rec.json()['loads'][0]['id']
        st=c.post(f'/sorting/{load_id}/start',headers=h)
        assert st.status_code==200, st.text
        meta=c.put(f'/sorting/{load_id}/metadata',headers=h,json={'foreign_materials':'Πλαστικό','foreign_weight':12,'special_waste':'Μπαταρίες','special_waste_weight':5})
        assert meta.status_code==200, meta.text
        detail=c.get(f'/sorting/{load_id}/detail',headers=h)
        assert detail.status_code==200, detail.text
        dj=detail.json(); assert dj['dpp_number']==1; assert dj['foreign_weight']==12; assert dj['special_waste_weight']==5
        x=c.get(f'/sorting/{load_id}/export?format=xlsx',headers=h)
        assert x.status_code==200, x.text
        assert x.content[:2]==b'PK'
        p=c.get(f'/sorting/{load_id}/export?format=pdf',headers=h)
        assert p.status_code==200, p.text
        assert p.content[:4]==b'%PDF'
