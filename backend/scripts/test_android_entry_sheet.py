"""Δοκιμή Android › ΠΑΡΑΛΑΒΕΣ › «Καταχωρήσεις»: γραμμές χωρίς κουμπιά + bottom sheet (ΕΠΕΞΕΡΓΑΣΙΑ / ΔΙΑΓΡΑΦΗ με επιβεβαίωση).
Χρήση: python backend/scripts/test_android_entry_sheet.py http://127.0.0.1:PORT [φάκελος screenshots]   (server σε ΑΝΤΙΓΡΑΦΟ βάσης: γράφει/διαγράφει καταχωρήσεις!)"""
import sys, os, re
sys.path.insert(0, os.path.dirname(__file__))
sys.stdout.reconfigure(encoding='utf-8')
from playwright.sync_api import sync_playwright
from _browser import launch
B = sys.argv[1]; S = (sys.argv[2] if len(sys.argv) > 2 else '.') + '/s_'
bad = []
def ck(name, ok, info=''):
    print(('✓ ' if ok else '✗ ') + name, info)
    if not ok: bad.append(name)
with sync_playwright() as p:
    b = launch(p); errs = []
    pg = b.new_page(viewport={'width': 360, 'height': 640}, is_mobile=True, has_touch=True, device_scale_factor=1)
    pg.on('pageerror', lambda e: errs.append(str(e)))
    pg.goto(B + '/mobile', wait_until='networkidle'); pg.click('#loginBtn'); pg.wait_for_selector('#app:not(.hidden)'); pg.wait_for_timeout(2500)
    L = pg.evaluate("api('/sorting/available').then(r=>r.find(x=>x.status!=='SUBMITTED'&&Number(x.net_weight)>0)||r[0])")
    lid = L['load_id']
    cats = pg.evaluate("cats.filter(c=>c.active!==false&&!c.is_internal_subcategory).slice(0,12).map(c=>c.id)")
    meds = pg.evaluate("media.filter(m=>/^\\D*\\d+$/.test(m.code)&&Number(m.tare_weight)>0).slice(-5)")
    post = lambda body: pg.evaluate("([lid,b])=>api('/sorting/'+lid+'/entries',{method:'POST',body:JSON.stringify(b)})", [lid, body])
    for i in range(10):
        if i < 4:
            post({'weee_category_id': cats[i], 'collection_medium_id': meds[i]['id'], 'entry_type': 'SCALE_GROSS', 'raw_weight': 300 + i, 'piece_count': None, 'notes': None})
        else:
            post({'weee_category_id': cats[i], 'collection_medium_id': None, 'entry_type': 'MEDIUM', 'raw_weight': 20 + i, 'piece_count': None, 'notes': None})
    pg.evaluate("document.querySelector('#loadList [data-id=\"%s\"]').click()" % lid); pg.wait_for_timeout(2500)
    rows = pg.evaluate("[...document.querySelectorAll('#entries .enItem')].map(r=>{const b=r.getBoundingClientRect();return {h:Math.round(b.height),t:r.innerText.replace(/\\s+/g,' ').trim()}})")
    print(len(rows), rows[:3])
    ck('10 γραμμές καταχωρήσεων', len(rows) == 10)
    ck('κάθε γραμμή ≥ 56px', all(r['h'] >= 56 for r in rows), str(min(r['h'] for r in rows)))
    ck('δεν υπάρχουν κουμπιά EDIT / ΔΙΑΓΡΑΦΗ στη λίστα', pg.evaluate("document.querySelectorAll('#entries button').length") == 0)
    ck('βελάκι › σε κάθε γραμμή', pg.evaluate("document.querySelectorAll('#entries .enGo').length") == 10)
    ck('γραμμές με απόβαρο χωρίς δεκαδικά', all(re.search(r'απόβαρο \d+ kg', r['t']) for r in rows if 'Χύμα' not in r['t']) and not any(re.search(r'\d\.000|απόβαρο \d+,\d', r['t']) for r in rows))
    ck('λεπτή γραμμή διαχωρισμού', pg.evaluate("getComputedStyle(document.querySelectorAll('#entries .enItem')[1]).borderTopWidth")=='1px')
    # κύλιση: η τελευταία γραμμή φτάνει πάνω από το κουμπί ΟΛΟΚΛΗΡΩΣΑ και κάτω από τη μπάρα
    pg.evaluate("window.scrollTo(0,document.body.scrollHeight)"); pg.wait_for_timeout(300)
    g = pg.evaluate("(()=>{const l=[...document.querySelectorAll('#entries .enItem')].pop().getBoundingClientRect(),t=document.querySelector('.top').getBoundingClientRect(),c=document.getElementById('confirm').getBoundingClientRect();return {lt:l.top,lb:l.bottom,topB:t.bottom,confT:c.top}})()"); print(g)
    ck('η λίστα κυλά και η τελευταία γραμμή φαίνεται (όχι κάτω από τη μπάρα ή το ΟΛΟΚΛΗΡΩΣΑ)', g['lt'] >= g['topB'] and g['lb'] <= g['confT'] + 1)
    NI = next(i for i, r in enumerate(rows) if 'απόβαρο' in r['t'])      # γραμμή με αριθμημένο μέσο και απόβαρο
    pg.evaluate("i=>document.querySelectorAll('#entries .enItem')[i].scrollIntoView({block:'center'})", NI); pg.wait_for_timeout(200)
    first_txt = pg.evaluate("document.querySelectorAll('#entries .enItem')[1].innerText.replace(/\\s+/g,' ')")
    pg.tap(f'#entries .enItem >> nth={NI}'); pg.wait_for_timeout(400)
    sh = pg.evaluate("(()=>{const p=document.querySelector('.shPanel').getBoundingClientRect(),cs=getComputedStyle(document.querySelector('.shPanel')),bs=[...document.querySelectorAll('.shBtns button')].map(b=>{const r=b.getBoundingClientRect(),c=getComputedStyle(b);return [b.innerText,Math.round(r.height),c.fontSize,c.fontWeight,c.backgroundColor]});return {vis:!document.getElementById('enSheet').classList.contains('hidden'),bottom:Math.round(innerHeight-p.bottom),rad:cs.borderTopLeftRadius,txt:document.getElementById('enSheetBody').innerText.replace(/\\s+/g,' '),bs}})()"); print(sh)
    ck('πάτημα γραμμής ανοίγει το παράθυρο από κάτω', sh['vis'] and sh['bottom'] <= 1)
    ck('στρογγυλεμένες πάνω γωνίες', sh['rad'] == '16px')
    ck('περιεχόμενο: κατηγορία, μέσο · αριθμός · kg', re.search(r'· \d+ · \d+ kg', sh['txt']) is not None, sh['txt'])
    ck('κουμπιά ΕΠΕΞΕΡΓΑΣΙΑ / ΔΙΑΓΡΑΦΗ 44px, 13px έντονα', [x[0] for x in sh['bs']] == ['ΕΠΕΞΕΡΓΑΣΙΑ', 'ΔΙΑΓΡΑΦΗ'] and all(x[1] == 44 and x[2] == '13px' and x[3] == '700' for x in sh['bs']))
    pg.screenshot(path=S + 'sheet.png')
    # κλείσιμο: έξω από το παράθυρο
    pg.tap('.shBack', position={'x': 180, 'y': 60}); pg.wait_for_timeout(300)
    ck('κλείνει πατώντας έξω', pg.evaluate("document.getElementById('enSheet').classList.contains('hidden')"))
    # κλείσιμο: Πίσω
    pg.tap(f'#entries .enItem >> nth={NI}'); pg.wait_for_timeout(300)
    ck('κλείνει με «Πίσω»', pg.evaluate("window.appBack()") is True and pg.evaluate("document.getElementById('enSheet').classList.contains('hidden')"))
    # ΕΠΕΞΕΡΓΑΣΙΑ
    pg.tap(f'#entries .enItem >> nth={NI}'); pg.wait_for_timeout(300); pg.tap('.shEdit'); pg.wait_for_timeout(800)
    ck('ΕΠΕΞΕΡΓΑΣΙΑ ανοίγει την φόρμα διόρθωσης', pg.evaluate("!document.getElementById('entry').classList.contains('hidden')&&/Edit/.test(document.getElementById('entryTitle').innerText)") and pg.evaluate("document.getElementById('enSheet').classList.contains('hidden')"))
    pg.evaluate("document.getElementById('cancel').click()"); pg.wait_for_timeout(300)
    # ΔΙΑΓΡΑΦΗ με επιβεβαίωση
    before = pg.evaluate("document.querySelectorAll('#entries .enItem').length")
    pg.evaluate("document.querySelectorAll('#entries .enItem')[2].scrollIntoView({block:'center'})"); pg.tap('#entries .enItem >> nth=2'); pg.wait_for_timeout(300); pg.tap('.shDel'); pg.wait_for_timeout(300)
    conf = pg.evaluate("document.getElementById('enSheetBody').innerText.replace(/\\s+/g,' ')"); print(conf)
    ck('ζητά επιβεβαίωση «Να διαγραφεί η καταχώρηση;» με Ακύρωση / Διαγραφή', 'Να διαγραφεί η καταχώρηση;' in conf and 'Ακύρωση' in conf and 'Διαγραφή' in conf)
    pg.screenshot(path=S + 'confirm.png')
    pg.tap('.shEdit'); pg.wait_for_timeout(300)   # Ακύρωση
    ck('Ακύρωση: δεν διαγράφει, επιστρέφει στο παράθυρο', pg.evaluate("document.querySelectorAll('#entries .enItem').length") == before and 'ΕΠΕΞΕΡΓΑΣΙΑ' in pg.inner_text('#enSheetBody'))
    pg.tap('.shDel'); pg.wait_for_timeout(300); pg.tap('.shDel'); pg.wait_for_timeout(1800)
    ck('Διαγραφή: διαγράφει και κλείνει', pg.evaluate("document.querySelectorAll('#entries .enItem').length") == before - 1 and pg.evaluate("document.getElementById('enSheet').classList.contains('hidden')"))
    api_n = pg.evaluate("id=>api('/sorting/'+id).then(s=>s.entries.length)", lid)
    ck('και στη βάση (μέσω API) 9 καταχωρήσεις', api_n == 9, str(api_n))
    ck('σφάλματα σελίδας', not errs, str(errs))
    b.close()
print('ΑΠΟΤΥΧΙΕΣ:', bad)
sys.exit(1 if bad else 0)
