"""Δοκιμή Windows › Μητρώα › Υλικά: φίλτρο «Κατηγορία αποθήκης» δίπλα στην αναζήτηση (Όλες / κάθε κατηγορία / Χωρίς κατηγορία), μαζί με αναζήτηση, μετρητής «N υλικά».
Χρήση: python backend/scripts/test_material_cat_filter.py http://127.0.0.1:PORT   (ΜΟΝΟ σε ΑΝΤΙΓΡΑΦΟ βάσης!)"""
import sys, os
sys.path.insert(0, os.path.dirname(__file__)); sys.stdout.reconfigure(encoding='utf-8')
from playwright.sync_api import sync_playwright
from _browser import launch
B = sys.argv[1]
bad = []
def ck(n, ok, i=''):
    print(('✓ ' if ok else '✗ ') + n, i)
    if not ok: bad.append(n)
with sync_playwright() as p:
    b = launch(p); errs = []
    pg = b.new_page(viewport={'width': 1366, 'height': 800}); pg.on('pageerror', lambda e: errs.append(str(e)))
    pg.goto(B + '/', wait_until='networkidle'); pg.click('#loginBtn'); pg.wait_for_selector('#metrics .card', timeout=20000)
    pg.click('.nav button[data-view="master"]'); pg.wait_for_timeout(600)
    pg.evaluate("document.querySelectorAll('.mtab').forEach(b=>{if(b.dataset.mtab==='materialsM')b.click()})"); pg.wait_for_selector('#materialRows tr', timeout=15000); pg.wait_for_timeout(800)
    allm = pg.evaluate("materialsCache.length"); groups = pg.evaluate("api('/master/storage-groups').then(a=>a.filter(g=>g.active).map(g=>[g.id,g.name]))")
    opts = pg.evaluate("[...document.querySelectorAll('#materialCatFilter option')].map(o=>[o.value,o.textContent])")
    ck('η λίστα: «Όλες», κάθε ενεργή κατηγορία από τα μητρώα, «Χωρίς κατηγορία»', opts[0][1].endswith('Όλες') and opts[-1][1] == 'Χωρίς κατηγορία' and [o[1] for o in opts[1:-1]] == [g[1] for g in groups], str(opts))
    nxt = lambda: pg.inner_text('#materialCatCnt')
    ck('μετρητής «N υλικά» στο σύνολο', nxt() == f'{allm} υλικά', nxt())
    pos = pg.evaluate("(()=>{let a=document.getElementById('materialSearch').getBoundingClientRect(),s=document.getElementById('materialCatFilter').getBoundingClientRect();return [Math.abs(a.top-s.top)<30,s.left>=a.right-1]})()")
    ck('δίπλα στην αναζήτηση (ίδια γραμμή, δεξιά της)', pos == [True, True], str(pos))
    for gid, gname in groups:
        exp = pg.evaluate("g=>materialsCache.filter(x=>x.storage_group_id===g).length", gid)
        pg.select_option('#materialCatFilter', gid); pg.wait_for_timeout(150)
        n = pg.locator('#materialRows tr.matMaster').count()
        ck(f'κατηγορία «{gname}»: μόνο τα υλικά της', n == exp and (exp == 0 or pg.evaluate("[...document.querySelectorAll('#materialRows tr.matMaster td:nth-child(5)')].every(c=>c.innerText.trim()===arguments[0])".replace('arguments[0]', repr(gname)))), f'{n}/{exp}')
        ck('  μετρητής ταιριάζει', nxt().split()[0] == str(exp), nxt())
    exp = pg.evaluate("materialsCache.filter(x=>!x.storage_group_id).length")
    pg.select_option('#materialCatFilter', 'none'); pg.wait_for_timeout(150)
    ck('«Χωρίς κατηγορία»', pg.locator('#materialRows tr.matMaster').count() == exp, f'{exp}')
    # μαζί με αναζήτηση
    pg.select_option('#materialCatFilter', groups[0][0]) if groups else None
    pg.fill('#materialSearch', 'ΖΖΖΖΖΖ'); pg.wait_for_timeout(200)
    ck('κατηγορία + αναζήτηση που δεν ταιριάζει → 0 υλικά', nxt() == '0 υλικά' and pg.locator('#materialRows tr.matMaster').count() == 0, nxt())
    pg.fill('#materialSearch', ''); pg.select_option('#materialCatFilter', ''); pg.wait_for_timeout(200)
    ck('«Όλες» ξανά δείχνει όλα', pg.locator('#materialRows tr.matMaster').count() == allm and nxt() == f'{allm} υλικά')
    # η υπάρχουσα επιλογή επιβιώνει της ανανέωσης (/events → loadMasterMaterials)
    if groups:
        pg.select_option('#materialCatFilter', groups[0][0]); pg.evaluate("loadMasterMaterials()"); pg.wait_for_timeout(1500)
        ck('μετά από ανανέωση δεδομένων το φίλτρο μένει', pg.input_value('#materialCatFilter') == groups[0][0])
    ck('σφάλματα σελίδας', not errs, str(errs[:2]))
    b.close()
print('ΑΠΟΤΥΧΙΕΣ:', bad)
sys.exit(1 if bad else 0)
