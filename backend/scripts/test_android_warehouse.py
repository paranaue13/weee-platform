"""Δοκιμή Android › Υλικά → Αποθήκη: διπλή λίστα (κατηγορίες+υλικά με κιλά αριστερά, ανάλυση επιλεγμένου δεξιά/από κάτω σε στενή οθόνη), ίδιοι αριθμοί, χρώματα, /events. 360×760 και 700×700.
Χρήση: python backend/scripts/test_android_warehouse.py http://127.0.0.1:PORT C:/ΑΝΤΙΓΡΑΦΟ.db   (ΜΟΝΟ σε ΑΝΤΙΓΡΑΦΟ βάσης!)"""
import sys, os, time
sys.path.insert(0, os.path.dirname(__file__)); sys.stdout.reconfigure(encoding='utf-8')
from playwright.sync_api import sync_playwright
from _browser import launch
B, DB = sys.argv[1], sys.argv[2]
bad = []
def ck(n, ok, i=''):
    print(('✓ ' if ok else '✗ ') + n, i)
    if not ok: bad.append(n)
NL = chr(10)
with sync_playwright() as p:
    b = launch(p); errs = []
    pg = b.new_page(viewport={'width': 360, 'height': 760}, is_mobile=True, has_touch=True); pg.on('pageerror', lambda e: errs.append(str(e)))
    pg.goto(B + '/mobile', wait_until='networkidle'); pg.click('#loginBtn'); pg.wait_for_selector('#app:not(.hidden)'); pg.wait_for_timeout(2500)
    api = lambda path: pg.evaluate("p=>api(p)", path)
    old = api('/mat/warehouse'); new = api('/mat/warehouse-grouped?include_inventory=false')
    ck('ΙΔΙΟΙ αριθμοί με τον παλιό υπολογισμό: τεμάχια και κιλά συνολικά', old['pieces'] == new['pieces'] and abs(old['kg'] - new['kg']) < 0.01, f"{old['pieces']}/{old['kg']} vs {new['pieces']}/{new['kg']}")
    om = {g['material_id']: (g['pieces'], round(g['kg'], 2)) for g in old['materials']}; nm = {m['material_id']: (m['pieces'], round(m['kg'], 2)) for c in new['categories'] for m in c['materials']}
    ck('ίδιοι αριθμοί ανά υλικό', om == nm, f'{len(om)} υλικά')
    wi = api('/mat/warehouse-grouped?include_inventory=true')
    ck('με απογραφή: τα κύρια kg ΔΕΝ αλλάζουν, προστίθενται τα inv_kg', abs(wi['kg'] - new['kg']) < 0.01 and wi['total_kg'] >= new['total_kg'] - 0.01, f"inv {wi['inv_kg']}")
    pg.tap('.secBtn[data-section=materials]'); pg.wait_for_selector('.matStart'); pg.tap('.matStart[data-m="stock"]'); pg.wait_for_selector('.mwCat', timeout=15000); pg.wait_for_timeout(500)
    ck('κεχριμπάρι διακόπτης «Συμπερίληψη ποσοτήτων απογραφής» στην κορυφή, όπως ήταν', 'Συμπερίληψη ποσοτήτων απογραφής' in pg.inner_text('.mtWhBar') and pg.evaluate("getComputedStyle(document.querySelector('.mtWhBar')).backgroundColor") == 'rgb(255, 233, 199)')
    ck('ΚΑΜΙΑ γκρι γραμμή τίτλων στηλών (ΥΛΙΚΟ/ΤΕΜ./ΚΙΛΑ)', pg.query_selector('.mtWhHead') is None and 'ΤΕΜ.' not in pg.inner_text('#mwL'))
    ncat = pg.locator('.mwCat').count()
    ck('μία γραμμή ανά κατηγορία με σύνολο kg, και από κάτω τα υλικά της', ncat == new['n_categories'] and pg.locator('.mwMat').count() == sum(len(c['materials']) for c in new['categories']))
    ck('τίτλοι κατηγοριών από τα μητρώα (με τη σειρά)', [c['category'] for c in new['categories']] == [t.split(NL)[0] for t in pg.locator('.mwCat').all_inner_texts()])
    first = new['categories'][0]
    ct = pg.locator('.mwCat').first.inner_text().replace(NL, ' ')
    ck('η κατηγορία δείχνει το σύνολο κιλών της', first['category'] in ct and ' kg' in ct, ct)
    col = pg.evaluate("""(()=>{let c=getComputedStyle(document.querySelector('.mwCat')),m=getComputedStyle(document.querySelector('.mwMat')),t=getComputedStyle(document.querySelector('.mwTot'));return [c.backgroundColor,c.color,m.backgroundColor,t.backgroundColor]})()""")
    ck('χρώματα: κατηγορία #e7eefe με μπλε #2b4c9b, υλικό λευκό, σύνολο #eff2f7', col == ['rgb(231, 238, 254)', 'rgb(43, 76, 155)', 'rgb(255, 255, 255)', 'rgb(239, 242, 247)'], str(col))
    tot = pg.inner_text('.mwTot').replace(NL, ' ')
    ck('γραμμή «Σύνολο» στο τέλος της λίστας', tot.startswith('Σύνολο') and ' kg' in tot, tot)
    ck('σημείωση για την απογραφή όπως σήμερα', 'Δεν περιλαμβάνονται οι ποσότητες της απογραφής' in pg.inner_text('#matArea'))
    ck('πριν επιλεγεί κάτι δεν υπάρχει δεξί/κάτω πάνελ', pg.query_selector('#mwR') is None)
    # ---- υλικό ----
    mrow = pg.locator('.mwMat').first; mid = mrow.get_attribute('data-sel')[2:]; mat = [m for c in new['categories'] for m in c['materials'] if m['material_id'] == mid][0]
    mrow.tap(); pg.wait_for_selector('#mwR'); pg.wait_for_timeout(300)
    dt = pg.inner_text('#mwR')
    ck('υλικό: όνομα (έντονα), μία γραμμή ανά μέσο, «Σύνολο N τεμ. · X kg»', mat['material'] in dt and f"{mat['total_pieces']} τεμ." in dt and 'Σύνολο' in dt, dt.replace(NL, ' | ')[:200])
    ck('υλικό: ΧΩΡΙΣ γραμμή «Κατηγορία · Κωδικός» και χωρίς επικεφαλίδες Μέσο/Κωδικός/Κιλά', mat['category'] not in dt.split('Σύνολο')[0] and 'Μέσο' not in dt.split(NL)[1:2].__str__() and 'Ημερομηνία' not in dt)
    it = mat['items'][0]
    rw = pg.locator('#mwR .mwRow').first.inner_text().replace(NL, ' ')
    ck('γραμμή μέσου: αριστερά Μέσο · Κωδικός, δεξιά κιλά και ημερομηνία', it['label'] in rw and (not it['code'] or it['code'] in rw) and ' kg' in rw and '/' in rw, rw)
    ck('επιλεγμένο υλικό με φόντο #d5e3fe', pg.evaluate("getComputedStyle(document.querySelector('.mwMat.on')).backgroundColor") == 'rgb(213, 227, 254)')
    below = pg.evaluate("(()=>{let l=document.getElementById('mwL').getBoundingClientRect(),r=document.getElementById('mwR').getBoundingClientRect();return r.top>=l.bottom-1})()")
    ck('σε στενή οθόνη το δεξί μέρος πηγαίνει ΚΑΤΩ από τη λίστα', below)
    ww = pg.evaluate("(()=>{let d=document.getElementById('mwR').getBoundingClientRect(),c=document.getElementById('matArea').getBoundingClientRect();return [d.left-c.left,c.right-d.right]})()")
    ck('και πιάνει όλο το πλάτος της κάρτας', ww[0] <= 6 and ww[1] <= 6, str(ww))
    pg.screenshot(path=os.environ['TEMP'] + '/shots/wh2_android.png', full_page=True)
    # ---- κατηγορία ----
    cats = new['categories']; ci = next((i for i, c in enumerate(cats) if any(i2['code'] for m in c['materials'] for i2 in m['items'])), 0); c = cats[ci]
    pg.locator('.mwCat').nth(ci).tap(); pg.wait_for_selector('#mwR'); pg.wait_for_timeout(300)
    dt = pg.inner_text('#mwR')
    ck('κατηγορία: όνομα κατηγορίας στο πάνελ + «Σύνολο <κατηγορία>» στο τέλος', dt.startswith(c['category']) and f"Σύνολο {c['category']}" in dt and f"{c['total_pieces']} τεμ." in dt, dt.replace(NL, ' | ')[:160])
    n_media = sum(1 for m in c['materials'] for i2 in m['items'] if i2['code'])
    ck('κατηγορία: οι γραμμές των εξαγμένων μέσων με το υλικό τους από κάτω (μικρά)', pg.locator('#mwR .mwRow small').count() >= n_media and n_media > 0, f'{n_media} μέσα')
    nomedia = [m for cc in cats for m in cc['materials'] if not any(i2['code'] for i2 in m['items'])]
    if nomedia:
        cn = next(cc for cc in cats if nomedia[0] in cc['materials']); pg.locator('.mwCat').nth(cats.index(cn)).tap(); pg.wait_for_timeout(300)
        ck('υλικό χωρίς μέσα: φαίνεται σαν μία γραμμή υλικού', nomedia[0]['material'] in pg.inner_text('#mwR'))
    # ---- διακόπτης απογραφής ----
    pg.evaluate("document.getElementById('mtWhInv').click()"); pg.wait_for_timeout(1500)
    ck('διακόπτης ON: ξαναφορτώνει χωρίς τη σημείωση, χωρίς επιλογή', pg.evaluate("document.getElementById('mtWhInv').checked") and 'Δεν περιλαμβάνονται' not in pg.inner_text('#matArea'))
    pg.evaluate("document.getElementById('mtWhInv').click()"); pg.wait_for_timeout(1200)
    # ---- μεγαλύτερη οθόνη: δύο στήλες ----
    pg.set_viewport_size({'width': 700, 'height': 760}); pg.wait_for_timeout(300)
    pg.locator('.mwMat').first.tap(); pg.wait_for_selector('#mwR'); pg.wait_for_timeout(300)
    side = pg.evaluate("(()=>{let l=document.getElementById('mwL').getBoundingClientRect(),r=document.getElementById('mwR').getBoundingClientRect();return r.left>=l.right-1&&Math.abs(r.top-l.top)<40})()")
    ck('σε πλατιά οθόνη: αριστερά η λίστα, δεξιά η ανάλυση', side)
    pg.set_viewport_size({'width': 360, 'height': 760}); pg.wait_for_timeout(300)
    # ---- άμεση ανανέωση με επιλεγμένο υλικό ----
    pw = b.new_page(viewport={'width': 1300, 'height': 800}); pw.goto(B + '/', wait_until='networkidle'); pw.click('#loginBtn'); pw.wait_for_selector('#metrics .card', timeout=20000)
    cat = pw.evaluate("api('/mat/catalog').then(c=>c.materials.find(m=>m.available_kg>=5))")
    kg0 = pg.evaluate("document.querySelector('.mwTot span:last-child').innerText")
    t0 = time.time()
    pw.evaluate("m=>fetch('/mat/export',{method:'POST',headers:{'Content-Type':'application/json',Authorization:'Bearer '+token},body:JSON.stringify({material_id:m,form:'BULK',net:2})})", cat['id'])
    pg.wait_for_function("k=>document.querySelector('.mwTot span:last-child').innerText!==k", arg=kg0, timeout=9000)
    ck('νέα εξαγωγή από άλλη οθόνη: η αποθήκη ανανεώνεται σε 1–3″ και η επιλογή ΜΕΝΕΙ', time.time() - t0 < 4.5 and pg.query_selector('#mwR') is not None, f'{time.time()-t0:.1f} s')
    ck('σφάλματα σελίδας', not errs, str(errs[:2]))
    b.close()
print('ΑΠΟΤΥΧΙΕΣ:', bad)
sys.exit(1 if bad else 0)
