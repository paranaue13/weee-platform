from fastapi.testclient import TestClient
from app.main import app


def auth(c):
    r = c.post('/auth/token', json={'username': 'admin', 'password': 'testpass'})
    assert r.status_code == 200, r.text
    return {'Authorization': 'Bearer ' + r.json()['access_token']}


def test_sorting_overview_is_read_only_and_validates():
    with TestClient(app) as c:
        h = auth(c)
        r = c.get('/sorting/overview', headers=h, params={'start': '2026-01-01', 'end': '2026-12-31'})
        assert r.status_code == 200, r.text
        assert isinstance(r.json()['loads'], dict)
        assert c.get('/sorting/overview', headers=h, params={'start': 'x', 'end': '2026-12-31'}).status_code == 422
