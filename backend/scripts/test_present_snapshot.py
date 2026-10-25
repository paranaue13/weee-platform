"""Δοκιμή server › στιγμιότυπο παρόντων σε κάθε αποστολή και Υπόλοιπο (μόνο αποθήκευση, κανένα kg δεν αλλάζει).
Χρήση: python backend/scripts/test_present_snapshot.py http://127.0.0.1:PORT C:/ΑΝΤΙΓΡΑΦΟ.db   (ΜΟΝΟ σε ΑΝΤΙΓΡΑΦΟ βάσης!)"""
import sys, os, sqlite3, json, datetime
sys.path.insert(0, os.path.dirname(__file__)); sys.stdout.reconfigure(encoding='utf-8')
from playwright.sync_api import sync_playwright
from _browser import launch
B, DB = sys.argv[1], sys.argv[2]
bad = []
def ck(n, ok, i=''):
    print(('✓ ' if ok else '✗ ') + n, i)
    if not ok: bad.append(n)
from _testdata import ensure_medium_lots; ensure_medium_lots(DB)
c = sqlite3.connect(DB)
lot = c.execute("select l.id,l.weee_category_id from weee_stock_lots l join collection_media m on m.id=l.collection_medium_id where l.available_weight>=120 order by l.id limit 1").fetchone()
unit = c.execute("select u.id from organizational_units u join employee_org_units e on e.org_unit_id=u.id join employees p on p.id=e.employee_id where u.active=1 and u.profile='PRODUCTION' and p.active=1 group by u.id having count(*)>=4 order by u.id limit 1").fetchone()[0]
emps = [r[0] for r in c.execute("select e.employee_id from employee_org_units e join employees p on p.id=e.employee_id where e.org_unit_id=? and p.active=1 order by e.employee_id limit 4", (unit,)).fetchall()]
E1, E2, E3, E4 = emps
today = datetime.date.today().isoformat(); now = datetime.datetime.now(); hm = lambda d: d.strftime('%H:%M')
with sync_playwright() as p:
    b = launch(p); pg = b.new_page()
    pg.goto(B + '/', wait_until='networkidle'); pg.wait_for_selector('#loginBtn', state='visible'); pg.click('#loginBtn'); pg.wait_for_selector('#metrics .card', timeout=20000); pg.wait_for_timeout(800)
    def call(m, path, body=None):
        return pg.evaluate("([m,p,b])=>fetch(p,{method:m,headers:{'Content-Type':'application/json','Authorization':'Bearer '+token},body:b?JSON.stringify(b):undefined}).then(async r=>[r.status,await r.json().catch(()=>null)])", [m, path, body])
    att = lambda e, **k: call('PUT', '/production/attendance', {'work_date': today, 'employee_id': e, **k})
    att(E1, status='PRESENT'); att(E2, status='ABSENT')
    att(E3, status='PRESENT', short_leaves=[{'from': hm(now - datetime.timedelta(minutes=2)), 'to': None}])
    att(E4, status='LEFT', since_at=(datetime.datetime.utcnow() - datetime.timedelta(minutes=1)).isoformat() + 'Z')
    # όλοι οι άλλοι του τμήματος: απόντες, ώστε η δοκιμή να είναι ακριβής
    for (e,) in c.execute("select e.employee_id from employee_org_units e where e.org_unit_id=?", (unit,)).fetchall():
        if e not in emps: att(e, status='ABSENT')
    null0 = c.execute("select count(*) from production_transfers where present_json is null").fetchone()[0]
    w0 = float(c.execute("select available_weight from weee_stock_lots where id=?", (lot[0],)).fetchone()[0])
    st, j = call('POST', '/production/transfers', {'destination_org_unit_id': unit, 'items': [{'stock_lot_id': lot[0], 'weight': 100}]})
    call('POST', '/production/work-entries', {'work_date': today + 'T00:00:00', 'org_unit_id': unit, 'weee_category_id': lot[1], 'weight_kg': 100, 'source': 'WINDOWS', 'transfer_id': j['id']})
    tid = j['id']; c2 = sqlite3.connect(DB)
    snap = json.loads(c2.execute("select present_json from production_transfers where id=?", (tid,)).fetchone()[0])
    ck('στιγμιότυπο αποθηκεύτηκε στην αποστολή', snap['unit_id'] == unit, str(snap))
    ck('παρών ΜΟΝΟ ο ΠΑΡΩΝ (όχι απών, όχι σε ολιγόωρη, όχι ΕΦΥΓΕ)', snap['employee_ids'] == [E1], str(snap['employee_ids']))
    item = call('GET', f'/production/device-list?date={today}')[1]; item = [d for d in item if d['transfer_id'] == tid][0]
    ck('τα kg στην οθόνη ΔΕΝ άλλαξαν (100)', item['weight_kg'] == 100 and item['sent_kg'] == 100)
    # αλλαγή παρουσιών και Υπόλοιπο → δεύτερο στιγμιότυπο
    att(E2, status='PRESENT'); att(E3, status='PRESENT', short_leaves=[])
    st, r = call('POST', f"/production/transfer-items/{item['item_id']}/remainder", {'mode': 'NET', 'kg': 30})
    rs = json.loads(sqlite3.connect(DB).execute("select remainder_present from production_transfer_items where id=?", (item['item_id'],)).fetchone()[0])
    ck('Υπόλοιπο: νέο στιγμιότυπο παρόντων (άλλοι από την αποστολή)', st == 200 and set(rs['employee_ids']) == {E1, E2, E3}, str(rs['employee_ids']))
    ck('η αρχική αποστολή κρατά το ΔΙΚΟ ΤΗΣ στιγμιότυπο', json.loads(sqlite3.connect(DB).execute("select present_json from production_transfers where id=?", (tid,)).fetchone()[0])['employee_ids'] == [E1])
    ck('kg: καθαρή παραγωγή 70 όπως πριν (δεν επηρεάστηκε από το στιγμιότυπο)', r['net_production'] == 70)
    call('POST', f"/production/transfer-items/{item['item_id']}/remainder/undo")
    ck('αναίρεση υπολοίπου καθαρίζει το δεύτερο στιγμιότυπο', sqlite3.connect(DB).execute("select remainder_present from production_transfer_items where id=?", (item['item_id'],)).fetchone()[0] is None)
    null1 = sqlite3.connect(DB).execute("select count(*) from production_transfers where present_json is null").fetchone()[0]
    ck('παλιές μεταφορές: ΚΑΜΙΑ αναπαράσταση (μένουν χωρίς στιγμιότυπο)', null1 == null0, f'{null0} → {null1}')
    call('POST', f'/production/transfers/{tid}/cancel')
    b.close()
print('ΑΠΟΤΥΧΙΕΣ:', bad)
sys.exit(1 if bad else 0)
