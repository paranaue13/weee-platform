"""Δοκιμή: καμία «αναλαμπή» επίσημου ονόματος πριν από τη σύντομη περιγραφή (Android Αποθήκη + ανανεώσεις). 360×700.
Χρήση: python backend/scripts/test_name_flicker.py http://127.0.0.1:PORT   (ΜΟΝΟ σε ΑΝΤΙΓΡΑΦΟ βάσης!)"""
import sys, os
sys.path.insert(0, os.path.dirname(__file__)); sys.stdout.reconfigure(encoding='utf-8')
from playwright.sync_api import sync_playwright
from _browser import launch
B = sys.argv[1]
bad = []
def ck(n, ok, i=''):
    print(('✓ ' if ok else '✗ ') + n, i)
    if not ok: bad.append(n)
SAMPLER = """names=>{window.__seen=0;window.__frames=0;const f=()=>{window.__frames++;const t=(document.getElementById('matArea')||document.body).innerText;
 if(names.some(n=>t.includes(n)))window.__seen++;requestAnimationFrame(f)};requestAnimationFrame(f)}"""
with sync_playwright() as p:
    b = launch(p); errs = []
    pg = b.new_page(viewport={'width': 360, 'height': 700}, is_mobile=True, has_touch=True); pg.on('pageerror', lambda e: errs.append(str(e)))
    pg.goto(B + '/mobile', wait_until='networkidle'); pg.click('#loginBtn'); pg.wait_for_selector('#app:not(.hidden)'); pg.wait_for_timeout(800)
    pg.evaluate("api('/settings/material-desc',{method:'PUT',body:JSON.stringify({modes:{android:'short'}})})"); pg.wait_for_timeout(300)   # η προεπιλογή είναι πλέον Επίσημη· η δοκιμή θέλει «Σύντομη»
    pg.reload(wait_until='networkidle'); pg.click('#loginBtn'); pg.wait_for_selector('#app:not(.hidden)'); pg.wait_for_timeout(1500)
    sn = pg.evaluate("api('/materials/short-names')")
    off = [n for x in sn if x.get('short') for n in x['names'] if n.strip().upper() != x['short'].strip().upper()]
    ck('υπάρχουν υλικά με σύντομη περιγραφή στο αντίγραφο', len(off) > 0, str(off[:3]))
    pg.evaluate(SAMPLER, off)
    pg.tap('.secBtn[data-section=materials]'); pg.wait_for_selector('.matStart'); pg.tap('.matStart[data-m="stock"]'); pg.wait_for_selector('.mwMat', timeout=15000)
    for _ in range(3):  # ανοίγω/κλείνω λεπτομέρεια (ξαναζωγραφίζει)
        pg.locator('.mwMat').first.tap(); pg.wait_for_timeout(250)
    pg.evaluate("mtStockRender(true)"); pg.wait_for_timeout(1500)
    pg.evaluate("liveRefreshA(['masters','settings','misc','materials'])"); pg.wait_for_timeout(2500)
    seen, frames = pg.evaluate("[window.__seen,window.__frames]")
    ck('κανένα καρέ με το επίσημο όνομα (φόρτωση, άνοιγμα, ανανέωση, /events)', seen == 0, f'{seen} από {frames} καρέ')
    pg.evaluate("api('/settings/material-desc',{method:'PUT',body:JSON.stringify({modes:{android:'official'}})})")
    ck('σφάλματα σελίδας', not errs, str(errs[:2]))
    b.close()
print('ΑΠΟΤΥΧΙΕΣ:', bad)
sys.exit(1 if bad else 0)
