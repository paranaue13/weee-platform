"""Δοκιμή server › /events (Server-Sent Events): ειδοποίηση αλλαγής μέσα σε 1–2″ για παρουσίες/παραγωγή.
Χρήση: python backend/scripts/test_events_server.py http://127.0.0.1:PORT C:/ΑΝΤΙΓΡΑΦΟ.db   (ΜΟΝΟ σε ΑΝΤΙΓΡΑΦΟ βάσης!)"""
import sys, os, sqlite3, datetime
sys.path.insert(0, os.path.dirname(__file__)); sys.stdout.reconfigure(encoding='utf-8')
from playwright.sync_api import sync_playwright
from _browser import launch
B, DB = sys.argv[1], sys.argv[2]
bad = []
def ck(n, ok, i=''):
    print(('✓ ' if ok else '✗ ') + n, i)
    if not ok: bad.append(n)
c = sqlite3.connect(DB)
emp = c.execute("select id from employees where active=1 order by id limit 1").fetchone()[0]
today = datetime.date.today().isoformat()
with sync_playwright() as p:
    b = launch(p); pg = b.new_page(viewport={'width': 1200, 'height': 800})
    pg.goto(B + '/', wait_until='networkidle'); pg.wait_for_selector('#loginBtn', state='visible'); pg.click('#loginBtn'); pg.wait_for_selector('#metrics .card', timeout=20000); pg.wait_for_timeout(800)
    r = pg.evaluate("fetch('/events?token=bad').then(r=>r.status)")
    ck('χωρίς έγκυρο token → 401', r == 401, str(r))
    pg.evaluate("""()=>{window.__ev=[];window.__es=new EventSource('/events?token='+encodeURIComponent(token));window.__es.onmessage=e=>window.__ev.push([performance.now(),JSON.parse(e.data)])}""")
    pg.wait_for_timeout(800)
    put = lambda: pg.evaluate("([e,d])=>{window.__t0=performance.now();return fetch('/production/attendance',{method:'PUT',headers:{'Content-Type':'application/json','Authorization':'Bearer '+token},body:JSON.stringify({work_date:d,employee_id:e,status:'PRESENT'})}).then(r=>r.status)}", [emp, today])
    st = put(); pg.wait_for_function("window.__ev.length>0", timeout=5000)
    lat = pg.evaluate("window.__ev[0][0]-window.__t0"); tp = pg.evaluate("window.__ev[0][1]")
    ck('αλλαγή παρουσίας → ειδοποίηση «attendance» σε <2″', st == 200 and 'attendance' in tp and lat < 2000, f'{lat:.0f} ms {tp}')
    n = pg.evaluate("window.__ev.length")
    pg.evaluate("fetch('/production/attendance?date=%s',{headers:{Authorization:'Bearer '+token}})" % today); pg.wait_for_timeout(700)
    ck('απλή ανάγνωση (GET) ΔΕΝ ειδοποιεί', pg.evaluate("window.__ev.length") == n)
    pg.evaluate("fetch('/production/transfers',{method:'POST',headers:{'Content-Type':'application/json','Authorization':'Bearer '+token},body:JSON.stringify({destination_org_unit_id:'x',items:[]})})"); pg.wait_for_timeout(700)
    ck('αποτυχημένη εγγραφή (σφάλμα) ΔΕΝ ειδοποιεί', pg.evaluate("window.__ev.length") == n)
    # πολλές αλλαγές μαζί → συγκεντρώνονται
    pg.evaluate("([e,d])=>{for(let i=0;i<3;i++)fetch('/production/attendance',{method:'PUT',headers:{'Content-Type':'application/json','Authorization':'Bearer '+token},body:JSON.stringify({work_date:d,employee_id:e,status:'PRESENT'})})}", [emp, today]); pg.wait_for_timeout(1200)
    ck('πολλές αλλαγές μαζί → λίγα μηνύματα (συγκέντρωση)', 1 <= pg.evaluate("window.__ev.length") - n <= 3, str(pg.evaluate("window.__ev.length") - n))
    # δεύτερος συνδρομητής (άλλη οθόνη)
    pg2 = b.new_page(); pg2.goto(B + '/', wait_until='networkidle'); pg2.click('#loginBtn'); pg2.wait_for_selector('#metrics .card', timeout=20000)
    pg2.evaluate("()=>{window.__ev=[];window.__es=new EventSource('/events?token='+encodeURIComponent(token));window.__es.onmessage=e=>window.__ev.push(JSON.parse(e.data))}"); pg2.wait_for_timeout(800)
    put(); pg2.wait_for_function("window.__ev.length>0", timeout=5000)
    ck('δεύτερη οθόνη λαμβάνει την ίδια ειδοποίηση', True)
    pg.evaluate("window.__es.close()"); pg2.evaluate("window.__es.close()"); pg.wait_for_timeout(500)
    ck('μετά το κλείσιμο ο server συνεχίζει κανονικά', pg.evaluate("fetch('/health').then(r=>r.status).catch(()=>0)") in (200, 404))
    b.close()
print('ΑΠΟΤΥΧΙΕΣ:', bad)
sys.exit(1 if bad else 0)
