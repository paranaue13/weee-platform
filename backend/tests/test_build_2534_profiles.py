from fastapi.testclient import TestClient
from app.main import app


def auth(c):
    r=c.post('/auth/token',json={'username':'admin','password':'testpass'})
    assert r.status_code==200, r.text
    return {'Authorization':'Bearer '+r.json()['access_token']}


def test_2534_registry_profiles_and_rules():
    with TestClient(app) as c:
        h=auth(c)
        # Customers registry role.
        r=c.post('/master/organizations',headers=h,json={'legal_name':'Πελάτης 2534','roles':['CLIENT']})
        assert r.status_code==200, r.text
        cid=r.json()['id']
        rows=c.get('/master/organizations',headers=h,params={'role':'CLIENT','include_inactive':'true'}).json()
        assert any(x['id']==cid for x in rows)
        # Materials: active iff ERP exists; export precision is material-driven.
        mats=c.get('/master/materials',headers=h,params={'include_inactive':'true'}).json()
        active=[m for m in mats if m['active']]
        assert active and all((m.get('galaxy_code') or '').strip() for m in active)
        assert any(m['is_precious'] and float(m['export_step_kg'])==0.05 for m in active)
        assert any((not m['is_precious']) and float(m['export_step_kg'])==0.5 for m in active)
        r=c.post('/master/materials',headers=h,json={'internal_code':'NOERP2534','internal_name':'Χωρίς ERP'})
        assert r.status_code==200 and r.json()['active'] is False
        assert c.post(f"/master/materials/{r.json()['id']}/activate",headers=h).status_code==409
        # WEEE canonical profile fields are exposed.
        wd=c.get('/master/weee-display',headers=h,params={'include_inactive':'true'}).json()
        assert wd and {'her_description','eka_code','processable'}.issubset(wd[0])
        # Container ownership by carrier.
        carrier=c.post('/master/organizations',headers=h,json={'legal_name':'Μεταφορική 2534','roles':['CARRIER']}).json()
        cont=c.post('/master/containers',headers=h,json={'container_number':'C2534','owner_organization_id':carrier['id'],'tare_weight':'2500'})
        assert cont.status_code==200 and cont.json()['owner_organization_id']==carrier['id']
        # Departments positions + multi-department employee.
        a=c.post('/master/org-units',headers=h,json={'code':'A2534','name_el':'Τμήμα Α','positions':['Θέση 1','Θέση 2']}).json()
        b=c.post('/master/org-units',headers=h,json={'code':'B2534','name_el':'Τμήμα Β','positions':['Θέση 3']}).json()
        emp=c.post('/master/employees',headers=h,json={'full_name':'Εργαζόμενος 2534','phone':'6900000000','org_unit_ids':[a['id'],b['id']]})
        assert emp.status_code==200 and len(emp.json()['org_unit_ids'])==2
        # Multi-department membership must also be visible through the listing endpoint.
        listing=c.get('/master/employees',headers=h,params={'include_inactive':'true'}).json()
        row=next(x for x in listing if x['id']==emp.json()['id'])
        assert len(row['org_unit_ids'])==2
