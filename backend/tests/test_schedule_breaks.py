from fastapi.testclient import TestClient
from app.main import app


def auth(c):
    r = c.post('/auth/token', json={'username': 'admin', 'password': 'testpass'})
    assert r.status_code == 200, r.text
    return {'Authorization': 'Bearer ' + r.json()['access_token']}


def body(**over):
    sm = {'start': '06:30', 'end': '14:50', 'b1': {'start': '', 'end': ''}, 'b2': {'start': '', 'end': ''},
          'B': {'b1': {'start': '', 'end': ''}, 'b2': {'start': '', 'end': ''}}}
    sm.update(over)
    return {'active': 'summer', 'summer': sm,
            'winter': {'start': '07:15', 'end': '15:35'}, 'special': {'start': '06:30', 'end': '14:50'}}


def test_schedule_defaults_have_empty_breaks_and_group_b():
    with TestClient(app) as c:
        h = auth(c)
        r = c.get('/settings/schedule', headers=h).json()
        assert r['summer']['b1'] == {'start': '', 'end': ''}
        assert r['summer']['B']['b1'] == {'start': '', 'end': ''}   # Τμήμα Β ξεκινά κενό, χωρίς προεπιλεγμένες ώρες


def test_schedule_break_rules():
    with TestClient(app) as c:
        h = auth(c)
        ok = body(b1={'start': '09:00', 'end': '09:10'}, b2={'start': '11:30', 'end': '11:40'},
                  B={'b1': {'start': '09:30', 'end': '09:40'}, 'b2': {'start': '', 'end': ''}})
        r = c.put('/settings/schedule', headers=h, json=ok)
        assert r.status_code == 200, r.text
        got = c.get('/settings/schedule', headers=h).json()
        assert got['summer']['b1']['start'] == '09:00' and got['summer']['B']['b1']['end'] == '09:40'
        # μισό διάλειμμα
        r = c.put('/settings/schedule', headers=h, json=body(b1={'start': '09:00', 'end': ''}))
        assert r.status_code == 422
        # λήξη πριν την έναρξη
        r = c.put('/settings/schedule', headers=h, json=body(b1={'start': '10:00', 'end': '09:00'}))
        assert r.status_code == 422
        # εκτός βάρδιας (νέο διάλειμμα)
        r = c.put('/settings/schedule', headers=h, json=body(b1={'start': '15:00', 'end': '15:10'}))
        assert r.status_code == 422
        # επικάλυψη στο ίδιο τμήμα
        r = c.put('/settings/schedule', headers=h, json=body(b1={'start': '09:00', 'end': '09:20'}, b2={'start': '09:10', 'end': '09:30'}))
        assert r.status_code == 422
        # ίδιες ώρες σε Α και Β επιτρέπονται (άλλη ομάδα)
        r = c.put('/settings/schedule', headers=h, json=body(b1={'start': '09:00', 'end': '09:20'}, B={'b1': {'start': '09:10', 'end': '09:30'}, 'b2': {'start': '', 'end': ''}}))
        assert r.status_code == 200, r.text


def test_shift_change_keeps_existing_break_outside_bounds():
    with TestClient(app) as c:
        h = auth(c)
        r = c.put('/settings/schedule', headers=h, json=body(b1={'start': '09:00', 'end': '09:10'}))
        assert r.status_code == 200, r.text
        # η βάρδια γίνεται 10:00-14:50: το ήδη αποθηκευμένο διάλειμμα 09:00-09:10 βγαίνει εκτός, ΔΕΝ απορρίπτεται και ΔΕΝ διαγράφεται
        r = c.put('/settings/schedule', headers=h, json=body(start='10:00', b1={'start': '09:00', 'end': '09:10'}))
        assert r.status_code == 200, r.text
        got = c.get('/settings/schedule', headers=h).json()
        assert got['summer']['b1'] == {'start': '09:00', 'end': '09:10'}


def test_break_groups_roundtrip():
    with TestClient(app) as c:
        h = auth(c)
        assert c.get('/settings/break-groups', headers=h).json() == {}
        r = c.put('/settings/break-groups', headers=h, json={'u1': 'B', 'u2': 'A'})
        assert r.status_code == 200
        assert c.get('/settings/break-groups', headers=h).json() == {'u1': 'B', 'u2': 'A'}
        assert c.put('/settings/break-groups', headers=h, json={'u1': 'Z'}).status_code == 422


def test_late_and_left_together_keep_both_times():
    with TestClient(app) as c:
        h = auth(c)
        emp = c.post('/master/employees', headers=h, json={'full_name': 'Δοκιμή Συνδυασμού'}).json()
        day = '2026-10-14'
        arr = '2026-10-14T05:40:00Z'
        left = '2026-10-14T10:30:00Z'
        # Αργοπορία
        r = c.put('/production/attendance', headers=h, json={'work_date': day, 'employee_id': emp['id'], 'status': 'PRESENT', 'late': True, 'arrived_at': arr})
        assert r.status_code == 200, r.text
        # + Έφυγε: κρατά αργοπορία και ώρα άφιξης
        r = c.put('/production/attendance', headers=h, json={'work_date': day, 'employee_id': emp['id'], 'status': 'LEFT', 'since_at': left})
        assert r.status_code == 200, r.text
        j = r.json()
        assert j['status'] == 'LEFT' and j['late'] is True and j['arrived_at'] and j['since_at']
        # αλλαγή ώρας άφιξης ενώ είναι «Έφυγε»
        r = c.put('/production/attendance', headers=h, json={'work_date': day, 'employee_id': emp['id'], 'status': 'LEFT', 'since_at': left, 'late': True, 'arrived_at': '2026-10-14T06:15:00Z'})
        j = r.json()
        assert j['status'] == 'LEFT' and j['late'] is True and j['arrived_at'].startswith('2026-10-14T06:15')
        # Απών σβήνει αργοπορία
        r = c.put('/production/attendance', headers=h, json={'work_date': day, 'employee_id': emp['id'], 'status': 'ABSENT'})
        j = r.json()
        assert j['status'] == 'ABSENT' and not j['late'] and not j['arrived_at']
