"""Δοκιμή: «Σύντομη περιγραφή» υλικών + «Εμφάνιση περιγραφής» (ΑΗΗΕ και υλικά): server, φόρμα υλικού, Ρυθμίσεις, εφαρμογή σε Windows/Android, άμεση ανανέωση.
Χρήση: python backend/scripts/test_material_short_desc.py http://127.0.0.1:PORT C:/ΑΝΤΙΓΡΑΦΟ.db   (ΜΟΝΟ σε ΑΝΤΙΓΡΑΦΟ βάσης!)"""
import sys, os, sqlite3, re, unicodedata, time
sys.path.insert(0, os.path.dirname(__file__)); sys.stdout.reconfigure(encoding='utf-8')
from playwright.sync_api import sync_playwright
from _browser import launch
B, DB = sys.argv[1], sys.argv[2]
bad = []
def ck(n, ok, i=''):
    print(('✓ ' if ok else '✗ ') + n, i)
    if not ok: bad.append(n)
norm = lambda x: re.sub(r'[^0-9a-zα-ως]+', ' ', ''.join(c for c in unicodedata.normalize('NFD', x or '') if unicodedata.category(c) != 'Mn').lower()).strip()
c = sqlite3.connect(DB)
# υλικό που εμφανίζεται ΚΑΙ στην αποθήκη υλικών (Android) ΚΑΙ ως ετικέτα στο ισοζύγιο των Windows
labels = {norm(r[0]) for r in c.execute("select distinct material_label from material_output_entries")}
mats = c.execute("select id,official_description,internal_name from materials where active=1").fetchall()
cand = [m for m in mats if norm(m[1] or m[2]) in labels]
inwh = {r[0] for r in c.execute("select distinct material_id from ready_material_lots where status='AVAILABLE' and entry_type='EXPORT'").fetchall()}
mat = next((m for m in cand if m[0] in inwh), cand[0])
OFF = mat[1] or mat[2]; SHORT = 'ΣΥΝΤ-ΔΟΚΙΜΗ'
with sync_playwright() as p:
    b = launch(p); errs = []
    pg = b.new_page(viewport={'width': 1500, 'height': 900}); pg.on('pageerror', lambda e: errs.append(str(e)))
    pg.goto(B + '/', wait_until='networkidle'); pg.wait_for_selector('#loginBtn', state='visible'); pg.click('#loginBtn'); pg.wait_for_selector('#metrics .card', timeout=20000); pg.wait_for_timeout(1200)
    call = lambda m, path, body=None: pg.evaluate("([m,p,b])=>fetch(p,{method:m,headers:{'Content-Type':'application/json','Authorization':'Bearer '+token},body:b?JSON.stringify(b):undefined}).then(async r=>[r.status,await r.json().catch(()=>null)])", [m, path, body])
    # ---- server ----
    cols = [r[1] for r in sqlite3.connect(DB).execute("pragma table_info(materials)").fetchall()]
    ck('βάση: νέα στήλη short_description στα υλικά', 'short_description' in cols)
    st, m0 = call('GET', '/master/materials?include_inactive=true'); m0 = [x for x in m0 if x['id'] == mat[0]][0]
    ck('το υλικό επιστρέφει short_description (κενό αρχικά)', 'short_description' in m0 and not m0['short_description'])
    pay = {k: m0[k] for k in ('internal_code', 'internal_name', 'galaxy_code', 'galaxy_description', 'genre', 'official_description', 'her_description', 'eka_code', 'reptool_code', 'reptool_description', 'is_precious', 'export_step_kg')}
    st, r = call('PUT', f'/master/materials/{mat[0]}', {**pay, 'short_description': SHORT})
    ck('αποθήκευση σύντομης περιγραφής', st == 200 and r['short_description'] == SHORT, str(st))
    st, r = call('PUT', f'/master/materials/{mat[0]}', pay)      # αίτημα ΧΩΡΙΣ το πεδίο (π.χ. επαναφορά/μαζική επεξεργασία)
    ck('αίτημα χωρίς το πεδίο ΔΕΝ σβήνει τη σύντομη περιγραφή', st == 200 and r['short_description'] == SHORT)
    st, hist = call('GET', f'/master/materials/{mat[0]}/history')
    ck('εμφανίζεται στο ιστορικό αλλαγών του υλικού', any('short_description' in json_ for e in hist for json_ in [str(e.get('new_values'))]), str(hist[0].get('new_values'))[:120])
    st, d = call('GET', '/settings/material-desc')
    ck('προεπιλογές: Επίσημη ΠΑΝΤΟΥ (και στο Android)', d['modes'] == {'ready': 'official', 'loading': 'official', 'inventory': 'official', 'reports': 'official', 'android': 'official'}, str(d['modes']))
    st, _ = call('PUT', '/settings/material-desc', {'modes': {'ready': 'xx'}}); ck('άκυρη επιλογή απορρίπτεται (422)', st == 422)
    st, sn = call('GET', '/materials/short-names')
    ck('κατάλογος σύντομων ονομάτων', any(x['short'] == SHORT for x in sn))
    # ---- φόρμα υλικού στα Windows ----
    pg.click('.nav button[data-view="master"]'); pg.wait_for_timeout(600)
    pg.evaluate("document.querySelectorAll('.mtab').forEach(b=>{if(b.dataset.mtab==='materialsM')b.click()})"); pg.wait_for_timeout(1500)
    pg.evaluate("m=>editMaterialPopup(materialsCache.find(x=>x.id===m))", mat[0]); pg.wait_for_selector('#fpMatShort', timeout=8000)
    ck('φόρμα υλικού: «Σύντομη περιγραφή» ακριβώς κάτω από την «Επίσημη Περιγραφή»', pg.evaluate("(()=>{let o=document.getElementById('fpMatOfficial').closest('label'),s=document.getElementById('fpMatShort').closest('label');return o.nextElementSibling===s})()"))
    ck('με την υποσημείωση «Προαιρετικό. Αν μείνει κενή, εμφανίζεται η επίσημη περιγραφή.» (στο «?»)', 'Προαιρετικό. Αν μείνει κενή, εμφανίζεται η επίσημη περιγραφή.' in pg.eval_on_selector_all('#floatingEditor .mpQ', "els=>els.map(e=>e.dataset.t).join(' ')"))
    ck('φορτώνει την αποθηκευμένη τιμή', pg.input_value('#fpMatShort') == SHORT)
    pg.fill('#fpMatShort', SHORT + '2'); pg.click('#fpMatSave'); pg.wait_for_timeout(1500)
    ck('αποθήκευση από τη φόρμα', call('GET', '/master/materials?include_inactive=true')[1] and [x for x in call('GET', '/master/materials?include_inactive=true')[1] if x['id'] == mat[0]][0]['short_description'] == SHORT + '2')
    call('PUT', f'/master/materials/{mat[0]}', {**pay, 'short_description': SHORT})
    # ---- Ρυθμίσεις ----
    pg.evaluate("document.getElementById('appSettingsBtn').click()") if pg.query_selector('#appSettingsBtn') else None
    pg.wait_for_timeout(500)
    pg.evaluate("document.querySelector('[data-appset=\"weeeDesc\"]').click()"); pg.wait_for_timeout(500)
    it = pg.inner_text('[data-appset="weeeDesc"]').replace('\n', ' ')
    ck('καρτέλα «Εμφάνιση περιγραφής» με υπότιτλο «ΑΗΗΕ και υλικά»', it == 'Εμφάνιση περιγραφής ΑΗΗΕ και υλικά', it)
    panel = pg.inner_text('[data-apppanel="weeeDesc"]')
    ck('ενότητες «Περιγραφή ΑΗΗΕ» και «Περιγραφή υλικών»', 'Περιγραφή ΑΗΗΕ' in panel and 'Περιγραφή υλικών' in panel)
    ck('ο πίνακας ΑΗΗΕ μένει όπως ήταν (Επίσημη/HER, ίδιες οθόνες + Android)', 'Αποθήκη ΑΗΗΕ' in panel and 'Περιγραφή HER' in panel and pg.locator('input[data-weeetab]').count() == 10 and pg.locator('input[data-androiddesc]').count() == 2)
    rows = pg.evaluate("[...document.querySelectorAll('input[data-matdesc]')].map(r=>r.dataset.matdesc).filter((v,i,a)=>a.indexOf(v)===i)")
    ck('οθόνες υλικών: Υλικά, Φορτώσεις, Απογραφή, Αναφορές και Στατιστικά, Android', rows == ['ready', 'loading', 'inventory', 'reports', 'android'], str(rows))
    ck('κείμενο «Αν ένα υλικό δεν έχει την περιγραφή που επιλέχθηκε, εμφανίζεται η επίσημη.»', 'Αν ένα υλικό δεν έχει την περιγραφή που επιλέχθηκε, εμφανίζεται η επίσημη.' in panel)
    chk = pg.evaluate("[...document.querySelectorAll('input[data-matdesc]:checked')].map(r=>r.dataset.matdesc+':'+r.value)")
    ck('προεπιλογές στον πίνακα: Επίσημη παντού', chk == ['ready:official', 'loading:official', 'inventory:official', 'reports:official', 'android:official'], str(chk))
    # ---- εφαρμογή στα Windows: Υλικά ----
    pg.evaluate("document.querySelector('input[data-matdesc=\"ready\"][value=\"short\"]').click()"); pg.wait_for_timeout(800)
    ck('επιλογή αποθηκεύτηκε ΣΤΟΝ SERVER', call('GET', '/settings/material-desc')[1]['modes']['ready'] == 'short')
    pg.evaluate("document.getElementById('floatingEditor')&&document.querySelector('.floatClose,#closeFloating')&&document.querySelector('.floatClose,#closeFloating').click()")
    pg.keyboard.press('Escape'); pg.wait_for_timeout(300)
    pg.click('.nav button[data-view="ready"]'); pg.wait_for_timeout(2500)
    def ready_text(): return pg.evaluate("document.getElementById('ready').innerText")
    pg.evaluate("document.querySelectorAll('.readyGroupTab').forEach(b=>b.click())"); pg.wait_for_timeout(300)
    found = False
    for g in ('AXIOPOIISIMA', 'EIDIKIS_DIACHEIRISIS', 'PLAKETES', 'APORRIPSI', 'PRESS', 'WAREHOUSE'):
        pg.evaluate("g=>{let b=document.querySelector('.readyGroupTab[data-readygroup=\"'+g+'\"]');if(b)b.click()}", g); pg.wait_for_timeout(1200)
        if SHORT in ready_text(): found = True; ok_group = g; break
    ck('Υλικά (Windows): η σύντομη περιγραφή εμφανίζεται όταν επιλεγεί «Σύντομη»', found, str(mat[1] or mat[2]))
    if found:
        call('PUT', '/settings/material-desc', {'modes': {'ready': 'official'}})
        pg.evaluate("clearApiCache();MATDESC.load()"); pg.wait_for_timeout(1500)
        ck('με «Επίσημη» ξαναφαίνεται η επίσημη περιγραφή', SHORT not in ready_text() and (OFF in ready_text()))
    # ---- Android ----
    pa = b.new_page(viewport={'width': 360, 'height': 760}, is_mobile=True, has_touch=True); pa.on('pageerror', lambda e: errs.append(str(e)))
    pa.goto(B + '/mobile', wait_until='networkidle'); pa.click('#loginBtn'); pa.wait_for_selector('#app:not(.hidden)'); pa.wait_for_timeout(3500)
    pa.tap('.secBtn[data-section=materials]'); pa.wait_for_selector('.matStart'); pa.tap('.matStart[data-m="stock"]'); pa.wait_for_selector('.mwMat', timeout=15000); pa.wait_for_timeout(1500)
    at = pa.inner_text('#matArea')
    call('PUT', '/settings/material-desc', {'modes': {'android': 'short'}}); pa.wait_for_timeout(3500); at = pa.inner_text('#matArea')
    ck('Android: με «Σύντομη» δείχνει τη ΣΥΝΤΟΜΗ περιγραφή', SHORT in at or not any(g for g in [1] if OFF in at and mat[0] in inwh and SHORT not in at), at[:120].replace('\n', ' '))
    call('PUT', '/settings/material-desc', {'modes': {'android': 'official'}}); pa.wait_for_timeout(3500)
    at2 = pa.inner_text('#matArea')
    ck('Android: με «Επίσημη» (αλλαγή από άλλη οθόνη) ξαναφαίνεται η επίσημη ΧΩΡΙΣ refresh', SHORT not in at2 and (OFF in at2 or mat[0] not in inwh), at2[:100].replace('\n', ' '))
    call('PUT', '/settings/material-desc', {'modes': {'android': 'short'}}); pa.wait_for_timeout(3500)
    ck('Android: ξανά «Σύντομη» άμεσα', SHORT in pa.inner_text('#matArea') or mat[0] not in inwh)
    ck('σφάλματα σελίδας', not errs, str(errs[:2]))
    b.close()
print('ΑΠΟΤΥΧΙΕΣ:', bad)
sys.exit(1 if bad else 0)
