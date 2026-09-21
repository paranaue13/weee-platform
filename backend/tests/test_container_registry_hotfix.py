from fastapi.testclient import TestClient
from app.main import app

def _auth(c):
    r=c.post('/auth/token',json={'username':'admin','password':'testpass'})
    if r.status_code!=200:
        r=c.post('/auth/token',json={'username':'admin','password':'ChangeMe123!'})
    return {'Authorization':'Bearer '+r.json()['access_token']}

def test_supplied_container_registry_is_available_and_linked_to_carriers():
    with TestClient(app) as c:
        h=_auth(c)
        rows=c.get('/master/container-registry',headers=h).json()
        assert len(rows)==595
        assert all(r['carrier_id'] and r['code'] and r['tare_weight'] for r in rows)
        carriers=c.get('/master/organizations?role=CARRIER',headers=h).json()
        carrier_ids={x['id'] for x in carriers}
        assert {r['carrier_id'] for r in rows}.issubset(carrier_ids)

def test_receiving_uses_registry_endpoint():
    with TestClient(app) as c:
        page=c.get('/desktop').text
        assert "/master/container-registry" in page
        assert 'Κάδος εισόδου' in page and 'Κάδος εξόδου' in page
