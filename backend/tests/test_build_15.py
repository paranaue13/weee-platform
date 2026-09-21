from fastapi.testclient import TestClient
from app.main import app

def auth(c):
    r=c.post('/auth/token',json={'username':'admin','password':'testpass'}); assert r.status_code==200
    return {'Authorization':'Bearer '+r.json()['access_token']}

def test_build15_weee_display_and_internal_category():
    with TestClient(app) as client:
        h=auth(client)
        rows=client.get('/master/weee-display',headers=h).json()
        assert rows and 'official_description' in rows[0] and 'display_name' in rows[0]
        target=next(x for x in rows if x['official_code']=='4Α2110' and not x['is_internal_subcategory'])
        r=client.put('/master/weee-display/'+target['id'],headers=h,json={'display_name':'Πλυντήρια TEST','display_group':'Δοκιμή'})
        assert r.status_code==200
        changed=next(x for x in client.get('/master/weee-display',headers=h).json() if x['id']==target['id'])
        assert changed['display_name']=='Πλυντήρια TEST'
        assert changed['official_description']==target['official_description']
        r=client.post('/master/weee-internal-subcategories',headers=h,json={'parent_category_id':target['id'],'display_name':'Πλυντήρια ειδική υποκατηγορία'})
        assert r.status_code==200 and r.json()['official_code']=='4Α2110'
