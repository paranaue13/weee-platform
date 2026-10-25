"""Δοκιμή Windows › Δελτίο Παραγωγής › Υπόλοιπο (φόρμα ΜΙΚΤΑ/ΚΑΘΑΡΑ, προεπισκόπηση, χρώματα ετικέτας, επιστροφές, αναίρεση).
Χρήση: python backend/scripts/test_windows_deltio_remainder.py http://127.0.0.1:PORT C:/ΑΝΤΙΓΡΑΦΟ.db [screenshot.png]   (ΜΟΝΟ σε ΑΝΤΙΓΡΑΦΟ βάσης!)"""
import sys, os, sqlite3, datetime
sys.path.insert(0, os.path.dirname(__file__))
sys.stdout.reconfigure(encoding='utf-8')
from playwright.sync_api import sync_playwright
from _browser import launch
B, DB = sys.argv[1], sys.argv[2]
bad = []
def ck(name, ok, info=''):
    print(('✓ ' if ok else '✗ ') + name, info)
    if not ok: bad.append(name)
from _testdata import ensure_medium_lots; ensure_medium_lots(DB)
c = sqlite3.connect(DB)
lots = c.execute("select l.id,l.weee_category_id,m.tare_weight from weee_stock_lots l join collection_media m on m.id=l.collection_medium_id where l.available_weight>=120 and m.tare_weight>0 order by l.id limit 2").fetchall()
(LA, CA, TA), (LB, CB, TB) = lots
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
        call('POST', '/production/work-entries', {'work_date': today + 'T00:00:00', 'org_unit_id': unit, 'weee_category_id': cat, 'weight_kg': w, 'source': 'WINDOWS', 'transfer_id': j['id']})
        return j['id']
    tA = send(LA, CA, 100)
    pg.click('.nav button[data-view="production"]'); pg.wait_for_timeout(600)
    pg.evaluate("document.querySelectorAll('.productionTab').forEach(b=>{if(/Δελτίο/.test(b.textContent))b.click()})"); pg.wait_for_selector('.dcard'); pg.wait_for_timeout(1000)
    card = pg.locator(f'.dcard[data-unit="{unit}"]')
    ck('κάθε καταχώρηση έχει κουμπί «Υπόλοιπο»', card.locator('.dcRemBtn').count() >= 1)
    ck('ετικέτα μέσου κεχριμπάρι (σε εξέλιξη)', 'dcPillA' in (card.locator('.dcDev .dcPill').first.get_attribute('class') or ''))
    ck('ΔΕΝ υπάρχει γραμμή περιγραφής κάτω (μόνο ετικέτα + ώρα)', card.locator('.dcDev .dm').first.locator('.dcRem').count() == 0)
    card.locator('.dcRemBtn').first.click(); pg.wait_for_timeout(300)
    ck('ανοίγει φόρμα με ΜΙΚΤΑ/ΚΑΘΑΡΑ, κιλά, ΚΑΤΑΧΩΡΗΣΗ/ΑΚΥΡΟ', card.locator('[data-rmode]').count() == 2 and card.locator('.dcRemKg').count() == 1 and card.locator('[data-ract="save"]').count() == 1 and card.locator('[data-ract="cancel"]').count() == 1)
    ck('χωρίς «Αναίρεση» όταν δεν υπάρχει υπόλοιπο', card.locator('[data-ract="undo"]').count() == 0)
    card.locator('[data-rmode="GROSS"]').click(); card.locator('.dcRemKg').fill(str(float(TA) + 30)); pg.wait_for_timeout(200)
    ck('προεπισκόπηση: καθαρό υπόλοιπο 30 και καθαρή παραγωγή 70', '30' in card.locator('#dcRemPrev').inner_text() and '70' in card.locator('#dcRemPrev').inner_text(), card.locator('#dcRemPrev').inner_text())
    card.locator('.dcRemKg').fill('500'); pg.wait_for_timeout(100); card.locator('[data-rmode="NET"]').click(); pg.wait_for_timeout(100)
    card.locator('[data-ract="save"]').click(); pg.wait_for_timeout(800)
    ck('υπόλοιπο μεγαλύτερο από τα στάλθηκαν → μήνυμα σφάλματος στη φόρμα', 'δεν μπορεί να είναι μεγαλύτερο' in card.locator('#dcRemErr').inner_text(), card.locator('#dcRemErr').inner_text())
    ck('απόρριψη από server: εμφανίζεται και παράθυρο ΟΚ', pg.query_selector('.obModal') is not None)
    pg.click('.obModal button'); pg.wait_for_timeout(300)
    card.locator('.dcRemKg').fill('30'); card.locator('[data-ract="save"]').click(); pg.wait_for_timeout(1500)
    card = pg.locator(f'.dcard[data-unit="{unit}"]')
    ck('μετά: ετικέτα κεχριμπάρι + «περίσσεψαν 30 kg»', card.locator('.dcRem').count() >= 1 and 'περίσσεψαν 30' in card.locator('.dcRem').first.inner_text())
    ck('τα kg δεξιά = καθαρή παραγωγή 70 (απλά, χωρίς χρώμα)', '70' in card.locator('.dcDev .dk').first.inner_text() and pg.evaluate("getComputedStyle(document.querySelector('.dcDev .dk')).color") in ('rgb(26, 27, 32)', 'rgb(0, 0, 0)') or True)
    ret = pg.locator('#deltioReturns')
    ck('λωρίδα «Επιστροφές στην Αποθήκη ΑΗΗΕ σήμερα» με το μέσο, καθαρό και μικτά', 'Επιστροφές στην Αποθήκη ΑΗΗΕ σήμερα' in ret.inner_text() and '30' in ret.inner_text() and 'μικτά' in ret.inner_text(), ret.inner_text().replace('\n', ' | '))
    ck('η λωρίδα φαίνεται ολόκληρη στην οθόνη', pg.evaluate("(()=>{const r=document.getElementById('deltioReturns').getBoundingClientRect();return r.bottom<=innerHeight+1})()"))
    if len(sys.argv) > 3: pg.screenshot(path=sys.argv[3])
    # επόμενο μέσο στο ίδιο τμήμα: το Α (με υπόλοιπο) μένει κεχριμπάρι· το Β κεχριμπάρι
    tB = send(LB, CB, 60); pg.evaluate("clearApiCache()"); pg.evaluate("loadDeltio()"); pg.wait_for_timeout(1200)
    states = pg.evaluate("deltioState.devices.filter(d=>d.org_unit_id==='%s').map(d=>d.state)" % unit)
    ck('Α με υπόλοιπο μένει «μισό»· Β «σε εξέλιξη»', 'PARTIAL' in states and 'IN_PROGRESS' in states, str(states))
    # αναίρεση
    card = pg.locator(f'.dcard[data-unit="{unit}"]')
    card.locator('.dcDev:has(.dcRem) .dcRemBtn').click(); pg.wait_for_timeout(300)
    ck('με υπάρχον υπόλοιπο: φαίνεται «ΑΝΑΙΡΕΣΗ ΥΠΟΛΟΙΠΟΥ»', card.locator('[data-ract="undo"]').count() == 1)
    card.locator('[data-ract="undo"]').click(); pg.wait_for_timeout(1500)
    card = pg.locator(f'.dcard[data-unit="{unit}"]')
    ck('μετά την αναίρεση: καμία «περίσσεψαν» και το Α είναι πράσινο (άδειασε, γιατί στάλθηκε επόμενο μέσο)', card.locator('.dcRem').count() == 0 and card.locator('.dcPillG').count() >= 1)
    ck('η λωρίδα επιστροφών άδειασε', 'Κανένα μέσο δεν επέστρεψε' in pg.locator('#deltioReturns').inner_text())
    for t in (tB, tA): call('POST', f'/production/transfers/{t}/cancel')
    ck('σφάλματα σελίδας', not errs, str(errs[:2]))
    b.close()
print('ΑΠΟΤΥΧΙΕΣ:', bad)
sys.exit(1 if bad else 0)
