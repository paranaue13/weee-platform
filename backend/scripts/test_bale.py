"""Δοκιμή ΜΠΑΛΑΣ: πεδίο can_bale/press_label στο υλικό, κουμπί «Μπάλα» στην εξαγωγή Android (μόνο για υλικά με can_bale), is_bale στην ίδια εγγραφή
(μετράει ΜΙΑ φορά στο απόθεμα), γραμμές «Κιλά μπάλες»/«Μπάλες» στην Πρέσα των Windows (χρώματα, χωρίς αλλαγή των υπαρχουσών γραμμών). 360×700 / 1366×800.
Χρήση: python backend/scripts/test_bale.py http://127.0.0.1:PORT C:/ΑΝΤΙΓΡΑΦΟ.db   (ΜΟΝΟ σε ΑΝΤΙΓΡΑΦΟ βάσης!)"""
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
    b = launch(p); errs = []
    pg = b.new_page(viewport={'width': 360, 'height': 700}, is_mobile=True, has_touch=True); pg.on('pageerror', lambda e: errs.append(str(e)))
    pg.goto(B + '/mobile', wait_until='networkidle'); pg.click('#loginBtn'); pg.wait_for_selector('#app:not(.hidden)'); pg.wait_for_timeout(2500)
    call = lambda m, path, body=None: pg.evaluate("""async([m,p,b])=>{let r=await fetch(p,{method:m,headers:{'Content-Type':'application/json',Authorization:'Bearer '+token},body:b?JSON.stringify(b):undefined});return [r.status,await r.json().catch(()=>null)]}""", [m, path, body])
    cat = pg.evaluate("api('/mat/catalog')"); cand = [m for m in cat['materials'] if m['available_kg'] >= 20 and not m.get('can_bale')]
    mA, mB = cand[0], cand[1]
    cols = [r[1] for r in db("pragma table_info(materials)")]
    ck('νέες στήλες στη βάση: materials.can_bale, materials.press_label, ready_material_lots.is_bale', 'can_bale' in cols and 'press_label' in cols and 'is_bale' in [r[1] for r in db("pragma table_info(ready_material_lots)")])
    ck('η λίστα υλικών δίνει το πεδίο can_bale', all('can_bale' in m for m in cat['materials']))
    # ---- Windows: προφίλ υλικού ----
    pw = b.new_page(viewport={'width': 1366, 'height': 800}); pw.on('pageerror', lambda e: errs.append(str(e)))
    pw.goto(B + '/', wait_until='networkidle'); pw.click('#loginBtn'); pw.wait_for_selector('#metrics .card', timeout=20000)
    pw.click('.nav button[data-view="master"]'); pw.wait_for_timeout(600)
    pw.evaluate("document.querySelectorAll('.mtab').forEach(b=>{if(b.dataset.mtab==='materialsM')b.click()})"); pw.wait_for_selector('#materialRows tr.matMaster', timeout=15000)
    pw.evaluate("id=>editMaterialPopup(materialsCache.find(x=>x.id===id))", mA['id']); pw.wait_for_selector('#fpMatBale', timeout=8000)
    tip = pw.inner_text('#floatingEditor') + ' ' + pw.eval_on_selector_all('#floatingEditor .mpQ', "els=>els.map(e=>e.dataset.t).join(' ')")   # οι επεξηγήσεις είναι πλέον στα «?» του νέου προφίλ
    ck('προφίλ υλικού: τετράγωνο «Μπορεί να γίνει μπάλα» με σύντομη εξήγηση + προαιρετικό «Όνομα στήλης Πρέσας»', 'Μπορεί να γίνει μπάλα' in tip and 'κουμπί «Μπάλα»' in tip and pw.query_selector('#fpMatPress') is not None)
    pw.check('#fpMatBale'); pw.fill('#fpMatPress', 'ΠΡΕΣΑ ΔΟΚΙΜΗ'); pw.click('#fpMatSave'); pw.wait_for_timeout(1500)
    row = db("select can_bale,press_label from materials where id=?", mA['id'])[0]
    ck('αποθηκεύεται (can_bale=1, press_label)', row == (1, 'ΠΡΕΣΑ ΔΟΚΙΜΗ'), str(row))
    # αίτημα χωρίς τα πεδία (παλιός πελάτης / μαζική επεξεργασία) ΔΕΝ τα σβήνει
    m = pw.evaluate("id=>materialsCache.find(x=>x.id===id)", mA['id']); body = {k: m[k] for k in ['internal_code', 'internal_name', 'galaxy_code', 'galaxy_description', 'genre', 'official_description', 'her_description', 'eka_code', 'reptool_code', 'reptool_description', 'is_precious', 'export_step_kg']}
    st, _ = call('PUT', '/master/materials/' + mA['id'], body)
    ck('PUT χωρίς τα πεδία δεν σβήνει can_bale/press_label', st == 200 and db("select can_bale,press_label from materials where id=?", mA['id'])[0] == (1, 'ΠΡΕΣΑ ΔΟΚΙΜΗ'), str(st))
    # ---- server: κανόνες ----
    st, r = call('POST', '/mat/export', {'material_id': mB['id'], 'form': 'PALLET', 'gross': 40, 'tare': 20, 'is_bale': True})
    ck('υλικό ΧΩΡΙΣ can_bale: η μπάλα απορρίπτεται (422)', st == 422, str(r))
    st, r = call('POST', '/mat/export', {'material_id': mA['id'], 'form': 'BULK', 'net': 5, 'is_bale': True})
    ck('μπάλα μόνο ως παλέτα (χύμα+μπάλα → 422)', st == 422)
    # ---- Android UI ----
    pg.evaluate("mtLoadCatalog&&mtLoadCatalog()"); pg.wait_for_timeout(800)
    pg.tap('.secBtn[data-section=materials]'); pg.wait_for_selector('.mtCat', timeout=15000); pg.wait_for_timeout(500)
    def open_mat(mid):
        pg.evaluate("m=>{mt.w=mtWiz('export');mt.w.mat=m;mt.w.cat=mtMatCat(m);mt.w.step=3;}".replace('mtMatCat(m)', "mt.catalog.materials.find(x=>x.id===m).category_id"), mid)
        pg.evaluate("mtLoadStep3()"); pg.wait_for_selector('.mtForm', timeout=8000)
    a_before = pg.evaluate("m=>api('/mat/warehouse-grouped').then(w=>{let x=w.categories.flatMap(c=>c.materials).find(y=>y.material_id===m);return x?[x.pieces,x.kg]:[0,0]})", mA['id'])
    open_mat(mB['id'])
    ck('υλικό ΧΩΡΙΣ can_bale: δεν υπάρχει κουμπί «Μπάλα»', pg.locator('.mtForm[data-form="BALE"]').count() == 0 and 'Μπάλα' not in pg.inner_text('.mtForms'))
    open_mat(mA['id'])
    ck('υλικό με can_bale: υπάρχει κουμπί «Μπάλα» στα μέσα αποθήκευσης', pg.locator('.mtForm[data-form="BALE"]').count() == 1 and pg.locator('.mtForms .mtForm').count() == 5)
    pg.locator('.mtForm[data-form="BALE"]').tap(); pg.wait_for_selector('#mtGross')
    ck('η Μπάλα ζητά μικτό ΚΑΙ απόβαρο', pg.query_selector('#mtTare') is not None)
    pg.fill('#mtGross', '60'); pg.fill('#mtTare', '20'); pg.wait_for_timeout(300)
    ck('περίληψη: «Μπάλα … 40 kg»', 'Μπάλα' in pg.inner_text('#mtSum') and '40' in pg.inner_text('#mtSum'), pg.inner_text('#mtSum'))
    pg.locator('#mtSend').tap(); pg.wait_for_timeout(3000)
    lot = db("select id,is_bale,net_weight,gross_weight,output_form,status from ready_material_lots where material_id=? and is_bale=1", mA['id'])
    ck('ΜΙΑ εγγραφή εξαγωγής με is_bale=1 (παλέτα 40 kg καθαρά)', len(lot) == 1 and float(lot[0][2]) == 40 and float(lot[0][3]) == 60 and lot[0][4] == 'CONTAINER', str(lot))
    a_after = pg.evaluate("m=>api('/mat/warehouse-grouped').then(w=>{let x=w.categories.flatMap(c=>c.materials).find(y=>y.material_id===m);return x?[x.pieces,x.kg]:[0,0]})", mA['id'])
    ck('στο απόθεμα μετράει ΜΙΑ φορά (+1 τεμάχιο, +40 kg)', a_after[0] - a_before[0] == 1 and abs((a_after[1] - a_before[1]) - 40) < 0.01, f'{a_before}→{a_after}')
    h = pg.inner_text('#matHist')
    ck('ιστορικό εξαγωγών: «Μπάλα»', 'Μπάλα' in h and '40 kg' in h, h.replace('\n', ' | ')[:120])
    ck('ιστορικό εξαγωγών: πρώτα το υλικό (έντονα), μετά τα κιλά', pg.evaluate("(()=>{let e=document.querySelector('#matHist .ptItem .ptL1');return !!e&&e.firstElementChild.classList.contains('ptMat')&&e.lastElementChild.classList.contains('ptKg')})()"))
    import re
    code1 = db("select c.code from ready_material_lots l join collection_media c on c.id=l.collection_medium_id where l.material_id=? and l.is_bale=1 order by l.created_at", mA['id'])
    num = lambda c: int(c.rsplit('-B', 1)[1])
    pre = lambda c: c.rsplit('-B', 1)[0]
    ck('κωδικός μπάλας με Β: ΥΥ-ΧΧΧ-Bνννν', len(code1) == 1 and re.fullmatch(r'\d\d-[A-Z]{3}-B\d{4}', code1[0][0]) is not None, str(code1))
    n1 = num(code1[0][0])
    pv = pg.evaluate("m=>api('/mat/next-code?form=PALLET&bale=1&material_id='+m)", mA['id'])
    ck('προεπισκόπηση επόμενου: ο επόμενος αριθμός της κατηγορίας (και χωρίς δέσμευση)', pre(pv['code']) == pre(code1[0][0]) and num(pv['code']) == n1 + 1, str(pv))
    st, r2 = call('POST', '/mat/export', {'material_id': mA['id'], 'form': 'PALLET', 'gross': 30, 'tare': 10, 'is_bale': True})
    ck('δεύτερη μπάλα του ίδιου υλικού: επόμενος αριθμός', st == 200 and r2['medium_code'] == pv['code'], str(r2))
    st, r3 = call('POST', '/mat/export', {'material_id': mA['id'], 'form': 'PALLET', 'gross': 30, 'tare': 10})
    ck('κανονική παλέτα: υπάρχουσα αρίθμηση (χωρίς Β)', st == 200 and '-B' not in r3['medium_code'], str(r3))
    ck('οι άλλες εξαγωγές δεν άγγιξαν τη σειρά των μπαλών', num(pg.evaluate("m=>api('/mat/next-code?form=PALLET&bale=1&material_id='+m)", mA['id'])['code']) == n1 + 2)
    # δεύτερο υλικό: αν είναι στην ίδια κατηγορία συνεχίζει την ΙΔΙΑ σειρά, αλλιώς έχει τη δική της κατηγορία
    pw.evaluate("id=>editMaterialPopup(materialsCache.find(x=>x.id===id))", mB['id']); pw.wait_for_selector('#fpMatBale'); pw.check('#fpMatBale'); pw.click('#fpMatSave'); pw.wait_for_timeout(1200)
    st, r4 = call('POST', '/mat/export', {'material_id': mB['id'], 'form': 'PALLET', 'gross': 30, 'tare': 10, 'is_bale': True})
    c4 = r4['medium_code']
    if pre(c4) == pre(code1[0][0]):
        ck('άλλο υλικό ΙΔΙΑΣ κατηγορίας: συνεχίζει την ίδια σειρά (n+2), όχι ξανά από 1', num(c4) == n1 + 2, c4)
    else:
        ck('άλλο υλικό ΑΛΛΗΣ κατηγορίας: δική της σειρά (πρώτος αριθμός ή επόμενος της κατηγορίας)', re.fullmatch(r'\d\d-[A-Z]{3}-B\d{4}', c4) is not None, c4)
    # μοναδικότητα: κανένας κωδικός δεν επαναλαμβάνεται
    allc = [x[0] for x in db("select code from collection_media where code like '%-B%'")]
    ck('ΟΛΟΙ οι κωδικοί μπαλών (Β) είναι μοναδικοί', len(allc) == len(set(allc)))
    # δύο υλικά ίδιας κατηγορίας από τη βάση: έλεγχος σειράς με άμεσες διαδοχικές εξαγωγές
    same = [m for m in cand if m['id'] not in (mA['id'], mB['id']) and m.get('category_id') == mA.get('category_id')]
    if same:
        pw.evaluate("id=>editMaterialPopup(materialsCache.find(x=>x.id===id))", same[0]['id']); pw.wait_for_selector('#fpMatBale'); pw.check('#fpMatBale'); pw.click('#fpMatSave'); pw.wait_for_timeout(1200)
        seq = []
        for m_ in (mA['id'], same[0]['id'], mA['id'], same[0]['id']):
            st, rr = call('POST', '/mat/export', {'material_id': m_, 'form': 'PALLET', 'gross': 30, 'tare': 10, 'is_bale': True}); seq.append(num(rr['medium_code']))
        ck('ίδια κατηγορία, εναλλάξ δύο υλικά: συνεχόμενοι αριθμοί, χωρίς διπλά', seq == list(range(seq[0], seq[0] + 4)), str(seq))
    pg.evaluate("mt.tab='stock';mtRender()"); pg.wait_for_selector('.mwMat', timeout=15000)
    pg.evaluate("(id)=>{mt.whSel='m:'+id;mtWhPaint()}", mA['id']); pg.wait_for_timeout(300)
    ck('Αποθήκη: το μέσο φαίνεται ως «Μπάλα»', 'Μπάλα' in pg.inner_text('#mwR'), pg.inner_text('#mwR').replace(chr(10), ' | ')[:120])
    # ---- Windows Πρέσα: προστίθενται στις τιμές του Excel ----
    sqlite3.connect(DB).execute("insert into bale_entries(id,period,material_group,bale_seq,weight_kg,is_bulk,bale_count,source,active,created_at,updated_at) values(lower(hex(randomblob(16))),datetime('now','localtime'),'ΠΡΕΣΑ ΔΟΚΙΜΗ',1,100,0,null,'WINDOWS',1,datetime('now'),datetime('now'))").connection.commit()
    pw.click('.nav button[data-view="ready"]'); pw.wait_for_timeout(800)
    pw.click('.readyGroupTab[data-readygroup="PRESS"]'); pw.wait_for_timeout(1500)
    ck('ανοίγει η καρτέλα Πρέσα', pw.query_selector('#readyPressBody') is not None)
    pw.evaluate("readyState.period='month';readyState.cursor=new Date(new Date().getFullYear(),new Date().getMonth(),1)"); pw.evaluate("loadReadyPress()"); pw.wait_for_timeout(1500)
    rows = pw.evaluate("[...document.querySelectorAll('#readyPressBody tr')].map(r=>[...r.children].map(c=>c.innerText.trim()))")
    heads = pw.evaluate("[...document.querySelectorAll('#readyPressHead th')].map(t=>t.innerText.trim())")
    ck('ΔΥΟ γραμμές: «Κιλά» και «Μπάλες» (το «Δέματα» έγινε «Μπάλες»)', len(rows) == 2 and rows[0][0] == 'Κιλά' and rows[1][0] == 'Μπάλες' and 'Δέματα' not in pw.inner_text('#readyPressBody'), str(rows))
    ck('καμία γραμμή με κεχριμπάρι φόντο', pw.query_selector('#readyPressBody tr.pressBaleRow') is None)
    ci = heads.index('ΠΡΕΣΑ ΔΟΚΙΜΗ')
    kg = lambda t: float(t.replace('.', '').replace(',', '.')) if t else 0
    bl = db("select sum(net_weight),count(*) from ready_material_lots where material_id=? and is_bale=1 and status!='CANCELLED'", mA['id'])[0]
    ck('κιλά = Excel 100 + μπάλες εφαρμογής', abs(kg(rows[0][ci]) - (100 + float(bl[0]))) < 0.01, str(rows[0]))
    ck('μπάλες = Excel 1 + μπάλες εφαρμογής', rows[1][ci] == str(1 + bl[1]), str(rows[1]))
    ck('ΣΥΝΟΛΟ προστίθεται κι αυτό (άθροισμα στηλών, κιλά και μπάλες)', abs(sum(kg(x) for x in rows[0][1:-1]) - kg(rows[0][-1])) < 0.01 and sum(kg(x) for x in rows[1][1:-1]) == kg(rows[1][-1]), str(rows))
    # ---- Η Πρέσα δείχνει ΠΑΝΤΑ όλες τις στήλες: υλικά με «Μπορεί να γίνει μπάλα» (μη εμπορικά) + στήλες από τα Excel της Πρέσας (οποιουδήποτε μήνα) ----
    # (με αποθηκευμένες αντιστοιχίσεις: στήλες Πρέσας που ανήκουν στο ΙΔΙΟ υλικό εμφανίζονται ως ΜΙΑ· «Δεν είναι υλικό» κρύβεται· τα ονόματα κεφαλίδας ακολουθούν τη ρύθμιση περιγραφής → συγκρίνεται το data-material)
    exp_cols = pw.evaluate("""async()=>{let pc=await api('/mat/press-columns');let s=new Set(),seen=new Set();[...pc.excel,...pc.materials.map(m=>m.name)].forEach(n=>{let m=readyState.maps&&readyState.maps.pkey[foldKeep(n)];
      if(m&&m.kind==='NONE')return;if(m&&m.kind==='MATERIAL'&&m.material_id){if(seen.has(m.material_id))return;seen.add(m.material_id)}s.add(foldKeep(n))});return [...s]}""")
    got = pw.evaluate("[...document.querySelectorAll('#readyPressHead th[data-material]')].map(t=>foldKeep(t.dataset.material))")
    ck('στήλες Πρέσας = όλα τα can_bale (μη εμπορικά) + όλες οι στήλες Excel, ακόμα και χωρίς κίνηση', len(got) == len(exp_cols) and len(got) >= 12, f'{len(got)} στήλες · λείπουν {sorted(set(exp_cols) - set(got))} · περισσεύουν {sorted(set(got) - set(exp_cols))}')
    ex_db = [r[0] for r in db("select distinct material_group from bale_entries where active=1")]
    ck('οι στήλες Excel (π.χ. πλαστικά) φαίνονται και όταν δεν έχουν το τσεκ μπάλας', sum(1 for n in ex_db if pw.evaluate("n=>foldKeep(n)", n) in got) >= len(ex_db) - 1)   # -1: το ΣΙΔΗΡΟΣ (ΧΥΜΑ) ενώνεται με το ΣΙΔΗΡΟΣ
    zero = pw.evaluate("(()=>{let h=[...document.querySelectorAll('#readyPressHead th')].map(t=>t.innerText.trim());let r=[...document.querySelectorAll('#readyPressBody tr')].map(x=>[...x.children].map(c=>c.innerText.trim()));return h.map((x,i)=>[x,r[0][i],r[1][i]])})()")
    ck('στήλη χωρίς κίνηση: κενά κελιά (0), χωρίς σφάλμα', any(z[1] in ('', '0') and z[2] in ('', '0') for z in zero[1:-1]))
    ck('εμπορικά υλικά ΔΕΝ φαίνονται στην Πρέσα', not any(n.startswith('ΔΟΚΙΜΗ ΕΜΠΟΡΙΚΟ') for n in got))
    ck('επικεφαλίδες στηλών όπως πριν (ΜΕΤΡΗΣΗ … ΣΥΝΟΛΟ)', heads[0] == 'ΜΕΤΡΗΣΗ' and heads[-1] == 'ΣΥΝΟΛΟ', str(heads))
    ck('σφάλματα σελίδας', not errs, str(errs[:2]))
    b.close()
print('ΑΠΟΤΥΧΙΕΣ:', bad)
sys.exit(1 if bad else 0)
