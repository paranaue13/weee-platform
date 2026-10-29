"""Καρτέλες Υλικών + αντιστοιχίσεις ετικετών (ΜΟΝΟ σε αντίγραφο, πόρτα 8020, env LM_COPY)."""
import sys, os, sqlite3
sys.path.insert(0, os.path.dirname(__file__)); sys.stdout.reconfigure(encoding='utf-8')
from playwright.sync_api import sync_playwright
from _browser import launch
B = 'http://127.0.0.1:8020'
cp = os.environ.get('LM_COPY'); assert cp and 'lm_test' in cp
with sync_playwright() as p:
    b = launch(p)
    pg = b.new_page(viewport={'width': 1700, 'height': 950})
    errs = []; pg.on('pageerror', lambda e: errs.append(str(e)))
    pg.goto(B + '/', wait_until='networkidle')
    pg.wait_for_selector('#loginBtn', state='visible'); pg.click('#loginBtn')
    pg.wait_for_selector('#metrics .card', timeout=20000); pg.wait_for_timeout(1200)
    ev = lambda js, a=None: pg.evaluate(js, a) if a is not None else pg.evaluate(js)
    # μήνας με δεδομένα: Σεπτέμβριος 2026
    def open_ready(grp='AXIOPOIISIMA'):
        pg.evaluate("g=>{document.querySelector('[data-view=ready]').click()}", grp)
        pg.wait_for_timeout(800)
        pg.evaluate("g=>{readyState.cursor=new Date(2026,8,1);readyState.period='month';readyState.activeGroup=g;return loadReadyMaterials()}", grp)
        pg.wait_for_timeout(1500)
    open_ready()
    heads0 = ev("()=>[...document.querySelectorAll('#readyMatHead th[data-material]')].map(x=>x.dataset.material)")
    print('Αξιοποιήσιμα χωρίς αντιστοιχίσεις: στήλες', len(heads0))
    # --- επιλογή ετικετών ---
    lab = ev("()=>readyAllLabels.filter(x=>effGroup(x.label,x.category_group)==='AXIOPOIISIMA'&&!PLAKETES_LABELS.has(x.label)).map(x=>x.label)")
    print('ετικέτες καρτέλας:', len(lab))
    kgs = ev("()=>{const m={};readyState.entries.forEach(e=>{m[e.material_label]=(m[e.material_label]||0)+Number(e.weight_kg||0)});return m}")
    withkg = [l for l in sorted(lab, key=lambda l: -kgs.get(l, 0)) if kgs.get(l, 0) > 0]
    rest = [l for l in lab if l not in withkg[:3]]
    S1, S2, INA = withkg[0], withkg[1], withkg[2]
    A, R, SUMLAB = rest[0], rest[1], rest[2]
    print('ετικέτες με κιλά Σεπτ.:', S1, round(kgs[S1], 1), '|', S2, round(kgs[S2], 1), '|', INA, round(kgs[INA], 1))
    # υλικά στο αντίγραφο: ομπρέλα + μέλη ομάδας ετικέτας + ανενεργό
    mats = ev("()=>api('/mat/label-universe').then(u=>u.materials.filter(m=>!m.comm).slice(0,200).map(m=>({id:m.id,erp:m.erp,name:m.name,active:m.active})))")
    act = [m for m in mats if m['active']]
    umb, m1, m2 = act[0], act[1], act[2]
    inactive_m = next((m for m in mats if not m['active']), None)
    cx = sqlite3.connect(cp)
    cx.execute("update materials set is_umbrella=1 where id=?", (umb['id'],))
    pressnames = [r[0] for r in cx.execute("select material_group from bale_entries where active=1 group by material_group order by count(*) desc limit 2")]
    print('στήλες Πρέσας για μέλη:', pressnames)
    cx.execute("update materials set label_group='ΟΜΑΔΑ ΔΟΚΙΜΗ', label_group_order=0, press_label=? where id=?", (pressnames[0], m1['id']))
    cx.execute("update materials set label_group='ΟΜΑΔΑ ΔΟΚΙΜΗ', label_group_order=1, press_label=? where id=?", (pressnames[1], m2['id']))
    cx.commit(); cx.close()
    w = ev("()=>api('/mat/label-universe').then(u=>u.weee.find(x=>x.stock_kg>0)||u.weee[0])")
    print('ΑΗΗΕ για παραλαβές:', w['code'], w['stock_kg'])
    items = [
        {'source': 'EXCEL', 'label': A, 'kind': 'NONE'},
        {'source': 'EXCEL', 'label': S1, 'kind': 'BULK_SUB', 'material_id': umb['id'], 'sort_order': 0},
        {'source': 'EXCEL', 'label': S2, 'kind': 'BULK_SUB', 'material_id': umb['id'], 'sort_order': 1},
        {'source': 'EXCEL', 'label': R, 'kind': 'RECEIPTS', 'weee_category_id': w['id']},
        {'source': 'EXCEL', 'label': SUMLAB, 'kind': 'SUM', 'group_name': 'ΟΜΑΔΑ ΔΟΚΙΜΗ'},
    ]
    if inactive_m: items.append({'source': 'EXCEL', 'label': INA, 'kind': 'MATERIAL', 'material_id': inactive_m['id']})
    ev("it=>api('/mat/label-maps/save',{method:'POST',body:JSON.stringify({items:it})})", items)
    open_ready()
    heads = ev("()=>[...document.querySelectorAll('#readyMatHead th[data-material]')].map(x=>x.dataset.material+'|'+x.textContent.trim())")
    keys = [h.split('|')[0] for h in heads]
    print('NONE κρυμμένη:', A not in keys)
    print('υποκατηγορίες δεν έχουν δικές τους στήλες:', S1 not in keys and S2 not in keys)
    print('ομπρέλα ως ΜΙΑ στήλη:', ('UMB:' + umb['id']) in keys, '| άθροισμα:', 'SUM:ΟΜΑΔΑ ΔΟΚΙΜΗ' in keys, '| παραλαβές:', R in keys)
    print('ανενεργό με/χωρίς κίνηση:', INA in keys, '(ανενεργό υλικό υπάρχει:', bool(inactive_m), ')')
    tot_cells = ev("()=>[...document.querySelectorAll('#readyMatFoot tr')].find(r=>r.children[0].textContent.startsWith('Σύνολο')).children.length")
    # κλικ για άνοιγμα ομπρέλας
    pg.click(f"#readyMatHead th[data-rmtoggle='UMB:{umb['id']}']"); pg.wait_for_timeout(500)
    rows = ev("()=>document.querySelectorAll('#readyMatHead tr').length")
    print('γραμμές κεφαλίδας ανοιχτής ομπρέλας:', rows)
    sub = ev("()=>[...document.querySelectorAll('#readyMatHead tr:nth-child(2) th')].map(x=>x.textContent.trim())")
    print('δεύτερη γραμμή:', sub)
    # σύνολο = άθροισμα υποκατηγοριών στη γραμμή «Σύνολο» (foot)
    vals = ev("""()=>{const r=[...document.querySelectorAll('#readyMatFoot tr')].find(r=>r.children[0].textContent.startsWith('Σύνολο'));
      const g=[...r.querySelectorAll('td.rmG')].map(x=>Number(x.textContent.replace(/\\./g,'').replace(',','.'))||0);return g}""")
    print('σύνολο ομπρέλας / υποκατηγορίες:', vals[0], vals[1:], '| άθροισμα ισχύει:', abs(vals[0] - sum(vals[1:])) < 0.01)
    fr = ev("()=>{const c=document.querySelector('#readyMatFoot td.rmGL');return c?getComputedStyle(c,'::after').borderLeftWidth:null}")
    print('πλαίσιο 2px αριστερά του «Σύνολο»:', fr)
    # στήλη-άθροισμα ετικέτας: κιλά = Πρέσα μελών
    pg.click("#readyMatHead th[data-rmtoggle='SUM:ΟΜΑΔΑ ΔΟΚΙΜΗ']"); pg.wait_for_timeout(500)
    sub2 = ev("()=>[...document.querySelectorAll('#readyMatHead tr:nth-child(2) th')].map(x=>x.textContent.trim())")
    print('άνοιγμα αθροίσματος, δεύτερη γραμμή:', sub2)
    pk = ev("""()=>{const r=[...document.querySelectorAll('#readyMatFoot tr')].find(r=>r.children[0].textContent.startsWith('Σύνολο'));
       return {all:[...r.children].map(x=>x.textContent.trim()).slice(0,40)}}""")
    srv = ev("""()=>api('/production/press-bales?start=2026-09-01&end=2026-09-30').then(a=>a.reduce((m,e)=>{m[e.material_group]=(m[e.material_group]||0)+Number(e.weight_kg||0);return m},{}))""")
    print('Πρέσα Σεπτ. για τα 2 μέλη (server):', {k: round(srv.get(k, 0), 1) for k in pressnames})
    # παραλαβές: τρέχον απόθεμα
    rb = ev(f"""()=>{{const i=[...document.querySelectorAll('#readyMatHead th[data-material]')].findIndex(x=>x.dataset.material==={R!r});return i}}""")
    # κλείνουν όλες οι ομάδες και διαβάζονται οι τιμές ανά στήλη
    ev("()=>{readyState.colOpen.clear();renderReadyMaterials()}")
    colv = ev("""()=>{const keys=[...document.querySelectorAll('#readyMatHead th[data-material]')].map(x=>x.dataset.material);
      const row=n=>[...document.querySelectorAll('#readyMatFoot tr')].find(r=>r.children[0].textContent.trim().startsWith(n));
      const o={};['Σύνολο','Τρέχον απόθεμα','Τεμάχια'].forEach(n=>{const r=row(n);o[n]=Object.fromEntries(keys.map((k,i)=>[k,r.children[i+2].textContent.trim()]))});return o}""")
    print('Σύνολο ομάδας ετικέτας (UI):', colv['Σύνολο'].get('SUM:ΟΜΑΔΑ ΔΟΚΙΜΗ'), '| server Πρέσα μελών:', round(sum(srv.get(k, 0) for k in pressnames), 1))
    print('Σύνολο ομπρέλας (UI):', colv['Σύνολο'].get('UMB:' + umb['id']), '| αναμενόμενο:', round(kgs[S1] + kgs[S2], 1))
    print('Τρέχον απόθεμα παραλαβών (UI):', colv['Τρέχον απόθεμα'].get(R), '| ανενεργό με κίνηση εμφανίζεται:', INA in colv['Σύνολο'], '| κεφαλίδα:', ev("i=>{const t=[...document.querySelectorAll('#readyMatHead th[data-material]')].find(x=>x.dataset.material===i);return t&&t.textContent.trim()}", INA))
    print('index στήλης παραλαβών:', rb)
    # αναδιάταξη με σύρσιμο υποκατηγοριών (API μέσω σύρσιμου)
    pg.click("#readyMatHead th[data-rmtoggle='UMB:" + umb['id'] + "']"); pg.wait_for_timeout(400)
    subs_before = ev(f"()=>readyState.maps.umb['{umb['id']}'].subs.map(s=>s.label)")
    s_els = pg.locator("#readyMatHead [data-sub]")
    print('υποκατηγορίες ορατές:', s_els.count())
    s_els.nth(0).drag_to(s_els.nth(1)); pg.wait_for_timeout(1500)
    subs_after = ev(f"()=>readyState.maps.umb['{umb['id']}'].subs.map(s=>s.label)")
    print('σειρά υποκατηγοριών πριν/μετά το σύρσιμο:', subs_before, '→', subs_after)
    ev("()=>{readyState.colOpen.clear();renderReadyMaterials()}")
    pg.click("#readyMatHead th[data-rmtoggle='SUM:ΟΜΑΔΑ ΔΟΚΙΜΗ']"); pg.wait_for_timeout(400)
    g_before = ev("()=>readyState.maps.grp['ΟΜΑΔΑ ΔΟΚΙΜΗ'].members.map(m=>m.name)")
    s_els = pg.locator("#readyMatHead [data-sub]")
    s_els.nth(0).drag_to(s_els.nth(1)); pg.wait_for_timeout(1500)
    g_after = ev("()=>readyState.maps.grp['ΟΜΑΔΑ ΔΟΚΙΜΗ'].members.map(m=>m.name)")
    print('σειρά μελών ομάδας ετικέτας πριν/μετά:', g_before, '→', g_after)
    # η ομάδα μετακινείται ως ΕΝΑ σύνολο σε άλλη καρτέλα (σύρσιμο στο κουμπί καρτέλας)
    ev("()=>{readyState.colOpen.clear();renderReadyMaterials()}")
    pg.locator("#readyMatHead th[data-material='UMB:" + umb['id'] + "']").drag_to(pg.locator("#readyGroupTabs [data-readygroup='APORRIPSI']")); pg.wait_for_timeout(1500)
    moved = ev(f"()=>readyState.maps.umb['{umb['id']}'].subs.map(s=>effGroup(s.label,'AXIOPOIISIMA'))")
    print('μετά το σύρσιμο στην καρτέλα Απόρριψη, καρτέλες των υποκατηγοριών:', moved)
    ev("g=>{readyState.activeGroup=g;return loadReadyMaterials()}", 'APORRIPSI'); pg.wait_for_timeout(1200)
    print('ομπρέλα στην καρτέλα Απόρριψη:', ev("k=>[...document.querySelectorAll('#readyMatHead th[data-material]')].some(x=>x.dataset.material===k)", 'UMB:' + umb['id']))
    # --- Φορτώσεις → Προετοιμασία: ομπρέλα = ΜΙΑ γραμμή με ανάλυση ---
    pg.click('[data-view=loading]'); pg.wait_for_timeout(600)
    pg.click('[data-lsub=prep]'); pg.wait_for_timeout(2500)
    wh = ev("()=>[...document.querySelectorAll('#pfWhList .prepBulk')].map(x=>x.dataset.bk)")
    print('Χύμα γραμμές στις Φορτώσεις:', len(wh), '| ομπρέλα ως μία γραμμή:', ('UMB:' + umb['id']) in wh, '| υποκατηγορίες κρυμμένες μέχρι να ανοίξει:', S1 not in wh and S2 not in wh, '| NONE κρυμμένη:', A not in wh)
    if ('UMB:' + umb['id']) in wh:
        pg.click(f"#pfWhList [data-arrb='UMB:{umb['id']}']"); pg.wait_for_timeout(500)
        wh2 = ev("()=>[...document.querySelectorAll('#pfWhList .prepBulk')].map(x=>x.dataset.bk)")
        print('μετά το άνοιγμα, υποκατηγορίες:', [x for x in wh2 if x in (S1, S2)])
    print('JS errors:', errs)
    pg.screenshot(path=os.environ['TEMP'] + '/ready_maps.png')
    b.close()
