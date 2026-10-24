"""Δοκιμή ΟΥΡΑΣ ΕΓΓΡΑΦΩΝ (Windows και Android): χαμένη σύνδεση, επανάληψη με τον ίδιο κωδικό, χαμένη απάντηση (χωρίς διπλή εγγραφή), σειρά, αποθήκευση στη συσκευή
(επανεκκίνηση σελίδας), ώρα της οθόνης, απόρριψη από τον server (παράθυρο ΟΚ), μήνυμα μετά από 5′, ανενεργό κουμπί, ελληνικά μηνύματα, ένδειξη OFFLINE.
Χρήση: python backend/scripts/test_outbox.py http://127.0.0.1:PORT C:/ΑΝΤΙΓΡΑΦΟ.db   (ΜΟΝΟ σε ΑΝΤΙΓΡΑΦΟ βάσης!)"""
import sys, os, sqlite3, datetime, json, time
sys.path.insert(0, os.path.dirname(__file__)); sys.stdout.reconfigure(encoding='utf-8')
from playwright.sync_api import sync_playwright
from _browser import launch
B, DB = sys.argv[1], sys.argv[2]
bad = []
def ck(n, ok, i=''):
    print(('✓ ' if ok else '✗ ') + n, i)
    if not ok: bad.append(n)
