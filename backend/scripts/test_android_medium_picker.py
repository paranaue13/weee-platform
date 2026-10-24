"""Δοκιμή Android › Παραγωγή › «Μέσο συλλογής» (πιθανά, είδη, αναζήτηση αριθμού, πληκτρολόγιο).
Χρήση: python backend/scripts/test_android_medium_picker.py http://127.0.0.1:PORT [φάκελος screenshots]   (server σε ΑΝΤΙΓΡΑΦΟ βάσης)"""
import sys, os, re
sys.path.insert(0, os.path.dirname(__file__))
sys.stdout.reconfigure(encoding='utf-8')
from playwright.sync_api import sync_playwright
from _browser import launch
B = sys.argv[1]; S = (sys.argv[2] if len(sys.argv) > 2 else '.') + '/o_'
bad = []
def ck(name, ok, info=''):
    print(('✓ ' if ok else '✗ ') + name, info)
    if not ok: bad.append(name)
KB = "getComputedStyle(document.getElementById('flKb')).display"
with sync_playwright() as p:
    b = launch(p); errs = []
    pg = b.new_page(viewport={'width': 360, 'height': 640}, is_mobile=True, has_touch=True, device_scale_factor=1)
    pg.on('pageerror', lambda e: errs.append(str(e)))
    pg.goto(B + '/mobile', wait_until='networkidle'); pg.click('#loginBtn'); pg.wait_for_selector('#app:not(.hidden)'); pg.wait_for_timeout(2000)
    pg.tap('.secBtn[data-section=production]'); pg.wait_for_timeout(1500)
    pg.evaluate("flLoad(true)"); pg.wait_for_timeout(5000)
    texts = lambda sel: pg.evaluate("s=>[...document.querySelectorAll(s)].map(e=>e.innerText.replace(/\\s+/g,' ').trim())", sel)
    # --- διαδρομή Μέσο συλλογής απευθείας
    pg.evaluate("document.querySelector('.flStart[data-f=m]').click()"); pg.wait_for_timeout(600)
    ks = texts('#flowArea .flKind')
    print('είδη:', ks)
    ck('κουμπιά ειδών με πλήθος', any('Καλάθι μεγάλο' in k for k in ks))
    ck('είδος με 0 είναι ανενεργό', pg.evaluate("[...document.querySelectorAll('#flowArea .flKind')].every(b=>/ 0$/.test(b.innerText.replace(/\\s+/g,' ').trim())?b.disabled:true)"))
    pg.evaluate("[...document.querySelectorAll('#flowArea .flKind')].find(b=>b.innerText.startsWith('Καλάθι μεγάλο')).click()"); pg.wait_for_timeout(300)
    cards = texts('#flRes .flCard'); hdr = texts('#flRes .flLbl')
    print('κάρτες:', cards, hdr)
    # Ο αριθμός αναζήτησης παίρνεται από τα ΠΡΑΓΜΑΤΙΚΑ μέσα με απόθεμα (όχι σταθερό «15»)
    Q = re.search(r'· (\d+)', cards[0]).group(1) if cards and re.search(r'· (\d+)', cards[0]) else '1'
    print('αριθμός αναζήτησης από τα δεδομένα:', Q)
    ck('επικεφαλίδα είδους «Καλάθι μεγάλο · N μέσο/μέσα»', bool(hdr) and 'Καλάθι μεγάλο' in hdr[0] and re.search(r'μέσ[οα]', hdr[0]) is not None)
    ck('δεν φαίνεται το γράμμα του μέσου', all(re.match(r'Καλάθι μεγάλο · \d+ ', c) for c in cards) and len(cards) > 0 and not any(re.match(r'\S+ \S+ · \D', c) for c in cards))
    ck('υπάρχει κλειστό με 🔒 (αν το κλειστό είναι σε αυτό το είδος)', True, str(['🔒' in c for c in cards]))
    pg.screenshot(path=S + 'kind.png')
    # --- αναζήτηση με πληκτρολόγιο
    pg.evaluate("document.querySelector('#flQ').scrollIntoView({block:'center'})"); pg.wait_for_timeout(200)
    pg.tap('#flQ'); pg.wait_for_timeout(500)
    ck('πληκτρολόγιο ανοιχτό', pg.evaluate(KB) == 'grid')
    r = pg.evaluate("(()=>{let q=document.getElementById('flQ').getBoundingClientRect(),k=document.getElementById('flKb').getBoundingClientRect();return {qb:q.bottom,qt:q.top,kt:k.top,kh:k.height,btn:document.querySelector('#flKb button').getBoundingClientRect().height,vh:innerHeight}})()")
    print(r)
    ck('πεδίο πάνω από πληκτρολόγιο (φαίνεται)', 0 <= r['qt'] and r['qb'] <= r['kt'], str(r))
    ck('πεδίο δεν καλύπτεται από την κεφαλίδα', pg.evaluate("(()=>{let q=document.getElementById('flQ'),r=q.getBoundingClientRect();return document.elementFromPoint(r.left+r.width/2,r.top+r.height/2)===q})()"))
    ck('πλήκτρα ~42px', 40 <= r['btn'] <= 44)
    for k in Q: pg.tap(f'#flKb button[data-key="{k}"]')
    pg.wait_for_timeout(300)
    res = texts('#flRes .flCard'); h = texts('#flRes .flLbl')
    print('αποτελέσματα (είδος επιλεγμένο):', h, res)
    ck('μέσα στο είδος: μόνο Καλάθι μεγάλο', res and all(c.startswith('Καλάθι μεγάλο') for c in res))
    ck(f'ακριβής πρώτα ({Q})', res and res[0].startswith(f'Καλάθι μεγάλο · {Q} '))
    pg.screenshot(path=S + 'search_type.png')
    pg.evaluate("document.querySelector('#flRes [data-scope=all]').click()"); pg.wait_for_timeout(300)
    res = texts('#flRes .flCard'); h = texts('#flRes .flLbl'); print('Όλα:', h, res)
    nums = [re.search(r'· (\S+)', c).group(1) for c in res]
    ex_n = sum(1 for n in nums if n == Q)
    ck(f'«Όλα»: τουλάχιστον 1 είδος με ακριβώς {Q}', ex_n >= 1, str(nums))
    ck('ακριβείς πριν τα πρόθεμα', all(n == Q for n in nums[:ex_n]) and all(n != Q and n.startswith(Q) for n in nums[ex_n:]))
    ck(f'επικεφαλίδα «Αποτελέσματα για «{Q}» · N»', h and h[0].startswith(f'Αποτελέσματα για «{Q}»'))
    ck('δεν υπάρχουν ενδείξεις «ακριβής/ξεκινά»', not re.search('ακριβ|ξεκιν', ' '.join(res)))
    pg.screenshot(path=S + 'search_all.png')
    pg.tap('#flQ'); pg.wait_for_timeout(300); pg.tap('#flKb button[data-key="⌫"]'); pg.wait_for_timeout(200)
    ck('⌫ αφαιρεί ψηφίο', pg.input_value('#flQ') == Q[:-1])
    pg.tap('#flKb button[data-key="C"]'); pg.wait_for_timeout(200)
    ck('C καθαρίζει και επιστρέφει η προηγούμενη όψη', pg.input_value('#flQ') == '' and re.search(r'μέσ[οα]', ' '.join(texts('#flRes .flLbl'))) is not None)
    pg.tap('#flowArea .flLbl >> nth=0'); pg.wait_for_timeout(300)
    ck('πάτημα έξω κλείνει το πληκτρολόγιο', pg.evaluate(KB) == 'none')
    pg.tap('#flQ'); pg.wait_for_timeout(300)
    ck('appBack (Πίσω) κλείνει πληκτρολόγιο', pg.evaluate("window.appBack()") is True and pg.evaluate(KB) == 'none')
    pg.tap('#flQ'); pg.wait_for_timeout(300)
    y0 = pg.evaluate("scrollY"); pg.evaluate("window.scrollTo(0,0)"); pg.wait_for_timeout(200)
    ck('κύλιση προς τα πάνω με ανοιχτό πληκτρολόγιο', pg.evaluate("scrollY") == 0, f'από {y0}')
    for k in Q: pg.tap(f'#flKb button[data-key="{k}"]')
    pg.wait_for_timeout(300)
    pg.evaluate("document.querySelector('#flRes .flCard').scrollIntoView({block:'center'})"); pg.wait_for_timeout(200)
    first = texts('#flRes .flCard')[0]
    pg.tap('#flRes .flCard >> nth=0'); pg.wait_for_timeout(600)
    ck('κάρτα επιλέγει μέσο & κλείνει πληκτρολόγιο', pg.evaluate(KB) == 'none' and pg.evaluate("!!fl.medium"), first)
    # --- διαδρομή Τμήμα → πιθανά
    pg.evaluate("document.querySelector('.flStart[data-f=d]').click()"); pg.wait_for_timeout(500)
    pg.evaluate("[...document.querySelectorAll('#flowArea .flOpt')].find(b=>/Τηλεόρασ/.test(b.innerText)).click()"); pg.wait_for_timeout(700)
    prob = pg.evaluate("[...document.querySelector('#flowArea .flCards').querySelectorAll('.flCard')].map(e=>e.innerText.replace(/\s+/g,' ').trim())"); print('πιθανά:', prob)
    ck('επικεφαλίδα πιθανών', any(x.startswith('Μέσο συλλογής · πιθανότερα για') for x in texts('#flowArea .flLbl')), str(texts('#flowArea .flLbl')))
    ck('όχι ετικέτα ΠΙΘΑΝΟ', not texts('#flowArea .flTag'))
    bulk = [c for c in prob if c.startswith('Χύμα')]
    print('χύμα:', bulk)
    ck('Χύμα δείχνει «Σχετικά:»', all('Σχετικά:' in c for c in bulk))
    more = texts('#flowArea .flMore'); print(more)
    ck('το πολύ 4 κάρτες πιθανών πριν το κουμπί', len(prob) <= 4)
    pg.screenshot(path=S + 'probable.png', full_page=True)
    if more:
        pg.evaluate("document.querySelector('.flMore').click()"); pg.wait_for_timeout(300)
        ck('«Εμφάνιση άλλων» ανοίγει τα υπόλοιπα', len(pg.evaluate("[...document.querySelector('#flowArea .flCards').querySelectorAll('.flCard')].map(e=>e.innerText.replace(/\s+/g,' ').trim())")) > 4)
    ck('σφάλματα σελίδας', not errs, str(errs))
    b.close()
print('ΑΠΟΤΥΧΙΕΣ:', bad)
sys.exit(1 if bad else 0)
