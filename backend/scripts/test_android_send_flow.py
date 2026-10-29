"""Δοκιμή Android › Αποστολή σε παραγωγή (βήμα Β): κουμπί αποστολής 3 γραμμών, Χύμα ανά ΑΗΗΕ, «Όλα τα μέσα» → Χύμα, ΚΙΛΑ|ΤΕΜΑΧΙΑ, άμεση ανανέωση /events.
Χρήση: python backend/scripts/test_android_send_flow.py http://127.0.0.1:PORT C:/ΑΝΤΙΓΡΑΦΟ.db   (ΜΟΝΟ σε ΑΝΤΙΓΡΑΦΟ βάσης!)"""
import sys, os, sqlite3, datetime, time, math
sys.path.insert(0, os.path.dirname(__file__)); sys.stdout.reconfigure(encoding='utf-8')
from playwright.sync_api import sync_playwright
from _browser import launch
B, DB = sys.argv[1], sys.argv[2]
bad = []
def ck(n, ok, i=''):
    print(('✓ ' if ok else '✗ ') + n, i)
    if not ok: bad.append(n)
PCS9 = ['4Α2110', '4Α2120', '4Α2200', '4Α1000', '1Α1100', '1Α1200', '1Α2100', '1Α2200', '1Α3000']
c = sqlite3.connect(DB)
# Εξασφάλιση χύμα μεριδίου σε κατηγορία των 9 με μέσο βάρος (στο ΑΝΤΙΓΡΑΦΟ)
PROD4 = ['4Α2110', '4Α2120', '4Α2200', '4Α1000']   # από τις 9, αυτές στέλνονται σε παραγωγή (οι 1Α* δεν είναι υλικά παραγωγής)
pc = c.execute("select id,code,average_weight from weee_categories where code in (%s) and average_weight>0 and active=1 limit 1" % ','.join('?' * 4), PROD4).fetchone()
big = c.execute("select id from weee_stock_lots where collection_medium_id is null and available_weight>=300 order by available_weight desc limit 1").fetchone()[0]
c.execute("update weee_stock_lots set weee_category_id=? where id=?", (pc[0], big)); c.commit()
AVG = float(pc[2])
unit_tv = c.execute("select id from organizational_units where name_el like '%Τηλεόρασ%' and active=1").fetchone()[0]
today = datetime.date.today().isoformat()
half_up = lambda x: int(math.floor(x + 0.5))
with sync_playwright() as p:
    b = launch(p); errs = []
    pg = b.new_page(viewport={'width': 360, 'height': 800}, is_mobile=True, has_touch=True); pg.on('pageerror', lambda e: errs.append(str(e)))
    pg.goto(B + '/mobile', wait_until='networkidle'); pg.click('#loginBtn'); pg.wait_for_selector('#app:not(.hidden)'); pg.wait_for_timeout(2500)
    pg.tap('.secBtn[data-section=production]'); pg.wait_for_timeout(1200); pg.evaluate("flLoad(true)"); pg.wait_for_timeout(2500)
    pg.evaluate("document.querySelector('.flStart[data-f=d]').click()"); pg.wait_for_timeout(400)
    btn = lambda: pg.inner_text('#flSend').replace('\n', ' | ')
    pg.evaluate("flPick('unit',prodUnits.find(u=>/Τηλεόρασ/.test(u.name_el)).id)"); pg.wait_for_timeout(600)
    ck('κουμπί αποστολής ΑΝΕΝΕΡΓΟ (γκρι) με «Διάλεξε μέσο και υλικό» και από κάτω «ΑΠΟΣΤΟΛΗ ΣΕ ΠΑΡΑΓΩΓΗ»', pg.evaluate("document.getElementById('flSend').disabled") and btn() == 'Διάλεξε μέσο και υλικό | ΑΠΟΣΤΟΛΗ ΣΕ ΠΑΡΑΓΩΓΗ', btn())
    nb = pg.locator('.flBulk').count()
    ck('πιθανές επιλογές: Χύμα ΕΝΑ ΕΝΑ ανά ΑΗΗΕ (κουμπιά)', nb >= 1, str(nb))
    first = pg.locator('.flBulk').first
    css = pg.evaluate("()=>{let b=document.querySelector('.flBulk'),s=getComputedStyle(b.querySelector('small')),n=getComputedStyle(b.querySelector('b'));return [s.fontSize,s.fontWeight,n.fontWeight,b.querySelector('.flBulkR span').innerText.indexOf('kg')>0]}")
    ck('μικρό «Χύμα» 13px έντονο, από κάτω όνομα ΑΗΗΕ έντονο και δεξιά τα kg', first.locator('small').inner_text() == 'Χύμα' and css[0] == '13px' and int(css[1]) >= 600 and int(css[2]) >= 600 and css[3], str(css))
    ck('δεν υπάρχει γενική κάρτα «Χύμα» στις πιθανές (αντικαταστάθηκε από τα ανά ΑΗΗΕ)', pg.locator('.flCard b:text-is("Χύμα")').count() == 0)
    ck('ο τίτλος «Μέσο συλλογής · πιθανότερα για …» είναι από πάνω', 'πιθανότερα για' in pg.locator('#flowArea .flLbl').nth(1).inner_text() or 'πιθανότερα για' in pg.inner_text('#flowArea'))
    name1 = first.locator('b').inner_text(); kgtxt = first.locator('.flBulkR span').inner_text()
    first.tap(); pg.wait_for_timeout(500)
    ck('πατώντας ένα Χύμα πηγαίνει ΚΑΤΕΥΘΕΙΑΝ στα κιλά (χωρίς άλλο βήμα)', pg.query_selector('#flKg') is not None and pg.query_selector('.flBulk') is None)
    ck('κουμπί αποστολής: γραμμή 1 = ΑΗΗΕ, γραμμή 2 = «kg · Χύμα», γραμμή 3 = «ΑΠΟΣΤΟΛΗ ΣΕ ΠΑΡΑΓΩΓΗ · τμήμα»', btn() == f"{name1} | {kgtxt} · Χύμα | ΑΠΟΣΤΟΛΗ ΣΕ ΠΑΡΑΓΩΓΗ · Τμήμα Τηλεόρασης", btn())
    fs = pg.evaluate("[...document.querySelectorAll('#flSend span')].map(s=>getComputedStyle(s).fontSize+' '+getComputedStyle(s).fontWeight)")
    ck('μεγέθη 19px / 17px έντονα και ~10px', fs[0].startswith('19px') and fs[1].startswith('17px') and fs[2].startswith('10px') and int(fs[0].split()[1]) >= 600 and int(fs[1].split()[1]) >= 600, str(fs))
    ck('ενεργό (πράσινο)', not pg.evaluate("document.getElementById('flSend').disabled"))
    pg.screenshot(path=os.environ['TEMP'] + '/shots/send_btn.png', full_page=True)
    # ---- «Όλα τα μέσα με υλικό» → Χύμα = ΟΛΑ τα χύμα ----
    pg.evaluate("flChange('medium')"); pg.wait_for_timeout(400)
    pg.evaluate("document.querySelector('[data-type=\"BULK\"]').click()"); pg.wait_for_timeout(500)
    n_all = pg.locator('#flRes .flBulk').count(); n_total = pg.evaluate("flMedia.find(g=>!g.medium_id).categories.length")
    ck('κουμπί «Χύμα» στη λίστα «Όλα τα μέσα»: ανοίγει ΟΛΑ τα χύμα (όλα τα ΑΗΗΕ)', n_all == n_total and n_all >= nb, f'{n_all} από {n_total}')
    # ---- ΤΕΜΑΧΙΑ ----
    pg.evaluate("c=>{fl.medium=flMedia.find(g=>!g.medium_id);fl.cat=flCat(c);fl.type=null;fl.kg=null;fl.mode='kg';flRender()}", pc[0]); pg.wait_for_timeout(400)
    ck('κατηγορία των 9 με μέσο βάρος: εμφανίζεται «ΚΙΛΑ | ΤΕΜΑΧΙΑ»', pg.locator('[data-um="kg"]').count() == 1 and pg.locator('[data-um="pcs"]').count() == 1)
    pg.locator('[data-um="pcs"]').tap(); pg.wait_for_selector('#flPcs')
    mx = pg.evaluate("flMax()"); n = 7; exp = half_up(n * AVG)
    pg.fill('#flPcs', str(n)); pg.wait_for_timeout(200)
    ck(f'προεπισκόπηση «{n} τεμάχια → {exp} kg» (ίδιος υπολογισμός/στρογγυλοποίηση με την Ταξινόμηση)', pg.inner_text('#flPcsPrev').strip() == f'{n} τεμάχια → {exp} kg', pg.inner_text('#flPcsPrev'))
    ck('το κουμπί αποστολής δείχνει τα kg από τα τεμάχια', f'{exp} kg · Χύμα' in btn(), btn())
    big_n = int(mx / AVG) + 50; pg.fill('#flPcs', str(big_n)); pg.wait_for_timeout(200)
    ck('έλεγχος: ξεπερνά τα διαθέσιμα → μήνυμα και ανενεργό κουμπί', 'Ξεπερνά τα διαθέσιμα' in pg.inner_text('#flPcsPrev') and pg.evaluate("document.getElementById('flSend').disabled"), pg.inner_text('#flPcsPrev'))
    pg.fill('#flPcs', '1.5'); pg.wait_for_timeout(200)
    ck('μη ακέραια τεμάχια → μήνυμα', 'ακέραιο' in pg.inner_text('#flPcsPrev') and pg.evaluate("document.getElementById('flSend').disabled"))
    # άλλη κατηγορία (όχι των 9): ΧΩΡΙΣ επιλογή τεμαχίων
    other = pg.evaluate("flMedia.find(g=>!g.medium_id).categories.map(c=>flCat(c.category_id)).find(o=>o&&!%s.includes(o.code)).id" % str(PCS9).replace('"', "'"))
    pg.evaluate("c=>{fl.cat=flCat(c);fl.mode='kg';flRender()}", other); pg.wait_for_timeout(300)
    ck('κατηγορία εκτός των 9: ΔΕΝ υπάρχει επιλογή «ΤΕΜΑΧΙΑ»', pg.locator('[data-um]').count() == 0)
    # αποστολή με τεμάχια
    pg.evaluate("c=>{fl.cat=flCat(c);fl.mode='pcs';fl.pcs='7';flRender()}", pc[0]); pg.wait_for_timeout(300)
    tot = lambda: float(sqlite3.connect(DB).execute("select sum(available_weight) from weee_stock_lots where collection_medium_id is null and weee_category_id=?", (pc[0],)).fetchone()[0])
    w0 = tot()
    pg.evaluate("document.getElementById('flSend').click()"); pg.wait_for_function("!fl.busy", timeout=30000); pg.wait_for_timeout(1500)
    row = sqlite3.connect(DB).execute("select weight_kg,source from production_work_entries where weee_category_id=? order by created_at desc limit 1", (pc[0],)).fetchone()
    ck(f'η αποστολή γράφτηκε με {exp} kg (από τεμάχια), πηγή ANDROID', row and float(row[0]) == exp and row[1] == 'ANDROID', str(row))
    w1 = tot()
    ck('το απόθεμα του χύμα μειώθηκε ακριβώς κατά τα kg της αποστολής', abs((w0 - w1) - exp) < 0.01, f'{w0} → {w1}')
    # ---- άμεση ανανέωση /events ----
    pg.evaluate("flReset();flRender()"); pg.wait_for_timeout(500)
    ck('το κανάλι /events είναι συνδεδεμένο στο Android', pg.evaluate("LIVEA.state()") == 1, str(pg.evaluate("LIVEA.state()")))
    pw = b.new_page(viewport={'width': 1300, 'height': 800}); pw.goto(B + '/', wait_until='networkidle'); pw.click('#loginBtn'); pw.wait_for_selector('#metrics .card', timeout=20000)
    call = lambda m, path, body=None: pw.evaluate("([m,p,b])=>fetch(p,{method:m,headers:{'Content-Type':'application/json','Authorization':'Bearer '+token},body:b?JSON.stringify(b):undefined}).then(async r=>[r.status,await r.json().catch(()=>null)])", [m, path, body])
    n0 = pg.locator('.ptItem').count(); t0 = time.time()
    st, j = call('POST', '/production/transfers', {'destination_org_unit_id': unit_tv, 'items': [{'stock_lot_id': big, 'weight': 9}], 'work_entry': {'weee_category_id': pc[0], 'source': 'WINDOWS'}}); tid = j['id']
    pg.wait_for_function("n=>document.querySelectorAll('.ptItem').length>n", arg=n0, timeout=9000)
    ck('αποστολή από άλλη οθόνη (Windows) εμφανίζεται στο ιστορικό του Android σε 1–3″ (χωρίς refresh)', time.time() - t0 < 4.5, f'{time.time()-t0:.1f} s')
    # φόρμα Υπόλοιπο ανοιχτή: δεν διακόπτεται
    pg.locator('.ptItem').first.tap(); pg.wait_for_timeout(200); pg.locator('.ptRemBtn').tap(); pg.wait_for_selector('#ptRemKg'); pg.fill('#ptRemKg', '3'); n1 = pg.locator('.ptItem').count()
    call('POST', '/production/transfers', {'destination_org_unit_id': unit_tv, 'items': [{'stock_lot_id': big, 'weight': 4}], 'work_entry': {'weee_category_id': pc[0], 'source': 'WINDOWS'}}); pg.wait_for_timeout(3500)
    ck('φόρμα «Υπόλοιπο» ανοιχτή με κείμενο: δεν κλείνει και δεν σβήνεται', pg.locator('#ptRemKg').count() == 1 and pg.input_value('#ptRemKg') == '3')
    call('POST', f'/production/transfers/{tid}/cancel')
    ck('σφάλματα σελίδας', not errs, str(errs[:2]))
    b.close()
print('ΑΠΟΤΥΧΙΕΣ:', bad)
sys.exit(1 if bad else 0)
