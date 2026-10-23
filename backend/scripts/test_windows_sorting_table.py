"""Δοκιμή Windows › Ταξινόμηση › πίνακας «Καταχώρηση ανά κατηγορία ΑΗΗΕ» (νέα μορφή).
Χρήση: python backend/scripts/test_windows_sorting_table.py http://127.0.0.1:PORT [φάκελος screenshots]   (server σε ΑΝΤΙΓΡΑΦΟ βάσης: γράφει καταχωρήσεις!)"""
import sys, os, re
sys.path.insert(0, os.path.dirname(__file__))
sys.stdout.reconfigure(encoding='utf-8')
from playwright.sync_api import sync_playwright
from _browser import launch
B = sys.argv[1]; S = (sys.argv[2] if len(sys.argv) > 2 else '.') + '/wt_'
bad = []
def ck(name, ok, info=''):
    print(('✓ ' if ok else '✗ ') + name, info)
    if not ok: bad.append(name)
num = lambda s: float(re.sub(r'[^\d,]', '', (s or '').replace('.', '')).replace(',', '.') or 0)
with sync_playwright() as p:
    b = launch(p); errs = []
    ctx = b.new_context(viewport={'width': 1600, 'height': 900})
    pg = ctx.new_page(); pg.on('pageerror', lambda e: errs.append(str(e)))
    pg.goto(B + '/', wait_until='networkidle'); pg.wait_for_selector('#loginBtn', state='visible'); pg.click('#loginBtn'); pg.wait_for_selector('#metrics .card', timeout=20000); pg.wait_for_timeout(1500)
    L = pg.evaluate("api('/sorting/available').then(r=>r.find(x=>x.status!=='SUBMITTED')||r[0])")
    lid = L['load_id']
    cats = pg.evaluate("api('/master/weee-display')")
    internal = next(c for c in cats if c['is_internal_subcategory'] and c['code'].startswith('INT-6A'))
    parent = next(c for c in cats if not c['is_internal_subcategory'] and c['official_code'] == internal['official_code'])
    other = next(c for c in cats if not c['is_internal_subcategory'] and c['active'] and c['id'] != parent['id'] and not re.match(r'^\d+$', c['official_code']))
    media = pg.evaluate("api('/master/media')")
    ms = [m for m in media if re.match(r'^\D*\d+$', str(m['code'])) and m.get('tare_weight') and float(m['tare_weight']) > 0][-3:]
    post = lambda body: pg.evaluate("([lid,b])=>api('/sorting/'+lid+'/entries',{method:'POST',body:JSON.stringify(b)})", [lid, body])
    # καταχωρήσεις «όπως από το Android» (εσωτερική υποκατηγορία, χωρίς εικονίδιο) και μία από PC
    post({'weee_category_id': internal['id'], 'collection_medium_id': ms[0]['id'], 'entry_type': 'SCALE_GROSS', 'raw_weight': 400, 'source': 'ANDROID'})
    post({'weee_category_id': internal['id'], 'collection_medium_id': ms[1]['id'], 'entry_type': 'SCALE_GROSS', 'raw_weight': 300, 'source': 'ANDROID'})
    pg.evaluate("openSortingDetail('%s')" % lid); pg.wait_for_selector('#sfTable tbody.sfBd', timeout=20000); pg.wait_for_timeout(800)
    # ---- B1: στήλες ----
    heads = pg.evaluate("[...document.querySelectorAll('#sfTable thead th')].map(t=>t.innerText.trim())")
    ck('Β1: σειρά στηλών', heads[:8] == ['Κωδικός', 'Περιγραφή', 'Μέσο βάρος', 'Καταχωρήσεις', 'Απόβαρο', 'Τεμ.', 'Μεικτό βάρος', 'Καθαρό βάρος'] and heads[8] == '', str(heads))
    ck('Β1: μεικτό και καθαρό δίπλα-δίπλα', heads.index('Μεικτό βάρος') + 1 == heads.index('Καθαρό βάρος'))
    # ---- A2: οι καταχωρήσεις Android φαίνονται στη γραμμή της επίσημης κατηγορίας ----
    row = pg.evaluate("(c)=>{const r=document.querySelector('#sfTable tr.sfCat[data-c=\"'+c+'\"]');return r?[...r.cells].map(x=>x.innerText.replace(/\\s+/g,' ').trim()):null}", parent['id'])
    print('κεντρική γραμμή (κλειστή):', row)
    ck('Α2: οι καταχωρήσεις του Android φαίνονται (κάψουλες)', row is not None and pg.evaluate("c=>document.querySelectorAll('#sfTable tr.sfCat[data-c=\"'+c+'\"] .sfEn').length", parent['id']) == 2)
    catnet = lambda: pg.evaluate("([id,a,b])=>{clearApiCache();return api('/sorting/'+id+'/detail').then(s=>s.entries.filter(e=>e.weee_category_id===a||e.weee_category_id===b).reduce((t,e)=>t+Number(e.approved_weight!=null?e.approved_weight:e.raw_weight),0))}", [lid, internal['id'], parent['id']])
    ck('Α2: σύνολα στη γραμμή = άθροισμα των καταχωρήσεων της βάσης', row is not None and abs(num(row[7]) - catnet()) < 1, f'{row[7] if row else None} vs {catnet()}')
    # άθροισμα καθαρού όλων των γραμμών = σύνολο ταξινόμησης
    api_tot = pg.evaluate("id=>api('/sorting/'+id+'/detail').then(s=>s.entries.reduce((t,e)=>t+Number(e.approved_weight!=null?e.approved_weight:e.raw_weight),0))", lid)
    tot = sum(num(x) for x in pg.evaluate("[...document.querySelectorAll('#sfTable tr.sfCat .sfSm')].map(c=>c.innerText)"))
    ck('άθροισμα γραμμών = σύνολο ταξινόμησης', abs(tot - api_tot) < 1, f'{tot} vs {api_tot}')
    # ---- Β2/Β6: άνοιγμα κατηγορίας, ευθυγράμμιση, φόρμα ήδη μέσα ----
    pg.evaluate("c=>document.querySelector('#sfTable tr.sfCat[data-c=\"'+c+'\"]').click()", parent['id']); pg.wait_for_timeout(500)
    ck('Β6: η φόρμα καταχώρησης υπάρχει ήδη μέσα στην ανοιχτή κατηγορία (χωρίς κουμπί «+ Νέα»)', pg.evaluate("c=>!!document.querySelector('#sfTable tbody.sfBd[data-c=\"'+c+'\"] tr.sfNr')", parent['id']))
    ck('Β6: ο δείκτης είναι στο πεδίο βάρους (μεικτό)', pg.evaluate("document.activeElement.className")=='sfGr')
    pre = pg.evaluate("c=>{const r=document.querySelector('#sfTable tr.sfNr[data-c=\"'+c+'\"]');return [r.querySelector('.sfT').value,r.querySelector('.sfM').value,r.querySelector('.sfTr').innerText]}", parent['id'])
    print('προσυμπλήρωση:', pre)
    ck('Β6: προσυμπληρωμένο το τελευταίο μέσο (είδος + αριθμός + απόβαρο)', bool(pre[0]) and bool(pre[1]) and num(pre[2]) > 0)
    al = pg.evaluate("""c=>{const tb=document.querySelector('#sfTable tbody.sfBd[data-c="'+c+'"]'),th=[...document.querySelectorAll('#sfTable thead th')].map(t=>t.getBoundingClientRect().left),bad=[];
      [...tb.rows].forEach((r,ri)=>{if(r.cells.length!==th.length){bad.push('γραμμή '+ri+': '+r.cells.length+' κελιά');return}[...r.cells].forEach((cell,i)=>{if(Math.abs(cell.getBoundingClientRect().left-th[i])>1)bad.push('γραμμή '+ri+' στήλη '+i)})});
      return {rows:tb.rows.length,bad}}""", parent['id'])
    ck('Β2: καμία ασυμφωνία στηλών (κεντρική, καταχωρήσεις, φόρμα)', not al['bad'] and al['rows'] >= 4, str(al))
    subs = pg.evaluate("c=>[...document.querySelectorAll('#sfTable tbody.sfBd[data-c=\"'+c+'\"] tr.sfSub')].map(r=>[...r.cells].map(x=>x.innerText.replace(/\\s+/g,' ').trim()))", parent['id'])
    print('υπο-γραμμές:', subs)
    ck('Β2: «Μέσο · Αριθμός» στη στήλη Καταχωρήσεις, απόβαρο/μεικτό/καθαρό από κάτω', len(subs) == 2 and all(re.search(r' · \d+', s[3]) and num(s[4]) > 0 and num(s[6]) > num(s[7]) > 0 for s in subs))
    ck('Β10: οι καταχωρήσεις από Android ΔΕΝ έχουν εικονίδιο', pg.evaluate("c=>document.querySelectorAll('#sfTable tbody.sfBd[data-c=\"'+c+'\"] tr.sfSub .sfIc').length", parent['id']) == 0)
    ck('Β11: ✎ και 🗑 με κενό ~12px', abs(pg.evaluate("c=>{const b=document.querySelectorAll('#sfTable tbody.sfBd[data-c=\"'+c+'\"] tr.sfSub')[0].querySelectorAll('.sfAc button');const a=b[0].getBoundingClientRect(),d=b[1].getBoundingClientRect();return d.left-a.right}", parent['id']) - 12) <= 1.5)
    ck('Β11: έντονη μπλε αριστερή γραμμή στην ανοιχτή κατηγορία', 'inset 4px' in pg.evaluate("c=>getComputedStyle(document.querySelector('#sfTable tr.sfCat[data-c=\"'+c+'\"] td')).boxShadow", parent['id']) or '4px' in pg.evaluate("c=>getComputedStyle(document.querySelector('#sfTable tr.sfCat[data-c=\"'+c+'\"] td')).boxShadow", parent['id']))
    gap = pg.evaluate("c=>{const r=document.querySelector('#sfTable tr.sfNr[data-c=\"'+c+'\"]'),a=r.querySelector('.sfT').getBoundingClientRect(),m=r.querySelector('.sfM').getBoundingClientRect();return m.left-a.right}", parent['id'])
    ck('Β6: Είδος/Αριθμός στη στήλη Καταχωρήσεις με κενό ~10px', abs(gap - 10) <= 1.5, str(gap))
    ck('Β6: κουμπί «Καταχώρηση» (όχι «Enter»)', pg.evaluate("c=>document.querySelector('#sfTable tr.sfNr[data-c=\"'+c+'\"] .sfAdd').innerText.trim()", parent['id']) == 'Καταχώρηση')
    pg.screenshot(path=S + 'open.png')
    # ---- Β7: μεικτό ↔ καθαρό ----
    tare = num(pre[2])
    sel = '#sfTable tr.sfNr[data-c="%s"]' % parent['id']
    pg.fill(sel + ' .sfGr', '500'); pg.wait_for_timeout(100)
    kv = pg.input_value(sel + ' .sfK'); print('μεικτό 500 → καθαρό', kv)
    ck('Β7: γράφω μεικτό → υπολογίζεται καθαρό (auto, διακεκομμένο)', num(kv) > 0 and num(kv) < 500 and pg.evaluate("document.querySelector('%s .sfK').classList.contains('auto')" % sel) and pg.evaluate("!document.querySelector('%s [data-for=K]').hidden" % sel))
    pg.fill(sel + ' .sfGr', ''); pg.fill(sel + ' .sfK', '100'); pg.wait_for_timeout(100)
    gv = pg.input_value(sel + ' .sfGr'); print('καθαρό 100 → μεικτό', gv)
    ck('Β7: γράφω καθαρό → υπολογίζεται μεικτό (auto)', num(gv) > 100 and pg.evaluate("document.querySelector('%s .sfGr').classList.contains('auto')" % sel))
    # ---- Β6: Enter καταχωρεί, η φόρμα μένει, ο δείκτης γυρίζει στο μεικτό ----
    n_before = pg.evaluate("id=>api('/sorting/'+id+'/detail').then(s=>s.entries.length)", lid)
    pg.fill(sel + ' .sfK', '50'); pg.press(sel + ' .sfK', 'Enter'); pg.wait_for_timeout(1200)
    n_after = pg.evaluate("id=>{clearApiCache();return api('/sorting/'+id+'/detail').then(s=>s.entries.length)}", lid)
    ck('Β6: Enter καταχωρεί', n_after == n_before + 1, f'{n_before}→{n_after}')
    ck('Β6: η φόρμα μένει ανοιχτή και ο δείκτης στο πεδίο μεικτού', pg.evaluate("c=>!!document.querySelector('#sfTable tr.sfNr[data-c=\"'+c+'\"]')&&document.activeElement.className", parent['id']) == 'sfGr')
    ck('Β6: το μέσο μένει προσυμπληρωμένο για την επόμενη', pg.input_value(sel + ' .sfM') == pre[1])
    ents = pg.evaluate("id=>{clearApiCache();return api('/sorting/'+id+'/detail').then(s=>s.entries.map(e=>[e.weee_category_id,e.source,Number(e.raw_weight)]))}", lid)
    ck('Β10: η καταχώρηση από PC αποθηκεύτηκε με προέλευση PC', any(e[1] == 'PC' for e in ents), str(ents))
    ck('Β10: μόνο η καταχώρηση PC δείχνει εικονίδιο 💻', pg.evaluate("c=>document.querySelectorAll('#sfTable tbody.sfBd[data-c=\"'+c+'\"] tr.sfSub .sfIc').length", parent['id']) == 1)
    # σύνολο γραμμής μετά τη νέα καταχώρηση
    row = pg.evaluate("(c)=>[...document.querySelector('#sfTable tr.sfCat[data-c=\"'+c+'\"]').cells].map(x=>x.innerText.replace(/\\s+/g,' ').trim())", parent['id'])
    ck('σύνολα κεντρικής γραμμής ενημερώθηκαν (3 καταχωρήσεις)', row[3].startswith('3') and abs(num(row[7]) - catnet()) < 1, f'{row[7]} vs {catnet()}')
    # ---- Β9: ζωντανή εμφάνιση από Android χωρίς να χαθεί ό,τι πληκτρολογεί ο χρήστης ----
    pg.fill(sel + ' .sfK', '77')   # ο χρήστης πληκτρολογεί
    pg.evaluate("([lid,c,m])=>api('/sorting/'+lid+'/entries',{method:'POST',body:JSON.stringify({weee_category_id:c,collection_medium_id:m,entry_type:'SCALE_GROSS',raw_weight:260,source:'ANDROID'})})", [lid, internal['id'], ms[2]['id']])
    pg.wait_for_selector('#sfTable tr.sfSub.sfFresh', timeout=15000); pg.wait_for_timeout(300)
    fresh = pg.evaluate("document.querySelector('#sfTable tr.sfSub.sfFresh').innerText.replace(/\\s+/g,' ')")
    ck('Β9: η νέα γραμμή εμφανίζεται μόνη της, πράσινη, «ΝΕΟ · μόλις τώρα»', 'ΝΕΟ · μόλις τώρα' in fresh, fresh)
    ck('Β9: ειδοποίηση «Νέα καταχώρηση από Android: …»', pg.evaluate("document.getElementById('sfToast')&&document.getElementById('sfToast').innerText")[:36] == 'Νέα καταχώρηση από Android: ' or 'Νέα καταχώρηση από Android' in pg.evaluate("document.getElementById('sfToast').innerText"))
    ck('Β9: ό,τι πληκτρολογεί ο χρήστης δεν χάνεται (τιμή και δείκτης)', pg.input_value(sel + ' .sfK') == '77' and pg.evaluate("document.activeElement.className") == 'sfK')
    row = pg.evaluate("(c)=>[...document.querySelector('#sfTable tr.sfCat[data-c=\"'+c+'\"]').cells].map(x=>x.innerText.replace(/\\s+/g,' ').trim())", parent['id'])
    ck('Β9: τα σύνολα ενημερώθηκαν (4 καταχωρήσεις)', row[3].startswith('4'), str(row))
    pg.screenshot(path=S + 'live.png')
    # ---- Β3: πλάτος στηλών (σύρσιμο, αποθήκευση, διπλό κλικ) ----
    w0 = pg.evaluate("document.querySelector('#sfTable thead th[data-wcol=desc]').getBoundingClientRect().width")
    r = pg.evaluate("(()=>{const r=document.querySelector('#sfTable thead th[data-wcol=desc]').getBoundingClientRect();return {x:r.right-1,y:r.top+r.height-4}})()")
    pg.mouse.move(r['x'], r['y']); pg.mouse.down(); pg.mouse.move(r['x'] + 60, r['y'], steps=6); pg.mouse.up(); pg.wait_for_timeout(300)
    w1 = pg.evaluate("document.querySelector('#sfTable thead th[data-wcol=desc]').getBoundingClientRect().width")
    ck('Β3: το σύρσιμο ορίου αλλάζει το πλάτος στήλης', abs((w1 - w0) - 60) <= 6, f'{w0}→{w1}')
    pg.evaluate("openSortingDetail('%s')" % lid); pg.wait_for_selector('#sfTable tbody.sfBd', timeout=20000); pg.wait_for_timeout(900)
    w2 = pg.evaluate("document.querySelector('#sfTable thead th[data-wcol=desc]').getBoundingClientRect().width")
    ck('Β3: το πλάτος θυμάται μετά το ξανάνοιγμα', abs(w2 - w1) <= 3, f'{w1} → {w2}')
    r = pg.evaluate("(()=>{const r=document.querySelector('#sfTable thead th[data-wcol=desc]').getBoundingClientRect();return {x:r.right-1,y:r.top+r.height-4}})()")
    pg.mouse.move(r['x'], r['y']); pg.mouse.dblclick(r['x'], r['y']); pg.wait_for_timeout(400)
    w3 = pg.evaluate("document.querySelector('#sfTable thead th[data-wcol=desc]').getBoundingClientRect().width")
    ck('Β3: διπλό κλικ στο όριο = αυτόματο πλάτος', abs(w3 - w0) <= 8, f'{w2} → {w3} (αρχικό {w0})')
    # ---- Β4: απόκρυψη/εμφάνιση στηλών με τον υπάρχοντα μηχανισμό (PinTable) ----
    info = pg.evaluate("(()=>{const m=PinTable.model(document.getElementById('sfTable'));return m.cols.map(c=>[c.name,c.ok])})()")
    print('PinTable στήλες:', info)
    lockd = {n: ok for n, ok in info}
    ck('Β4: Κωδικός, Περιγραφή, Καταχωρήσεις, Καθαρό βάρος ΠΑΝΤΑ ορατές (κλειδωμένες)', not lockd['code'] and not lockd['desc'] and not lockd['ens'] and not lockd['net'])
    ck('Β4: οι άλλες στήλες κρύβονται/εμφανίζονται (Μέσο βάρος, Απόβαρο, Τεμ., Μεικτό)', lockd['avg'] and lockd['tare'] and lockd['pcs'] and lockd['gross'])
    r = pg.evaluate("(()=>{const r=document.querySelector('#sfTable thead th[data-wcol=tare]').getBoundingClientRect();return {x:r.left+r.width/2,y:r.top+r.height/2,right:r.right}})()")
    eye = 0
    for i in range(8):
        pg.mouse.move(r['x'] + i * 3, r['y']); pg.wait_for_timeout(700)
        eye = pg.evaluate("document.querySelectorAll('.pinLayer .pinEye').length")
        if eye: break
    ck('Β4: εικονίδιο απόκρυψης (PinTable) στη στήλη Απόβαρο', eye == 1, str(eye))
    pg.evaluate("document.querySelector('.pinLayer .pinEye').click()"); pg.wait_for_timeout(500)
    hid = pg.evaluate("getComputedStyle(document.querySelector('#sfTable thead th[data-wcol=tare]')).display")
    ck('Β4: η στήλη Απόβαρο κρύφτηκε (και στις γραμμές)', hid == 'none' and pg.evaluate("[...document.querySelectorAll('#sfTable tbody tr')].every(r=>!r.cells[4]||getComputedStyle(r.cells[4]).display==='none')"))
    pg.evaluate("PinTable.model(document.getElementById('sfTable'))"); pg.evaluate("localStorage.setItem('keep','1')")
    marks = pg.evaluate("document.querySelectorAll('.pinMkLayer .pinMk').length")
    ck('Β4: ένδειξη κρυμμένης στήλης για επαναφορά', marks >= 1, str(marks))
    pg.evaluate("document.querySelector('.pinMkLayer .pinMk').click()"); pg.wait_for_timeout(500)
    ck('Β4: η στήλη Απόβαρο επανεμφανίζεται', pg.evaluate("getComputedStyle(document.querySelector('#sfTable thead th[data-wcol=tare]')).display") != 'none')
    # ---- Β5: σταθερή επικεφαλίδα ----
    pg.evaluate("document.getElementById('sortingDetail').scrollTop=700"); pg.wait_for_timeout(300)
    hd = pg.evaluate("(()=>{const th=document.querySelector('#sfTable thead th').getBoundingClientRect(),ph=document.querySelector('#sortingDetail .sortingPopupHeader').getBoundingClientRect();return {thTop:th.top,thBottom:th.bottom,phBottom:ph.bottom,sh:getComputedStyle(document.querySelector('#sfTable thead th')).boxShadow}})()")
    ck('Β5: η επικεφαλίδα μένει κολλημένη κάτω από την κεφαλίδα του παραθύρου, με σκιά', abs(hd['thTop'] - hd['phBottom']) <= 3 and hd['sh'] != 'none', str(hd))
    pg.screenshot(path=S + 'scrolled.png')
    # ---- Βήμα 1: όψη/πλάτη όπως πριν (χωρίς αλλαγή χρωμάτων, χωρίς ξέφευγμα δεξιά, σύρσιμο χωρίς «πήδημα») ----
    pg.evaluate("openSortingDetail('%s')" % lid); pg.wait_for_selector('#sfTable tbody.sfBd', timeout=20000); pg.wait_for_timeout(800)
    g = pg.evaluate("""(()=>{const sd=document.getElementById('sortingDetail'),t=document.getElementById('sfTable'),th=t.querySelector('thead th'),td=t.querySelector('tbody tr.sfCat td'),hasTd=t.querySelector('tr.sfCat.has td'),cs=getComputedStyle;
      return {popup:sd.getBoundingClientRect().width,vw:innerWidth,hs:sd.scrollWidth>sd.clientWidth+1,desc:t.querySelector('th[data-wcol=desc]').getBoundingClientRect().width,
        thBg:cs(th).backgroundColor,thBb:cs(th).borderBottomWidth,tdBb:cs(td).borderBottomWidth,tdBt:cs(td).borderTopColor,hasBg:cs(hasTd).backgroundColor}})()""")
    print('όψη:', g)
    ck('Βήμα 1: το παράθυρο έχει το αρχικό πλάτος (≤1040) και δεν βγαίνει εκτός οθόνης', g['popup'] <= 1041 and g['popup'] <= g['vw'], str(g['popup']))
    ck('Βήμα 1: καμία οριζόντια μπάρα με τα προεπιλεγμένα πλάτη', not g['hs'])
    ck('Βήμα 1: η Περιγραφή έχει χώρο (≥140px)', g['desc'] >= 140, str(g['desc']))
    ck('Βήμα 1: ίδια χρώματα με πριν (κεφαλίδα #f0f3fa, επιλεγμένη γραμμή, περίγραμμα #e3e5ec)', g['thBg'] == 'rgb(240, 243, 250)' and g['tdBt'] == 'rgb(227, 229, 236)' and g['hasBg'].startswith('color(srgb 0.93'), str((g['thBg'], g['tdBt'], g['hasBg'])))
    ck('Βήμα 1: χωρίς διπλά περιγράμματα', g['tdBb'] == '0px' and g['thBb'] == '0px')
    for col, dx in (('avg', 40), ('avg', -30), ('pcs', -12), ('gross', -25), ('desc', 50), ('desc', -50)):
        rr = pg.evaluate("c=>{const r=document.querySelector('#sfTable thead th[data-wcol=\"'+c+'\"]').getBoundingClientRect();return {x:r.right-1,y:r.bottom-4}}", col)
        w0 = pg.evaluate("c=>document.querySelector('#sfTable thead th[data-wcol=\"'+c+'\"]').getBoundingClientRect().width", col)
        pg.mouse.move(rr['x'], rr['y']); pg.mouse.down(); pg.mouse.move(rr['x'] + dx, rr['y'], steps=6)
        wm = pg.evaluate("c=>document.querySelector('#sfTable thead th[data-wcol=\"'+c+'\"]').getBoundingClientRect().width", col)
        pg.mouse.up(); pg.wait_for_timeout(900)
        w9 = pg.evaluate("c=>document.querySelector('#sfTable thead th[data-wcol=\"'+c+'\"]').getBoundingClientRect().width", col)
        ck(f'Βήμα 1: σύρσιμο {col} {dx:+d}px — μένει εκεί που την άφησα', abs(w9 - wm) <= 2 and abs((wm - w0) - dx) <= 6, f'{w0:.0f}→{wm:.0f}→{w9:.0f}')
    # ---- Α2: κατηγορία που λείπει από τη λίστα (π.χ. ανενεργή) φαίνεται ΠΑΝΤΑ ----
    ck('σφάλματα σελίδας', not errs, str(errs[:3]))
    b.close()
print('ΑΠΟΤΥΧΙΕΣ:', bad)
sys.exit(1 if bad else 0)
