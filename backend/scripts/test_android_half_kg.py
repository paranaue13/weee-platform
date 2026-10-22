"""Δοκιμή Android › καταχώρηση ταξινόμησης: δεκαδικά (κόμμα/τελεία), στρογγυλοποίηση ΠΡΟΣ ΤΑ ΠΑΝΩ στο μισό κιλό, εμφάνιση χωρίς περιττά μηδενικά.
Χρήση: python backend/scripts/test_android_half_kg.py http://127.0.0.1:PORT   (server σε ΑΝΤΙΓΡΑΦΟ βάσης: γράφει καταχωρήσεις!)"""
import sys, os
sys.path.insert(0, os.path.dirname(__file__))
sys.stdout.reconfigure(encoding='utf-8')
from playwright.sync_api import sync_playwright
from _browser import launch
B = sys.argv[1]
bad = []
def ck(name, ok, info=''):
    print(('✓ ' if ok else '✗ ') + name, info)
    if not ok: bad.append(name)
# (είσοδος, αναμενόμενη αποθηκευμένη τιμή, αναμένεται μήνυμα στρογγυλοποίησης)
CASES = [('0', 0, False), ('0,1', 0.5, True), ('0,5', 0.5, False), ('237', 237, False), ('237,1', 237.5, True), ('237,3', 237.5, True),
         ('237,5', 237.5, False), ('237,6', 238, True), ('237.5', 237.5, False), ('238', 238, False)]
with sync_playwright() as p:
    b = launch(p); errs = []
    pg = b.new_page(viewport={'width': 360, 'height': 640}, is_mobile=True, has_touch=True, device_scale_factor=1)
    pg.on('pageerror', lambda e: errs.append(str(e)))
    pg.goto(B + '/mobile', wait_until='networkidle'); pg.click('#loginBtn'); pg.wait_for_selector('#app:not(.hidden)'); pg.wait_for_timeout(2500)
    # 1) καθαρή συνάρτηση (όλες οι τιμές του αιτήματος)
    for v, exp, _ in CASES:
        got = pg.evaluate("v=>{let x=parseKgA(v);return ceilHalf(x)}", v)
        ck(f'στρογγυλοποίηση «{v}» → {exp}', got == exp, str(got))
    ck('άκυρη τιμή «abc» απορρίπτεται', pg.evaluate("Number.isNaN(parseKgA('abc'))"))
    ck('πεδίο: αριθμητικό πληκτρολόγιο με κόμμα (inputmode=decimal)', pg.evaluate("$('weight').getAttribute('inputmode')")=='decimal' and pg.evaluate("$('weight').type")=='text')
    # 2) μέσω της φόρμας: μήνυμα, εμφάνιση με κόμμα, αποθήκευση, λίστα
    L = pg.evaluate("api('/sorting/available').then(r=>r.find(x=>x.status!=='SUBMITTED'&&Number(x.net_weight)>0)||r[0])")
    lid = L['load_id']
    cats = pg.evaluate("cats.filter(c=>c.active!==false&&!c.is_internal_subcategory).slice(0,12).map(c=>c.id)")
    pg.evaluate("document.querySelector('#loadList [data-id=\"%s\"]').click()" % lid); pg.wait_for_timeout(2500)
    saved = []
    for i, (v, exp, msg) in enumerate(CASES):
        if exp == 0:   # το 0 δεν αποθηκεύεται (ζητά βάρος)· ελέγχεται μόνο το μήνυμα
            pg.evaluate("c=>choose(c)", cats[i]); pg.wait_for_timeout(600); pg.evaluate("document.getElementById('noMedium').onclick()"); pg.wait_for_timeout(400)
            pg.fill('#weight', v); pg.evaluate("document.getElementById('weight').blur()")
            ck('0: χωρίς μήνυμα στρογγυλοποίησης', pg.inner_text('#wRound') == '')
            pg.evaluate("document.getElementById('cancel').click()"); continue
        pg.evaluate("c=>choose(c)", cats[i]); pg.wait_for_timeout(600); pg.evaluate("document.getElementById('noMedium').onclick()"); pg.wait_for_timeout(400)
        pg.fill('#weight', v); pg.wait_for_timeout(100)
        m = pg.inner_text('#wRound')
        if msg:
            exp_txt = 'Θα καταχωρηθεί ' + str(exp).replace('.', ',').replace(',0', '') + ' kg (στρογγυλοποίηση προς τα πάνω στο μισό κιλό)'
            ck(f'«{v}»: μήνυμα πριν την Αποθήκευση', m == exp_txt, m)
        else:
            ck(f'«{v}»: χωρίς μήνυμα', m == '', m)
        pg.evaluate("document.getElementById('weight').blur()")
        shown = pg.input_value('#weight')
        ck(f'«{v}»: το πεδίο δείχνει κόμμα', ',' in shown or '.' not in shown, shown)
        pg.evaluate("document.getElementById('save').click()"); pg.wait_for_timeout(1500)
        saved.append((v, exp, cats[i]))
    ents = pg.evaluate("id=>api('/sorting/'+id).then(s=>s.entries.map(e=>[e.weee_category_id,Number(e.raw_weight)]))", lid)
    for v, exp, cid in saved:
        got = [w for c, w in ents if c == cid]
        ck(f'αποθηκεύτηκε «{v}» ως {exp}', got == [exp], str(got))
    txt = pg.inner_text('#entries')
    ck('λίστα: «237,5 kg», «0,5 kg», «238 kg» χωρίς .000', '237,5 kg' in txt and '0,5 kg' in txt and '238 kg' in txt and '.000' not in txt and ',000' not in txt)
    meta = pg.inner_text('#meta'); print(meta.replace('\n', ' '))
    ck('μπάρα προόδου: χωρίς .000 και με κόμμα', '.000' not in meta and ',000' not in meta and 'ταξινομήθηκαν' in meta)
    # επεξεργασία: το πεδίο δείχνει «237,5» (όχι 237.500)
    pg.evaluate("document.querySelector('#entries .enItem').click()"); pg.wait_for_timeout(300); pg.evaluate("document.querySelector('.shEdit').click()"); pg.wait_for_timeout(700)
    ev = pg.input_value('#weight'); print('επεξεργασία:', ev)
    ck('επεξεργασία: χωρίς περιττά μηδενικά', ev in ('238', '237,5', '237') and '.' not in ev)
    # τιμές στη βάση ΔΕΝ αλλάζουν από την εμφάνιση: σύνολο API = άθροισμα αποθηκευμένων
    tot = pg.evaluate("id=>api('/sorting/'+id).then(s=>Number(s.sorting_weight))", lid)
    ck('σύνολο στο API ίσο με το άθροισμα των αποθηκευμένων', abs(tot - sum(e[1] for e in ents)) < 1e-6, str(tot))
    ck('σφάλματα σελίδας', not errs, str(errs))
    b.close()
print('ΑΠΟΤΥΧΙΕΣ:', bad)
sys.exit(1 if bad else 0)
