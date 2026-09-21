from fastapi.testclient import TestClient
from app.main import app

def auth(c):
    r=c.post('/auth/token',json={'username':'admin','password':'testpass'})
    assert r.status_code==200, r.text
    return {'Authorization':'Bearer '+r.json()['access_token']}

def test_galaxy_mapping_and_idempotent_queue():
    with TestClient(app) as c:
        h=auth(c)
        m=c.post('/integration/galaxy/mappings',headers=h,json={'mapping_type':'MATERIAL','internal_key':'Α00001','external_key':'A00001'}); assert m.status_code==200,m.text
        a=c.post('/integration/galaxy/enqueue',headers=h,json={'entity_type':'TEST','entity_id':'abc','operation':'UPSERT','payload':{'x':1}}); assert a.status_code==200,a.text
        b=c.post('/integration/galaxy/enqueue',headers=h,json={'entity_type':'TEST','entity_id':'abc','operation':'UPSERT','payload':{'x':2}}); assert b.status_code==200,b.text
        assert a.json()['id']==b.json()['id']
        st=c.get('/integration/galaxy/status',headers=h); assert st.status_code==200
        assert st.json()['connector_configured'] is False
        assert st.json()['mappings']>=1
