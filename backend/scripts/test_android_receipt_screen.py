"""Δοκιμή Android › ΠΑΡΑΛΑΒΕΣ › οθόνη ταξινόμησης (πάνω μπάρα, σταθερές σειρές, πρόοδος, Συχνά, Καταχωρήσεις, μαζεμένα στοιχεία ελέγχου).
Χρήση: python backend/scripts/test_android_receipt_screen.py http://127.0.0.1:PORT [φάκελος screenshots]   (server σε ΑΝΤΙΓΡΑΦΟ βάσης: γράφει καταχωρήσεις!)"""
import sys, os, re, json
sys.path.insert(0, os.path.dirname(__file__))
sys.stdout.reconfigure(encoding='utf-8')
from playwright.sync_api import sync_playwright
from _browser import launch
B = sys.argv[1]; S = (sys.argv[2] if len(sys.argv) > 2 else '.') + '/r_'
bad = []
def ck(name, ok, info=''):
    print(('✓ ' if ok else '✗ ') + name, info)
    if not ok: bad.append(name)
with sync_playwright() as p:
    b = launch(p); errs = []
    pg = b.new_page(viewport={'width': 360, 'height': 640}, is_mobile=True, has_touch=True, device_scale_factor=1)
    pg.on('pageerror', lambda e: errs.append(str(e)))
    pg.goto(B + '/mobile', wait_until='networkidle'); pg.click('#loginBtn'); pg.wait_for_selector('#app:not(.hidden)'); pg.wait_for_timeout(2500)
    # --- 1) πάνω μπάρα
    h = pg.evaluate("document.querySelector('.topDark').getBoundingClientRect().height")
    ck('πάνω μπάρα ~34px', 33 <= h <= 36, str(h))
    r = pg.evaluate("""(()=>{const t=document.querySelector('.topDark').getBoundingClientRect();
      const ids=['clock','appTitle','net','topDeltioBtn','who','refreshBtn'];const o={};
      ids.forEach(i=>{const e=document.getElementById(i).getBoundingClientRect();o[i]=[Math.round(e.left),Math.round(e.right),Math.round(e.top-t.top),Math.round(e.bottom-t.top)]});
      return {o,w:innerWidth,txt:[clock.innerText,appTitle.innerText,netTxt.innerText,who.innerText]}})()""")
    print(r)
    ck('όλα στην ίδια γραμμή και μέσα στην οθόνη', all(v[0] >= 0 and v[1] <= r['w'] and v[2] >= 0 and v[3] <= 36 for v in r['o'].values()))
    ck('ώρα ωω:λλ', re.fullmatch(r'\d\d:\d\d', r['txt'][0]) is not None, r['txt'][0])
    ck('«WEEE 2.5.41»', r['txt'][1].startswith('WEEE 2.'), r['txt'][1])
    pg.screenshot(path=S + 'top.png')
    # --- ανοίγει παραλαβή
    loads = pg.evaluate("api('/sorting/available')")
    print('παραλαβές:', len(loads))
    L = pg.evaluate("api('/sorting/available').then(r=>r.filter(x=>x.status!=='SUBMITTED'&&Number(x.net_weight)>0)[0]||r[0])")
    lid = L['load_id']; net = float(L['net_weight'])
    cats = pg.evaluate("cats.filter(c=>c.active!==false).slice(0,60).map(c=>[c.id,c.code])")
    def add(cid, raw, et='MEDIUM'):
        return pg.evaluate("([lid,cid,raw,et])=>api('/sorting/'+lid+'/entries',{method:'POST',body:JSON.stringify({weee_category_id:cid,collection_medium_id:null,entry_type:et,raw_weight:raw,piece_count:null,notes:null})})", [lid, cid, raw, et])
    pg.evaluate("document.querySelector('#loadList [data-id=\"%s\"]').click()" % lid); pg.wait_for_timeout(2500)
    # καθαρά: η προόδος πριν
    meta0 = pg.inner_text('#meta'); print('πρόοδος αρχικά:', meta0)
    ck('υπάρχει μπάρα προόδου', pg.evaluate("!!document.querySelector('#meta .prog i')"))
    ck('κείμενο «ταξινομήθηκαν (N%)» και «απομένουν»', 'ταξινομήθηκαν' in meta0 and 'απομένουν' in meta0)
    # καταχωρήσεις (3 κατηγορίες, με μέσο και απόβαρο)
    mid = pg.evaluate("api('/inventory/weee/media-with-stock').then(x=>0)")
    meds = pg.evaluate("media.filter(m=>/^\D*\d+$/.test(m.code)&&Number(m.tare_weight)>0).slice(-3)")
    ids = [c[0] for c in cats[:3]]
    for k, cid in enumerate(ids):
        pg.evaluate("([lid,cid,mid,raw])=>api('/sorting/'+lid+'/entries',{method:'POST',body:JSON.stringify({weee_category_id:cid,collection_medium_id:mid,entry_type:'SCALE_GROSS',raw_weight:raw,piece_count:null,notes:null})})", [lid, cid, meds[k]['id'], 300 + k])
    pg.evaluate("refresh()"); pg.wait_for_timeout(1500)
    meta1 = pg.inner_text('#meta'); print('πρόοδος μετά:', meta1)
    got = pg.evaluate("api('/sorting/'+cur.id).then(s=>[Number(s.sorting_weight),Number(s.net_weight)])")
    exp_pct = round(got[0] / got[1] * 100) if got[1] else 0
    ck('ποσοστό σωστό', f'({exp_pct}%)' in meta1, f'{got} → {exp_pct}%')
    ck('κιλά χωρίς δεκαδικά', not re.search(r'\d[.,]\d{1,3}\s*kg(?!\w)', re.sub(r'(\d)\.(\d{3})', r'\1\2', meta1)))
    w = pg.evaluate("document.querySelector('#meta .prog i').style.width"); print('πλάτος μπάρας', w)
    # --- 6) καταχωρήσεις
    ents = pg.evaluate("[...document.querySelectorAll('#entries .entry')].map(e=>e.innerText.replace(/\\s+/g,' ').trim())")
    print(ents[:3])
    ck('«Καταχωρήσεις» χωρίς περιγραφή «Νεότερη…»', 'Νεότερη' not in pg.inner_text('#work'))
    ck('κάθε καταχώρηση: κατηγορία, μέσο · αριθμός, kg, απόβαρο χωρίς δεκαδικά', all(re.search(r'· \d+', e) and re.search(r'\d+ kg', e) and re.search(r'απόβαρο \d+ kg', e) for e in ents[:3]) and not any(re.search(r'\d\.000|\d,\d', e) for e in ents[:3]))
    # --- 5) Συχνά
    q1 = pg.evaluate("[...document.querySelectorAll('#quick .q')].map(b=>b.innerText)"); print('Συχνά:', q1)
    last_name = pg.evaluate("dname(cats.find(c=>c.id=='%s'))" % ids[2])
    ck('Συχνά: η καταχωρημένη (πιο πρόσφατη) κατηγορία πρώτη', q1 and q1[0] == last_name, f'{q1[0]!r} vs {last_name!r}')
    ck('Συχνά: το πολύ 3', len(q1) <= 3)
    # --- 7) σειρά + μαζεμένη ενότητα
    order = pg.evaluate("(()=>{const y=id=>document.getElementById(id).getBoundingClientRect().top;return [y('entries'),y('ctrlToggle'),y('confirm')]})()"); print(order)
    ck('σειρά: Καταχωρήσεις → Στοιχεία ελέγχου → ΟΛΟΚΛΗΡΩΣΑ', order[0] < order[1] < order[2])
    ck('μαζεμένη ενότητα με σύνοψη', pg.inner_text('#ctrlToggle').replace('\n', ' ').startswith('Στοιχεία ελέγχου & Φωτογραφίες') and 'καμία επιλογή, 0 φωτο' in pg.inner_text('#ctrlToggle') and pg.evaluate("document.getElementById('ctrlBody').classList.contains('hidden')"))
    pg.evaluate("document.getElementById('ctrlToggle').scrollIntoView({block:'center'})"); pg.tap('#ctrlToggle'); pg.wait_for_timeout(300)
    ck('ανοίγει με 4 κουμπιά ελέγχου + ΦΩΤΟ', pg.evaluate("document.querySelectorAll('#ctrlBody [data-flag]').length")==4 and pg.is_visible('#photoBtn'))
    pg.tap('#ctrlBody [data-flag=check_kday]'); pg.tap('#ctrlBody [data-flag=load_pure]'); pg.wait_for_timeout(800)
    ck('σύνοψη «2 επιλογές, 0 φωτο»', '2 επιλογές, 0 φωτο' in pg.inner_text('#ctrlToggle'), pg.inner_text('#ctrlToggle'))
    pg.screenshot(path=S + 'ctrl_open.png')
    pg.tap('#ctrlBody [data-flag=check_kday]'); pg.tap('#ctrlBody [data-flag=load_pure]'); pg.wait_for_timeout(800)
    pg.tap('#ctrlToggle'); pg.wait_for_timeout(200)
    # --- διαγραφή: η πρόοδος ενημερώνεται
    before = pg.evaluate("document.querySelector('#meta .progTxt span').innerText")
    pg.evaluate("document.querySelector('[data-open]').click()"); pg.wait_for_timeout(300); pg.evaluate("document.querySelector('.shDel').click()"); pg.wait_for_timeout(300); pg.evaluate("document.querySelector('.shDel').click()"); pg.wait_for_timeout(1800)
    after = pg.evaluate("document.querySelector('#meta .progTxt span').innerText")
    ck('πρόοδος ενημερώνεται μετά από διαγραφή', before != after, f'{before} → {after}')
    # υπέρβαση 100%
    add(ids[0], net * 2, 'MEDIUM'); pg.evaluate("refresh()"); pg.wait_for_timeout(1500)
    ck('>100%: μπάρα γεμάτη, απομένουν 0 kg', pg.evaluate("document.querySelector('#meta .prog i').style.width")=='100%' and 'απομένουν 0 kg' in pg.inner_text('#meta'), pg.inner_text('#meta').replace('\n', ' '))
    # --- 2) σταθερές σειρές όταν κυλάει
    pg.evaluate("window.scrollTo(0,400)"); pg.wait_for_timeout(300)
    g = pg.evaluate("""(()=>{const sec=document.querySelector('.secRow').getBoundingClientRect(),top=document.querySelector('.top').getBoundingClientRect(),btn=document.querySelector('.secBtn').getBoundingClientRect();
      const x=sec.left+sec.width/2,y=sec.bottom+2;const el=document.elementFromPoint(x,y);
      return {secB:sec.bottom,topB:top.bottom,btnB:btn.bottom,gap:sec.bottom-btn.bottom,below:el?el.className+'/'+el.tagName:null,bg:getComputedStyle(document.querySelector('.secRow')).backgroundColor,bg2:getComputedStyle(document.querySelector('.profBar')).backgroundColor}})()""")
    print(g)
    ck('κενό κάτω από τα κουμπιά ΠΑΡΑΛΑΒΕΣ.. ≥ 8px', g['gap'] >= 8, str(g['gap']))
    ck('αδιαφανές φόντο σταθερών σειρών', 'rgba(0, 0, 0, 0)' not in (g['bg'], g['bg2']))
    ck('η επικεφαλίδα Καταχωρήσεις δεν καλύπτει την πρώτη καταχώρηση', pg.evaluate("(()=>{const h=document.querySelector('#entries').previousElementSibling.getBoundingClientRect(),e=document.querySelector('#entries .entry').getBoundingClientRect();return h.bottom<=e.top+1})()"))
    pg.evaluate("document.getElementById('entries').scrollIntoView({block:'start'})"); pg.wait_for_timeout(300)
    pg.screenshot(path=S + 'scrolled.png')
    pg.evaluate("window.scrollTo(0,0)"); pg.wait_for_timeout(200)
    pg.screenshot(path=S + 'top_of_page.png')
    # --- 4) κουμπιά μέσου
    pg.evaluate("choose(cats[3].id)"); pg.wait_for_timeout(2000)
    mt = pg.evaluate("[...document.querySelectorAll('#mediumTypes [data-mt]')].map(b=>b.innerText.replace(/\\s+/g,' ').trim())"); print('τύποι μέσου:', mt)
    ck('κουμπιά μέσου χωρίς «χρησιμοποιήθηκε»', mt and not any('χρησιμοποιήθηκε' in x for x in mt))
    pg.screenshot(path=S + 'medium_types.png', full_page=False)
    ck('σφάλματα σελίδας', not errs, str(errs))
    b.close()
print('ΑΠΟΤΥΧΙΕΣ:', bad)
sys.exit(1 if bad else 0)
