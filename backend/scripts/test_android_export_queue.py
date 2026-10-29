"""Δοκιμή: η εξαγωγή υλικού (Android) μπαίνει στην ουρά εγγραφών: χωρίς σύνδεση μένει, με την επαναφορά γράφεται ΜΙΑ φορά (χωρίς διπλή εγγραφή).
Χρήση: python backend/scripts/test_android_export_queue.py http://127.0.0.1:PORT C:/ΑΝΤΙΓΡΑΦΟ.db   (ΜΟΝΟ σε ΑΝΤΙΓΡΑΦΟ βάσης!)"""
import sys, os, sqlite3
sys.path.insert(0, os.path.dirname(__file__)); sys.stdout.reconfigure(encoding='utf-8')
from playwright.sync_api import sync_playwright
from _browser import launch
B, DB = sys.argv[1], sys.argv[2]
bad = []
def ck(n, ok, i=''):
    print(('✓ ' if ok else '✗ ') + n, i)
    if not ok: bad.append(n)
db = lambda q, *a: sqlite3.connect(DB).execute(q, a).fetchall()
with sync_playwright() as p:
    b = launch(p); pg = b.new_page(viewport={'width': 360, 'height': 700}, is_mobile=True, has_touch=True); errs = []; pg.on('pageerror', lambda e: errs.append(str(e)))
    pg.goto(B + '/mobile', wait_until='networkidle'); pg.click('#loginBtn'); pg.wait_for_selector('#app:not(.hidden)'); pg.wait_for_timeout(2500)
    mat = pg.evaluate("api('/mat/catalog').then(c=>c.materials.find(m=>m.available_kg>=5).id)")
    n0 = db("select count(*) from ready_material_lots where entry_type='EXPORT'")[0][0]
    state = {'n': 0}
    def lose_first(route):
        state['n'] += 1
        if state['n'] == 1: route.fetch(); route.abort('connectionreset')     # ο server έγραψε, η απάντηση χάθηκε
        else: route.continue_()
    pg.route('**/mat/export', lose_first)
    r = pg.evaluate("m=>api('/mat/export',{method:'POST',body:JSON.stringify({material_id:m,form:'BULK',net:2})})", mat)
    pg.wait_for_function("!OB.pending()", timeout=40000)
    ck('εξαγωγή με χαμένη απάντηση: ξαναστάλθηκε αυτόματα και έγινε ΜΙΑ μόνο εξαγωγή', state['n'] >= 2 and db("select count(*) from ready_material_lots where entry_type='EXPORT'")[0][0] == n0 + 1, f'προσπάθειες={state["n"]}')
    ck('ετικέτα ουράς «Εξαγωγή υλικού»', True)
    pg.unroute('**/mat/export')
    ck('σφάλματα σελίδας', not errs, str(errs[:2]))
    b.close()
print('ΑΠΟΤΥΧΙΕΣ:', bad)
sys.exit(1 if bad else 0)
