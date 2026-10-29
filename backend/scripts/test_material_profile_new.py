"""Νέο Προφίλ Υλικού (ΜΟΝΟ σε αντίγραφο, πόρτα 8020, env LM_COPY)."""
import sys, os
sys.path.insert(0, os.path.dirname(__file__)); sys.stdout.reconfigure(encoding='utf-8')
from playwright.sync_api import sync_playwright
from _browser import launch
B = 'http://127.0.0.1:8020'
assert 'lm_test' in os.environ.get('LM_COPY', '')
with sync_playwright() as p:
    b = launch(p)
    pg = b.new_page(viewport={'width': 1500, 'height': 950})
    errs = []; pg.on('pageerror', lambda e: errs.append(str(e)))
    dlg = []; pg.on('dialog', lambda d: (dlg.append(d.message), d.accept()))
    pg.goto(B + '/', wait_until='networkidle')
    pg.wait_for_selector('#loginBtn', state='visible'); pg.click('#loginBtn')
    pg.wait_for_selector('#metrics .card', timeout=20000); pg.wait_for_timeout(1200)
    ev = lambda js, a=None: pg.evaluate(js, a) if a is not None else pg.evaluate(js)
    mats = ev("()=>api('/master/materials?include_inactive=true')")
    with_hist = next(m for m in mats if m['active'] and m.get('galaxy_code'))
    print('υλικό:', with_hist['galaxy_code'], with_hist.get('official_description'))
    ev("m=>{document.querySelector('[data-view=master]').click();editMaterialPopup(m)}", with_hist); pg.wait_for_timeout(1800)
    secs = ev("()=>[...document.querySelectorAll('#floatingEditor .mpSec>h4')].map(x=>x.textContent.trim())")
    print('ενότητες:', secs)
    print('«?» εικονίδια:', ev("()=>document.querySelectorAll('#floatingEditor .mpQ').length"))
    print('πεδίο Πρέσας κρυφό όταν δεν είναι μπάλα:', ev("()=>document.getElementById('mpPressWrap').classList.contains('hidden')") == (not with_hist.get('can_bale')))
    pg.check('#fpMatBale'); print('πεδίο Πρέσας ορατό με τσεκ Μπάλα:', not ev("()=>document.getElementById('mpPressWrap').classList.contains('hidden')"))
    pg.check('#fpMatComm'); print('σημείωση εμπορικού ορατή:', not ev("()=>document.getElementById('mpTwin').classList.contains('hidden')"))
    pg.uncheck('#fpMatBale'); pg.uncheck('#fpMatComm')
    use = ev("()=>document.getElementById('mpUse').innerText.replace(/\\n/g,' | ')")
    print('Πού χρησιμοποιείται:', use)
    lock = ev("()=>({dis:document.getElementById('fpMatPurge').disabled,why:document.getElementById('mpLockWhy').textContent})")
    print('Οριστική Διαγραφή κλειδωμένη:', lock)
    print('ιστορικό πτυσσόμενο:', ev("()=>document.querySelector('#floatingEditor details.mpHist').open === false"), '|', ev("()=>document.getElementById('mpHistSum').textContent"))
    # προειδοποίηση συνέπειας Reptool/ΕΚΑ
    pg.fill('#fpMatRep', '16 02 16 / 17'); pg.fill('#fpMatEka', '20 01 36')
    print('προειδοποίηση ασυμφωνίας:', ev("()=>document.getElementById('mpWarn').textContent"))
    pg.fill('#fpMatEka', '16 02 16')
    print('μετά τη διόρθωση ΕΚΑ:', repr(ev("()=>document.getElementById('mpWarn').textContent")))
    # --- ομαδοποίηση: ομπρέλα με 2 υποκατηγορίες (αντίγραφο) ---
    pg.check('#mpUmb'); pg.wait_for_timeout(1500)
    opts = ev("()=>[...document.querySelectorAll('#mpSubSel option')].map(o=>o.value).slice(0,3)")
    for o in opts[:2]:
        pg.select_option('#mpSubSel', o); pg.click('#mpSubAdd')
    print('υποκατηγορίες στη λίστα:', ev("()=>[...document.querySelectorAll('#mpSubList .mpName')].map(x=>x.textContent)"))
    pg.locator('#mpSubList [data-j]').nth(0).drag_to(pg.locator('#mpSubList [data-j]').nth(1)); pg.wait_for_timeout(300)
    pg.locator('#mpSubList [data-t]').nth(0).click()
    print('μετά σύρσιμο + εναλλαγή:', ev("()=>[...document.querySelectorAll('#mpSubList .mpRow')].map(x=>x.innerText.replace(/\\s+/g,' ').trim())"))
    # --- ετικέτα ---
    pg.check('#mpLab'); pg.wait_for_timeout(800)
    pg.select_option('#mpLabSel', '__new'); pg.fill('#mpLabNew', 'ΟΜΑΔΑ ΠΡΟΦΙΛ')
    pg.click('#fpMatSave'); pg.wait_for_timeout(2000)
    saved = ev("id=>api('/master/materials?include_inactive=true').then(a=>a.find(m=>m.id===id))", with_hist['id'])
    print('αποθηκεύτηκε: ομπρέλα', saved.get('is_umbrella'), '| ετικέτα', saved.get('label_group'), '| order', saved.get('label_group_order'))
    eff = ev("()=>api('/mat/label-maps/effective')")
    u = next((x for x in eff['umbrellas'] if x['id'] == with_hist['id']), None)
    print('υποκατηγορίες στον server:', [(s['label'], s['active'], s['sort_order']) for s in (u['subs'] if u else [])])
    print('ομάδες ετικετών:', [(g['name'], [m['name'] for m in g['members']]) for g in eff['groups'] if g['name'] == 'ΟΜΑΔΑ ΠΡΟΦΙΛ'])
    # --- νέο υλικό χωρίς ιστορικό: οριστική διαγραφή ΕΠΙΤΡΕΠΕΤΑΙ (αντίγραφο) ---
    ev("()=>{editMaterialPopup(null)}"); pg.wait_for_timeout(600)
    pg.fill('#fpMatGalaxy', '99999'); pg.fill('#fpMatOfficial', 'ΔΟΚΙΜΗ ΠΡΟΦΙΛ'); pg.click('#fpMatSave'); pg.wait_for_timeout(1800)
    new = ev("()=>api('/master/materials?include_inactive=true').then(a=>a.find(m=>m.galaxy_code==='99999'))")
    print('νέο υλικό δημιουργήθηκε:', bool(new))
    if new:
        ev("m=>{editMaterialPopup(m)}", new); pg.wait_for_timeout(1500)
        print('κλείδωμα νέου υλικού χωρίς ιστορικό:', ev("()=>document.getElementById('fpMatPurge').disabled"))
        pg.click('#fpMatPurge'); pg.wait_for_timeout(1500)
        print('διαγράφηκε:', not ev("()=>api('/master/materials?include_inactive=true').then(a=>a.some(m=>m.galaxy_code==='99999'))"))
    # υλικό με ιστορικό/εγγραφές: η οριστική διαγραφή κλειδώνει και η πληροφορία «Πού χρησιμοποιείται» γεμίζει
    locked = ev("""async()=>{const a=await api('/master/materials?include_inactive=true');
      for(const m of a.filter(x=>x.galaxy_code)){const u=await api('/mat/usage/'+m.id);if(u.delete_locked&&u.mapped_labels.length+u.moves>0)return m}return null}""")
    if locked:
        ev("m=>{editMaterialPopup(m)}", locked); pg.wait_for_timeout(2000)
        print('υλικό με ιστορικό:', locked['galaxy_code'], '| Πού χρησιμοποιείται:', ev("()=>document.getElementById('mpUse').innerText.replace(/\\n/g,' | ')"))
        print('οριστική διαγραφή κλειδωμένη:', ev("()=>document.getElementById('fpMatPurge').disabled"), '|', ev("()=>document.getElementById('mpLockWhy').textContent"))
    print('JS errors:', errs, '| dialogs:', dlg)
    pg.screenshot(path=os.environ['TEMP'] + '/profile_new.png')
    b.close()
