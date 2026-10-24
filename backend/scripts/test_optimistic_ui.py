"""Δοκιμή: ΑΙΣΙΟΔΟΞΗ ΕΝΗΜΕΡΩΣΗ (Android Εργαζόμενοι + Windows Παρουσιολόγιο): η οθόνη αλλάζει ΑΜΕΣΑ ακόμα κι αν ο server αργεί 6″, και επιστρέφει όταν ο server απορρίπτει.
Χρήση: python backend/scripts/test_optimistic_ui.py http://127.0.0.1:PORT   (ΜΟΝΟ σε ΑΝΤΙΓΡΑΦΟ βάσης!)"""
import sys, os, time, json
sys.path.insert(0, os.path.dirname(__file__)); sys.stdout.reconfigure(encoding='utf-8')
from playwright.sync_api import sync_playwright
from _browser import launch
B = sys.argv[1]
bad = []
def ck(n, ok, i=''):
    print(('✓ ' if ok else '✗ ') + n, i)
    if not ok: bad.append(n)
with sync_playwright() as p:
    b = launch(p)
    # ---------------- Android ----------------
    pg = b.new_page(viewport={'width': 360, 'height': 640}, is_mobile=True, has_touch=True); errs = []; pg.on('pageerror', lambda e: errs.append(str(e)))
    pg.goto(B + '/mobile', wait_until='networkidle'); pg.click('#loginBtn'); pg.wait_for_selector('#app:not(.hidden)'); pg.wait_for_timeout(2500)
    pg.tap('#topDeltioBtn'); pg.wait_for_selector('.dlRow'); pg.wait_for_timeout(1500)
    eid = pg.locator('.dlRow').nth(2).locator('.dlSt').first.get_attribute('data-e')
    on = lambda s: pg.evaluate("([e,s])=>document.querySelector('.dlSt[data-e=\"'+e+'\"][data-s=\"'+s+'\"]').classList.contains('on')", [eid, s])
    pg.evaluate("e=>deltioSaveAttendance(e,{status:'PRESENT',late:false})", eid); pg.evaluate("loadDeltioAndroid()"); pg.wait_for_timeout(1500)
    # ο server «αργεί» 6 δευτερόλεπτα στις εγγραφές
    DELAY = "()=>{if(!window.__dl){window.__dl=1;let f=window.fetch;window.fetch=function(u,o){return (o&&o.method==='PUT'&&window.__delay)?new Promise(r=>setTimeout(r,window.__delay)).then(()=>f.call(this,u,o)):f.apply(this,arguments)}}}"
    pg.evaluate(DELAY)
    slow_on = lambda page: page.evaluate("window.__delay=6000"); slow_off = lambda page: page.evaluate("window.__delay=0")
    slow_on(pg)
    t0 = time.time(); pg.locator('.dlSt.a[data-e="%s"]' % eid).tap()
    pg.wait_for_function("e=>document.querySelector('.dlSt.a[data-e=\"'+e+'\"]').classList.contains('on')", arg=eid, timeout=3000)
    dt = time.time() - t0
    ck('Android: ΑΠΩΝ φαίνεται ΑΜΕΣΑ (<1″) ενώ ο server αργεί 6″', dt < 1.0 and on('ABSENT'), f'{dt*1000:.0f} ms')
    pg.wait_for_function("!OB.pending()", timeout=40000); slow_off(pg)
    ck('Android: η επιβεβαίωση ήρθε από πίσω και η κατάσταση μένει ΑΠΩΝ', on('ABSENT') and pg.query_selector('.obModal') is None)
    # ο server απορρίπτει → παράθυρο ΟΚ και η οθόνη ΕΠΙΣΤΡΕΦΕΙ
    pg.route('**/production/attendance', lambda r: r.fulfill(status=422, content_type='application/json', body=json.dumps({'detail': 'Δοκιμαστική απόρριψη από τον server'})) if r.request.method == 'PUT' else r.continue_())
    pg.locator('.dlSt.p[data-e="%s"]' % eid).tap()
    pg.wait_for_selector('.obModal', timeout=10000); pg.wait_for_timeout(500)
    ck('Android: απόρριψη → παράθυρο ΟΚ με το μήνυμα', 'Δοκιμαστική απόρριψη' in pg.inner_text('.obModal'))
    ck('Android: η οθόνη ΕΠΕΣΤΡΕΨΕ στην προηγούμενη κατάσταση (ΑΠΩΝ)', on('ABSENT') and not on('PRESENT'))
    pg.click('.obModal button'); pg.unroute('**/production/attendance')
    # Ολιγόωρη αισιόδοξα
    pg.evaluate("e=>deltioSaveAttendance(e,{status:'PRESENT'})", eid); pg.wait_for_function("!OB.pending()", timeout=40000)
    slow_on(pg)
    t0 = time.time(); pg.locator('.dlSt.s[data-e="%s"]' % eid).tap(); pg.wait_for_selector('.dlShAdd', timeout=3000)
    ck('Android: ΟΛΙΓΟΩΡΗ ανοίγει το πάνελ ΑΜΕΣΑ', time.time() - t0 < 1.5, f'{(time.time()-t0)*1000:.0f} ms')
    pg.wait_for_function("!OB.pending()", timeout=40000); slow_off(pg)
    ck('Android: σφάλματα σελίδας', not errs, str(errs[:2])); pg.close()
    # ---------------- Windows ----------------
    pw = b.new_page(viewport={'width': 1500, 'height': 900}); errs = []; pw.on('pageerror', lambda e: errs.append(str(e)))
    pw.goto(B + '/', wait_until='networkidle'); pw.wait_for_selector('#loginBtn', state='visible'); pw.click('#loginBtn'); pw.wait_for_selector('#metrics .card', timeout=20000); pw.wait_for_timeout(1000)
    pw.click('#openPresence'); pw.wait_for_selector('#presBody tr', timeout=15000); pw.wait_for_timeout(1500)
    e0 = pw.locator('#presBody button[data-s="PRESENT"]').first.get_attribute('data-e')
    pw.evaluate("e=>api('/production/attendance',{method:'PUT',body:JSON.stringify({work_date:localISODate(new Date()),employee_id:e,status:'PRESENT'})})", e0); pw.evaluate("presRefresh()"); pw.wait_for_timeout(1000)
    on_w = lambda s: pw.evaluate("([e,s])=>{let b=document.querySelector('#presBody button[data-e=\"'+e+'\"][data-s=\"'+s+'\"]');return b.classList.contains('on')||b.classList.contains('active')||b.getAttribute('aria-pressed')==='true'}", [e0, s])
    pw.evaluate(DELAY); slow_on(pw)
    t0 = time.time(); pw.click('#presBody button[data-e="%s"][data-s="ABSENT"]' % e0)
    pw.wait_for_function("e=>{let b=document.querySelector('#presBody button[data-e=\"'+e+'\"][data-s=\"ABSENT\"]');return b&&(b.classList.contains('on')||b.classList.contains('active')||b.getAttribute('aria-pressed')==='true')}", arg=e0, timeout=3000)
    ck('Windows Παρουσιολόγιο: ΑΠΩΝ φαίνεται ΑΜΕΣΑ (<1″) ενώ ο server αργεί 6″', time.time() - t0 < 1.0, f'{(time.time()-t0)*1000:.0f} ms')
    pw.wait_for_function("!OB.pending()", timeout=40000); slow_off(pw); pw.wait_for_timeout(1500)
    pw.route('**/production/attendance', lambda r: r.fulfill(status=422, content_type='application/json', body=json.dumps({'detail': 'Δοκιμαστική απόρριψη από τον server'})) if r.request.method == 'PUT' else r.continue_())
    pw.click('#presBody button[data-e="%s"][data-s="PRESENT"]' % e0)
    pw.wait_for_selector('.obModal', timeout=10000); pw.wait_for_timeout(1500)
    ck('Windows: απόρριψη → παράθυρο ΟΚ και η οθόνη ΕΠΙΣΤΡΕΦΕΙ στο ΑΠΩΝ', on_w('ABSENT') and not on_w('PRESENT'), str([on_w('ABSENT'), on_w('PRESENT'), pw.inner_text('#presMsg'), pw.evaluate("e=>[JSON.stringify(presState.att.find(x=>x.employee_id===e)),[...apiCache.keys()].filter(k=>/effective/.test(k)).map(k=>JSON.stringify(apiCache.get(k).data.find(x=>x.employee_id===e)).slice(0,160))]", e0)]))
    pw.click('.obModal button'); pw.unroute('**/production/attendance')
    ck('Windows: σφάλματα σελίδας', not errs, str(errs[:2])); pw.close()
    b.close()
print('ΑΠΟΤΥΧΙΕΣ:', bad)
sys.exit(1 if bad else 0)
