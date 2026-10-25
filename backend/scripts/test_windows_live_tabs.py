"""Δοκιμή Windows › άμεση ανανέωση (/events) στο Παρουσιολόγιο και στις καρτέλες «Παραγωγή ανά ΑΗΗΕ» / «Παραγωγή ανά Τμήμα / Άτομο».
Χρήση: python backend/scripts/test_windows_live_tabs.py http://127.0.0.1:PORT C:/ΑΝΤΙΓΡΑΦΟ.db   (ΜΟΝΟ σε ΑΝΤΙΓΡΑΦΟ βάσης!)"""
import sys, os, sqlite3, datetime, time
sys.path.insert(0, os.path.dirname(__file__)); sys.stdout.reconfigure(encoding='utf-8')
from playwright.sync_api import sync_playwright
from _browser import launch
B, DB = sys.argv[1], sys.argv[2]
bad = []
def ck(n, ok, i=''):
    print(('✓ ' if ok else '✗ ') + n, i)
    if not ok: bad.append(n)
c = sqlite3.connect(DB)
lot = c.execute("select id,weee_category_id from weee_stock_lots where available_weight>=100 order by id limit 1").fetchone()
U = c.execute("select id from organizational_units where active=1 and profile='PRODUCTION' order by id limit 1").fetchone()[0]
today = datetime.date.today().isoformat()
with sync_playwright() as p:
    b = launch(p); errs = []
    pg = b.new_page(viewport={'width': 1500, 'height': 900}); pg.on('pageerror', lambda e: errs.append(str(e)))
    def login(page):
        page.goto(B + '/', wait_until='networkidle'); page.wait_for_selector('#loginBtn', state='visible'); page.click('#loginBtn'); page.wait_for_selector('#metrics .card', timeout=20000); page.wait_for_timeout(1000)
    login(pg)
    pg2 = b.new_page(viewport={'width': 1300, 'height': 800}); login(pg2)
    call = lambda page, m, path, body=None: page.evaluate("([m,p,b])=>fetch(p,{method:m,headers:{'Content-Type':'application/json','Authorization':'Bearer '+token},body:b?JSON.stringify(b):undefined}).then(async r=>[r.status,await r.json().catch(()=>null)])", [m, path, body])
    # ---- Παρουσιολόγιο ----
    pg.click('#openPresence'); pg.wait_for_selector('#presBody tr', timeout=15000); pg.wait_for_timeout(1500)
    e0 = pg.locator('#presBody button[data-s="PRESENT"]').first.get_attribute('data-e')
    call(pg2, 'PUT', '/production/attendance', {'work_date': today, 'employee_id': e0, 'status': 'PRESENT'}); pg.wait_for_timeout(2500)
    is_abs = lambda: pg.evaluate("e=>{let b=document.querySelector('#presBody button[data-e=\"'+e+'\"][data-s=\"ABSENT\"]');return b.classList.contains('on')||b.classList.contains('active')||b.getAttribute('aria-pressed')==='true'}", e0)
    t0 = time.time(); call(pg2, 'PUT', '/production/attendance', {'work_date': today, 'employee_id': e0, 'status': 'ABSENT'})
    pg.wait_for_function("e=>{let b=document.querySelector('#presBody button[data-e=\"'+e+'\"][data-s=\"ABSENT\"]');return b&&(b.classList.contains('on')||b.classList.contains('active')||b.getAttribute('aria-pressed')==='true')}", arg=e0, timeout=8000)
    ck('Παρουσιολόγιο: αλλαγή από άλλη οθόνη φαίνεται σε 1–2″ χωρίς refresh', time.time() - t0 < 3.5, f'{time.time()-t0:.1f} s')
    # όσο πληκτρολογείς ώρα, δεν σβήνεται
    tin = pg.locator('#presBody .tpk .tfIn').first
    if tin.count():
        tin.click(); tin.fill('08:15'); pg.wait_for_timeout(300)
        call(pg2, 'PUT', '/production/attendance', {'work_date': today, 'employee_id': e0, 'status': 'PRESENT'}); pg.wait_for_timeout(3000)
        ck('Παρουσιολόγιο: ό,τι πληκτρολογείς ΔΕΝ σβήνεται από την ανανέωση', tin.input_value() == '08:15', tin.input_value())
        pg.keyboard.press('Escape'); pg.mouse.click(5, 5); pg.wait_for_timeout(500)
    # ---- Παραγωγή ανά ΑΗΗΕ ----
    pg.click('.nav button[data-view="production"]'); pg.wait_for_timeout(800)
    pg.evaluate("document.querySelectorAll('.productionTab').forEach(b=>{if(/ΑΗΗΕ/.test(b.textContent))b.click()})"); pg.wait_for_timeout(2500)
    kpi0 = pg.evaluate("document.getElementById('productionKpis').innerText")
    wrap = pg.locator('#production .prodTableWrap').first
    rng = wrap.evaluate("w=>[w.scrollHeight-w.clientHeight,w.scrollWidth-w.clientWidth]") if wrap.count() else [0, 0]
    if wrap.count(): wrap.evaluate("w=>{w.scrollTop=40;w.scrollLeft=60}")
    t0 = time.time()
    st, j = call(pg2, 'POST', '/production/transfers', {'destination_org_unit_id': U, 'items': [{'stock_lot_id': lot[0], 'weight': 77}], 'work_entry': {'weee_category_id': lot[1], 'source': 'ANDROID'}}); tid = j['id']
    pg.wait_for_function("k=>document.getElementById('productionKpis').innerText!==k", arg=kpi0, timeout=10000)
    ck('Παραγωγή ανά ΑΗΗΕ: η νέα καταχώρηση από άλλη οθόνη φαίνεται σε 1–3″ (χωρίς refresh)', time.time() - t0 < 4.5, f'{time.time()-t0:.1f} s')
    if wrap.count() and (rng[0] > 40 or rng[1] > 60):
        pg.wait_for_timeout(800)
        sc = wrap.evaluate("w=>[w.scrollTop,w.scrollLeft]")
        ck('το scroll του πίνακα ΔΕΝ γύρισε στην αρχή', sc[0] >= 30 or sc[1] >= 30, str(sc))
    if not (rng[0] > 40 or rng[1] > 60): print('⚠ ο πίνακας δεν έχει αρκετό περιεχόμενο για έλεγχο scroll (εύρος', rng, ')')
    # ---- Παραγωγή ανά Τμήμα / Άτομο ----
    pg.evaluate("document.querySelectorAll('.productionTab').forEach(b=>{if(/Τμήμα/.test(b.textContent))b.click()})"); pg.wait_for_timeout(2500)
    kpi1 = pg.evaluate("document.getElementById('productionKpis').innerText")
    call(pg2, 'POST', f'/production/transfers/{tid}/cancel')
    pg.wait_for_function("k=>document.getElementById('productionKpis').innerText!==k", arg=kpi1, timeout=10000)
    ck('Παραγωγή ανά Τμήμα / Άτομο: η ακύρωση από άλλη οθόνη φαίνεται χωρίς refresh', True)
    ck('σφάλματα σελίδας', not errs, str(errs[:2]))
    b.close()
print('ΑΠΟΤΥΧΙΕΣ:', bad)
sys.exit(1 if bad else 0)
