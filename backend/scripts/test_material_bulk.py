"""Δοκιμή Windows › Μητρώα › Υλικά: στήλη «Μπάλα», «Μαζική επεξεργασία» (τρικατάστατο «Μπορεί να γίνει μπάλα», Μη ενεργό / Ενεργό / Διαγραφή με επιβεβαίωση και μπλοκάρισμα
για υλικά με κινήσεις), πράσινο «Ενεργό» στο προφίλ μη ενεργού υλικού. 1366×800.
Χρήση: python backend/scripts/test_material_bulk.py http://127.0.0.1:PORT C:/ΑΝΤΙΓΡΑΦΟ.db   (ΜΟΝΟ σε ΑΝΤΙΓΡΑΦΟ βάσης!)"""
import sys, os, sqlite3, time
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
    pw = b.new_page(viewport={'width': 1366, 'height': 900}); pw.on('pageerror', lambda e: errs.append(str(e)))
    pw.goto(B + '/', wait_until='networkidle'); pw.click('#loginBtn'); pw.wait_for_selector('#metrics .card', timeout=20000)
    tag = str(int(time.time()))[-6:]
    mk = lambda n: pw.evaluate("""async n=>{let r=await api('/master/materials',{method:'POST',body:JSON.stringify({internal_code:'TB-'+n,internal_name:'ΔΟΚΙΜΗ ΜΑΖΙΚΗ '+n,galaxy_code:'TB'+n,galaxy_description:'ΔΟΚΙΜΗ ΜΑΖΙΚΗ '+n,official_description:'ΔΟΚΙΜΗ ΜΑΖΙΚΗ '+n,is_precious:false,export_step_kg:0.5})});return r.id}""", n)
    ids = [mk(tag + 'A'), mk(tag + 'B'), mk(tag + 'C')]
    pw.click('.nav button[data-view="master"]'); pw.wait_for_timeout(600)
    pw.evaluate("document.querySelectorAll('.mtab').forEach(b=>{if(b.dataset.mtab==='materialsM')b.click()})"); pw.wait_for_selector('#materialRows tr.matMaster', timeout=15000); pw.wait_for_timeout(500)
    heads = pw.evaluate("[...document.querySelectorAll('.materialsRegistryTable thead th')].map(t=>t.innerText.trim())")
    ck('νέα στήλη «Μπάλα» ακριβώς πριν την «Κατάσταση»', heads[-2:] == ['Μπάλα', 'Κατάσταση'] and heads[:6] == ['', 'ERP', 'Επίσημη περιγραφή', 'Γένος', 'Κατηγορία αποθήκης', 'Βήμα εξαγωγής'], str(heads))
    cells = pw.evaluate("[...document.querySelectorAll('#materialRows tr.matMaster')].map(r=>r.children[6].innerText.trim())")
    ck('«Ναι» ή παύλα στα κελιά', set(cells) <= {'Ναι', '—'}, str(set(cells)))
    ck('«Ναι» με χρώμα τονισμού (μπλε)', pw.evaluate("(()=>{let e=[...document.querySelectorAll('#materialRows tr.matMaster td:nth-child(7) b')][0];return !e||getComputedStyle(e).color!==getComputedStyle(document.body).color})()"))
    pw.fill('#materialSearch', 'ΔΟΚΙΜΗ ΜΑΖΙΚΗ ' + tag); pw.wait_for_timeout(300)
    ck('οι 3 δοκιμαστικές γραμμές φαίνονται', pw.locator('#materialRows tr.matMaster').count() == 3)
    pw.evaluate("document.querySelectorAll('.materialRowCheck').forEach(c=>c.click())"); pw.wait_for_timeout(200)
    ck('η μπάρα επιλογής μένει όπως ήταν (Κατηγορία αποθήκης, Εφαρμογή, Επεξεργασία, Ακύρωση)', 'Κατηγορία αποθήκης' in pw.inner_text('#materialGroupBar') and pw.query_selector('#sgBulkApply') is not None and pw.query_selector('#sgBulkCancel') is not None and pw.query_selector('#materialBulkEditBtn') is not None)
    pw.click('#materialBulkEditBtn'); pw.wait_for_selector('#fpMatBulkApply'); pw.wait_for_timeout(300)
    ck('στο παράθυρο: κουμπιά Εφαρμογή, Μη ενεργό, Ενεργό, Διαγραφή', all(pw.query_selector(i) is not None for i in ['#fpMatBulkApply', '#fpMatBulkOff', '#fpMatBulkOn', '#fpMatBulkDel']))
    pos = pw.evaluate("(()=>{let r=i=>document.getElementById(i).getBoundingClientRect();return [r('fpMatBulkDel').left<r('fpMatBulkOff').left,r('fpMatBulkOff').left<r('fpMatBulkOn').left,r('fpMatBulkOn').left<r('fpMatBulkApply').left]})()")
    ck('διάταξη: Διαγραφή αριστερά, μετά Μη ενεργό, Ενεργό, Εφαρμογή δεξιά', pos == [True, True, True], str(pos))
    cols = pw.evaluate("['fpMatBulkOff','fpMatBulkOn','fpMatBulkDel','fpMatBulkApply'].map(i=>{let s=getComputedStyle(document.getElementById(i));return [s.backgroundColor,s.color]})")
    ck('χρώματα: Μη ενεργό κεχριμπάρι, Ενεργό πράσινο, Διαγραφή κόκκινο περίγραμμα, Εφαρμογή μπλε', cols[1] == ['rgb(214, 240, 220)', 'rgb(31, 107, 52)'] and cols[0][0] != cols[1][0] and cols[3][0] != cols[1][0], str(cols))
    st = lambda: pw.evaluate("(()=>{let b=document.getElementById('fpBulkMatBale');return [b.indeterminate,b.checked]})()")
    ck('τετράγωνο «Μπορεί να γίνει μπάλα»: αρχικά παύλα (χωρίς αλλαγή)', st() == [True, False])
    ck('με επεξήγηση', 'κουμπί «Μπάλα»' in pw.inner_text('#floatingEditor'))
    # Εφαρμογή χωρίς αλλαγή στο τετράγωνο: δεν αγγίζει τη ρύθμιση
    pw.fill('#fpBulkMatGenre', 'ΔΟΚΙΜΗΓΕΝΟΣ'); pw.click('#fpMatBulkApply'); pw.wait_for_timeout(2500); pw.evaluate("document.getElementById('floatingEditor').classList.add('hidden')")
    r = db("select genre,can_bale from materials where id in (?,?,?)", *ids)
    ck('Εφαρμογή με παύλα: αλλάζει μόνο το γένος, το can_bale μένει 0', all(x[0] == 'ΔΟΚΙΜΗΓΕΝΟΣ' and not x[1] for x in r), str(r))
    pw.evaluate("document.querySelectorAll('.materialRowCheck').forEach(c=>{if(!c.checked)c.click()})"); pw.wait_for_timeout(200)
    pw.click('#materialBulkEditBtn'); pw.wait_for_selector('#fpMatBulkApply')
    pw.click('#fpBulkMatBale'); ck('κλικ 1: τσεκ (Ναι)', st() == [False, True])
    pw.click('#fpMatBulkApply'); pw.wait_for_timeout(2500); pw.evaluate("document.getElementById('floatingEditor').classList.add('hidden')")
    ck('Εφαρμογή με τσεκ: can_bale=1 σε όλα', all(x[0] == 1 for x in db("select can_bale from materials where id in (?,?,?)", *ids)))
    ck('η στήλη «Μπάλα» δείχνει «Ναι»', pw.evaluate("[...document.querySelectorAll('#materialRows tr.matMaster')].every(r=>r.children[6].innerText.trim()==='Ναι')"))
    pw.evaluate("document.querySelectorAll('.materialRowCheck').forEach(c=>{if(!c.checked)c.click()})"); pw.wait_for_timeout(200)
    pw.click('#materialBulkEditBtn'); pw.wait_for_selector('#fpMatBulkApply')
    pw.click('#fpBulkMatBale'); pw.click('#fpBulkMatBale'); ck('κλικ 2: άδειο (Όχι)', st() == [False, False])
    pw.click('#fpMatBulkApply'); pw.wait_for_timeout(2500); pw.evaluate("document.getElementById('floatingEditor').classList.add('hidden')")
    ck('Εφαρμογή με άδειο: can_bale=0 σε όλα', all(x[0] == 0 for x in db("select can_bale from materials where id in (?,?,?)", *ids)))
    # Μη ενεργό / Ενεργό
    pw.evaluate("document.querySelectorAll('.materialRowCheck').forEach(c=>{if(!c.checked)c.click()})"); pw.wait_for_timeout(200)
    pw.click('#materialBulkEditBtn'); pw.wait_for_selector('#fpMatBulkOff'); pw.click('#fpMatBulkOff'); pw.wait_for_timeout(2500)
    ck('«Μη ενεργό»: αμέσως σε όλα τα επιλεγμένα', all(x[0] == 0 for x in db("select active from materials where id in (?,?,?)", *ids)) and 'Έγιναν μη ενεργά: 3' in pw.inner_text('#fpMatBulkResult'), pw.inner_text('#fpMatBulkResult')[:80])
    pw.evaluate("document.getElementById('floatingEditor').classList.add('hidden')")
    pw.wait_for_timeout(300)
    # προφίλ μη ενεργού: πράσινο «Ενεργό»
    pw.evaluate("id=>editMaterialPopup(materialsCache.find(x=>x.id===id))", ids[0]); pw.wait_for_selector('#fpMatDelete')
    pw.wait_for_timeout(600)
    pr = pw.evaluate("(()=>{let b=document.getElementById('fpMatDelete'),s=getComputedStyle(b);return [b.innerText.trim(),s.backgroundColor,s.color]})()")
    ck('προφίλ μη ενεργού υλικού: πράσινο κουμπί «Ενεργό»', pr == ['Ενεργό', 'rgb(214, 240, 220)', 'rgb(31, 107, 52)'], str(pr))
    pw.evaluate("document.getElementById('floatingEditor').classList.add('hidden')")
    pw.fill('#materialSearch', 'ΔΟΚΙΜΗ ΜΑΖΙΚΗ ' + tag); pw.wait_for_timeout(300)
    pw.evaluate("document.querySelectorAll('.materialRowCheck').forEach(c=>{if(!c.checked)c.click()})"); pw.wait_for_timeout(200)
    pw.click('#materialBulkEditBtn'); pw.wait_for_selector('#fpMatBulkOn'); pw.click('#fpMatBulkOn'); pw.wait_for_timeout(2500)
    ck('«Ενεργό»: αμέσως σε όλα', all(x[0] == 1 for x in db("select active from materials where id in (?,?,?)", *ids)) and 'Έγιναν ενεργά: 3' in pw.inner_text('#fpMatBulkResult'))
    # Διαγραφή: επιβεβαίωση + μπλοκάρισμα υλικού με κινήσεις
    used = ids[2]
    pw.evaluate("m=>api('/mat/inventory',{method:'POST',body:JSON.stringify({material_id:m,form:'BULK',net:1})})", used)   # κίνηση (ζύγιση απογραφής) στο 3ο υλικό
    pw.evaluate("document.getElementById('floatingEditor').classList.add('hidden')")
    pw.fill('#materialSearch', ''); pw.wait_for_timeout(200); pw.fill('#materialSearch', 'ΔΟΚΙΜΗ ΜΑΖΙΚΗ ' + tag); pw.wait_for_timeout(300)
    pw.evaluate("document.querySelectorAll('.materialRowCheck').forEach(c=>{if(!c.checked)c.click()})"); pw.wait_for_timeout(200)
    pw.click('#materialBulkEditBtn'); pw.wait_for_selector('#fpMatBulkDel')
    pw.click('#fpMatBulkDel'); pw.wait_for_selector('#fpMatBulkDelYes')
    ck('«Διαγραφή» ζητά επιβεβαίωση μέσα στο παράθυρο (δεν διαγράφει ακόμα)', 'Οριστική διαγραφή' in pw.inner_text('#fpMatBulkConfirm') and db("select count(*) from materials where id in (?,?,?)", *ids)[0][0] == 3)
    pw.click('#fpMatBulkDelNo'); ck('«Άκυρο» κλείνει την επιβεβαίωση', pw.query_selector('#fpMatBulkDelYes') is None)
    pw.click('#fpMatBulkDel'); pw.click('#fpMatBulkDelYes'); pw.wait_for_timeout(3000)
    res = pw.inner_text('#fpMatBulkResult')
    ck('διαγράφονται τα 2 υλικά χωρίς κινήσεις', db("select count(*) from materials where id in (?,?)", ids[0], ids[1])[0][0] == 0 and 'Διαγράφηκαν: 2' in res, res.replace(chr(10), ' | ')[:160])
    ck('το υλικό ΜΕ κινήσεις μπλοκάρεται με σαφές μήνυμα και μένει', db("select count(*) from materials where id=?", used)[0][0] == 1 and 'Δεν έγιναν (1)' in res and 'χρησιμοποιηθεί' in res, res.replace(chr(10), ' | ')[-200:])
    ck('σφάλματα σελίδας', not errs, str(errs[:2]))
    b.close()
print('ΑΠΟΤΥΧΙΕΣ:', bad)
sys.exit(1 if bad else 0)
