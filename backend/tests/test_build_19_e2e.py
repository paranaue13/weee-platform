from fastapi.testclient import TestClient
from app.main import app

def auth(c):
    r=c.post('/auth/token',json={'username':'admin','password':'testpass'}); assert r.status_code==200,r.text
    return {'Authorization':'Bearer '+r.json()['access_token']}

def test_android_submit_visible_as_detailed_windows_review():
    with TestClient(app) as c:
        h=auth(c)
        supplier=c.post('/master/organizations',headers=h,json={'legal_name':'Build19 Supplier','roles':['SUPPLIER']}).json()
        rec=c.post('/receipts',headers=h,json={'receipt_type':'SMALL_POINTS','receipt_date':'2026-08-27T09:00:00+03:00','loads':[{'supplier_id':supplier['id'],'order_number':'B19-ORD-1','gross_weight':12000,'tare_weight':11500}]}).json()
        load=rec['loads'][0]
        assert c.post(f"/receipts/{rec['id']}/ready-for-sorting",headers=h).status_code==200
        display=c.get('/master/weee-display',headers=h).json()
        cat=next(x for x in display if x.get('parent_code')=='6Α0000')
        media=c.get('/master/media',headers=h).json()
        med=next(x for x in media if x.get('active',True))
        add=c.post(f"/sorting/{load['id']}/entries",headers=h,json={'weee_category_id':cat['id'],'collection_medium_id':med['id'],'entry_type':'MEDIUM','raw_weight':25})
        assert add.status_code==200,add.text
        conf=c.post(f"/sorting/{load['id']}/confirm",headers=h); assert conf.status_code==200,conf.text
        avail=c.get('/sorting/available',headers=h).json(); assert load['id'] not in [x['id'] for x in avail]
        q=c.get('/sorting/review-queue',headers=h); assert q.status_code==200,q.text
        assert any(x['load_id']==load['id'] and x['order_number']=='B19-ORD-1' for x in q.json())
        d=c.get(f"/sorting/{load['id']}/detail",headers=h); assert d.status_code==200,d.text
        body=d.json(); assert body['order_number']=='B19-ORD-1' and len(body['entries'])==1
        assert body['entries'][0]['official_code']=='6Α0000'
        assert body['entries'][0]['display_name']==cat['display_name']
