from app.main import app

def test_reopen_route_exists():
    paths={r.path for r in app.routes}
    assert '/sorting/{load_id}/reopen' in paths
