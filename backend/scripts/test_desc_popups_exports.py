"""Περιγραφές: παράθυρα ακολουθούν την οθόνη, αναφορές ακολουθούν «Αναφορές και Στατιστικά» (ΜΟΝΟ σε αντίγραφο, 8020, env LM_COPY)."""
import sys, os, sqlite3
sys.path.insert(0, os.path.dirname(__file__)); sys.stdout.reconfigure(encoding='utf-8')
from playwright.sync_api import sync_playwright
from _browser import launch
B = 'http://127.0.0.1:8020'
cp = os.environ.get('LM_COPY'); assert cp and 'lm_test' in cp
SH = 'ΣΥΝΤΟΜΟ ΔΟΚΙΜΗ'
with sync_playwright() as p:
    b = launch(p)
    pg = b.new_page(viewport={'width': 1700, 'height': 950})
    errs = []; pg.on('pageerror', lambda e: errs.append(str(e)))
    pg.goto(B + '/', wait_until='networkidle')
    pg.wait_for_selector('#loginBtn', state='visible'); pg.click('#loginBtn')
    pg.wait_for_selector('#metrics .card', timeout=20000); pg.wait_for_timeout(1200)
    ev = lambda js, a=None: pg.evaluate(js, a) if a is not None else pg.evaluate(js)
    def open_ready():
        pg.evaluate("()=>document.querySelector('[data-view=ready]').click()"); pg.wait_for_timeout(700)
        pg.evaluate("()=>{readyState.cursor=new Date(2026,8,1);readyState.period='month';readyState.activeGroup='AXIOPOIISIMA';return loadReadyMaterials()}"); pg.wait_for_timeout(1500)
    open_ready()
    # ετικέτα με ακριβώς ένα υλικό στο μητρώο → σύντομη περιγραφή στο αντίγραφο
    lab = ev("""async()=>{const u=await api('/mat/label-universe');return u.labels.find(l=>l.group==='AXIOPOIISIMA'&&l.derived.length===1&&!l.map)}""")
    mat_id = lab['derived'][0]; L = lab['label']
    cx = sqlite3.connect(cp); cx.execute("update materials set short_description=? where id=?", (SH, mat_id)); cx.commit(); cx.close()
    print('ετικέτα:', L)
    def setmodes(m): ev("m=>api('/settings/material-desc',{method:'PUT',body:JSON.stringify({modes:m})}).then(a=>MATDESC.setModes(a.modes))", m); ev("()=>MATDESC.load()"); pg.wait_for_timeout(800)
    head = lambda: ev("L=>{const t=[...document.querySelectorAll('#readyMatHead th[data-material]')].find(x=>x.dataset.material===L);return t&&t.textContent.trim()}", L)
    # Α) οθόνη Υλικά = σύντομη, Αναφορές = επίσημη
    setmodes({'ready': 'short', 'reports': 'official'}); open_ready(); pg.wait_for_timeout(600)
    print('Α) κεφαλίδα Υλικά (σύντομη):', head())
    # παράθυρο διορθώσεων ανοίγει από την οθόνη Υλικά
    btn = pg.locator(f"#readyMatFoot .corrBtn[data-label='{L}']").first
    btn.click(); pg.wait_for_timeout(700)
    print('   τίτλος παραθύρου (ακολουθεί Υλικά=σύντομη):', ev("()=>document.querySelector('.corrPop .cpTitle span')?.textContent"))
    pg.keyboard.press('Escape'); ev("()=>corrPopClose()")
    sh = ev("()=>reportSheetFromTable(document.querySelector('#readyMatPanel table'),'Υλικά')")
    print('   αναφορά (Αναφορές=επίσημη) περιέχει επίσημη:', L in sh['columns'] or any(L in c for c in sh['columns']), '| περιέχει σύντομη:', any(SH in c for c in sh['columns']))
    # Β) οθόνη Υλικά = επίσημη, Αναφορές = σύντομη
    setmodes({'ready': 'official', 'reports': 'short'}); open_ready(); pg.wait_for_timeout(600)
    print('Β) κεφαλίδα Υλικά (επίσημη):', head())
    sh = ev("()=>reportSheetFromTable(document.querySelector('#readyMatPanel table'),'Υλικά')")
    print('   αναφορά (Αναφορές=σύντομη) περιέχει σύντομη:', any(SH in c for c in sh['columns']), '| περιέχει επίσημη:', any(L in c for c in sh['columns']))
    # επαναφορά ρυθμίσεων (αντίγραφο)
    setmodes({'ready': 'official', 'reports': 'official'})
    print('JS errors:', errs)
    b.close()
