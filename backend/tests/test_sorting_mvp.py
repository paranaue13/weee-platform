from fastapi.testclient import TestClient
from app.main import app


def auth(c):
    r=c.post('/auth/token',json={'username':'admin','password':'testpass'})
    assert r.status_code==200, r.text
    return {'Authorization':'Bearer '+r.json()['access_token']}


def test_sorting_to_management_close():
    with TestClient(app) as c:
        h=auth(c)
        supplier=c.post('/master/organizations',headers=h,json={'legal_name':'Sort Supplier','roles':['SUPPLIER']}).json()
        rec=c.post('/receipts',headers=h,json={'receipt_type':'CURTAIN_TRAILER','receipt_date':'2026-08-25T10:00:00+03:00','loads':[{'supplier_id':supplier['id'],'gross_weight':10000,'tare_weight':9000}]})
        assert rec.status_code==200, rec.text
        rid=rec.json()['id']; load=rec.json()['loads'][0]
        assert c.post(f'/receipts/{rid}/ready-for-sorting',headers=h).status_code==200
        assert c.post(f"/sorting/{load['id']}/start",headers=h).status_code==200
        cats=c.get('/master/weee-categories',headers=h).json(); cat=next(x for x in cats if x['code']=='4Α2110')
        e=c.post(f"/sorting/{load['id']}/entries",headers=h,json={'weee_category_id':cat['id'],'raw_weight':999.5,'entry_type':'MEDIUM'})
        assert e.status_code==200, e.text
        conf=c.post(f"/sorting/{load['id']}/confirm",headers=h)
        assert conf.status_code==200 and conf.json()['status']=='LOGISTICS_REVIEW'
        # Submitted work must disappear immediately from operator Android availability.
        available=c.get('/sorting/available',headers=h)
        assert available.status_code==200
        assert load['id'] not in {x['load_id'] for x in available.json()}
        lr=c.post(f"/sorting/{load['id']}/logistics-review",headers=h,json={'requires_management_approval':True})
        assert lr.status_code==200 and lr.json()['status']=='MANAGEMENT_REVIEW'
        mg=c.post(f"/sorting/{load['id']}/management-approve",headers=h)
        assert mg.status_code==200 and mg.json()['status']=='CLOSED'


def test_legacy_big_bag_is_not_offered_as_active_medium_type():
    with TestClient(app) as c:
        h=auth(c)
        types=c.get('/master/medium-types',headers=h).json()
        assert 'BIG_BAG' not in {x['code'] for x in types}
        # The current sack types remain available instead of reactivating the legacy BIG_BAG type.
        assert {'SACK_1KG','SACK_2KG_UN'} <= {x['code'] for x in types}

def test_overdue_day_alert():
    with TestClient(app) as c:
        h=auth(c)
        supplier=c.post('/master/organizations',headers=h,json={'legal_name':'Old Supplier','roles':['SUPPLIER']}).json()
        rec=c.post('/receipts',headers=h,json={'receipt_type':'CURTAIN_TRAILER','receipt_date':'2026-08-20T10:00:00+03:00','loads':[{'supplier_id':supplier['id'],'gross_weight':5000,'tare_weight':4500}]})
        assert rec.status_code==200
        assert c.post(f"/receipts/{rec.json()['id']}/ready-for-sorting",headers=h).status_code==200
        ds=c.get('/workflow/day-status',headers=h)
        assert ds.status_code==200
        day=next(x for x in ds.json() if x['date']=='2026-08-20')
        assert day['color']=='GRAY'
        assert day['overdue']>=1
