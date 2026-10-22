"""Δοκιμή Android › πάτημα της ήδη ενεργής καρτέλας → αρχική οθόνη (με/χωρίς ανοιχτή φόρμα), 360×640.
Χρήση: python backend/scripts/test_android_tab_home.py http://127.0.0.1:PORT [φάκελος screenshots]   (server σε ΑΝΤΙΓΡΑΦΟ βάσης)"""
import sys, os
sys.path.insert(0, os.path.dirname(__file__))
sys.stdout.reconfigure(encoding='utf-8')
from playwright.sync_api import sync_playwright
from _browser import launch
B = sys.argv[1]; S = (sys.argv[2] if len(sys.argv) > 2 else '.') + '/t_'
bad = []
def ck(name, ok, info=''):
    print(('✓ ' if ok else '✗ ') + name, info)
    if not ok: bad.append(name)
with sync_playwright() as p:
    b = launch(p); errs = []
    pg = b.new_page(viewport={'width': 360, 'height': 640}, is_mobile=True, has_touch=True, device_scale_factor=1)
    pg.on('pageerror', lambda e: errs.append(str(e)))
    pg.goto(B + '/mobile', wait_until='networkidle'); pg.click('#loginBtn'); pg.wait_for_selector('#app:not(.hidden)'); pg.wait_for_timeout(2500)
    hid = lambda sel: pg.evaluate("s=>document.querySelector(s).classList.contains('hidden')", sel)
    sheet_open = lambda: not hid('#enSheet') and 'Να φύγεις χωρίς αποθήκευση;' in pg.inner_text('#enSheetBody')
    sec = lambda n: pg.tap(f'.secBtn[data-section={n}]')
    # ---------- ΠΑΡΑΛΑΒΕΣ ----------
    L = pg.evaluate("api('/sorting/available').then(r=>r.find(x=>x.status!=='SUBMITTED'&&Number(x.net_weight)>0)||r[0])")
    lid = L['load_id']
    n0 = pg.evaluate("id=>api('/sorting/'+id).then(s=>s.entries.length)", lid)
    pg.evaluate("document.querySelector('#loadList [data-id=\"%s\"]').click()" % lid); pg.wait_for_timeout(2000)
    ck('ΠΑΡΑΛΑΒΕΣ: μέσα στην παραλαβή', not hid('#work') and hid('#loads'))
    pg.evaluate("window.scrollTo(0,300)"); sec('receiving'); pg.wait_for_timeout(1200)
    ck('ΠΑΡΑΛΑΒΕΣ (χωρίς φόρμα): πάει στη λίστα παραλαβών, κορυφή', hid('#work') and not hid('#loads') and pg.evaluate("scrollY") == 0)
    # με ανοιχτή φόρμα ΑΛΛΑ χωρίς αλλαγές → κατευθείαν
    pg.evaluate("document.querySelector('#loadList [data-id=\"%s\"]').click()" % lid); pg.wait_for_timeout(2000)
    pg.evaluate("document.getElementById('allBtn').click()"); pg.wait_for_timeout(300)
    pg.evaluate("choose(cats.find(c=>c.active!==false&&!c.is_internal_subcategory).id)"); pg.wait_for_timeout(1500)
    ck('φόρμα καταχώρησης ανοιχτή', not hid('#entry'))
    sec('receiving'); pg.wait_for_timeout(1200)
    ck('ΠΑΡΑΛΑΒΕΣ (φόρμα χωρίς αλλαγές): φεύγει κατευθείαν, χωρίς ερώτηση', hid('#work') and not sheet_open() and hid('#entry'))
    # με αλλαγμένη φόρμα → επιβεβαίωση
    pg.evaluate("document.querySelector('#loadList [data-id=\"%s\"]').click()" % lid); pg.wait_for_timeout(2000)
    pg.evaluate("choose(cats.find(c=>c.active!==false&&!c.is_internal_subcategory).id)"); pg.wait_for_timeout(1500)
    pg.evaluate("document.getElementById('noMedium').onclick()"); pg.wait_for_timeout(300)
    pg.fill('#weight', '55'); sec('receiving'); pg.wait_for_timeout(500)
    ck('ΠΑΡΑΛΑΒΕΣ (φόρμα με αλλαγές): ζητά «Να φύγεις χωρίς αποθήκευση;»', sheet_open())
    pg.screenshot(path=S + 'leave.png')
    pg.tap('.shEdit'); pg.wait_for_timeout(300)   # Παραμονή
    ck('Παραμονή: μένω στη φόρμα και τα στοιχεία μένουν', not hid('#entry') and pg.input_value('#weight') == '55' and hid('#enSheet'))
    sec('receiving'); pg.wait_for_timeout(400); pg.tap('.shDel'); pg.wait_for_timeout(1200)   # Έξοδος
    ck('Έξοδος: πάει στη λίστα παραλαβών', hid('#work') and not hid('#loads') and hid('#entry'))
    n1 = pg.evaluate("id=>api('/sorting/'+id).then(s=>s.entries.length)", lid)
    ck('δεν χάθηκε/προστέθηκε αποθηκευμένη καταχώρηση', n0 == n1, f'{n0} → {n1}')
    # το «← ΠΑΡΑΛΑΒΕΣ» δουλεύει όπως πριν
    pg.evaluate("document.querySelector('#loadList [data-id=\"%s\"]').click()" % lid); pg.wait_for_timeout(2000)
    pg.tap('#back'); pg.wait_for_timeout(1000)
    ck('«← ΠΑΡΑΛΑΒΕΣ»: συνεχίζει να λειτουργεί', hid('#work') and not hid('#loads'))
    # ---------- ΠΑΡΑΓΩΓΗ ----------
    sec('production'); pg.wait_for_timeout(2500)
    pg.evaluate("document.querySelector('.flStart[data-f=a]').click()"); pg.wait_for_timeout(500)
    pg.evaluate("document.querySelector('#flowArea .flOpt[data-k=cat]')?.click()"); pg.wait_for_timeout(500)
    st = pg.evaluate("[fl.f,!!fl.cat]"); print('παραγωγή πριν:', st)
    pg.evaluate("window.scrollTo(0,200)"); sec('production'); pg.wait_for_timeout(800)
    ck('ΠΑΡΑΓΩΓΗ (χωρίς φόρμα): αρχική οθόνη (ροή ΤΜΗΜΑ, καθαρή), κορυφή', pg.evaluate("[fl.f,!!fl.cat,!!fl.unit]") == ['d', False, False] and pg.evaluate("scrollY") == 0)
    pg.evaluate("document.querySelector('.flStart[data-f=m]').click()"); pg.wait_for_timeout(400)
    pg.evaluate("document.querySelector('.flStart[data-f=m]').click()"); pg.wait_for_timeout(400)
    ck('υποκαρτέλα ΜΕΣΟ ΣΥΛΛΟΓΗΣ ξανά: αρχή της ροής (καθαρή)', pg.evaluate("[fl.f,!!fl.medium]") == ['m', False])
    pg.evaluate("fl.kg='12'"); sec('production'); pg.wait_for_timeout(400)
    ck('ΠΑΡΑΓΩΓΗ (με κιλά που δεν στάλθηκαν): ζητά επιβεβαίωση', sheet_open())
    pg.tap('.shEdit'); pg.wait_for_timeout(300)
    ck('Παραμονή: τα κιλά μένουν', pg.evaluate("fl.kg") == '12')
    sec('production'); pg.wait_for_timeout(300); pg.tap('.shDel'); pg.wait_for_timeout(800)
    ck('Έξοδος: αρχική οθόνη ΠΑΡΑΓΩΓΗΣ', pg.evaluate("[fl.f,fl.kg]") == ['d', None] and not sheet_open())
    # ---------- ΥΛΙΚΑ ----------
    sec('materials'); pg.wait_for_timeout(2500)
    pg.evaluate("document.querySelector('.matStart[data-m=stock]').click()"); pg.wait_for_timeout(1500)
    pg.evaluate("window.scrollTo(0,200)"); sec('materials'); pg.wait_for_timeout(1500)
    ck('ΥΛΙΚΑ (χωρίς φόρμα): αρχική οθόνη = ΕΞΑΓΩΓΗ, κορυφή', pg.evaluate("mt.tab") == 'export' and pg.evaluate("document.querySelector('.matStart.on').dataset.m") == 'export' and pg.evaluate("scrollY") == 0)
    pg.evaluate("document.querySelector('.matStart[data-m=stock]').click()"); pg.wait_for_timeout(800)
    pg.evaluate("document.querySelector('.matStart[data-m=stock]').click()"); pg.wait_for_timeout(800)
    ck('υποκαρτέλα ΑΠΟΘΗΚΗ ξανά: μένει στην ΑΠΟΘΗΚΗ (αρχή της)', pg.evaluate("mt.tab") == 'stock')
    pg.evaluate("document.querySelector('.matStart[data-m=export]').click()"); pg.wait_for_timeout(800)
    pg.evaluate("mt.w.step=2;mt.w.gross='100'"); sec('materials'); pg.wait_for_timeout(400)
    ck('ΥΛΙΚΑ (με μισοσυμπληρωμένη ζύγιση): ζητά επιβεβαίωση', sheet_open())
    pg.tap('.shEdit'); pg.wait_for_timeout(300)
    ck('Παραμονή: η ζύγιση μένει', pg.evaluate("mt.w.gross") == '100')
    pg.evaluate("document.querySelector('.matStart[data-m=export]').click()"); pg.wait_for_timeout(300); pg.tap('.shDel'); pg.wait_for_timeout(800)
    ck('Έξοδος (υποκαρτέλα): νέα κενή ζύγιση', pg.evaluate("[mt.w.step,mt.w.gross]") == [1, ''])
    # ---------- ΦΟΡΤΩΣΕΙΣ ----------
    sec('loading'); pg.wait_for_timeout(2000)
    pg.evaluate("window.scrollTo(0,150)"); sec('loading'); pg.wait_for_timeout(1500)
    ck('ΦΟΡΤΩΣΕΙΣ (λίστα): παραμένει στη λίστα, κορυφή', not hid('#secLoading') and pg.evaluate("scrollY") == 0)
    pg.tap('#loadingNewBtn'); pg.wait_for_timeout(500)
    ck('νέο δελτίο: φόρμα ανοιχτή', not hid('#loadingNew'))
    sec('loading'); pg.wait_for_timeout(1200)
    ck('ΦΟΡΤΩΣΕΙΣ (κενή φόρμα): φεύγει κατευθείαν στη λίστα', hid('#loadingNew') and not hid('#secLoading') and not sheet_open())
    pg.tap('#loadingNewBtn'); pg.wait_for_timeout(500); pg.fill('#loadingPlate', 'ΧΧΧ-1234'); sec('loading'); pg.wait_for_timeout(500)
    ck('ΦΟΡΤΩΣΕΙΣ (φόρμα με στοιχεία): ζητά επιβεβαίωση', sheet_open() and not hid('#loadingNew'))
    pg.tap('.shEdit'); pg.wait_for_timeout(300)
    ck('Παραμονή: τα στοιχεία μένουν', pg.input_value('#loadingPlate') == 'ΧΧΧ-1234')
    sec('loading'); pg.wait_for_timeout(300); pg.tap('.shDel'); pg.wait_for_timeout(1200)
    ck('Έξοδος: λίστα φορτώσεων', hid('#loadingNew') and not hid('#secLoading'))
    # «Πίσω» κλείνει την επιβεβαίωση (= Παραμονή)
    pg.tap('#loadingNewBtn'); pg.wait_for_timeout(400); pg.fill('#loadingPlate', 'Α'); sec('loading'); pg.wait_for_timeout(300)
    ck('«Πίσω» κλείνει την ερώτηση (Παραμονή)', pg.evaluate("window.appBack()") is True and hid('#enSheet') and not hid('#loadingNew'))
    ck('σφάλματα σελίδας', not errs, str(errs))
    b.close()
print('ΑΠΟΤΥΧΙΕΣ:', bad)
sys.exit(1 if bad else 0)
