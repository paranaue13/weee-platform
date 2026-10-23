"""Δοκιμή Android › ΕΡΓΑΖΟΜΕΝΟΙ (ΠΑΡΟΥΣΙΕΣ με ΟΛΙΓΟΩΡΗ + ώρες + ωράριο, ΤΜΗΜΑΤΑ, «‹ Πίσω»), 360×640.
Χρήση: python backend/scripts/test_android_employees.py http://127.0.0.1:PORT [φάκελος screenshots]   (server σε ΑΝΤΙΓΡΑΦΟ βάσης: γράφει παρουσίες/τμήματα!)"""
import sys, os, re
sys.path.insert(0, os.path.dirname(__file__))
sys.stdout.reconfigure(encoding='utf-8')
from playwright.sync_api import sync_playwright
from _browser import launch
B = sys.argv[1]; S = (sys.argv[2] if len(sys.argv) > 2 else '.') + '/e_'
bad = []
def ck(name, ok, info=''):
    print(('✓ ' if ok else '✗ ') + name, info)
    if not ok: bad.append(name)
with sync_playwright() as p:
    b = launch(p); errs = []
    pg = b.new_page(viewport={'width': 360, 'height': 640}, is_mobile=True, has_touch=True, device_scale_factor=1)
    pg.on('pageerror', lambda e: errs.append(str(e)))
    pg.goto(B + '/mobile', wait_until='networkidle'); pg.click('#loginBtn'); pg.wait_for_selector('#app:not(.hidden)'); pg.wait_for_timeout(2500)
    ck('πάνω κουμπί λέγεται «ΕΡΓΑΖΟΜΕΝΟΙ»', pg.inner_text('#topDeltioBtn').strip() == 'ΕΡΓΑΖΟΜΕΝΟΙ')
    pg.tap('#topDeltioBtn'); pg.wait_for_selector('.dlRow', timeout=15000); pg.wait_for_timeout(800)
    ck('τίτλος σελίδας «Εργαζόμενοι»', pg.inner_text('#deltioPanel h2').strip() == 'Εργαζόμενοι')
    ck('καρτέλες «ΠΑΡΟΥΣΙΕΣ» και «ΤΜΗΜΑΤΑ»', pg.inner_text('#deltioEmpBtn').strip() == 'ΠΑΡΟΥΣΙΕΣ' and pg.inner_text('#deltioDeptBtn').strip() == 'ΤΜΗΜΑΤΑ')
    ck('ωράριο πάνω: Βάρδια, Τμήμα Α, Τμήμα Β', all(t in pg.inner_text('#dlSched') for t in ['Βάρδια', 'Τμήμα Α', 'Τμήμα Β']), pg.inner_text('#dlSched').replace('\n', ' '))
    ck('η σελίδα δεν γίνεται πλατύτερη από το κινητό (χωρίς οριζόντιο scroll)', pg.evaluate('document.documentElement.scrollWidth') <= 360, str(pg.evaluate('document.documentElement.scrollWidth')))
    ck('5 κουμπιά ανά εργαζόμενο', pg.locator('.dlRow').first.locator('.dlSt').count() == 5 and 'ΟΛΙΓΟΩΡΗ' in pg.locator('.dlRow').first.inner_text())
    ck('μετρητές σε ΜΙΑ σειρά (5 chips στο ίδιο ύψος)', pg.evaluate("[...document.querySelectorAll('#dlCnt .dlChip')].map(c=>Math.round(c.getBoundingClientRect().top)).filter((v,i,a)=>a.indexOf(v)===i).length") == 1 and pg.locator('#dlCnt .dlChip').count() == 5, pg.inner_text('#dlCnt').replace('\n', ' '))
    ck('καθαρές ώρες δίπλα στο όνομα (ω:λλ ή —)', all(re.match(r'^(\d+:\d\d|—)$', t.strip()) for t in pg.locator('.dlHrs').all_inner_texts()) and pg.locator('.dlHrs').count() > 0)
    pg.screenshot(path=S + 'presences.png')
    # Ολιγόωρη
    row = pg.locator('.dlRow').first; eid = row.locator('.dlSt').first.get_attribute('data-e')
    pg.evaluate("e=>deltioSaveAttendance(e,{status:'PRESENT',late:false,short_leaves:[]})", eid); pg.evaluate("loadDeltioAndroid()"); pg.wait_for_timeout(1200)
    n0 = pg.evaluate("()=>[...document.querySelectorAll('#dlCnt .dlChip')].pop().textContent")
    pg.locator(f'.dlSt.s[data-e="{eid}"]').tap(); pg.wait_for_timeout(1500)
    ck('ΟΛΙΓΟΩΡΗ ανοίγει πεδία Έφυγε / Επέστρεψε και «Δεν επέστρεψε → Πρόωρη αποχώρηση»', pg.locator('.dlShT').count() == 2 and pg.locator('.dlShNr').count() == 1 and pg.locator('.dlShAdd').count() == 1)
    c1 = pg.evaluate("()=>[...document.querySelectorAll('#dlCnt .dlChip')].pop().textContent")
    ck('μετρητής Ολιγόωρη αυξήθηκε', c1 != n0, f'{n0} → {c1}')
    pg.locator('.dlShT[data-k="from"]').first.fill('10:00'); pg.wait_for_timeout(1800); pg.locator('.dlShT[data-k="to"]').first.fill('10:30'); pg.wait_for_timeout(1800)
    sl = pg.evaluate("e=>api('/production/attendance/effective?date='+deltioDate).then(r=>r.find(x=>x.employee_id===e).short_leaves)", eid)
    ck('αποθηκεύτηκε στον server 10:00–10:30', sl and sl[0]['from'] == '10:00' and sl[0]['to'] == '10:30', str(sl))
    pg.locator('.dlShAdd').first.tap(); pg.wait_for_timeout(1500)
    ck('«+ Άλλη ολιγόωρη»: δεύτερο κελί', pg.locator('.dlShT[data-k="from"]').count() == 2)
    pg.locator('.dlShX').nth(1).tap(); pg.wait_for_timeout(1500)
    ck('× διαγράφει το δεύτερο', pg.locator('.dlShT[data-k="from"]').count() == 1)
    pg.locator('.dlShT[data-k="to"]').first.fill(''); pg.wait_for_timeout(1500)
    ck('ανοιχτή ολιγόωρη → ώρες «—»', pg.locator(f'.dlRow:has(.dlSt[data-e="{eid}"]) .dlHrs').inner_text().strip() == '—')
    pg.screenshot(path=S + 'short.png')
    pg.locator('.dlShX').first.tap(); pg.wait_for_timeout(1500)
    ck('χωρίς κελιά: το κουμπί ΟΛΙΓΟΩΡΗ ανενεργό', 'on' not in (pg.locator(f'.dlSt.s[data-e="{eid}"]').get_attribute('class') or '').split())
    # ΤΜΗΜΑΤΑ
    pg.tap('#deltioDeptBtn'); pg.wait_for_selector('.dlDept'); pg.wait_for_timeout(500)
    ck('ΤΜΗΜΑΤΑ: χωρίς κουμπιά υλικού', 'ΥΛΙΚΟ' not in pg.inner_text('#dlMain'))
    pg.locator('.dlWk').first.tap(); pg.wait_for_selector('#dlSheet button'); pg.wait_for_timeout(300)
    sh = pg.inner_text('#dlSheet')
    ck('οθόνη εργάτη: Μετακίνηση / Προσθήκη και σε άλλο τμήμα', 'Μετακίνηση' in sh and 'Προσθήκη και σε άλλο τμήμα' in sh)
    ck('ΧΩΡΙΣ «ΛΕΠΤΟΜΕΡΕΙΕΣ / ΥΛΙΚΟ»', 'ΛΕΠΤΟΜΕΡΕΙΕΣ' not in sh)
    one = pg.evaluate("()=>{const e=dlOpenSheet;return null}")
    ck('1 τμήμα → ΔΕΝ υπάρχει «Αφαίρεση από τμήμα»', 'Αφαίρεση από τμήμα' not in sh or pg.evaluate("document.querySelectorAll('#dlSheet .dlChipU').length") >= 2)
    pg.screenshot(path=S + 'sheet.png')
    pg.tap('#dlSheet [data-act="close"]'); pg.wait_for_timeout(300)
    # Πίσω στη Τοποθέτηση εργαζομένων
    pg.tap('#dlPerm'); pg.wait_for_selector('#roster:not(.hidden)'); pg.wait_for_timeout(500)
    ck('«‹ Πίσω» υπάρχει στην Τοποθέτηση εργαζομένων', 'Πίσω' in pg.inner_text('#backRoster'))
    pg.tap('#backRoster'); pg.wait_for_timeout(600)
    ck('«‹ Πίσω» γυρνά στους Εργαζόμενους', pg.evaluate("document.querySelector('#roster').classList.contains('hidden')") and pg.evaluate("!!document.querySelector('#deltioPanel').offsetParent"))
    ck('σφάλματα σελίδας', not errs, str(errs[:2]))
    b.close()
print('ΑΠΟΤΥΧΙΕΣ:', bad)
sys.exit(1 if bad else 0)
