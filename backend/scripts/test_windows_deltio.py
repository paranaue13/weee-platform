"""Δοκιμή Windows › Παραγωγή › Δελτίο Παραγωγής (κάρτες τμημάτων, ώρες, βελάκι, λίστα συσκευών, ρύθμιση ΑΗΗΕ).
Χρήση: python backend/scripts/test_windows_deltio.py http://127.0.0.1:PORT   (server σε ΑΝΤΙΓΡΑΦΟ βάσης: γράφει παρουσίες/τμήματα!)"""
import sys, os, datetime
sys.path.insert(0, os.path.dirname(__file__))
sys.stdout.reconfigure(encoding='utf-8')
from playwright.sync_api import sync_playwright
from _browser import launch
B = sys.argv[1]
bad = []
def ck(name, ok, info=''):
    print(('✓ ' if ok else '✗ ') + name, info)
    if not ok: bad.append(name)
DAY = datetime.date.today().isoformat()
with sync_playwright() as p:
    b = launch(p); errs = []
    pg = b.new_page(viewport={'width': 1500, 'height': 900}); pg.on('pageerror', lambda e: errs.append(str(e)))
    pg.goto(B + '/', wait_until='networkidle'); pg.wait_for_selector('#loginBtn', state='visible'); pg.click('#loginBtn'); pg.wait_for_selector('#metrics .card', timeout=20000); pg.wait_for_timeout(1200)
    pg.click('.nav button[data-view="production"]'); pg.wait_for_timeout(800)
    pg.click('.productionTab[data-prodtab="deltio"]') if pg.query_selector('.productionTab[data-prodtab="deltio"]') else pg.evaluate("document.querySelectorAll('.productionTab').forEach(b=>{if(/Δελτίο/.test(b.textContent))b.click()})")
    pg.wait_for_selector('.deltioDeptCard', timeout=15000); pg.wait_for_timeout(800)
    ck('δεν υπάρχει πια λίστα «διαθέσιμων εργαζομένων»', pg.query_selector('#deltioWorkerList') is None)
    ck('δεν υπάρχει κουμπί «Έφυγε» (✕) στο Δελτίο', pg.query_selector('.deltioLeaveBtn') is None)
    ck('κάρτες τμημάτων', pg.locator('.deltioDeptCard').count() > 0, str(pg.locator('.deltioDeptCard').count()))
    ck('στήλη «Ώρες» με ω:λλ ή —', all(__import__('re').match(r'^(\d+:\d\d|—)$', t.strip()) for t in pg.locator('.deltioHrs').all_inner_texts()) and pg.locator('.deltioHrs').count() > 0)
    ck('βελάκι → σε κάθε εργαζόμενο', pg.locator('.deltioArrow').count() == pg.locator('.deltioHrs').count() > 0)
    # εργαζόμενος με 1 τμήμα: μενού χωρίς «Αφαίρεση»
    emps = pg.evaluate("prodState.employees.filter(e=>e.active!==false&&(e.org_unit_ids||[]).length===1).map(e=>[e.id,e.org_unit_ids[0],e.full_name])")
    units = pg.evaluate("prodState.units.filter(u=>u.active!==false&&u.profile!=='MANAGEMENT').map(u=>u.id)")
    e = next(x for x in emps if x[1] in units)
    btn = pg.locator(f'.deltioDeptCard[data-unit="{e[1]}"] .deltioArrow[data-emp="{e[0]}"]'); btn.click(); pg.wait_for_selector('.deltioMenu')
    ck('μενού: «Μεταφορά» και «Εργασία» για τα άλλα τμήματα', pg.locator('.deltioMenu button[data-k="move"]').count() > 0 and pg.locator('.deltioMenu button[data-k="add"]').count() > 0)
    ck('μενού: ΧΩΡΙΣ «Αφαίρεση» όταν ανήκει σε 1 τμήμα', pg.locator('.deltioMenu button[data-k="remove"]').count() == 0)
    other = pg.locator('.deltioMenu button[data-k="add"]').first.get_attribute('data-to')
    pg.locator('.deltioMenu button[data-k="add"]').first.click(); pg.wait_for_timeout(1500)
    ck('«Εργασία»: ο εργαζόμενος εμφανίζεται και στα 2 τμήματα', pg.locator(f'.deltioArrow[data-emp="{e[0]}"]').count() == 2)
    pg.locator(f'.deltioDeptCard[data-unit="{e[1]}"] .deltioArrow[data-emp="{e[0]}"]').click(); pg.wait_for_selector('.deltioMenu')
    ck('μενού με 2 τμήματα: υπάρχει «Αφαίρεση από αυτό το τμήμα»', pg.locator('.deltioMenu button[data-k="remove"]').count() == 1)
    pg.locator('.deltioMenu button[data-k="remove"]').click(); pg.wait_for_timeout(1500)
    ck('«Αφαίρεση»: μένει μόνο στο άλλο τμήμα', pg.locator(f'.deltioArrow[data-emp="{e[0]}"]').count() == 1 and pg.locator(f'.deltioDeptCard[data-unit="{other}"] .deltioArrow[data-emp="{e[0]}"]').count() == 1)
    # Μεταφορά πίσω
    pg.locator(f'.deltioDeptCard[data-unit="{other}"] .deltioArrow[data-emp="{e[0]}"]').click(); pg.wait_for_selector('.deltioMenu')
    pg.locator(f'.deltioMenu button[data-k="move"][data-to="{e[1]}"]').click(); pg.wait_for_timeout(1500)
    ck('«Μεταφορά»: πήγε πίσω και έφυγε από το άλλο', pg.locator(f'.deltioArrow[data-emp="{e[0]}"]').count() == 1 and pg.locator(f'.deltioDeptCard[data-unit="{e[1]}"] .deltioArrow[data-emp="{e[0]}"]').count() == 1)
    ck('μενού κλείνει με κλικ έξω', (pg.locator(f'.deltioDeptCard[data-unit="{e[1]}"] .deltioArrow[data-emp="{e[0]}"]').click(), pg.wait_for_selector('.deltioMenu'), pg.mouse.click(5, 5), pg.wait_for_timeout(300), pg.query_selector('.deltioMenu') is None)[-1])
    # διοίκηση εξαιρείται
    mg = pg.evaluate("prodState.units.filter(u=>u.profile==='MANAGEMENT').map(u=>u.id)")
    ck('τμήματα Διοίκησης δεν έχουν κάρτα', all(pg.query_selector(f'.deltioDeptCard[data-unit="{m}"]') is None for m in mg), str(len(mg)))
    # λίστα συσκευών: ίδιο API
    devs = pg.evaluate("d=>api('/production/device-list?date='+d)", DAY)
    ck('API συσκευών απαντά (λίστα)', isinstance(devs, list), str(len(devs)))
    ck('ρύθμιση «Δελτίο Παραγωγής» στο Εμφάνιση ΑΗΗΕ', pg.evaluate("WEEE_DESC_TABS.some(t=>t[0]==='deltio')"))
    ck('επικεφαλίδα λίστας συσκευών στις κάρτες παραγωγής', pg.locator('.deltioDevHead').count() > 0 and 'ΣΥΣΚΕΥΕΣ ΠΟΥ ΜΠΗΚΑΝ ΣΤΟ ΤΜΗΜΑ' in pg.locator('.deltioDevHead').first.inner_text())
    # Παρουσιολόγιο: οι ώρες = του server
    ck('σφάλματα σελίδας', not errs, str(errs[:2]))
    b.close()
print('ΑΠΟΤΥΧΙΕΣ:', bad)
sys.exit(1 if bad else 0)
