"""Δοκιμή: αυτόματη ανανέωση Δελτίου Παραγωγής (Windows) + κινήσεις «Χύμα» σε Windows/Android.
Χρήση: python backend/scripts/test_deltio_autorefresh_bulk.py http://127.0.0.1:PORT C:/ΑΝΤΙΓΡΑΦΟ.db   (ΜΟΝΟ σε ΑΝΤΙΓΡΑΦΟ βάσης!)"""
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
bulk = c.execute("select id,weee_category_id,available_weight from weee_stock_lots where collection_medium_id is null and available_weight>=20 order by id limit 1").fetchone()
med = c.execute("select l.id,l.weee_category_id from weee_stock_lots l where l.collection_medium_id is not null and l.available_weight>=120 order by l.id limit 3").fetchall()
unit = c.execute("select id from organizational_units where active=1 and profile='PRODUCTION' order by id limit 1").fetchone()[0]
today = datetime.date.today().isoformat()
with sync_playwright() as p:
    b = launch(p); errs = []
    pg = b.new_page(viewport={'width': 1300, 'height': 900}); pg.on('pageerror', lambda e: errs.append(str(e)))
    pg.goto(B + '/', wait_until='networkidle'); pg.wait_for_selector('#loginBtn', state='visible'); pg.click('#loginBtn'); pg.wait_for_selector('#metrics .card', timeout=20000); pg.wait_for_timeout(800)
    def call(m, path, body=None):
        return pg.evaluate("([m,p,b])=>fetch(p,{method:m,headers:{'Content-Type':'application/json','Authorization':'Bearer '+token},body:b?JSON.stringify(b):undefined}).then(async r=>[r.status,await r.json().catch(()=>null)])", [m, path, body])
    def send(lot, cat, w):
        st, j = call('POST', '/production/transfers', {'destination_org_unit_id': unit, 'items': [{'stock_lot_id': lot, 'weight': w}]})
        call('POST', '/production/work-entries', {'work_date': today + 'T00:00:00', 'org_unit_id': unit, 'weee_category_id': cat, 'weight_kg': w, 'source': 'ANDROID', 'transfer_id': j['id']})
        return j['id']
    pg.click('.nav button[data-view="production"]'); pg.wait_for_timeout(600)
    pg.evaluate("document.querySelectorAll('.productionTab').forEach(b=>{if(/Δελτίο/.test(b.textContent))b.click()})"); pg.wait_for_selector('.dcard'); pg.wait_for_timeout(1000)
    n0 = pg.locator('.dcDev').count()
    t1 = send(med[0][0], med[0][1], 50)
    pg.wait_for_function("n=>document.querySelectorAll('.dcDev').length>n", arg=n0, timeout=25000)
    ck('αυτόματη ανανέωση: νέα συσκευή από «Android» εμφανίστηκε χωρίς refresh', True)
    # scroll οριζόντια + πάνελ ανοιχτό → αναστολή
    pg.evaluate("document.getElementById('deltioDepts').scrollLeft=300"); sl0 = pg.evaluate("document.getElementById('deltioDepts').scrollLeft")
    pg.locator('.dcArrow').first.click(); pg.wait_for_timeout(300)
    n1 = pg.locator('.dcDev').count(); t2 = send(med[1][0], med[1][1], 40); pg.wait_for_timeout(17500)
    ck('ανοιχτό πάνελ «διάλεξε τμήμα»: η ανανέωση ΑΝΑΣΤΑΛΗΚΕ (δεν έκλεισε, δεν άλλαξε η λίστα)', pg.locator('.dcPanel').count() == 1 and pg.locator('.dcDev').count() == n1)
    pg.locator('.dcArrow').first.click(); pg.wait_for_function("n=>document.querySelectorAll('.dcDev').length>n", arg=n1, timeout=25000)
    ck('μόλις κλείσει το πάνελ, ανανεώνεται', True)
    ck('το οριζόντιο scroll ΔΕΝ γύρισε στην αρχή', abs(pg.evaluate("document.getElementById('deltioDepts').scrollLeft") - sl0) <= 2, f"{sl0} → {pg.evaluate('document.getElementById(\"deltioDepts\").scrollLeft')}")
    # φόρμα υπολοίπου + πληκτρολόγηση
    pg.locator('.dcRemBtn').first.click(); pg.wait_for_timeout(300); pg.locator('.dcRemKg').fill('12'); n2 = pg.locator('.dcDev').count()
    t3 = send(med[2][0], med[2][1], 30); pg.wait_for_timeout(17500)
    ck('φόρμα «Υπόλοιπο» ανοιχτή: δεν κλείνει και δεν σβήνεται το κείμενο', pg.locator('.dcRemKg').count() == 1 and pg.locator('.dcRemKg').input_value() == '12' and pg.locator('.dcDev').count() == n2)
    pg.locator('[data-ract="cancel"]').click(); pg.wait_for_function("n=>document.querySelectorAll('.dcDev').length>n", arg=n2, timeout=25000)
    ck('μετά το κλείσιμο της φόρμας ανανεώνεται', True)
    # ΧΥΜΑ
    if bulk:
        tb = send(bulk[0], bulk[1], 20)
        dv = [d for d in call('GET', f'/production/device-list?date={today}')[1] if d['transfer_id'] == tb]
        ck('ΧΥΜΑ: ο server επιστρέφει την κίνηση (χωρίς μέσο)', len(dv) == 1 and dv[0]['medium_id'] is None, str(dv and (dv[0]['medium_code'], dv[0]['weight_kg'])))
        pg.evaluate("clearApiCache();loadDeltio()"); pg.wait_for_timeout(1200)
        ck('ΧΥΜΑ στα Windows: φαίνεται με ετικέτα «ΧΥΜΑ»', 'ΧΥΜΑ' in pg.locator(f'.dcard[data-unit="{unit}"]').inner_text() or 'Χύμα' in pg.locator(f'.dcard[data-unit="{unit}"]').inner_text())
        st, j = call('POST', f'/production/transfer-items/{dv[0]["item_id"]}/remainder', {'mode': 'NET', 'kg': 5})
        ck('ΧΥΜΑ: υπόλοιπο ΚΑΘΑΡΑ δουλεύει', st == 200, str(j))
        call('POST', f'/production/transfer-items/{dv[0]["item_id"]}/remainder/undo')
        pg2 = b.new_page(viewport={'width': 360, 'height': 640}, is_mobile=True, has_touch=True); pg2.goto(B + '/mobile', wait_until='networkidle'); pg2.click('#loginBtn'); pg2.wait_for_selector('#app:not(.hidden)'); pg2.wait_for_timeout(2500)
        pg2.tap('.secBtn[data-section=production]'); pg2.wait_for_timeout(1500); pg2.evaluate("loadProdToday()"); pg2.wait_for_timeout(1500)
        txt = pg2.inner_text('#prodTodayList')
        ck('ΧΥΜΑ στο Android: φαίνεται στο ιστορικό με «Χύμα»', 'Χύμα' in txt, txt[:200].replace(chr(10), ' | '))
        call('POST', f'/production/transfers/{tb}/cancel')
    else:
        print('⚠ δεν βρέθηκε χύμα απόθεμα στο αντίγραφο')
    for t in (t1, t2, t3): call('POST', f'/production/transfers/{t}/cancel')
    ck('σφάλματα σελίδας', not errs, str(errs[:2]))
    b.close()
print('ΑΠΟΤΥΧΙΕΣ:', bad)
sys.exit(1 if bad else 0)
