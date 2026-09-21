from fastapi.testclient import TestClient
from app.main import app

def test_health_and_seed():
    with TestClient(app) as c:
        assert c.get("/health").status_code==200
        r=c.post("/auth/token",json={"username":"admin","password":"testpass"})
        assert r.status_code==200
        token=r.json()["access_token"]
        h={"Authorization":f"Bearer {token}"}
        units=c.get("/master/org-units",headers=h)
        assert units.status_code==200
        assert any(x["name_el"]=="Τμήμα Ταξινόμησης" for x in units.json())
        cats=c.get("/master/weee-categories",headers=h)
        assert cats.status_code==200 and len(cats.json())>30
        mats=c.get("/master/materials",headers=h)
        assert mats.status_code==200 and any(x["galaxy_code"]=="Α00001" for x in mats.json())
        mts=c.get("/master/medium-types",headers=h).json()
        # BIG_BAG is a deprecated legacy type (kept inactive for old-database
        # compatibility, see test_sorting_mvp.test_legacy_big_bag_is_not_offered_as_active_medium_type).
        # Current active numbered type is BASKET_LARGE.
        basket=next(x for x in mts if x["code"]=="BASKET_LARGE")
        made=c.post("/master/media",headers=h,json={"type_id":basket["id"],"code":"SMOKE-BASKET-001"})
        assert made.status_code==200
        assert made.json()["code"]=="SMOKE-BASKET-001"
