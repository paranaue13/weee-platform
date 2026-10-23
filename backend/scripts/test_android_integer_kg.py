"""Δοκιμή Android › καταχώρηση ταξινόμησης: κάθε καταχώρηση αποθηκεύεται σε ΑΚΕΡΑΙΑ kg (από ,50 ανεβαίνει, μέχρι ,49 κατεβαίνει)· οι οθόνες δείχνουν μόνο ακέραια.
Χρήση: python backend/scripts/test_android_integer_kg.py http://127.0.0.1:PORT   (server σε ΑΝΤΙΓΡΑΦΟ βάσης: γράφει καταχωρήσεις!)"""
import sys, os, re
sys.path.insert(0, os.path.dirname(__file__))
sys.stdout.reconfigure(encoding='utf-8')
from playwright.sync_api import sync_playwright
from _browser import launch
B = sys.argv[1]
bad = []
def ck(name, ok, info=''):
    print(('✓ ' if ok else '✗ ') + name, info)
    if not ok: bad.append(name)
# (είσοδος, αποθηκευμένο — None = δεν γίνεται δεκτό)
CASES = [('0', None), ('0,4', None), ('0,5', 1), ('237', 237), ('237,1', 237), ('237,45', 237), ('237,5', 238), ('237,6', 238), ('237.5', 238), ('238', 238)]
with sync_playwright() as p:
    b = launch(p); errs = []
    pg = b.new_page(viewport={'width': 360, 'height': 640}, is_mobile=True, has_touch=True, device_scale_factor=1)
    pg.on('pageerror', lambda e: errs.append(str(e)))
    pg.goto(B + '/mobile', wait_until='networkidle'); pg.click('#loginBtn'); pg.wait_for_selector('#app:not(.hidden)'); pg.wait_for_timeout(2500)
    for v, exp in CASES:
        got = pg.evaluate("v=>roundInt(parseKgA(v))", v)
        ck(f'στρογγύλευση «{v}» → {got}', (exp is None and got <= 0) or got == exp, str(got))
    L = pg.evaluate("api('/sorting/available').then(r=>r.find(x=>x.status!=='SUBMITTED'&&Number(x.net_weight)>0)||r[0])")
    lid = L['load_id']
    cats = pg.evaluate("cats.filter(c=>c.active!==false&&!c.is_internal_subcategory).slice(0,14).map(c=>c.id)")
    pg.evaluate("document.querySelector('#loadList [data-id=\"%s\"]').click()" % lid); pg.wait_for_timeout(2500)
    saved = []
    for i, (v, exp) in enumerate(CASES):
        pg.evaluate("c=>choose(c)", cats[i]); pg.wait_for_timeout(600); pg.evaluate("document.getElementById('noMedium').onclick()"); pg.wait_for_timeout(300)
        pg.fill('#weight', v); pg.wait_for_timeout(100)
        m = pg.inner_text('#wRound')
        r = pg.evaluate("v=>roundInt(parseKgA(v))", v)
        if exp is not None and r != float(v.replace(',', '.')):
            ck(f'«{v}»: μήνυμα πριν την Αποθήκευση', m == f'Θα καταχωρηθεί {exp} kg (στρογγύλευση στο ακέραιο)', m)
        elif exp is not None:
            ck(f'«{v}»: χωρίς μήνυμα', m == '', m)
        pg.evaluate("document.getElementById('save').click()"); pg.wait_for_timeout(1300)
        if exp is None:
            ck(f'«{v}»: δεν γίνεται δεκτό (μήνυμα σφάλματος)', pg.inner_text('#entryMsg').strip() != '' and not pg.evaluate("document.getElementById('entry').classList.contains('hidden')")==True or pg.inner_text('#entryMsg').strip() != '')
            pg.evaluate("document.getElementById('cancel').click()")
        else:
            saved.append((v, exp, cats[i]))
    ents = pg.evaluate("id=>api('/sorting/'+id).then(s=>s.entries.map(e=>[e.weee_category_id,Number(e.raw_weight)]))", lid)
    for v, exp, cid in saved:
        got = [w for c, w in ents if c == cid]
        ck(f'αποθηκεύτηκε «{v}» ως {exp}', got == [exp], str(got))
    ck('όλα τα αποθηκευμένα βάρη των νέων καταχωρήσεων είναι ακέραια', all(float(w).is_integer() for _, w in ents))
    txt = pg.inner_text('#entries')
    ck('λίστα: μόνο ακέραια («238 kg», «237 kg», «1 kg»)', '238 kg' in txt and '237 kg' in txt and '1 kg' in txt and not re.search(r'\d,\d+ kg', txt))
    meta = pg.inner_text('#meta'); print(meta.replace('\n', ' '))
    ck('μπάρα προόδου: μόνο ακέραια', not re.search(r'\d,\d', meta) and 'ταξινομήθηκαν' in meta)
    pg.evaluate("document.querySelector('#entries .enItem').click()"); pg.wait_for_timeout(300); pg.evaluate("document.querySelector('.shEdit').click()"); pg.wait_for_timeout(700)
    ev = pg.input_value('#weight'); print('επεξεργασία:', ev)
    ck('επεξεργασία: ακέραιο στο πεδίο', re.fullmatch(r'\d+', ev) is not None)
    tot = pg.evaluate("id=>api('/sorting/'+id).then(s=>Number(s.sorting_weight))", lid)
    ck('σύνολο = άθροισμα ακεραίων', abs(tot - sum(w for _, w in ents)) < 1e-6 and float(tot).is_integer(), str(tot))
    ck('σφάλματα σελίδας', not errs, str(errs))
    b.close()
print('ΑΠΟΤΥΧΙΕΣ:', bad)
sys.exit(1 if bad else 0)
