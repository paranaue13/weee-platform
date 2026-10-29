"""Δοκιμή Android › Υλικά → Εξαγωγή (απευθείας μετάβαση, περίγραμμα, «ΕΞΑΓΩΓΗ», ιστορικό εξαγωγών, πάτημα Εξαγωγή/Υλικά → πίσω) + «πίσω» του συστήματος (appBack) σε όλες τις οθόνες. 360×640.
Χρήση: python backend/scripts/test_android_materials_back.py http://127.0.0.1:PORT C:/ΑΝΤΙΓΡΑΦΟ.db   (ΜΟΝΟ σε ΑΝΤΙΓΡΑΦΟ βάσης!)"""
import sys, os, sqlite3, datetime
sys.path.insert(0, os.path.dirname(__file__)); sys.stdout.reconfigure(encoding='utf-8')
from playwright.sync_api import sync_playwright
from _browser import launch
B, DB = sys.argv[1], sys.argv[2]
bad = []
def ck(n, ok, i=''):
    print(('✓ ' if ok else '✗ ') + n, i)
    if not ok: bad.append(n)
with sync_playwright() as p:
    b = launch(p); errs = []
    pg = b.new_page(viewport={'width': 360, 'height': 700}, is_mobile=True, has_touch=True); pg.on('pageerror', lambda e: errs.append(str(e)))
    pg.goto(B + '/mobile', wait_until='networkidle'); pg.click('#loginBtn'); pg.wait_for_selector('#app:not(.hidden)'); pg.wait_for_timeout(2500)
    back = lambda: pg.evaluate("window.appBack()")
    vis = lambda sel: pg.evaluate("s=>{let e=document.querySelector(s);return !!e&&e.offsetParent!==null}", sel)
    # ---------- ΥΛΙΚΑ ----------
    pg.tap('.secBtn[data-section=materials]'); pg.wait_for_selector('.mtCat', timeout=15000); pg.wait_for_timeout(800)
    ck('κανένα κουμπί «ΣΥΝΕΧΕΙΑ» στα Υλικά', pg.query_selector('#mtNext') is None and 'ΣΥΝΕΧΕΙΑ' not in pg.inner_text('#matArea'))
    cat = pg.locator('.mtCat:not(.haz)').first; cat.tap(); pg.wait_for_selector('.mtMatBtn', timeout=8000)
    ck('πατώντας κατηγορία πηγαίνει ΑΜΕΣΩΣ στα υλικά', pg.locator('.mtMatBtn').count() > 0 and pg.query_selector('#mtNext') is None)
    mats = pg.locator('.mtMatBtn'); n = mats.count()
    # υλικό με διαθέσιμα kg
    idx = pg.evaluate("[...document.querySelectorAll('.mtMatBtn')].findIndex(b=>{let k=b.querySelector('b');return k&&parseFloat(k.innerText.replace(/\\./g,'').replace(',','.'))>=5})")
    idx = 0 if idx < 0 else idx
    # περίγραμμα επιλεγμένου κουτιού: μέσα στο κουτί (inset), όχι outline που κόβεται
    pg.evaluate("i=>document.querySelectorAll('.mtMatBtn')[i].classList.add('on')", idx)
    st = pg.evaluate("i=>{let e=document.querySelectorAll('.mtMatBtn')[i],s=getComputedStyle(e),r=e.getBoundingClientRect(),l=e.parentElement.getBoundingClientRect();return [s.outlineStyle,s.boxShadow,r.left>=l.left,r.right<=l.right]}", idx)
    ck('περίγραμμα επιλεγμένου υλικού ΜΕΣΑ στο κουτί (inset), χωρίς outline', st[0] == 'none' and 'inset' in st[1] and st[2] and st[3], str(st))
    pg.evaluate("i=>document.querySelectorAll('.mtMatBtn')[i].classList.remove('on')", idx)
    mats.nth(idx).tap(); pg.wait_for_selector('.mtForm', timeout=8000)
    ck('πατώντας υλικό πηγαίνει ΑΜΕΣΩΣ στο μέσο αποθήκευσης', pg.locator('.mtForm').count() >= 1 and pg.query_selector('#mtNext') is None)
    pg.locator('.mtForm[data-form="BULK"]').tap(); pg.wait_for_selector('#mtNet'); pg.fill('#mtNet', '3'); pg.wait_for_timeout(300)
    ck('το τελικό κουμπί γράφει μόνο «ΕΞΑΓΩΓΗ»', pg.inner_text('#mtSend').strip() == 'ΕΞΑΓΩΓΗ', pg.inner_text('#mtSend'))
    # πάτημα «ΕΞΑΓΩΓΗ» (πάνω) με γραμμένα κιλά → ρωτά· χωρίς κιλά → αμέσως
    pg.fill('#mtNet', ''); pg.wait_for_timeout(200)
    pg.locator('.matStart[data-m="export"]').tap(); pg.wait_for_timeout(500)
    ck('πάτημα «Εξαγωγή» μέσα στο υλικό (χωρίς κιλά): γυρνά ΑΜΕΣΩΣ στην αρχή, χωρίς παράθυρο', pg.query_selector('.mtCat') is not None and pg.query_selector('#enSheet:not(.hidden)') is None)
    cat = pg.locator('.mtCat:not(.haz)').first; cat.tap(); pg.wait_for_selector('.mtMatBtn'); pg.locator('.mtMatBtn').nth(idx).tap(); pg.wait_for_selector('.mtForm')
    pg.tap('.secBtn[data-section=materials]'); pg.wait_for_timeout(600)
    ck('πάτημα «Υλικά» (πάνω) μέσα στο υλικό: γυρνά ΑΜΕΣΩΣ στην αρχή, χωρίς παράθυρο', pg.query_selector('.mtCat') is not None and not vis('#enSheet'))
    # ---- «πίσω» του συστήματος στα Υλικά ----
    pg.locator('.mtCat:not(.haz)').first.tap(); pg.wait_for_selector('.mtMatBtn'); pg.locator('.mtMatBtn').nth(idx).tap(); pg.wait_for_selector('.mtForm')
    r1 = back(); pg.wait_for_timeout(300)
    ck('«πίσω» συστήματος από το μέσο → στα υλικά', r1 is True and pg.query_selector('.mtMatBtn') is not None)
    r2 = back(); pg.wait_for_timeout(300)
    ck('«πίσω» → στις κατηγορίες', r2 is True and pg.query_selector('.mtCat') is not None)
    r3 = back(); pg.wait_for_timeout(500)
    ck('«πίσω» από την αρχή των Υλικών → στην αρχική οθόνη (ΠΑΡΑΛΑΒΕΣ)', r3 is True and vis('#secReceiving'))
    ck('«πίσω» στην αρχική οθόνη → false (κανονικό κλείσιμο της εφαρμογής)', back() is False)
    # ---- εξαγωγή + ιστορικό ----
    pg.tap('.secBtn[data-section=materials]'); pg.wait_for_selector('.mtCat'); pg.locator('.mtCat:not(.haz)').first.tap(); pg.wait_for_selector('.mtMatBtn'); pg.locator('.mtMatBtn').nth(idx).tap(); pg.wait_for_selector('.mtForm')
    matname = pg.evaluate("document.querySelector('.flPicked span:not(small)')?document.querySelectorAll('.flPicked span')[1].innerText:''")
    pg.locator('.mtForm[data-form="BULK"]').tap(); pg.wait_for_selector('#mtNet'); pg.fill('#mtNet', '3'); pg.wait_for_timeout(200)
    pg.locator('#mtSend').tap(); pg.wait_for_timeout(2500)
    ck('μετά την εξαγωγή: γυρνά στις κατηγορίες και το ιστορικό είναι ορατό', pg.query_selector('.mtCat') is not None and vis('#matHistCard'))
    h = pg.inner_text('#matHist')
    ck('ιστορικό: ομάδα «ΣΗΜΕΡΑ» με υλικό, μέσο (Χύμα), κιλά και ώρα', 'ΣΗΜΕΡΑ' in h.upper() and '3 kg' in h and 'Χύμα' in h and datetime.datetime.now().strftime('%H:') in h, h.replace('\n', ' | ')[:200])
    ck('ΔΕΝ υπάρχουν κουμπιά ΔΙΟΡΘΩΣΗ/ΔΙΑΓΡΑΦΗ ακόμα (θα μπουν μετά την έγκριση)', 'ΔΙΟΡΘΩΣΗ' not in h)
    nb = pg.evaluate("document.querySelectorAll('#matHist .ptItem').length")
    # ---- «πίσω» σε Παραγωγή ----
    pg.tap('.secBtn[data-section=production]'); pg.wait_for_timeout(1500); pg.evaluate("flLoad(true)"); pg.wait_for_timeout(2500)
    pg.evaluate("document.querySelector('.flStart[data-f=d]').click()"); pg.wait_for_timeout(300)
    pg.evaluate("flPick('unit',prodUnits.find(u=>/Τηλεόρασ/.test(u.name_el)).id)"); pg.wait_for_timeout(400)
    pg.locator('.flBulk').first.tap(); pg.wait_for_timeout(500)
    ck('Παραγωγή: έτοιμη αποστολή (τμήμα+ΑΗΗΕ)', pg.query_selector('#flKg') is not None)
    r = back(); pg.wait_for_timeout(300); ck('«πίσω» → βήμα ΑΗΗΕ (έφυγε η επιλογή ΑΗΗΕ)', r is True and pg.evaluate("!fl.cat"))
    r = back(); pg.wait_for_timeout(300); ck('«πίσω» → βήμα μέσο (έφυγε το μέσο)', r is True and pg.evaluate("!fl.medium&&!!fl.unit"))
    r = back(); pg.wait_for_timeout(300); ck('«πίσω» → βήμα τμήμα', r is True and pg.evaluate("!fl.unit"))
    r = back(); pg.wait_for_timeout(500); ck('«πίσω» από την αρχή της Παραγωγής → ΠΑΡΑΛΑΒΕΣ', r is True and vis('#secReceiving'))
    # κιλά γραμμένα → ρωτά
    pg.tap('.secBtn[data-section=production]'); pg.wait_for_timeout(1000); pg.evaluate("document.querySelector('.flStart[data-f=d]').click()"); pg.evaluate("flPick('unit',prodUnits.find(u=>/Τηλεόρασ/.test(u.name_el)).id)"); pg.wait_for_timeout(300)
    pg.locator('.flBulk').first.tap(); pg.wait_for_selector('#flKg'); pg.fill('#flKg', '2'); pg.wait_for_timeout(200)
    r = back(); pg.wait_for_timeout(400)
    ck('με κιλά που έγραψα: το «πίσω» ΡΩΤΑ πριν χάσω τη φόρμα (δεν χάνεται σιωπηλά)', r is True and vis('#enSheetBody') and pg.query_selector('#flKg') is not None and 'χωρίς αποθήκευση' in pg.inner_text('#enSheetBody'))
    pg.locator('#enSheetBody [data-sh="stay"]').tap(); pg.wait_for_timeout(300)
    ck('«Παραμονή»: μένει η φόρμα με τα κιλά', pg.input_value('#flKg') == '2')
    # ---- Εργαζόμενοι ----
    pg.tap('#topDeltioBtn'); pg.wait_for_selector('.dlRow'); pg.wait_for_timeout(500)
    r = back(); pg.wait_for_timeout(500); ck('«πίσω» από τους Εργαζόμενους → Μεταφορά υλικού (Παραγωγή)', r is True and vis('#prodTransferPanel') and not vis('#deltioPanel'))
    # ρόστερ
    pg.tap('#topDeltioBtn'); pg.wait_for_selector('.dlRow'); pg.tap('#deltioDeptBtn'); pg.wait_for_selector('#dlPerm'); pg.tap('#dlPerm'); pg.wait_for_selector('#roster:not(.hidden)'); pg.wait_for_timeout(500)
    r = back(); pg.wait_for_timeout(500); ck('«πίσω» από την Τοποθέτηση εργαζομένων → πίσω στους Εργαζόμενους', r is True and not vis('#roster') and vis('#deltioPanel'))
    ck('σφάλματα σελίδας', not errs, str(errs[:2]))
    b.close()
print('ΑΠΟΤΥΧΙΕΣ:', bad)
sys.exit(1 if bad else 0)
