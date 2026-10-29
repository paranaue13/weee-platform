"""Δοκιμή ΕΜΠΟΡΙΚΩΝ υλικών + σύγκριση ελληνικών/λατινικών γραμμάτων.
Τσεκ «Εμπορικό υλικό» (προφίλ, μαζική επεξεργασία), καρτέλα Windows «Εμπορικά» (πριν την «Αποθήκη», χωρίς απογραφή/αποστολές, κεχριμπάρι γραμμές εξαγωγών, παράθυρο εξαγωγής),
απόθεμα ανά υλικό (ERP/id, όχι όνομα), αφαίρεση από Αποθήκη/Android, εξαίρεση από απογραφή και καρτέλες υλικών, Android κατηγορία «Εμπορικά», ΙΝΟΧ = INOX.
Χρήση: python backend/scripts/test_commercial.py http://127.0.0.1:PORT C:/ΑΝΤΙΓΡΑΦΟ.db   (ΜΟΝΟ σε ΑΝΤΙΓΡΑΦΟ βάσης!)"""
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
NL = chr(10)
with sync_playwright() as p:
    b = launch(p); errs = []
    pw = b.new_page(viewport={'width': 1600, 'height': 900}); pw.on('pageerror', lambda e: errs.append(str(e)))
    pw.goto(B + '/', wait_until='networkidle'); pw.click('#loginBtn'); pw.wait_for_selector('#metrics .card', timeout=20000)
    call = lambda m, path, body=None: pw.evaluate("""async([m,p,b])=>{let r=await fetch(p,{method:m,headers:{'Content-Type':'application/json',Authorization:'Bearer '+token},body:b?JSON.stringify(b):undefined});return [r.status,await r.json().catch(()=>null)]}""", [m, path, body])
    tag = str(int(time.time()))[-6:]
    mk = lambda n, erp, name: pw.evaluate("""async([n,erp,name])=>{let r=await api('/master/materials',{method:'POST',body:JSON.stringify({internal_code:'TC-'+n,internal_name:name,galaxy_code:erp,galaxy_description:name,official_description:name,is_precious:false,export_step_kg:0.5})});return r.id}""", [n, erp, name])
    nameA = 'ΔΟΚΙΜΗ ΕΜΠΟΡΙΚΟ ' + tag
    cA = mk(tag + 'a', 'TCA' + tag, nameA)           # εμπορικό (ERP TCA…)
    cP = mk(tag + 'p', 'TCP' + tag, nameA)           # ΙΔΙΟ όνομα, διαφορετικό ERP, ΜΗ εμπορικό
    cB = mk(tag + 'b', 'TCB' + tag, 'ΔΟΚΙΜΗ ΕΜΠΟΡΙΚΟ Β ' + tag)
    # ---- προφίλ υλικού: τσεκ ----
    pw.click('.nav button[data-view="master"]'); pw.wait_for_timeout(600)
    pw.evaluate("document.querySelectorAll('.mtab').forEach(b=>{if(b.dataset.mtab==='materialsM')b.click()})"); pw.wait_for_selector('#materialRows tr.matMaster', timeout=15000); pw.wait_for_timeout(500)
    pw.evaluate("async()=>{await loadMasterMaterials()}"); pw.wait_for_timeout(500)
    pw.evaluate("id=>editMaterialPopup(materialsCache.find(x=>x.id===id))", cA); pw.wait_for_selector('#fpMatComm', timeout=8000)
    t = pw.inner_text('#floatingEditor') + ' ' + pw.eval_on_selector_all('#floatingEditor .mpQ', "els=>els.map(e=>e.dataset.t).join(' ')")   # οι επεξηγήσεις είναι πλέον στα «?» του νέου προφίλ
    ck('προφίλ υλικού: τετράγωνο «Εμπορικό υλικό» με την επεξήγηση του σχεδίου', 'Εμπορικό υλικό' in t and 'Φαίνεται μόνο στην Αποθήκη Υλικών και στην καρτέλα «Εμπορικά»' in t and 'ως «Εμπορικά»' in t)
    pw.check('#fpMatComm'); pw.click('#fpMatSave'); pw.wait_for_timeout(1500)
    ck('αποθηκεύεται is_commercial=1 μόνο στο ένα υλικό (ίδιο όνομα, άλλο ERP μένει μη εμπορικό)', db("select is_commercial from materials where id=?", cA)[0][0] == 1 and db("select is_commercial from materials where id=?", cP)[0][0] == 0)
    # μαζική επεξεργασία: τρικατάστατο
    pw.fill('#materialSearch', 'ΔΟΚΙΜΗ ΕΜΠΟΡΙΚΟ Β ' + tag); pw.wait_for_timeout(300)
    pw.evaluate("document.querySelectorAll('.materialRowCheck').forEach(c=>c.click())"); pw.click('#materialBulkEditBtn'); pw.wait_for_selector('#fpBulkMatComm')
    st = lambda: pw.evaluate("(()=>{let b=document.getElementById('fpBulkMatComm');return [b.indeterminate,b.checked]})()")
    ck('μαζική επεξεργασία: «Εμπορικό υλικό» τρικατάστατο, αρχικά παύλα', st() == [True, False])
    pw.click('#fpBulkMatComm'); ck('κλικ → τσεκ', st() == [False, True])
    pw.click('#fpMatBulkApply'); pw.wait_for_timeout(2500); pw.evaluate("document.getElementById('floatingEditor').classList.add('hidden')")
    ck('Εφαρμογή: is_commercial=1', db("select is_commercial from materials where id=?", cB)[0][0] == 1)
    # ---- ποσότητες (Android εξαγωγές) ----
    st_, r = call('POST', '/mat/export', {'material_id': cA, 'form': 'BULK', 'net': 1000})
    st_, r2 = call('POST', '/mat/export', {'material_id': cA, 'form': 'PALLET', 'gross': 130, 'tare': 30})
    st_, r3 = call('POST', '/mat/export', {'material_id': cA, 'form': 'PALLET', 'gross': 130, 'tare': 30})
    st_, r4 = call('POST', '/mat/export', {'material_id': cP, 'form': 'BULK', 'net': 77})
    cat = pw.evaluate("api('/mat/catalog')")
    ca = next(m for m in cat['materials'] if m['id'] == cA); cp = next(m for m in cat['materials'] if m['id'] == cP)
    ck('Android: απόθεμα εμπορικού = δικές του παρτίδες (1200 kg)', abs(ca['available_kg'] - 1200) < 0.01, str(ca))
    ck('Android: το ΜΗ εμπορικό με ίδιο όνομα ΔΕΝ παίρνει το απόθεμα του εμπορικού (ανά ERP/υλικό)', abs(cp['available_kg'] - 0) < 0.01, str(cp))
    cg = [c for c in cat['categories'] if c['name'] == 'Εμπορικά']
    ck('Android εξαγωγή: κατηγορία «Εμπορικά» περιέχει τα υλικά με το τσεκ', bool(cg) and ca['category_id'] == cg[0]['id'] and cp['category_id'] != cg[0]['id'], str(cg[:1]))
    ck('Android: το κατάλογο δίνει is_commercial', ca['is_commercial'] is True and cp['is_commercial'] is False)
    st_, e = call('POST', '/mat/inventory', {'material_id': cA, 'form': 'BULK', 'net': 5})
    ck('απογραφή: το εμπορικό δεν μετρά (422 με σαφές μήνυμα)', st_ == 422 and 'απογραφή' in str(e), str(e))
    # ---- καρτέλα Εμπορικά ----
    pw.click('.nav button[data-view="ready"]'); pw.wait_for_timeout(800)
    tabs = pw.evaluate("[...document.querySelectorAll('#readyGroupTabs .readyGroupTab')].map(b=>b.innerText.trim())")
    ck('καρτέλα «Εμπορικά» ΠΡΙΝ την «Αποθήκη»', tabs[-2:] == ['Εμπορικά', 'Αποθήκη'], str(tabs))
    pw.click('.readyGroupTab[data-readygroup="COMMERCIAL"]'); pw.wait_for_selector('#readyCommHead th', timeout=10000); pw.wait_for_timeout(1000)
    heads = pw.evaluate("[...document.querySelectorAll('#readyCommHead th')].map(t=>t.innerText.trim())")
    ck('στήλες = εμπορικά υλικά (και ΟΧΙ το μη εμπορικό με ίδιο όνομα)', heads[:2] == ['ΗΜΕΡΟΜΗΝΙΑ', 'ΣΥΝΟΛΟ (KG)'] and heads.count(nameA) == 1 and ('ΔΟΚΙΜΗ ΕΜΠΟΡΙΚΟ Β ' + tag) in heads, str(heads))
    foot = pw.evaluate("[...document.querySelectorAll('#readyCommFoot tr')].map(r=>r.children[0].innerText.trim())")
    ck('κάτω γραμμές: Εξαγωγές, Εξαγωγές τεμαχίων, Σύνολο, Τρέχον απόθεμα, Τεμάχια — ΧΩΡΙΣ «Ποσότητα απογραφής»/«Αποστολές»', foot[0] == 'Εξαγωγές' and foot[1] == 'Εξαγωγές τεμαχίων' and any(x.startswith('Τρέχον απόθεμα') for x in foot) and not any('απογραφής' in x or 'Αποστολές' in x for x in foot), str(foot))
    am = pw.evaluate("['readyCommExRow','readyCommExPcRow'].map(i=>getComputedStyle(document.getElementById(i).children[1]).backgroundColor)")
    pw.click('.readyGroupTab[data-readygroup="AXIOPOIISIMA"]'); pw.wait_for_timeout(900)
    ref = pw.evaluate("(()=>{let e=document.querySelector('#readyCorrectionRow td');return e?getComputedStyle(e).backgroundColor:null})()")
    pw.click('.readyGroupTab[data-readygroup="COMMERCIAL"]'); pw.wait_for_timeout(900)
    ck('γραμμές «Εξαγωγές»: κεχριμπάρι, ίδιο χρώμα με τη γραμμή «Διορθώσεις» των Αξιοποιήσιμων', am[0] == ref and am[1] == ref and ref == 'rgb(255, 246, 228)', f'{am} / {ref}')
    bal = pw.inner_text('#readyCommBalRow').replace(NL, ' ')
    ck('Τρέχον απόθεμα εμπορικού 1.200', '1.200' in bal, bal)
    idx = heads.index(nameA)
    pw.click(f'#readyCommExRow td:nth-child({idx + 1})'); pw.wait_for_selector('.corrPop #ccAdd')
    ck('παράθυρο εξαγωγής: τίτλος, πεδία Κιλά/Τεμάχια/Ημερομηνία (σήμερα)/Σημείωση, κουμπί «Προσθήκη»', 'Εξαγωγή – ' + nameA in pw.inner_text('.corrPop') and pw.input_value('#ccDate') == time.strftime('%Y-%m-%d') and all(pw.query_selector(i) for i in ['#ccKg', '#ccPc', '#ccNote']))
    pw.fill('#ccKg', '500'); pw.fill('#ccPc', '1'); pw.fill('#ccNote', 'δοκιμή'); pw.click('#ccAdd'); pw.wait_for_timeout(2500)
    ck('η εξαγωγή αποθηκεύτηκε (500 kg, 1 τεμ.) με σημείωση', db("select kg,pieces,note,active from commercial_exports where material_id=?", cA) == [(500, 1, 'δοκιμή', 1)], str(db("select kg,pieces,note from commercial_exports where material_id=?", cA)))
    ck('το παράθυρο μένει ανοιχτό και δείχνει την εξαγωγή του μήνα', pw.query_selector('.corrPop') is not None and '500' in pw.inner_text('.corrPop'))
    pw.keyboard.press('Escape'); pw.wait_for_timeout(300)
    bal = pw.inner_text('#readyCommBalRow').replace(NL, ' ')
    ck('Τρέχον απόθεμα μειώθηκε: 700', '700' in bal, bal)
    exr = pw.inner_text('#readyCommExRow').replace(NL, ' ')
    ck('γραμμή Εξαγωγές δείχνει −500', '−500' in exr, exr)
    # Αποθήκη (Windows desktop και Android) λαμβάνουν την εξαγωγή
    wd = pw.evaluate("api('/mat/warehouse-desktop')"); wa = pw.evaluate("api('/mat/warehouse-grouped')"); wo = pw.evaluate("api('/mat/warehouse')")
    mm = lambda w: next(m for c in w['categories'] for m in c['materials'] if m['material_id'] == cA)
    ck('Αποθήκη Windows: 700 kg και 1 τεμάχιο (2 παλέτες − 1 εξαγωγή)', abs(mm(wd)['kg'] - 700) < 0.01 and mm(wd)['pieces'] == 1 and any(i['kind'] == 'commercial_export' and i['kg'] == -500 for i in mm(wd)['items']), str((mm(wd)['kg'], mm(wd)['pieces'])))
    ck('Αποθήκη Android (ομαδοποιημένη): ίδια νούμερα, κατηγορία «Εμπορικά»', abs(mm(wa)['kg'] - 700) < 0.01 and mm(wa)['pieces'] == 1 and mm(wa)['category'] == 'Εμπορικά')
    ck('Αποθήκη Android (παλιός υπολογισμός): ίδια κιλά', abs(next(m for m in wo['materials'] if m['material_id'] == cA)['kg'] - 700) < 0.01)
    ck('το μη εμπορικό υλικό με ίδιο όνομα έχει ΔΙΚΑ ΤΟΥ 77 kg (δεν ενώθηκε)', abs(next(m for c in wd['categories'] for m in c['materials'] if m['material_id'] == cP)['kg'] - 77) < 0.01)
    # ουρά εγγραφών: εξαγωγή μέσω OB
    ck('η εγγραφή εξαγωγής περνά από την ουρά εγγραφών των Windows', pw.evaluate("OB.wants('/mat/commercial-exports','POST')&&OB.wants('/mat/commercial-exports/abc','DELETE')"))
    pw.evaluate("(()=>{let c=[...document.querySelectorAll('#readyCommFoot .commCell')][%d];c.click()})()" % (idx - 2)); pw.wait_for_selector('.corrPop .cpDel')
    pw.click('.corrPop .cpDel'); pw.wait_for_timeout(2000)
    ck('διαγραφή εξαγωγής: το απόθεμα επανέρχεται (1.200)', '1.200' in pw.inner_text('#readyCommBalRow') and db("select active from commercial_exports where material_id=?", cA) == [(0,)])
    pw.keyboard.press('Escape')
    # ---- εξαίρεση από άλλες καρτέλες/απογραφή ----
    row = db("""select l.material_label, count(*), sum(l.weight_kg) from material_output_entries l where l.active=1 group by l.material_label order by 3 desc""")
    names = {}
    for mid, o, i in db("select id, official_description, internal_name from materials where active=1 and galaxy_code is not null and galaxy_code!=''"):
        for n in (o, i):
            if n: names.setdefault(n.strip().upper(), set()).add(mid)
    cand = next((r_ for r_ in row if len(names.get((r_[0] or '').strip().upper(), set())) == 1), None)
    if cand:
        lb = cand[0]; mid_ = next(iter(names[lb.strip().upper()]))
        def labels_everywhere():
            out = []
            for g in ['AXIOPOIISIMA', 'EIDIKIS_DIACHEIRISIS', 'PLAKETES', 'APORRIPSI']:
                pw.click(f'.readyGroupTab[data-readygroup="{g}"]'); pw.wait_for_timeout(900)
                out += pw.evaluate("[...document.querySelectorAll('#readyMatHead th')].map(t=>t.innerText.trim())")
            return out
        before = labels_everywhere()
        ck(f'(προϋπόθεση) η ετικέτα «{lb}» φαίνεται σε κάποια καρτέλα πριν γίνει εμπορική', lb in before)
        inv0 = pw.evaluate("api('/reports/inventory-count?year=2026')")
        setc = lambda v: pw.evaluate("""async([id,v])=>{let m=await api('/master/materials?include_inactive=true').then(a=>a.find(x=>x.id===id));let k=['internal_code','internal_name','galaxy_code','galaxy_description','genre','official_description','her_description','eka_code','reptool_code','reptool_description','is_precious','export_step_kg'],b={};k.forEach(x=>b[x]=m[x]);b.is_commercial=v;await api('/master/materials/'+id,{method:'PUT',body:JSON.stringify(b)})}""", [mid_, v])
        setc(True)
        pw.evaluate("clearApiCache&&clearApiCache()"); pw.reload(wait_until='networkidle'); pw.wait_for_selector('#metrics .card', timeout=20000) if pw.query_selector('#metrics .card') else (pw.click('#loginBtn'), pw.wait_for_selector('#metrics .card', timeout=20000))
        pw.click('.nav button[data-view="ready"]'); pw.wait_for_timeout(1200)
        after = labels_everywhere()
        ck('μετά το τσεκ «Εμπορικό» η ετικέτα ΔΕΝ φαίνεται σε Αξιοποιήσιμα/Ειδικής Διαχείρισης/Πλακέτες/Απόρριψη', lb not in after, f'{lb}: {lb in after}')
        pw.click('.readyGroupTab[data-readygroup="PRESS"]'); pw.wait_for_timeout(1500)
        inv1 = pw.evaluate("api('/reports/inventory-count?year=2026')")
        tot = lambda d: round(sum(x2 for r_ in d['rows'] for q_ in r_['quarters'] for x2 in [q_.get('processing') or 0, q_.get('sales') or 0]), 3)
        ck('απογραφή (αναφορά): τα ποσά του εμπορικού δεν μετρούν πια', tot(inv1) < tot(inv0) or lb not in str(inv0), f'{tot(inv0)} → {tot(inv1)}')
        setc(False)
    else:
        print('· (παράλειψη εξαίρεσης: δεν βρέθηκε ετικέτα με μοναδικό υλικό)')
    # ---- ΙΝΟΧ = INOX ----
    inox = db("select id from materials where active=1 and galaxy_code='00020'")
    if inox:
        call('POST', '/inventory/material-corrections', {'work_date': time.strftime('%Y-%m-%d'), 'material_label': 'ΙΝΟΧ', 'weight_kg_delta': 5000, 'piece_delta': 0, 'reason': 'δοκιμή'})   # θετικό ισοζύγιο στην ετικέτα με ΕΛΛΗΝΙΚΑ γράμματα
        lab = db("select count(*) from material_output_entries where material_label='ΙΝΟΧ' and active=1")[0][0]
        led = (db("select coalesce(sum(weight_kg),0) from material_output_entries where active=1 and material_label='ΙΝΟΧ'")[0][0] or 0) - (db("select coalesce(sum(weight_kg),0) from material_shipment_entries where active=1 and material_label='ΙΝΟΧ'")[0][0] or 0) + (db("select coalesce(sum(weight_kg_delta),0) from material_correction_entries where material_label='ΙΝΟΧ'")[0][0] or 0)
        cat = pw.evaluate("api('/mat/catalog')"); mi = next(m for m in cat['materials'] if m['id'] == inox[0][0])
        exp_ = db("select coalesce(sum(coalesce(counted_kg,net_weight)),0) from ready_material_lots where material_id=? and entry_type='EXPORT' and is_demo=0 and status!='CANCELLED'", inox[0][0])[0][0] or 0
        ck('απόθεμα Android: η ετικέτα «ΙΝΟΧ» (ελληνικά) δίνει απόθεμα στο υλικό «INOX» (λατινικά)', lab > 0 and abs(mi['available_kg'] - max(0, led - exp_)) < 0.01 and (led - exp_) > 0, f"ετικέτες {lab} · ισοζύγιο {led:.1f} · διαθέσιμο {mi['available_kg']}")
    ck('σύγκριση στο πρόγραμμα: «ΙΝΟΧ» = «INOX», «Β» ≠ «Β+»', pw.evaluate("foldName('ΙΝΟΧ')===foldName('INOX')&&foldName('ΠΛΑΚΕΤΕΣ ΚΑΤΗΓΟΡΙΑΣ B')===foldName('ΠΛΑΚΕΤΕΣ ΚΑΤΗΓΟΡΙΑΣ Β')&&foldName('ΠΛΑΚΕΤΕΣ ΚΑΤΗΓΟΡΙΑΣ B+')!==foldName('ΠΛΑΚΕΤΕΣ ΚΑΤΗΓΟΡΙΑΣ Β')&&foldName('ΚΑΤΗΓΟΡΙΑΣ ΑA1')===foldName('ΚΑΤΗΓΟΡΙΑΣ ΑΑ1')"))
    ck('σφάλματα σελίδας', not errs, str(errs[:2]))
    b.close()
print('ΑΠΟΤΥΧΙΕΣ:', bad)
sys.exit(1 if bad else 0)
