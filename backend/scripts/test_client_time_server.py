"""Δοκιμή server › ώρα της οθόνης (X-Occurred-At) για παρουσίες/αποστολές/Υπόλοιπο/μεταφορές + καθαρισμός παλιών κωδικών (30 ημέρες).
Χρήση: python backend/scripts/test_client_time_server.py http://127.0.0.1:PORT C:/ΑΝΤΙΓΡΑΦΟ.db
ΠΡΟΣΟΧΗ: πριν την εκκίνηση του server σε ΑΝΤΙΓΡΑΦΟ, τρέξε με --seed για να μπουν παλιοί κωδικοί:  python ... --seed C:/ΑΝΤΙΓΡΑΦΟ.db"""
import sys, os, sqlite3, datetime
sys.path.insert(0, os.path.dirname(__file__)); sys.stdout.reconfigure(encoding='utf-8')
if sys.argv[1] == '--seed':
    c = sqlite3.connect(sys.argv[2]); now = datetime.datetime.utcnow()
    c.execute("create table if not exists idempotency_keys (id varchar(64) primary key, method varchar(10), path varchar(300), status integer, body text, created_at datetime)")
    c.execute("insert or replace into idempotency_keys values ('old-35d','POST','/x',200,'{}',?)", ((now - datetime.timedelta(days=35)).isoformat(sep=' '),))
    c.execute("insert or replace into idempotency_keys values ('old-31d','POST','/x',200,'{}',?)", ((now - datetime.timedelta(days=31)).isoformat(sep=' '),))
    c.execute("insert or replace into idempotency_keys values ('new-5d','POST','/x',200,'{}',?)", ((now - datetime.timedelta(days=5)).isoformat(sep=' '),))
    c.commit(); print('seed ok'); sys.exit(0)
from playwright.sync_api import sync_playwright
from _browser import launch
B, DB = sys.argv[1], sys.argv[2]
bad = []
def ck(n, ok, i=''):
    print(('✓ ' if ok else '✗ ') + n, i)
    if not ok: bad.append(n)
