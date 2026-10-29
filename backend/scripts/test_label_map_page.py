"""Δοκιμή σελίδας Μητρώα → Αντιστοίχιση ετικετών (σε ΑΝΤΙΓΡΑΦΟ, πόρτα 8020)."""
import sys, os
sys.path.insert(0, os.path.dirname(__file__)); sys.stdout.reconfigure(encoding='utf-8')
from playwright.sync_api import sync_playwright
from _browser import launch
B = 'http://127.0.0.1:8020'
with sync_playwright() as p:
    b = launch(p)
    pg = b.new_page(viewport={'width': 1400, 'height': 900})
    errs = []; pg.on('pageerror', lambda e: errs.append(str(e)))
    pg.goto(B + '/', wait_until='networkidle')
    pg.wait_for_selector('#loginBtn', state='visible'); pg.click('#loginBtn')
    pg.wait_for_selector('#metrics .card', timeout=20000); pg.wait_for_timeout(1500)
    u = pg.evaluate("()=>api('/mat/label-universe')")
    print('labels', len(u['labels']), 'press', len(u['press']), 'materials', len(u['materials']), 'weee', len(u['weee']))
    # το εργαλείο ΔΕΝ είναι πια στα Μητρώα: ανοίγει από Ρυθμίσεις → «Εισαγωγή από Excel»
    print('Μητρώα χωρίς καρτέλα αντιστοίχισης:', pg.evaluate("()=>!document.querySelector('[data-mtab=labelMapM]')"))
    pg.evaluate("()=>document.getElementById('appSettingsBtn').click()"); pg.wait_for_timeout(600)
    pg.click('[data-appset=xlImport]'); pg.click('#xlImportOpen'); pg.wait_for_function("()=>LM.d", timeout=90000); pg.wait_for_timeout(500)
    print('οθόνη ορατή από Ρυθμίσεις:', pg.evaluate("()=>{const o=document.getElementById('labelMapM');return !!o&&!o.classList.contains('hidden')&&getComputedStyle(o).display!=='none'}"))
    xl = pg.evaluate("()=>LM.d.excel&&{files:LM.d.excel.files.length,added:LM.d.excel.added.length,addedPress:LM.d.excel.added_press}")
    print('πηγή Excel:', xl)
    print('cells', pg.locator('#lmBody .lmCell').count(), '| progress:', pg.inner_text('#lmProg'))
    print('tabs', pg.locator('#lmTabs .lmTab').count())
    # δοκιμή αποθήκευσης: πρώτη ετικέτα χωρίς απάντηση → «Δεν είναι υλικό», μετά αφαίρεση
    lab = pg.evaluate("()=>{const l=LM.d.labels.find(x=>!lmDone(x));return l?l.label:null}")
    print('πρώτη χωρίς απάντηση:', lab)
    if lab:
        pg.evaluate("l=>{const x=LM.d.labels.find(y=>y.label===l);return lmSave(x,{kind:'NONE'})}", lab)
        pg.wait_for_timeout(800)
        print('μετά NONE:', pg.evaluate("l=>LM.d.labels.find(y=>y.label===l).map", lab))
        pg.evaluate("l=>{const x=LM.d.labels.find(y=>y.label===l);return lmSave(x,{kind:'CLEAR'})}", lab)
        pg.wait_for_timeout(800)
        print('μετά CLEAR:', pg.evaluate("l=>LM.d.labels.find(y=>y.label===l).map", lab))
    # --- όλα τα είδη αντιστοίχισης (στο αντίγραφο) ---
    L = lambda i: pg.evaluate("i=>{const a=LM.d.labels.filter(x=>!lmDone(x));return a[i].label}", i)
    def save(label, item):
        pg.evaluate("([l,it])=>{const x=LM.d.labels.find(y=>y.label===l);return lmSave(x,it)}", [label, item]); pg.wait_for_timeout(700)
        return pg.evaluate("l=>LM.d.labels.find(y=>y.label===l).map", label)
    mid = pg.evaluate("()=>LM.d.materials.find(m=>m.active&&!m.comm).id")
    inact = pg.evaluate("()=>{const m=LM.d.materials.find(m=>!m.active);return m&&m.id}")
    w = pg.evaluate("()=>LM.d.weee[0].id")
    l1, l2, l3, l4, l5 = L(0), L(1), L(2), L(3), L(4)
    print('MATERIAL      ', save(l1, {'kind': 'MATERIAL', 'material_id': mid})['kind'])
    print('MATERIAL ανεν.', save(l5, {'kind': 'MATERIAL', 'material_id': inact})['kind'] if inact else 'δεν υπάρχει ανενεργό')
    print('RECEIPTS      ', save(l2, {'kind': 'RECEIPTS', 'weee_category_id': w})['kind'])
    print('SUM           ', save(l3, {'kind': 'SUM', 'group_name': 'ΠΛΑΣΤΙΚΑ ΜΕΡΗ ΔΟΚΙΜΗ'})['kind'])
    # υλικό-ομπρέλα στο αντίγραφο → BULK_SUB
    import sqlite3
    cp = os.environ.get('LM_COPY')
    assert cp and 'lm_test' in cp, 'ΜΟΝΟ σε αντίγραφο'
    cx = sqlite3.connect(cp); cx.execute("update materials set is_umbrella=1 where id=(select id from materials where active=1 and is_commercial=0 order by galaxy_code desc limit 1)"); cx.commit(); cx.close()
    pg.evaluate("()=>lmLoad()"); pg.wait_for_timeout(900)
    umb = pg.evaluate("()=>{const m=LM.d.materials.find(m=>m.umbrella);return m&&m.id}")
    print('υλικό-ομπρέλα στο αντίγραφο:', umb)
    print('BULK_SUB σε μη-ομπρέλα (πρέπει να απορριφθεί):', save(l4, {'kind': 'BULK_SUB', 'material_id': mid}), '|', pg.inner_text('#lmMsg')[:90])
    if umb: print('BULK_SUB      ', save(l4, {'kind': 'BULK_SUB', 'material_id': umb}))
    # ετικέτα που επιστρέφει ως twin/εξαίρεση: ίδια ετικέτα με δύο υλικά θα έπρεπε να αρνηθεί ή να αντικαταστήσει
    eff = pg.evaluate("()=>api('/mat/label-maps/effective')")
    print('effective maps:', len(eff) if hasattr(eff, '__len__') else eff)
    # κουμπί πρόταση
    pg.evaluate("()=>{LM.tab='NOMAT';lmPaint()}")
    sg = pg.locator('#lmBody .lmSg')
    if sg.count():
        txt = sg.first.inner_text(); sg.first.click(); pg.wait_for_timeout(900)
        print('πρόταση πατήθηκε:', txt[:60], '| αποθηκευμένες τώρα:', pg.evaluate("()=>LM.d.labels.concat(LM.d.press).filter(x=>x.map).length"))
    # επαναφορά: αφαίρεση όλων (αντίγραφο)
    pg.evaluate("async()=>{for(const x of LM.d.labels.concat(LM.d.press)) if(x.map) await lmSave(x,{kind:'CLEAR'})}"); pg.wait_for_timeout(500)
    print('μετά καθαρισμό:', pg.evaluate("()=>LM.d.labels.concat(LM.d.press).filter(x=>x.map).length"))
    print('στήλες Πρέσας από εφαρμογή:', pg.evaluate("()=>LM.d.press.filter(x=>x.from_app).length"), '| με μήνες:', pg.evaluate("()=>LM.d.labels.filter(x=>x.months.length).length"))
    pg.evaluate("()=>{LM.tab='NOMAT';lmPaint()}")
    print('χωρίς υλικό:', pg.locator('#lmBody .lmCell').count(), '| προτάσεις:', pg.locator('#lmBody .lmSg').count())
    pg.screenshot(path=os.environ['TEMP'] + '/lm_page.png')
    print('JS errors:', errs)
    b.close()
