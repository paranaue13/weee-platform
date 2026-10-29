"""Δοκιμή «Περιγραφή υλικών»: τρίτη επιλογή «Περιγραφή HER» (Ρυθμίσεις Windows + εφαρμογή σε Windows και Android), προεπιλογή Επίσημη παντού, υποχώρηση στην επίσημη όταν λείπει η περιγραφή.
Χρήση: python backend/scripts/test_material_her.py http://127.0.0.1:PORT   (ΜΟΝΟ σε ΑΝΤΙΓΡΑΦΟ βάσης!)"""
import sys, os, time
sys.path.insert(0, os.path.dirname(__file__)); sys.stdout.reconfigure(encoding='utf-8')
from playwright.sync_api import sync_playwright
from _browser import launch
B = sys.argv[1]
bad = []
def ck(n, ok, i=''):
    print(('✓ ' if ok else '✗ ') + n, i)
    if not ok: bad.append(n)
with sync_playwright() as p:
    b = launch(p); errs = []
    pw = b.new_page(viewport={'width': 1600, 'height': 900}); pw.on('pageerror', lambda e: errs.append(str(e)))
    pw.goto(B + '/', wait_until='networkidle'); pw.click('#loginBtn'); pw.wait_for_selector('#metrics .card', timeout=20000)
    call = lambda m, path, body=None: pw.evaluate("""async([m,p,b])=>{let r=await fetch(p,{method:m,headers:{'Content-Type':'application/json',Authorization:'Bearer '+token},body:b?JSON.stringify(b):undefined});return [r.status,await r.json().catch(()=>null)]}""", [m, path, body])
    tag = str(int(time.time()))[-6:]
    OFF1, SH1, HE1 = 'ΔΟΚΙΜΗ ΕΠΙΣΗΜΗ ' + tag, 'ΣΥΝΤΟΜΗ ' + tag, 'ΠΕΡΙΓΡΑΦΗ HER ' + tag
    OFF2 = 'ΔΟΚΙΜΗ ΧΩΡΙΣ HER ' + tag
    mk = lambda n, erp, name, sh, her, comm: pw.evaluate("""async([n,erp,name,sh,her,comm])=>{let r=await api('/master/materials',{method:'POST',body:JSON.stringify({internal_code:'TH-'+n,internal_name:name,galaxy_code:erp,galaxy_description:name,official_description:name,her_description:her,short_description:sh,is_commercial:comm,is_precious:false,export_step_kg:0.5})});return r.id}""", [n, erp, name, sh, her, comm])
    m1 = mk(tag + 'a', 'THA' + tag, OFF1, SH1, HE1, True)
    m2 = mk(tag + 'b', 'THB' + tag, OFF2, None, None, True)
    call('POST', '/mat/export', {'material_id': m1, 'form': 'BULK', 'net': 40}); call('POST', '/mat/export', {'material_id': m2, 'form': 'BULK', 'net': 30})
    sn = call('GET', '/materials/short-names')[1]
    x1 = next(x for x in sn if x['id'] == m1)
    ck('κατάλογος: το υλικό έχει και σύντομη και HER', x1['short'] == SH1 and x1['her'] == HE1, str(x1))
    ck('κατάλογος: το υλικό ΧΩΡΙΣ σύντομη/HER δεν υπάρχει', not any(x['id'] == m2 for x in sn))
    ck('προεπιλογές: Επίσημη ΠΑΝΤΟΥ', call('GET', '/settings/material-desc')[1]['modes'] == {'ready': 'official', 'loading': 'official', 'inventory': 'official', 'reports': 'official', 'android': 'official'})
    st, e = call('PUT', '/settings/material-desc', {'modes': {'ready': 'xx'}}); ck('άκυρη τιμή απορρίπτεται', st == 422)
    # ---- Ρυθμίσεις (Windows) ----
    pw.evaluate("document.getElementById('appSettingsBtn')&&document.getElementById('appSettingsBtn').click()"); pw.wait_for_timeout(600)
    pw.evaluate("document.querySelector('[data-appset=\"weeeDesc\"]').click()"); pw.wait_for_timeout(500)
    th = pw.evaluate("(()=>{let t=[...document.querySelectorAll('[data-apppanel=weeeDesc] table')].pop();return [...t.querySelectorAll('thead th')].map(x=>x.innerText.trim())})()")
    ck('πίνακας «Περιγραφή υλικών»: Οθόνη | Επίσημη | Σύντομη | Περιγραφή HER', th == ['Οθόνη', 'Επίσημη περιγραφή', 'Σύντομη περιγραφή', 'Περιγραφή HER'], str(th))
    rows = pw.evaluate("[...new Set([...document.querySelectorAll('input[data-matdesc]')].map(r=>r.dataset.matdesc))]")
    ck('οι γραμμές μένουν (Υλικά, Φορτώσεις, Απογραφή, Αναφορές και Στατιστικά, Android)', rows == ['ready', 'loading', 'inventory', 'reports', 'android'], str(rows))
    ck('πρόσθετη επεξήγηση: «Αν ένα υλικό δεν έχει την περιγραφή που επιλέχθηκε, εμφανίζεται η επίσημη.»', 'Αν ένα υλικό δεν έχει την περιγραφή που επιλέχθηκε, εμφανίζεται η επίσημη.' in pw.inner_text('[data-apppanel=weeeDesc]'))
    ck('προεπιλογή στον πίνακα: Επίσημη σε όλες', pw.evaluate("[...document.querySelectorAll('input[data-matdesc]:checked')].map(r=>r.value)") == ['official'] * 5)
    pw.evaluate("document.querySelector('input[data-matdesc=\"ready\"][value=\"her\"]').click()"); pw.wait_for_timeout(900)
    ck('η επιλογή HER αποθηκεύτηκε στον server', call('GET', '/settings/material-desc')[1]['modes']['ready'] == 'her')
    pw.evaluate("document.getElementById('floatingEditor').classList.add('hidden')")
    # ---- Windows: καρτέλα Υλικά ----
    pw.click('.nav button[data-view="ready"]'); pw.wait_for_timeout(800); pw.click('.readyGroupTab[data-readygroup="COMMERCIAL"]'); pw.wait_for_selector('#readyCommHead th', timeout=10000); pw.wait_for_timeout(1200)
    heads = lambda: pw.evaluate("[...document.querySelectorAll('#readyCommHead th')].map(t=>t.innerText.trim())")
    h = heads(); ck('Windows (Υλικά) με HER: το υλικό με HER δείχνει την περιγραφή HER', HE1 in h and OFF1 not in h, str(h[:6]))
    ck('και το υλικό ΧΩΡΙΣ HER δείχνει την επίσημη', OFF2 in h)
    call('PUT', '/settings/material-desc', {'modes': {'ready': 'short'}}); pw.evaluate("clearApiCache();MATDESC.load()"); pw.wait_for_timeout(1500)
    h = heads(); ck('με Σύντομη: δείχνει τη σύντομη (αλλαγή από HER χωρίς refresh)', SH1 in h and HE1 not in h and OFF2 in h, str(h[:6]))
    call('PUT', '/settings/material-desc', {'modes': {'ready': 'official'}}); pw.evaluate("clearApiCache();MATDESC.load()"); pw.wait_for_timeout(1500)
    h = heads(); ck('με Επίσημη: ξαναφαίνεται η επίσημη', OFF1 in h and SH1 not in h and HE1 not in h, str(h[:6]))
    # ---- Android ----
    pa = b.new_page(viewport={'width': 360, 'height': 760}, is_mobile=True, has_touch=True); pa.on('pageerror', lambda e: errs.append(str(e)))
    pa.goto(B + '/mobile', wait_until='networkidle'); pa.click('#loginBtn'); pa.wait_for_selector('#app:not(.hidden)'); pa.wait_for_timeout(3000)
    pa.tap('.secBtn[data-section=materials]'); pa.wait_for_selector('.matStart'); pa.tap('.matStart[data-m="stock"]'); pa.wait_for_selector('.mwCat', timeout=15000); pa.wait_for_timeout(1000)
    at = pa.inner_text('#matArea'); ck('Android προεπιλογή (Επίσημη): φαίνεται η επίσημη', OFF1 in at and HE1 not in at and OFF2 in at)
    call('PUT', '/settings/material-desc', {'modes': {'android': 'her'}}); pa.wait_for_timeout(4000); at = pa.inner_text('#matArea')
    ck('Android με HER (αλλαγή από άλλη οθόνη, χωρίς refresh): HER στο υλικό που έχει, επίσημη στο άλλο', HE1 in at and OFF1 not in at and OFF2 in at, at[:200].replace(chr(10), ' '))
    call('PUT', '/settings/material-desc', {'modes': {'android': 'short'}}); pa.wait_for_timeout(4000); at = pa.inner_text('#matArea')
    ck('Android με Σύντομη', SH1 in at and HE1 not in at)
    call('PUT', '/settings/material-desc', {'modes': {'android': 'official'}}); pa.wait_for_timeout(4000)
    ck('Android ξανά Επίσημη', OFF1 in pa.inner_text('#matArea'))
    ck('σφάλματα σελίδας', not errs, str(errs[:2]))
    b.close()
print('ΑΠΟΤΥΧΙΕΣ:', bad)
sys.exit(1 if bad else 0)