db = lambda q, *a: sqlite3.connect(DB).execute(q, a).fetchall()
c = sqlite3.connect(DB)
lot = c.execute("select l.id,l.weee_category_id from weee_stock_lots l join collection_media m on m.id=l.collection_medium_id where l.available_weight>=120 order by l.id limit 1").fetchone()
U1 = c.execute("select id from organizational_units where active=1 and profile='PRODUCTION' order by id limit 1").fetchone()[0]
emps = [r[0] for r in c.execute("select e.employee_id from employee_org_units e join employees p on p.id=e.employee_id where e.org_unit_id=? and p.active=1 order by e.employee_id limit 2", (U1,)).fetchall()]
E1, E2 = emps[0], emps[1] if len(emps) > 1 else emps[0]
today = datetime.date.today().isoformat()
P = lambda s: datetime.datetime.fromisoformat(str(s).replace('Z', '')[:26])
def run(kind, p):
    print('=====', kind)
    b = launch(p)
    if kind == 'ANDROID': pg = b.new_page(viewport={'width': 360, 'height': 640}, is_mobile=True, has_touch=True)
    else: pg = b.new_page(viewport={'width': 1300, 'height': 900})
    errs = []; pg.on('pageerror', lambda e: errs.append(str(e)))
    url = B + ('/mobile' if kind == 'ANDROID' else '/')
    def login():
        pg.wait_for_selector('#loginBtn', state='visible'); pg.click('#loginBtn')
        pg.wait_for_selector('#app:not(.hidden)' if kind == 'ANDROID' else '#metrics .card', timeout=20000); pg.wait_for_timeout(2000)
    pg.goto(url, wait_until='networkidle'); login()
    pgctx = pg.context
    put = lambda body: pg.evaluate("b=>api('/production/attendance',{method:'PUT',body:JSON.stringify(b)})", body)
    # 1) κανονική εγγραφή
    r = put({'work_date': today, 'employee_id': E1, 'status': 'PRESENT'})
    ck('κανονική εγγραφή: επιβεβαιώνεται και η ουρά αδειάζει', r.get('employee_id') == E1 and not r.get('__queued') and pg.evaluate('!OB.pending()'))
    # 2) Greek message για ανάγνωση χωρίς σύνδεση + OFFLINE
    pgctx.set_offline(True)
    msg = pg.evaluate("api('/master/org-units').then(()=>'ok').catch(e=>e.message)")
    ck('χωρίς σύνδεση: μήνυμα στα ελληνικά (όχι «Failed to fetch»)', msg.startswith('Δεν έγινε επικοινωνία με τον server'), msg)
    ck('ένδειξη OFFLINE εμφανίζεται', ('OFFLINE' in pg.inner_text('#netTxt')) if kind == 'ANDROID' else pg.evaluate("document.getElementById('netState').style.display!=='none'"))
    pgctx.set_offline(False)
    block = lambda route: route.abort('connectionrefused') if route.request.method != 'GET' else route.continue_()
    pg.route('**/production/**', block)      # ο server «δεν απαντά» στις εγγραφές
    # 3) εγγραφές χωρίς σύνδεση: μπαίνουν σε ουρά, με τη σειρά
    t0 = time.time()
    pg.evaluate("document.body.insertAdjacentHTML('beforeend','<button id=obT>t</button>');document.getElementById('obT').addEventListener('click',()=>api('/production/attendance',{method:'PUT',body:JSON.stringify(%s)}).catch(()=>{}))" % json.dumps({'work_date': today, 'employee_id': E2, 'status': 'ABSENT'}))
    pg.click('#obT'); dis = pg.evaluate("document.getElementById('obT').disabled")
    ck('ανενεργό κουμπί όσο γίνεται η αποστολή', dis is True)
    a1 = pg.evaluate("b=>api('/production/attendance',{method:'PUT',body:JSON.stringify(b)})", {'work_date': today, 'employee_id': E1, 'status': 'ABSENT'})
    a2 = pg.evaluate("b=>api('/production/attendance',{method:'PUT',body:JSON.stringify(b)})", {'work_date': today, 'employee_id': E1, 'status': 'PRESENT', 'late': True})
    ck('χωρίς σύνδεση: το UI δεν κολλά (συνεχίζει «αισιόδοξα» σε λίγα δευτερόλεπτα)', a1.get('__queued') and a2.get('__queued') and time.time() - t0 < 40, f'{time.time()-t0:.0f}s')
    ck('η ουρά έχει 3 εκκρεμείς ενέργειες, αποθηκευμένες στη συσκευή', pg.evaluate('OB.list().length') == 3 and len(json.loads(pg.evaluate("localStorage.getItem('outbox.v1')"))) == 3)
    ck('πριν περάσουν 5′: ΚΑΝΕΝΑ μήνυμα', pg.query_selector('#obBanner') is None)
    # 4) ώρα οθόνης = 10′ πριν + επανεκκίνηση σελίδας (η ουρά μένει)
    t10 = (datetime.datetime.utcnow() - datetime.timedelta(minutes=10))
    pg.evaluate("t=>{let q=JSON.parse(localStorage.getItem('outbox.v1'));q.forEach((e,i)=>{e.at=new Date(new Date(t).getTime()+i*1000).toISOString()});localStorage.setItem('outbox.v1',JSON.stringify(q))}", t10.isoformat() + 'Z')
    pg.reload(wait_until='networkidle'); login()
    ck('μετά από επανεκκίνηση της σελίδας η ουρά ΜΕΝΕΙ (3 ενέργειες)', pg.evaluate("OB.list().length") == 3)
    # 5) μήνυμα μετά από 5′ (1 ενέργεια → μία γραμμή, 3 → «Δεν έχουν επιβεβαιωθεί ακόμα 3 ενέργειες»)
    pg.evaluate("()=>{let q=JSON.parse(localStorage.getItem('outbox.v1'));q.forEach(e=>e.created=Date.now()-6*60000);localStorage.setItem('outbox.v1',JSON.stringify(q))}")
    pg.reload(wait_until='networkidle'); login()
    pg.wait_for_timeout(11500)
    bn = pg.query_selector('#obBanner'); txt = bn.inner_text() if bn else ''
    ck('μετά από 5′: εμφανές μήνυμα «Δεν έχουν επιβεβαιωθεί ακόμα 3 ενέργειες» + λίστα + «συνεχίζει να προσπαθεί»', 'Δεν έχουν επιβεβαιωθεί ακόμα 3 ενέργειες' in txt and 'συνεχίζει να προσπαθεί' in txt and txt.count('•') == 3, txt.replace('\n', ' | '))
    pg.screenshot(path=os.environ['TEMP'] + f'/ob_{kind}.png')
    # 6) επαναφορά σύνδεσης → στέλνονται με τη σειρά, με την ώρα της οθόνης
    pg.unroute('**/production/**')
    pg.wait_for_function("!OB.pending()", timeout=90000)
    ck('με την επαναφορά σύνδεσης η ουρά αδειάζει μόνη της', True)
    ck('σειρά: το τελικό αποτέλεσμα είναι το τελευταίο που έγινε (ΠΑΡΩΝ, αργοπορία)', db("select status,late from production_attendance where employee_id=? order by updated_at desc limit 1", E1)[0] == ('PRESENT', 1))
    ck('το μήνυμα εξαφανίστηκε μόλις επιβεβαιώθηκαν', pg.query_selector('#obBanner') is None)
    arr = db("select arrived_at from production_attendance where employee_id=? order by updated_at desc limit 1", E1)[0][0]
    ck('ώρα άφιξης = ώρα της οθόνης (10′ πριν), όχι η ώρα που έφτασε το αίτημα', abs((P(arr) - t10).total_seconds()) < 180, f'{arr} vs {t10.isoformat()}')
    # 7) χαμένη ΑΠΑΝΤΗΣΗ (ο server έγραψε): επανάληψη με ίδιο κωδικό → ΚΑΜΙΑ διπλή εγγραφή
    n0 = db("select count(*) from production_transfers")[0][0]; state = {'n': 0}
    def lose_first(route):
        state['n'] += 1
        if state['n'] == 1:
            route.fetch(); route.abort('connectionreset')       # ο server έλαβε και έγραψε, η απάντηση «χάθηκε»
        else: route.continue_()
    pg.route('**/production/transfers', lose_first)
    body = {'destination_org_unit_id': U1, 'items': [{'stock_lot_id': lot[0], 'weight': 20}], 'work_entry': {'weee_category_id': lot[1], 'source': 'WINDOWS'}}
    pg.evaluate("b=>api('/production/transfers',{method:'POST',body:JSON.stringify(b)})", body)
    pg.wait_for_function("!OB.pending()", timeout=40000)
    ck('χαμένη απάντηση: ξαναστάλθηκε αυτόματα και υπάρχει ΜΙΑ μόνο μεταφορά (καμία διπλή)', state['n'] >= 2 and db("select count(*) from production_transfers")[0][0] == n0 + 1, f'προσπάθειες={state["n"]}')
    pg.unroute('**/production/transfers')
    # 8) απόρριψη από τον server → παράθυρο ΟΚ και η ενέργεια βγαίνει από την ουρά
    pg.evaluate("b=>api('/production/transfers',{method:'POST',body:JSON.stringify(b)}).catch(e=>window.__rej=e.message)", {**body, 'items': [{'stock_lot_id': lot[0], 'weight': 999999}]})
    pg.wait_for_selector('.obModal', timeout=15000)
    mt = pg.inner_text('.obModal')
    ck('απόρριψη: παράθυρο με σαφές μήνυμα και ΟΚ', 'Η ενέργεια δεν έγινε' in mt and 'Αποστολή υλικού' in mt and 'ΟΚ' in mt, mt.replace('\n', ' | '))
    ck('απορριφθείσα ενέργεια ΔΕΝ μένει στην ουρά (δεν ξαναδοκιμάζεται)', pg.evaluate('!OB.pending()'))
    pg.click('.obModal button'); ck('ΟΚ κλείνει το παράθυρο', pg.query_selector('.obModal') is None)
    # καθαρισμός
    tid = db("select id from production_transfers order by created_at desc limit 1")[0][0]
    pg.evaluate("t=>api('/production/transfers/'+t+'/cancel',{method:'POST'})", tid); pg.wait_for_function("!OB.pending()", timeout=20000)
    ck('σφάλματα σελίδας', not errs, str(errs[:2]))
    b.close()
with sync_playwright() as p:
    run('WINDOWS', p); run('ANDROID', p)
print('ΑΠΟΤΥΧΙΕΣ:', bad)
sys.exit(1 if bad else 0)
