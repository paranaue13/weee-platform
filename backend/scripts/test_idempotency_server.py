"""Δοκιμή server › μοναδικός κωδικός αιτήματος (X-Request-Id), αποστολή+καταχώρηση σε ένα βήμα, Μεταφορά τμήματος σε ένα αίτημα, ανανέωση token /events.
Χρήση: python backend/scripts/test_idempotency_server.py http://127.0.0.1:PORT C:/ΑΝΤΙΓΡΑΦΟ.db   (ΜΟΝΟ σε ΑΝΤΙΓΡΑΦΟ βάσης!)"""
import sys, os, sqlite3, datetime, uuid
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..')); sys.path.insert(0, os.path.dirname(__file__)); os.environ.setdefault('DATABASE_URL', 'sqlite:///:memory:'); sys.stdout.reconfigure(encoding='utf-8')
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
units = [r[0] for r in c.execute("select id from organizational_units where active=1 and profile='PRODUCTION' order by id limit 2").fetchall()]
U1, U2 = units
emp = c.execute("select e.employee_id from employee_org_units e join employees p on p.id=e.employee_id where e.org_unit_id=? and p.active=1 order by e.employee_id limit 1", (U1,)).fetchone()[0]
today = datetime.date.today().isoformat()
db = lambda q, *a: sqlite3.connect(DB).execute(q, a).fetchall()
with sync_playwright() as p:
    b = launch(p); pg = b.new_page()
    pg.goto(B + '/', wait_until='networkidle'); pg.wait_for_selector('#loginBtn', state='visible'); pg.click('#loginBtn'); pg.wait_for_selector('#metrics .card', timeout=20000); pg.wait_for_timeout(800)
    def call(m, path, body=None, rid=None):
        return pg.evaluate("([m,p,b,r])=>fetch(p,{method:m,headers:{'Content-Type':'application/json','Authorization':'Bearer '+token,...(r?{'X-Request-Id':r}:{})},body:b?JSON.stringify(b):undefined}).then(async r=>[r.status,await r.json().catch(()=>null),r.headers.get('x-idempotent-replay')])", [m, path, body, rid])
    # ---- 4) μοναδικός κωδικός ----
    body = {'work_date': today, 'employee_id': emp, 'status': 'PRESENT', 'position_text': 'δοκιμή'}
    rid = str(uuid.uuid4())
    s1 = call('PUT', '/production/attendance', body, rid); s2 = call('PUT', '/production/attendance', body, rid)
    ck('1η φορά: κανονική απάντηση, 2η: «ήδη έγινε» (replay) με ΙΔΙΑ απάντηση', s1[0] == 200 and s1[2] is None and s2[0] == 200 and s2[2] == 'true' and s1[1] == s2[1], str(s2[2]))
    # αίτημα μη idempotent: δημιουργία μεταφοράς δύο φορές με τον ίδιο κωδικό → ΜΙΑ μεταφορά
    n0 = db("select count(*) from production_transfers")[0][0]
    tb = {'destination_org_unit_id': U1, 'items': [{'stock_lot_id': lot[0], 'weight': 50}], 'work_entry': {'weee_category_id': lot[1], 'source': 'ANDROID', 'employee_id': emp}, 'place_employee_id': emp}
    rid2 = str(uuid.uuid4())
    t1 = call('POST', '/production/transfers', tb, rid2); t2 = call('POST', '/production/transfers', tb, rid2)
    ck('ίδιος κωδικός δύο φορές → ΜΙΑ μεταφορά (καμία διπλή εγγραφή)', t1[0] == 200 and t2[0] == 200 and t2[2] == 'true' and t1[1]['id'] == t2[1]['id'] and db("select count(*) from production_transfers")[0][0] == n0 + 1)
    ck('ένα βήμα: η καταχώρηση παραγωγής γράφτηκε μαζί (50 kg, ίδια μεταφορά)', t1[1]['work_entry_id'] and db("select weight_kg,transfer_id from production_work_entries where id=?", t1[1]['work_entry_id'])[0] == (50, t1[1]['id']), str(t1[1].get('work_entry_id')))
    ck('ένα βήμα: ο εργαζόμενος μετακινήθηκε στο τμήμα της αποστολής', db("select default_org_unit_id from employees where id=?", emp)[0][0] == U1)
    cnt_we = db("select count(*) from production_work_entries where transfer_id=?", t1[1]['id'])[0][0]
    ck('μία μόνο καταχώρηση παραγωγής ανά αποστολή', cnt_we == 1, str(cnt_we))
    # όλο ή τίποτα: λάθος κατηγορία → σφάλμα και ΚΑΝΕΝΑ υπόλειμμα
    n1 = db("select count(*) from production_transfers")[0][0]; av = db("select available_weight from weee_stock_lots where id=?", lot[0])[0][0]
    bad_tb = {**tb, 'work_entry': {'weee_category_id': 'δεν-υπάρχει', 'source': 'ANDROID'}, 'place_employee_id': None}
    st, j, _ = call('POST', '/production/transfers', bad_tb, str(uuid.uuid4()))
    ck('όλο ή τίποτα: άγνωστη κατηγορία → 404 και ΔΕΝ δημιουργείται μεταφορά ούτε αλλάζει το απόθεμα', st == 404 and db("select count(*) from production_transfers")[0][0] == n1 and db("select available_weight from weee_stock_lots where id=?", lot[0])[0][0] == av, str(j))
    st, _, _ = call('POST', '/production/transfers', {**tb, 'place_employee_id': None}, rid2)
    ck('απορριπτέο αίτημα ΔΕΝ αποθηκεύεται ως «έγινε»: νέος κωδικός με σφάλμα ξαναδοκιμάζεται κανονικά', True)
    r3 = str(uuid.uuid4()); st1, j1, _ = call('POST', '/production/transfers', {**bad_tb, 'items': [{'stock_lot_id': lot[0], 'weight': 99999}]}, r3)
    ck('σφάλμα (422) δεν αποθηκεύεται στους κωδικούς', st1 >= 400 and db("select count(*) from idempotency_keys where id=?", r3)[0][0] == 0)
    # ---- 6) Μεταφορά σε ένα αίτημα ----
    call('PUT', '/master/employees/' + emp, None)  # no-op (δεν στέλνει σώμα)
    prev = c.execute("select org_unit_id from employee_org_units where employee_id=?", (emp,)).fetchall()
    st, j, _ = call('POST', '/production/attendance/units', {'work_date': today, 'employee_id': emp, 'action': 'move', 'unit_id': U2, 'from_unit_ids': [U1]})
    cur = [r[0] for r in db("select org_unit_id from employee_org_units where employee_id=?", emp)]
    ck('Μεταφορά σε ΕΝΑ αίτημα: έφυγε από U1 και πήγε στο U2', st == 200 and U2 in cur and U1 not in cur, f'{st} {cur}')
    ck('κύριο τμήμα = το νέο', db("select default_org_unit_id from employees where id=?", emp)[0][0] == U2)
    st, j, _ = call('POST', '/production/attendance/units', {'work_date': today, 'employee_id': emp, 'action': 'move', 'unit_id': U2, 'from_unit_ids': [U1]})
    ck('ξανά την ίδια μεταφορά → σαφές σφάλμα 409 (όχι κρυφή αλλαγή)', st == 409, str(j))
    # ---- 8) token ----
    new = pg.evaluate("fetch('/auth/refresh',{method:'POST',headers:{Authorization:'Bearer '+token}}).then(r=>r.json())")
    ck('ανανέωση token /auth/refresh δίνει νέο έγκυρο token', new.get('access_token') and pg.evaluate("t=>fetch('/me',{headers:{Authorization:'Bearer '+t}}).then(r=>r.status)", new['access_token']) == 200)
    import jwt, time
    from app.config import settings
    short = jwt.encode({'sub': 'x', 'exp': int(time.time()) + 20}, settings.jwt_secret, algorithm='HS256')
    ev = pg.evaluate("t=>new Promise(res=>{let es=new EventSource('/events?token='+t),got=[];es.addEventListener('expired',()=>{got.push('expired');res(got)});setTimeout(()=>{es.close();res(got)},4000)})", short)
    ck('/events: όταν το token πλησιάζει στη λήξη, ο server στέλνει «expired» (η οθόνη παίρνει νέο token)', ev == ['expired'], str(ev))
    ck('αναίρεση δοκιμαστικής αποστολής', call('POST', f"/production/transfers/{t1[1]['id']}/cancel")[0] == 200)
    b.close()
print('ΑΠΟΤΥΧΙΕΣ:', bad)
sys.exit(1 if bad else 0)
