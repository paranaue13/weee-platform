"""Δοκιμή Windows › Δελτίο Παραγωγής (βήμα Β): διακόπτης «Μόνο ενεργά», σύρσιμο εργαζομένου (Μεταφορά / Ctrl = Εργασία), χωρίς «μάτι» απόκρυψης, άμεση ανανέωση /events.
Χρήση: python backend/scripts/test_windows_step_b.py http://127.0.0.1:PORT C:/ΑΝΤΙΓΡΑΦΟ.db   (ΜΟΝΟ σε ΑΝΤΙΓΡΑΦΟ βάσης!)"""
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
today = datetime.date.today().isoformat()
with sync_playwright() as p:
    b = launch(p); errs = []
    pg = b.new_page(viewport={'width': 1500, 'height': 900}); pg.on('pageerror', lambda e: errs.append(str(e)))
    pg.goto(B + '/', wait_until='networkidle'); pg.wait_for_selector('#loginBtn', state='visible'); pg.click('#loginBtn'); pg.wait_for_selector('#metrics .card', timeout=20000); pg.wait_for_timeout(1000)
    def call(page, m, path, body=None):
        return page.evaluate("([m,p,b])=>fetch(p,{method:m,headers:{'Content-Type':'application/json','Authorization':'Bearer '+token},body:b?JSON.stringify(b):undefined}).then(async r=>[r.status,await r.json().catch(()=>null)])", [m, path, body])
    pg.click('.nav button[data-view="production"]'); pg.wait_for_timeout(600)
    pg.evaluate("document.querySelectorAll('.productionTab').forEach(b=>{if(/Δελτίο/.test(b.textContent))b.click()})"); pg.wait_for_selector('.dcard'); pg.wait_for_timeout(1200)
    units = pg.evaluate("prodState.units.filter(u=>u.active!==false)")
    prod = [u for u in units if u['profile'] not in ('SUPPORT', 'MANAGEMENT')]
    # ---------- α) διακόπτης ----------
    sw = pg.locator('#deltioOnly'); lbl = pg.locator('.dlOnly')
    ck('διακόπτης «Μόνο ενεργά» υπάρχει, αριστερά, κλειστός', 'Μόνο ενεργά' in lbl.inner_text() and not sw.is_checked() and lbl.bounding_box()['x'] < pg.locator('#deltioDate').bounding_box()['x'])
    ck('η ημερομηνία μένει δεξιά', pg.locator('#deltioDate').bounding_box()['x'] > 700)
    n_all = pg.locator('.dcard').count()
    pg.evaluate("document.getElementById('deltioOnly').click()"); pg.wait_for_timeout(300)
    withdev = {d['org_unit_id'] for d in (pg.evaluate("deltioState.devices") or [])}
    shown = set(pg.evaluate("[...document.querySelectorAll('.dcard')].map(c=>c.dataset.unit)"))
    ck('ΑΝΟΙΧΤΟΣ: μόνο τα τμήματα παραγωγής με καταχώρηση + ΠΑΝΤΑ η κάρτα «Θέσεις υποστήριξης»', shown == ({u['id'] for u in prod} & withdev) | {'support'}, f'{len(shown)} κάρτες')
    pg.evaluate("document.getElementById('deltioOnly').click()"); pg.wait_for_timeout(300)
    ck('ΚΛΕΙΣΤΟΣ: ξανά όλα', pg.locator('.dcard').count() == n_all)
    # ---------- γ) κανένα «μάτι» ----------
    pg.locator('.dcT tbody tr td').first.hover(); pg.wait_for_timeout(500)
    ck('ΧΩΡΙΣ εικονίδιο «μάτι»/απόκρυψης πάνω στις γραμμές και τις ώρες', pg.query_selector('.pinEye') is None and pg.query_selector('.pinLayer .pinEye') is None)
    pg.locator('.dcT td.r').first.hover(); pg.wait_for_timeout(500)
    ck('ούτε πάνω στις «Καθαρές ώρες»', pg.query_selector('.pinEye') is None)
    # ---------- β) σύρσιμο ----------
    emps = pg.evaluate("prodState.employees.filter(e=>e.active!==false&&(e.org_unit_ids||[]).length===1&&prodState.units.find(u=>u.id===e.org_unit_ids[0]&&u.profile!=='SUPPORT'&&u.profile!=='MANAGEMENT')).map(e=>[e.id,e.org_unit_ids[0]])")
    e0, u0 = emps[0]; u1 = next(u['id'] for u in prod if u['id'] != u0)
    pg.evaluate("document.getElementById('deltioDepts').scrollLeft=0")
    grip = pg.locator(f'.dcard[data-unit="{u0}"] .dcGrip[data-emp="{e0}"]')
    ck('λαβή ⋮⋮ αριστερά σε κάθε εργαζόμενο', grip.count() == 1 and '⋮' in grip.inner_text())
    def drag_to(unit, ctrl=False):
        pg.evaluate("document.querySelector('.dcard[data-unit=\"%s\"]').scrollIntoView({inline:'center',block:'nearest'})" % unit)
        src = pg.locator(f'.dcGrip[data-emp="{e0}"]').first.bounding_box(); tgt = pg.locator(f'.dcard[data-unit="{unit}"] h3').bounding_box()
        pg.mouse.move(src['x'] + 4, src['y'] + 4); pg.mouse.down()
        pg.mouse.move(tgt['x'] + 20, tgt['y'] + 20, steps=12)
        hl = pg.evaluate("document.querySelectorAll('.dcard.dcOver').length")
        if ctrl: pg.keyboard.down('Control')
        pg.mouse.up()
        if ctrl: pg.keyboard.up('Control')
        pg.wait_for_timeout(1800); return hl
    hl = drag_to(u1)
    ck('η κάρτα που περνάω τονίζεται (διακεκομμένο μπλε περίγραμμα)', hl == 1)
    units_now = lambda: pg.evaluate("e=>prodState.employees.find(x=>x.id===e).org_unit_ids", e0)
    ck('άφημα σε άλλη κάρτα = Μεταφορά (πήγε στο νέο, έφυγε από το παλιό)', units_now() == [u1], str(units_now()))
    ck('στην οθόνη: ο εργαζόμενος είναι στη νέα κάρτα και όχι στην παλιά', pg.locator(f'.dcard[data-unit="{u1}"] .dcGrip[data-emp="{e0}"]').count() == 1 and pg.locator(f'.dcard[data-unit="{u0}"] .dcGrip[data-emp="{e0}"]').count() == 0)
    hl = drag_to(u0, ctrl=True)
    ck('με Ctrl πατημένο = Εργασία (σε ΔΥΟ τμήματα)', set(units_now()) == {u0, u1}, str(units_now()))
    ck('εμφανίζεται και στις δύο κάρτες', pg.locator(f'.dcGrip[data-emp="{e0}"]').count() == 2)
    # άφημα στην ίδια κάρτα: καμία αλλαγή
    # αυτόματη κύλιση στα άκρα
    pg.evaluate("document.getElementById('deltioDepts').scrollLeft=0")
    src = pg.locator(f'.dcGrip[data-emp="{e0}"]').first.bounding_box(); wr = pg.locator('#deltioDepts').bounding_box()
    pg.mouse.move(src['x'] + 4, src['y'] + 4); pg.mouse.down(); pg.mouse.move(wr['x'] + wr['width'] - 20, src['y'] + 4, steps=10)
    for k in range(8): pg.mouse.move(wr['x'] + wr['width'] - 20 + (k % 2), src['y'] + 4); pg.wait_for_timeout(150)   # στο πραγματικό πρόγραμμα περιήγησης το dragover επαναλαμβάνεται συνεχώς
    sl = pg.evaluate("document.getElementById('deltioDepts').scrollLeft"); pg.mouse.up(); pg.wait_for_timeout(1200)
    ck('κοντά στο δεξί άκρο η σειρά καρτών κυλά μόνη της', sl > 100, str(sl))
    # επαναφορά: αφαίρεση από το u1 (έχει 2 τμήματα)
    call(pg, 'POST', '/production/attendance/units', {'work_date': today, 'employee_id': e0, 'action': 'remove', 'unit_id': u1})
    # ---------- δ) άμεση ανανέωση /events ----------
    pg.evaluate("clearApiCache();loadDeltio()"); pg.wait_for_timeout(1500)
    ck('το κανάλι /events είναι συνδεδεμένο στα Windows', pg.evaluate("LIVE.state()") == 1, str(pg.evaluate("LIVE.state()")))
    pg2 = b.new_page(viewport={'width': 1300, 'height': 800}); pg2.goto(B + '/', wait_until='networkidle'); pg2.wait_for_selector('#loginBtn', state='visible'); pg2.click('#loginBtn'); pg2.wait_for_selector('#metrics .card', timeout=20000); pg2.wait_for_timeout(800)
    n0 = pg.locator('.dcDev').count(); t0 = time.time()
    st, j = call(pg2, 'POST', '/production/transfers', {'destination_org_unit_id': u0, 'items': [{'stock_lot_id': lot[0], 'weight': 40}], 'work_entry': {'weee_category_id': lot[1], 'source': 'ANDROID'}}); tid = j['id']
    pg.wait_for_function("n=>document.querySelectorAll('.dcDev').length>n", arg=n0, timeout=8000); dt = time.time() - t0
    ck('αποστολή από ΑΛΛΗ οθόνη εμφανίζεται στο Δελτίο μέσα σε 1–2″ (χωρίς refresh)', dt < 3.5, f'{dt:.1f} s')
    # σκληρό σενάριο: ανοιχτό πάνελ → η ανανέωση ΑΝΑΣΤΕΛΛΕΤΑΙ
    pg.locator(f'.dcard[data-unit="{u0}"] .dcArrow').first.click(); pg.wait_for_timeout(300)
    nd = pg.locator('.dcDev').count()
    call(pg2, 'POST', '/production/transfers', {'destination_org_unit_id': u0, 'items': [{'stock_lot_id': lot[0], 'weight': 10}], 'work_entry': {'weee_category_id': lot[1], 'source': 'ANDROID'}}); pg.wait_for_timeout(3500)
    ck('ανοιχτό πάνελ «διάλεξε τμήμα»: δεν κλείνει και δεν αλλάζει η λίστα', pg.locator('.dcPanel').count() == 1 and pg.locator('.dcDev').count() == nd)
    pg.locator(f'.dcard[data-unit="{u0}"] .dcArrow.sel, .dcard[data-unit="{u0}"] .dcArrow').first.click(); pg.wait_for_function("n=>document.querySelectorAll('.dcDev').length>n", arg=nd, timeout=20000)
    ck('μόλις κλείσει το πάνελ, ανανεώνεται με την καθυστερημένη αλλαγή', True)
    # φόρμα Υπόλοιπο + πληκτρολόγηση
    pg.locator('.dcRemBtn').first.click(); pg.wait_for_timeout(300); pg.locator('.dcRemKg').fill('7'); nd = pg.locator('.dcDev').count()
    call(pg2, 'POST', '/production/transfers', {'destination_org_unit_id': u0, 'items': [{'stock_lot_id': lot[0], 'weight': 5}], 'work_entry': {'weee_category_id': lot[1], 'source': 'ANDROID'}}); pg.wait_for_timeout(3500)
    ck('φόρμα «Υπόλοιπο» με κείμενο: δεν κλείνει, δεν σβήνεται το «7»', pg.locator('.dcRemKg').count() == 1 and pg.locator('.dcRemKg').input_value() == '7' and pg.locator('.dcDev').count() == nd)
    pg.locator('[data-ract="cancel"]').click(); pg.wait_for_timeout(2500)
    # scroll οριζόντια διατηρείται
    pg.evaluate("document.getElementById('deltioDepts').scrollLeft=420"); call(pg2, 'PUT', '/production/attendance', {'work_date': today, 'employee_id': e0, 'status': 'PRESENT', 'position_text': 'δοκιμή'}); pg.wait_for_timeout(3500)
    ck('το οριζόντιο scroll ΔΕΝ γυρίζει στην αρχή μετά από ανανέωση', abs(pg.evaluate("document.getElementById('deltioDepts').scrollLeft") - 420) <= 3, str(pg.evaluate("document.getElementById('deltioDepts').scrollLeft")))
    # επανασύνδεση του καναλιού
    pg.evaluate("LIVE.state()"); pg.evaluate("(()=>{let es=window.__es;})()")
    pg.context.set_offline(True); pg.wait_for_timeout(1500); pg.context.set_offline(False); pg.wait_for_timeout(9000)
    ck('μετά από πτώση σύνδεσης το κανάλι ξανασυνδέεται μόνο του', pg.evaluate("LIVE.state()") == 1, str(pg.evaluate("LIVE.state()")))
    for t in (tid,): call(pg2, 'POST', f'/production/transfers/{t}/cancel')
    ck('σφάλματα σελίδας', not errs, str(errs[:2]))
    b.close()
print('ΑΠΟΤΥΧΙΕΣ:', bad)
sys.exit(1 if bad else 0)