db = lambda q, *a: sqlite3.connect(DB).execute(q, a).fetchall()
ids = [r[0] for r in db("select id from idempotency_keys")]
ck('καθαρισμός στην εκκίνηση: κωδικοί >30 ημερών σβήστηκαν', 'old-35d' not in ids and 'old-31d' not in ids, str(ids))
ck('οι πρόσφατοι κωδικοί (5 ημερών) ΜΕΝΟΥΝ', 'new-5d' in ids)
c = sqlite3.connect(DB)
lot = c.execute("select l.id,l.weee_category_id from weee_stock_lots l join collection_media m on m.id=l.collection_medium_id where l.available_weight>=120 order by l.id limit 1").fetchone()
U1, U2 = [r[0] for r in c.execute("select id from organizational_units where active=1 and profile='PRODUCTION' order by id limit 2").fetchall()]
emp = c.execute("select e.employee_id from employee_org_units e join employees p on p.id=e.employee_id where e.org_unit_id=? and p.active=1 order by e.employee_id limit 1", (U1,)).fetchone()[0]
today = datetime.date.today().isoformat()
iso = lambda d: d.strftime('%Y-%m-%dT%H:%M:%S.000Z')
with sync_playwright() as p:
    b = launch(p); pg = b.new_page()
    pg.goto(B + '/', wait_until='networkidle'); pg.wait_for_selector('#loginBtn', state='visible'); pg.click('#loginBtn'); pg.wait_for_selector('#metrics .card', timeout=20000); pg.wait_for_timeout(800)
    def call(m, path, body=None, at=None):
        return pg.evaluate("([m,p,b,a])=>fetch(p,{method:m,headers:{'Content-Type':'application/json','Authorization':'Bearer '+token,...(a?{'X-Occurred-At':a}:{})},body:b?JSON.stringify(b):undefined}).then(async r=>[r.status,await r.json().catch(()=>null)])", [m, path, body, at])
    now = datetime.datetime.utcnow(); t10 = now - datetime.timedelta(minutes=10)
    near = lambda a, b_, sec=90: abs((a - b_).total_seconds()) <= sec
    P = lambda s: datetime.datetime.fromisoformat(str(s).replace('Z', '')[:26])
    # ---- παρουσίες: απών → ήρθε (η άφιξη = ώρα της οθόνης, 10′ πριν) ----
    call('PUT', '/production/attendance', {'work_date': today, 'employee_id': emp, 'status': 'ABSENT'})
    st, j = call('PUT', '/production/attendance', {'work_date': today, 'employee_id': emp, 'status': 'PRESENT', 'late': True}, iso(t10))
    arr = db("select arrived_at from production_attendance where employee_id=? order by updated_at desc limit 1", emp)[0][0]
    ck('παρουσία: η ώρα άφιξης = η ώρα της οθόνης (10′ πριν), όχι η ώρα που έφτασε', st == 200 and near(P(arr), t10), f'{arr} vs {iso(t10)}')
    ev = db("select created_at from production_attendance_events where employee_id=? and status='PRESENT' and late=1 order by created_at desc limit 1", emp)[0][0]
    ck('ιστορικό αλλαγών: ώρα = ώρα της οθόνης', near(P(ev), t10), str(ev))
    # ---- αποστολή υλικού ----
    st, j = call('POST', '/production/transfers', {'destination_org_unit_id': U1, 'items': [{'stock_lot_id': lot[0], 'weight': 50}], 'work_entry': {'weee_category_id': lot[1], 'source': 'ANDROID'}, 'place_employee_id': emp}, iso(t10))
    tid = j['id']
    tc = db("select created_at from production_transfers where id=?", tid)[0][0]
    ck('αποστολή: ώρα μεταφοράς = ώρα της οθόνης', near(P(tc), t10), str(tc))
    ck('αποστολή: ώρα καταχώρησης παραγωγής και κίνησης αποθήκης = ώρα της οθόνης', near(P(db("select created_at from production_work_entries where transfer_id=?", tid)[0][0]), t10) and db("select count(*) from stock_movements where lot_id=? and movement_type='TO_PRODUCTION' and created_at between ? and ?", lot[0], (t10 - datetime.timedelta(minutes=1)).isoformat(sep=' '), (t10 + datetime.timedelta(minutes=1)).isoformat(sep=' '))[0][0] >= 1)
    dv = [d for d in call('GET', f'/production/device-list?date={today}')[1] if d['transfer_id'] == tid][0]
    ck('η λίστα συσκευών δείχνει την ώρα της οθόνης (HH:MM τοπική)', dv['time'] == (t10.replace(tzinfo=datetime.timezone.utc).astimezone()).strftime('%H:%M'), dv['time'])
    # ---- Υπόλοιπο ----
    t5 = now - datetime.timedelta(minutes=5)
    st, j = call('POST', f"/production/transfer-items/{dv['item_id']}/remainder", {'mode': 'NET', 'kg': 10}, iso(t5))
    ra = db("select remainder_at from production_transfer_items where id=?", dv['item_id'])[0][0]
    ck('Υπόλοιπο: ώρα = ώρα της οθόνης (5′ πριν)', st == 200 and near(P(ra), t5), str(ra))
    # ---- μεταφορά εργαζομένου: ώρα διαστήματος τοποθέτησης ----
    st, j = call('POST', '/production/attendance/units', {'work_date': today, 'employee_id': emp, 'action': 'move', 'unit_id': U2, 'from_unit_ids': [U1]}, iso(t5))
    iv = db("select started_at from production_placement_intervals where employee_id=? order by started_at desc limit 1", emp)[0][0]
    ck('μεταφορά εργαζομένου: έναρξη διαστήματος τοποθέτησης = ώρα της οθόνης', st == 200 and near(P(iv), t5), str(iv))
    # ---- έλεγχοι ----
    st, j = call('PUT', '/production/attendance', {'work_date': today, 'employee_id': emp, 'status': 'PRESENT'}, iso(now + datetime.timedelta(minutes=20)))
    ck('ώρα στο ΜΕΛΛΟΝ (+20′) → απορρίπτεται με σαφές μήνυμα', st == 422 and 'μέλλον' in j['detail'], str(j))
    st, j = call('PUT', '/production/attendance', {'work_date': today, 'employee_id': emp, 'status': 'PRESENT'}, iso(now + datetime.timedelta(minutes=2)))
    ck('μικρή διαφορά ρολογιού (+2′) → δεκτή (κόβεται στην τωρινή)', st == 200)
    st, j = call('PUT', '/production/attendance', {'work_date': today, 'employee_id': emp, 'status': 'PRESENT'}, iso(now - datetime.timedelta(days=4)))
    ck('ώρα πολύ παλιά (4 ημέρες) → απορρίπτεται με σαφές μήνυμα', st == 422 and '3 ημέρες' in j['detail'], str(j))
    st, j = call('PUT', '/production/attendance', {'work_date': today, 'employee_id': emp, 'status': 'PRESENT'}, 'garbage')
    ck('μη έγκυρη ώρα → απορρίπτεται', st == 422)
    n = db("select count(*) from production_transfers")[0][0]
    st, j = call('POST', '/production/transfers', {'destination_org_unit_id': U1, 'items': [{'stock_lot_id': lot[0], 'weight': 5}]}, iso(now + datetime.timedelta(hours=2)))
    ck('απορριπτέο αίτημα (ώρα μέλλοντος) ΔΕΝ γράφει τίποτα', st == 422 and db("select count(*) from production_transfers")[0][0] == n)
    # χωρίς header: συμπεριφορά όπως πριν (ώρα server)
    st, j = call('POST', '/production/transfers', {'destination_org_unit_id': U1, 'items': [{'stock_lot_id': lot[0], 'weight': 5}]})
    tc2 = db("select created_at from production_transfers where id=?", j['id'])[0][0]
    ck('χωρίς ώρα οθόνης: γράφεται η ώρα του server (όπως πριν)', near(P(tc2), datetime.datetime.utcnow(), 30), str(tc2))
    for t in (tid, j['id']): call('POST', f'/production/transfers/{t}/cancel')
    b.close()
print('ΑΠΟΤΥΧΙΕΣ:', bad)
sys.exit(1 if bad else 0)
