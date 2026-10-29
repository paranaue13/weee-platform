"""Καρτέλες Υλικών με τις πραγματικές αντιστοιχίσεις του χρήστη (ΜΟΝΟ σε αντίγραφο, πόρτα 8020, μετά το xl_apply_mapping.py)."""
import sys, os
sys.path.insert(0, os.path.dirname(__file__)); sys.stdout.reconfigure(encoding='utf-8')
from playwright.sync_api import sync_playwright
from _browser import launch
B = 'http://127.0.0.1:8020'
with sync_playwright() as p:
    b = launch(p)
    pg = b.new_page(viewport={'width': 1700, 'height': 950})
    errs = []; pg.on('pageerror', lambda e: errs.append(str(e)))
    pg.goto(B + '/', wait_until='networkidle')
    pg.wait_for_selector('#loginBtn', state='visible'); pg.click('#loginBtn')
    pg.wait_for_selector('#metrics .card', timeout=20000); pg.wait_for_timeout(1200)
    ev = lambda js, a=None: pg.evaluate(js, a) if a is not None else pg.evaluate(js)
    pg.evaluate("()=>document.querySelector('[data-view=ready]').click()"); pg.wait_for_timeout(700)
    for g, nm in [('AXIOPOIISIMA', 'Αξιοποιήσιμα'), ('EIDIKIS_DIACHEIRISIS', 'Ειδικής Διαχείρισης'), ('PLAKETES', 'Πλακέτες'), ('APORRIPSI', 'Προς Απόρριψη')]:
        ev("g=>{readyState.cursor=new Date(2026,8,1);readyState.period='month';readyState.activeGroup=g;readyState.colOpen=new Set();return loadReadyMaterials()}", g); pg.wait_for_timeout(1800)
        heads = ev("()=>[...document.querySelectorAll('#readyMatHead th[data-material]')].map(x=>x.textContent.trim())")
        grp = ev("()=>[...document.querySelectorAll('#readyMatHead th[data-rmtoggle]')].map(x=>x.dataset.rmtoggle)")
        print(f'== {nm}: {len(heads)} στήλες · ομαδοποιημένες: {grp}')
        print('   ', heads[:60])
        # άνοιγμα όλων των ομάδων και έλεγχος αθροίσματος «Σύνολο» = άθροισμα υποκατηγοριών (γραμμή Σύνολο περιόδου)
        for k in grp:
            ev("k=>{readyState.colOpen.add(k);renderReadyMaterials()}", k)
        if grp:
            chk = ev("""()=>{const r=[...document.querySelectorAll('#readyMatFoot tr')].find(r=>r.children[0].textContent.trim().startsWith('Σύνολο'));
              const tops=[...document.querySelectorAll('#readyMatHead tr:first-child th[data-rmtoggle]')];
              const cells=[...r.children].slice(2);const num=t=>Number(String(t).replace(/\\./g,'').replace(',','.'))||0;
              // κάθε ομάδα: το πρώτο κελί με .rmGL είναι το σύνολο, τα επόμενα έως .rmGR οι υποκατηγορίες
              const out=[];let i=0;while(i<cells.length){if(cells[i].classList.contains('rmGL')){let tot=num(cells[i].textContent),s=0,j=i+1;while(j<cells.length&&cells[j].classList.contains('rmG')&&!cells[j].classList.contains('rmGL')){s+=num(cells[j].textContent);if(cells[j].classList.contains('rmGR')){j++;break}j++}out.push([tot,Math.round(s*1000)/1000]);i=j}else i++}return out}""")
            print('    σύνολο ομάδας vs υποκατηγορίες:', chk)
    # Πρέσα
    ev("()=>{readyState.activeGroup='PRESS';return loadReadyPress()}"); pg.wait_for_timeout(1800)
    print('== Πρέσα:', ev("()=>[...document.querySelectorAll('#readyPressHead th')].map(x=>x.textContent.trim())"))
    # Φορτώσεις προετοιμασία
    pg.click('[data-view=loading]'); pg.wait_for_timeout(600); pg.click('[data-lsub=prep]'); pg.wait_for_timeout(3000)
    print('== Φορτώσεις χύμα γραμμές:', ev("()=>[...document.querySelectorAll('#pfWhList .prepBulk')].map(x=>x.dataset.bk)"))
    print('JS errors:', errs)
    pg.screenshot(path=os.environ['TEMP'] + '/real_map.png')
    b.close()
