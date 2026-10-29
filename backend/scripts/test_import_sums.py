"""Μετά την εισαγωγή (σε ΑΝΤΙΓΡΑΦΟ, 8020): σύνολα ημερών/μηνών των καρτελών Υλικών = σύνολα των Excel. Επίσης: μόνο ημέρες με εγγραφή, «ματάκι» στο κελί ΗΜΕΡΟΜΗΝΙΑΣ.
Χρήση: python test_import_sums.py <base_url> <αρχείο βάσης αντιγράφου>"""
import sys, os, sqlite3, collections
sys.path.insert(0, os.path.dirname(__file__)); sys.stdout.reconfigure(encoding='utf-8')
B, DB = sys.argv[1], sys.argv[2]
sys.argv = ['x', '--db', DB]
import xl_import as X
from app.mat_warehouse import _fold_key
from playwright.sync_api import sync_playwright
from _browser import launch

ro = sqlite3.connect('file:' + DB.replace('\\', '/') + '?mode=ro', uri=True)
st = X.db_state(ro); xl = X.extract()
EXC = ('NONE', 'SUM', 'RECEIPTS')
exp = collections.defaultdict(lambda: collections.defaultdict(float))     # καρτέλα -> ημέρα -> kg
for c in xl['cells']:
    if c['date'][:7] != '2026-09' or c['sheet'] == 'COMMERCIAL': continue
    tab = 'PLAKETES' if (c['sheet'] == 'EIDIKIS_DIACHEIRISIS' and c['plak']) else c['sheet']
    m = st['maps'].get(('EXCEL', _fold_key(c['label'])))
    if not m or m['kind'] in EXC: continue
    if m.get('sheet') and m['sheet'] != tab: continue
    exp[tab][c['date']] += c['kg'] + c['diff']
num = lambda t: float(str(t).replace('.', '').replace(',', '.') or 0) if str(t).strip() else 0.0
ok_all = True
def ck(name, cond, info=''):
    global ok_all
    print(('✓ ' if cond else '✗ ') + name, info); ok_all = ok_all and bool(cond)
with sync_playwright() as p:
    b = launch(p)
    pg = b.new_page(viewport={'width': 1700, 'height': 950})
    errs = []; pg.on('pageerror', lambda e: errs.append(str(e)))
    pg.goto(B + '/', wait_until='networkidle')
    pg.wait_for_selector('#loginBtn', state='visible'); pg.click('#loginBtn')
    pg.wait_for_selector('#metrics .card', timeout=20000); pg.wait_for_timeout(1200)
    pg.evaluate("()=>document.querySelector('[data-view=ready]').click()"); pg.wait_for_timeout(700)
    for g, nm in [('AXIOPOIISIMA', 'Αξιοποιήσιμα'), ('EIDIKIS_DIACHEIRISIS', 'Ειδικής Διαχείρισης'), ('PLAKETES', 'Πλακέτες'), ('APORRIPSI', 'Προς Απόρριψη')]:
        pg.evaluate("g=>{readyState.cursor=new Date(2026,8,1);readyState.period='month';readyState.activeGroup=g;readyState.colOpen=new Set();return loadReadyMaterials()}", g); pg.wait_for_timeout(2200)
        body = pg.evaluate("()=>[...document.querySelectorAll('#readyMatBody tr:not(.tFill)')].map(r=>[r.children[0].innerText.trim(),r.children[1].innerText.trim()])")
        foot = pg.evaluate("()=>{const r=[...document.querySelectorAll('#readyMatFoot tr')].find(r=>r.children[0].innerText.trim().startsWith('Σύνολο'));return r.children[1].innerText.trim()}")
        days_ui = {('2026-%s-%s' % (d[3:5], d[0:2])): num(t) for d, t in body if d[6:10] == '2026' and d[3:5] == '09'}
        e = exp.get(g, {})
        tot_e = round(sum(e.values()), 1); tot_ui = num(foot)
        ck(f'{nm}: σύνολο Σεπτεμβρίου UI = Excel', abs(tot_ui - tot_e) <= 1.0, f'UI {tot_ui} · Excel {tot_e}')
        ck(f'{nm}: άθροισμα ημερών UI = σύνολο μήνα', abs(sum(days_ui.values()) - tot_ui) <= 1.0, f'{round(sum(days_ui.values()),1)} vs {tot_ui}')
        bad = [(d, days_ui.get(d), round(e.get(d, 0), 1)) for d in sorted(set(days_ui) | set(e)) if abs(days_ui.get(d, 0) - e.get(d, 0)) > 1.0]
        ck(f'{nm}: ημερήσια σύνολα UI = Excel', not bad, str(bad[:6]))
        ck(f'{nm}: μόνο ημέρες με εγγραφή (χωρίς κενές γραμμές)', all(abs(v) > 0 for v in days_ui.values()) and len(body) == len(days_ui), f'{len(body)} γραμμές · {len(days_ui)} ημέρες')
    # «ματάκι»: στο κελί ΗΜΕΡΟΜΗΝΙΑΣ, όχι πάνω στο ΣΥΝΟΛΟ
    pg.evaluate("g=>{readyState.activeGroup=g;return loadReadyMaterials()}", 'AXIOPOIISIMA'); pg.wait_for_timeout(2000)
    cell0 = pg.locator('#readyMatBody tr').first.locator('td').nth(0); box0 = cell0.bounding_box()
    box1 = pg.locator('#readyMatBody tr').first.locator('td').nth(1).bounding_box()
    pg.mouse.move(box0['x'] + 5, box0['y'] + box0['height'] / 2); pg.wait_for_timeout(500)
    eye = pg.evaluate("()=>{const e=document.querySelector('.pinLayer .pinEye');if(!e)return null;const r=e.getBoundingClientRect();return {x:r.x,y:r.y,w:r.width,h:r.height}}")
    ck('εμφανίζεται «ματάκι» στη γραμμή', eye is not None, str(eye))
    if eye:
        ck('το «ματάκι» είναι μέσα στο κελί ΗΜΕΡΟΜΗΝΙΑΣ (δεξιά) και όχι πάνω στο ΣΥΝΟΛΟ', box0['x'] <= eye['x'] and eye['x'] + eye['w'] <= box0['x'] + box0['width'] + 1 and eye['x'] + eye['w'] <= box1['x'] + 1, f"εικονίδιο x={eye['x']:.0f}-{eye['x']+eye['w']:.0f} · ημερομηνία {box0['x']:.0f}-{box0['x']+box0['width']:.0f} · σύνολο από {box1['x']:.0f}")
    ck('σφάλματα σελίδας', not errs, str(errs[:2]))
    b.close()
print('ΟΛΑ ΟΚ' if ok_all else 'ΥΠΑΡΧΟΥΝ ΑΠΟΤΥΧΙΕΣ')
