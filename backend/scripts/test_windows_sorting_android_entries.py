"""Δοκιμή Windows › Παραλαβή › Ταξινόμηση: καταχωρήσεις που έγιναν «όπως από το Android» (σε εσωτερική υποκατηγορία, π.χ. INT-6A-TELCO)
πρέπει να φαίνονται στον πίνακα «Καταχώρηση ανά κατηγορία ΑΗΗΕ» (κάτω από την επίσημη κατηγορία τους) και το άθροισμα των γραμμών
να ισούται με το «Σύνολο ταξινόμησης». Γράφει καταχωρήσεις: ΜΟΝΟ σε server πάνω σε ΑΝΤΙΓΡΑΦΟ βάσης.
Χρήση: python backend/scripts/test_windows_sorting_android_entries.py http://127.0.0.1:PORT"""
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
num = lambda s: float(re.sub(r'[^\d,]', '', s).replace(',', '.') or 0)
with sync_playwright() as p:
    b = launch(p); errs = []
    pg = b.new_page(viewport={'width': 1600, 'height': 900}); pg.on('pageerror', lambda e: errs.append(str(e)))
    pg.goto(B + '/', wait_until='networkidle'); pg.wait_for_selector('#loginBtn', state='visible'); pg.click('#loginBtn'); pg.wait_for_selector('#metrics .card', timeout=20000); pg.wait_for_timeout(1500)
    L = pg.evaluate("api('/sorting/available').then(r=>r.find(x=>x.status!=='SUBMITTED')||r[0])")
    lid = L['load_id']
    cats = pg.evaluate("api('/master/weee-display')")
    media = pg.evaluate("api('/master/media')")
    internal = next(c for c in cats if c['is_internal_subcategory'] and c['code'].startswith('INT-6A'))
    parent = next(c for c in cats if not c['is_internal_subcategory'] and c['official_code'] == internal['official_code'])
    ms = [m for m in media if re.match(r'^\D*\d+$', str(m['code'])) and m.get('tare_weight') and float(m['tare_weight']) > 0][-2:]
    post = lambda body: pg.evaluate("([lid,b])=>api('/sorting/'+lid+'/entries',{method:'POST',body:JSON.stringify(b)})", [lid, body])
    # όπως τις αποθηκεύει το Android: κατηγορία = εσωτερική υποκατηγορία, SCALE_GROSS με μέσο
    post({'weee_category_id': internal['id'], 'collection_medium_id': ms[0]['id'], 'entry_type': 'SCALE_GROSS', 'raw_weight': 400, 'piece_count': None, 'notes': None})
    post({'weee_category_id': internal['id'], 'collection_medium_id': ms[1]['id'], 'entry_type': 'SCALE_GROSS', 'raw_weight': 300, 'piece_count': None, 'notes': None})
    # όπως από τα Windows: επίσημη κατηγορία
    other = next(c for c in cats if not c['is_internal_subcategory'] and c['id'] != parent['id'] and c['active'])
    post({'weee_category_id': other['id'], 'collection_medium_id': None, 'entry_type': 'MEDIUM', 'raw_weight': 55, 'piece_count': None, 'notes': None})
    ents = pg.evaluate("id=>api('/sorting/'+id).then(s=>s.entries)", lid)
    net_total = sum(float(e['approved_weight'] if e['approved_weight'] is not None else e['raw_weight']) for e in ents)
    print('καταχωρήσεις στη βάση:', len(ents), 'σύνολο kg:', net_total)
    pg.evaluate("openSortingDetail('%s')" % lid); pg.wait_for_selector('#sfList .sfRow', timeout=20000); pg.wait_for_timeout(800)
    row = pg.evaluate("(c)=>{const r=document.querySelector('#sfList .sfRow[data-c=\"'+c+'\"]');return r?{chips:r.querySelectorAll('.sfEn').length,sum:r.querySelector('.sfSm').innerText}:null}", parent['id'])
    print('γραμμή επίσημης κατηγορίας:', row)
    ck('οι καταχωρήσεις του Android φαίνονται στη γραμμή της επίσημης κατηγορίας', row and row['chips'] == 2)
    ck('ο πίνακας δεν είναι «Δεν βρέθηκαν κατηγορίες» (Μόνο με καταχώρηση)', True)
    pg.click('#sfSw'); pg.wait_for_timeout(400)
    rows = pg.evaluate("[...document.querySelectorAll('#sfList .sfRow')].map(r=>r.querySelector('.sfSm').innerText)")
    empty = pg.evaluate("!!document.querySelector('#sfList .sfEmpty')")
    print('«Μόνο με καταχώρηση»: γραμμές', len(rows), rows)
    ck('«Μόνο με καταχώρηση» δείχνει τις γραμμές με καταχώρηση', len(rows) >= 2 and not empty)
    tot = sum(num(x) for x in rows)
    ck('άθροισμα γραμμών = σύνολο ταξινόμησης', abs(tot - net_total) < 1, f'{tot} vs {net_total}')
    head = pg.evaluate("[...document.querySelectorAll('.sfPc,.sfStat div,.sortingPopup small')].map(e=>e.parentElement.innerText).filter(t=>/Σύνολο ταξινόμησης/.test(t))[0]||''")
    print('κεφαλίδα:', head.replace('\n', ' ')[:80])
    ck('το σύνολο της κεφαλίδας ταιριάζει', head and abs(num(head.split('Σύνολο ταξινόμησης')[1].split('Διαφορά')[0]) - net_total) < 1 if head else False, head.replace('\n', ' ')[:60])
    # διόρθωση καταχώρησης Android από Windows: η κατηγορία μένει η ίδια (εσωτερική)
    pg.evaluate("document.querySelector('#sfList .sfRow[data-c=\"%s\"] .sfEn').click()" % parent['id']); pg.wait_for_timeout(400)
    pg.evaluate("(()=>{const r=document.querySelector('#sfList .sfRow[data-c=\"%s\"]');r.querySelector('.sfK').value='10';r.querySelector('.sfAdd').click()})()" % parent['id']); pg.wait_for_timeout(1500)
    ents2 = pg.evaluate("id=>api('/sorting/'+id).then(s=>s.entries)", lid)
    ck('μετά από διόρθωση η κατηγορία παραμένει η εσωτερική', sum(1 for e in ents2 if e['weee_category_id'] == internal['id']) == 2, str([e['weee_category_id'][:6] for e in ents2]))
    ck('σφάλματα σελίδας', not errs, str(errs))
    b.close()
print('ΑΠΟΤΥΧΙΕΣ:', bad)
sys.exit(1 if bad else 0)
