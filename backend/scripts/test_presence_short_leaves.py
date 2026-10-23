"""Δοκιμή Windows › Παρουσιολόγιο › «Ολιγόωρη άδεια» (κουμπί, στήλη, chip, καθαρές ώρες, «Δεν επέστρεψε», server).
Χρήση: python backend/scripts/test_presence_short_leaves.py http://127.0.0.1:PORT   (server σε ΑΝΤΙΓΡΑΦΟ βάσης: γράφει παρουσίες!)"""
import sys, os, re, datetime
sys.path.insert(0, os.path.dirname(__file__))
sys.stdout.reconfigure(encoding='utf-8')
from playwright.sync_api import sync_playwright
from _browser import launch
B = sys.argv[1]
bad = []
def ck(name, ok, info=''):
    print(('✓ ' if ok else '✗ ') + name, info)
    if not ok: bad.append(name)
DAY = datetime.date.today().isoformat()
with sync_playwright() as p:
    b = launch(p); errs = []
    pg = b.new_page(viewport={'width': 1600, 'height': 900}); pg.on('pageerror', lambda e: errs.append(str(e)))
    pg.goto(B + '/', wait_until='networkidle'); pg.wait_for_selector('#loginBtn', state='visible'); pg.click('#loginBtn'); pg.wait_for_selector('#metrics .card', timeout=20000); pg.wait_for_timeout(1200)
    emps = pg.evaluate("api('/master/employees').then(r=>r.filter(e=>e.active!==false).map(e=>[e.id,e.full_name]))")
    E1, E2, E3, E4 = [e[0] for e in emps[:4]]; N1 = emps[0][1]
    put = lambda body: pg.evaluate("b=>fetch('/production/attendance',{method:'PUT',headers:{'Content-Type':'application/json','Authorization':'Bearer '+token},body:JSON.stringify(b)}).then(async r=>[r.status,await r.json()])", body)
    base = lambda e, **k: dict({'work_date': DAY, 'employee_id': e, 'status': 'PRESENT'}, **k)
    # ---------- server ----------
    for e in (E1, E2, E3, E4): put(base(e, short_leaves=[]))
    st, d = put(base(E1, short_leaves=[{'from': '11:40', 'to': '12:20'}]))
    ck('server: αποθήκευση ολιγόωρης {από, έως}', st == 200 and d['short_leaves'] == [{'from': '11:40', 'to': '12:20'}], str(d.get('short_leaves')))
    st, d = put(base(E1, short_leaves=[{'from': '10:00', 'to': '10:30'}, {'from': '10:20', 'to': '11:00'}]))
    ck('server: απορρίπτει επικάλυψη (422)', st == 422, str(d)[:80])
    st, d = put(base(E1, short_leaves=[{'from': '11:40', 'to': '11:40'}]))
    ck('server: απορρίπτει «Επέστρεψε» ≤ «Έφυγε» (422)', st == 422)
    st, d = put(base(E1, short_leaves=[{'from': '25:61', 'to': None}]))
    ck('server: απορρίπτει άκυρη ώρα (422)', st == 422)
    st, d = put(base(E1))      # αίτημα χωρίς το πεδίο (όπως το Android): οι ολιγόωρες μένουν
    ck('server: αίτημα χωρίς short_leaves (Android) δεν σβήνει τις ολιγόωρες', st == 200 and d['short_leaves'] == [{'from': '11:40', 'to': '12:20'}], str(d.get('short_leaves')))
    pg.evaluate('clearApiCache()')
    eff = pg.evaluate("d=>api('/production/attendance/effective?date='+d).then(r=>r)", DAY)
    ck('server: /effective επιστρέφει short_leaves (και [] για όσους δεν έχουν)', next(x for x in eff if x['employee_id'] == E1)['short_leaves'] == [{'from': '11:40', 'to': '12:20'}] and all(isinstance(x.get('short_leaves'), list) for x in eff))
    rg = pg.evaluate("d=>api('/production/attendance/effective-range?start='+d+'&end='+d)", DAY)
    ck('server: /effective-range (Αναφορές) επιστρέφει τις ίδιες ολιγόωρες', next(x for x in rg if x['employee_id'] == E1)['short_leaves'] == [{'from': '11:40', 'to': '12:20'}])
    put(base(E1, short_leaves=[]))
    # ---------- καθαρές ώρες (ΚΟΙΝΗ συνάρτηση) ----------
    net = lambda p, sch: pg.evaluate("([p,s])=>attendanceNetMinutes(p,s)", [p, sch])
    A = {'s': 435, 'e': 935, 'b': [[570, 575], [710, 725]]}       # 07:15–15:35, διαλείμματα Τμήματος Α: 09:30–09:35, 11:50–12:05
    base_net = net({}, A)
    ck('καθαρές ώρες χωρίς ολιγόωρη = 480΄', base_net == 480, str(base_net))
    ck('ΠΑΡΑΔΕΙΓΜΑ: διάλειμμα 11:50–12:05, ολιγόωρη 11:40–12:20 (40΄) → αφαιρούνται 25΄ (όχι 40΄, όχι διπλά)', net({'shorts': [[700, 740]]}, A) == 455, str(net({'shorts': [[700, 740]]}, A)))
    ck('ολιγόωρη ΜΕΣΑ στο διάλειμμα (11:52–12:00) → αφαιρούνται 0΄', net({'shorts': [[712, 720]]}, A) == 480)
    ck('δύο ολιγόωρες (10:00–10:30 και 13:00–13:15) → −45΄', net({'shorts': [[600, 630], [780, 795]]}, A) == 480 - 45)
    ck('ολιγόωρη εκτός ωραρίου (06:00–07:00) → τίποτα', net({'shorts': [[360, 420]]}, A) == 480)
    ck('με αργοπορία 08:00: ολιγόωρη 07:30–08:30 περιορίζεται στο [προσέλευση, αποχώρηση] → −30΄', net({'late': True, 'arrived': 480, 'shorts': [[450, 510]]}, A) == net({'late': True, 'arrived': 480}, A) - 30)
    ck('με πρόωρη αποχώρηση 14:00: ολιγόωρη 13:50–14:30 → −10΄', net({'left': True, 'leave': 840, 'shorts': [[830, 870]]}, A) == net({'left': True, 'leave': 840}, A) - 10)
    ck('ανοιχτή ολιγόωρη (χωρίς «Επέστρεψε») → null («—»), δεν αφαιρεί τίποτα', net({'shorts': [[700, None]]}, A) is None)
    ck('απών → 0 (ακόμα και με ολιγόωρη)', net({'absent': True, 'shorts': [[700, 740]]}, A) == 0)
    # με τις πραγματικές ρυθμίσεις του Τμήματος Α
    real = pg.evaluate("api('/settings/schedule').then(sc=>{const A=scheduleToMinutes(sc,null,'A');return {A,n0:attendanceNetMinutes({},A),n1:attendanceNetMinutes({shorts:[[700,740]]},A)}})")
    print('ρυθμίσεις Τμήματος Α:', real['A']['b'], real['n0'], '→', real['n1'])
    ck('πραγματικό ωράριο Τμήματος Α: ολιγόωρη 11:40–12:20 αφαιρεί 25΄', real['n0'] - real['n1'] == 25 and [710, 725] in real['A']['b'], str(real['A']['b']))
    # Αναφορές = ίδια συνάρτηση με τις ολιγόωρες (έλεγχος κώδικα)
    html = pg.evaluate("fetch('/desktop').then(r=>r.text())")
    ck('Αναφορές: καλούν την ίδια attendanceNetMinutes με shorts', 'shorts:shortsToMinutes(a.short_leaves)' in html and html.count('function attendanceNetMinutes') == 1)
    # ---------- Παρουσιολόγιο (UI) ----------
    for e in (E1, E2, E3, E4): put(base(e, short_leaves=[]))
    pg.evaluate('clearApiCache()'); pg.click('#openPresence'); pg.wait_for_selector('#presBody tr'); pg.wait_for_timeout(1200)
    row = lambda e: '#presBody tr:has(button[data-e="%s"][data-s="PRESENT"])' % e
    chip = lambda: int(pg.inner_text('#presence [data-pc="S"]'))
    heads = pg.evaluate("[...document.querySelectorAll('#presence .presTable thead th')].map(t=>t.innerText.trim())")
    ck('στήλη «Ολιγόωρες απουσίες» ανάμεσα σε «Αργοπορημένη προσέλευση» και «Πρόωρη αποχώρηση»', heads[3] == 'Αργοπορημένη προσέλευση' and heads[4] == 'Ολιγόωρες απουσίες' and heads[5] == 'Πρόωρη αποχώρηση', str(heads))
    segs = pg.evaluate("e=>[...document.querySelectorAll('#presBody button[data-e=\"'+e+'\"]')].map(b=>b.innerText)", E1)
    ck('κουμπί «Ολιγόωρη» μετά το «Έφυγε»', segs == ['Παρών', 'Αργοπορία', 'Απών', 'Έφυγε', 'Ολιγόωρη'], str(segs))
    c0 = chip()
    pg.click(row(E1) + ' button[data-s="SHORT"]'); pg.wait_for_timeout(1200)
    now = datetime.datetime.now(); nm = now.hour * 60 + now.minute
    fr = pg.input_value(row(E1) + ' .tpk[data-k="sfrom"] .tfIn'); to = pg.input_value(row(E1) + ' .tpk[data-k="sto"] .tfIn')
    fm = int(fr[:2]) * 60 + int(fr[3:])
    ck('πάτημα «Ολιγόωρη»: νέο κελί με «Έφυγε» = τρέχουσα ώρα και «Επέστρεψε» κενό', abs(fm - nm) <= 2 and to == '', f'{fr} / «{to}»')
    ck('το κουμπί φαίνεται ενεργό με μπλε #DCE6FB / #1F3F94', pg.evaluate("e=>{const b=document.querySelector('#presBody button[data-e=\"'+e+'\"][data-s=\"SHORT\"]'),c=getComputedStyle(b);return b.getAttribute('aria-pressed')==='true'&&c.backgroundColor==='rgb(220, 230, 251)'&&c.color==='rgb(31, 63, 148)'}", E1))
    ck('chip «Ολιγόωρη N» αυξήθηκε κατά 1 (μπλε)', chip() == c0 + 1 and pg.evaluate("getComputedStyle(document.querySelector('#presence .cs')).backgroundColor") in ('rgb(220, 230, 251)', 'rgb(230, 232, 238)'))
    ck('ανοιχτή ολιγόωρη → «—» στις καθαρές ώρες', pg.inner_text(row(E1) + ' .presNet').strip() in ('–', '—'))
    ck('εμφανίζεται «Δεν επέστρεψε → Πρόωρη αποχώρηση» και «+ Άλλη ολιγόωρη»', pg.is_visible(row(E1) + ' .slNr') and pg.inner_text(row(E1) + ' .slAdd') == '+ Άλλη ολιγόωρη')
    pg.screenshot(path=os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..', 'sl_tmp.png')) if False else None
    # δεύτερο πάτημα όσο υπάρχει ανοιχτή → επικάλυψη: μήνυμα, όχι αποθήκευση
    pg.click(row(E1) + ' .slAdd'); pg.wait_for_timeout(900)
    n = pg.evaluate("e=>document.querySelectorAll('#presBody tr:has(button[data-e=\"'+e+'\"][data-s=\"PRESENT\"]) .slv').length", E1)
    ck('επικάλυψη με ανοιχτή ολιγόωρη: μήνυμα και ΟΧΙ νέο κελί', n == 1 and 'επικαλύπτ' in pg.inner_text('#presMsg'), pg.inner_text('#presMsg'))
    # «Επέστρεψε» πριν το «Έφυγε» → μήνυμα, όχι αποθήκευση
    pg.evaluate("e=>{const i=document.querySelector('#presBody .tpk[data-e=\"'+e+'\"][data-k=\"sfrom\"] .tfIn');i.value='10:00';i.dispatchEvent(new Event('change',{bubbles:true}))}", E1); pg.wait_for_timeout(1000)
    pg.evaluate("e=>{const i=document.querySelector('#presBody .tpk[data-e=\"'+e+'\"][data-k=\"sto\"] .tfIn');i.value='09:00';i.dispatchEvent(new Event('change',{bubbles:true}))}", E1); pg.wait_for_timeout(1000)
    pg.evaluate('clearApiCache()')
    sv = pg.evaluate("d=>api('/production/attendance/effective?date='+d).then(r=>r.find(x=>x.employee_id==='%s').short_leaves)" % E1, DAY)
    ck('«Επέστρεψε» πριν το «Έφυγε»: μήνυμα και δεν αποθηκεύεται', 'μετά' in pg.inner_text('#presMsg') and sv == [{'from': '10:00', 'to': None}], f'{pg.inner_text("#presMsg")} | {sv}')
    # σωστή επιστροφή 10:30 → αφαιρεί 30΄ (δεν υπάρχει επικάλυψη διαλείμματος: Τμήμα Α/Β μετά τις 09:35)
    pg.evaluate("e=>{const i=document.querySelector('#presBody .tpk[data-e=\"'+e+'\"][data-k=\"sto\"] .tfIn');i.value='10:30';i.dispatchEvent(new Event('change',{bubbles:true}))}", E1); pg.wait_for_timeout(1300)
    n1 = pg.inner_text(row(E1) + ' .presNet').strip()
    ck('κλειστή ολιγόωρη 10:00–10:30: οι καθαρές ώρες ξαναϋπολογίζονται (όχι «—»)', n1 not in ('–', '—'), n1)
    # δεύτερη ολιγόωρη (από την τρέχουσα ώρα), μετά διαγραφή και των δύο
    if nm > 10 * 60 + 31:
        pg.click(row(E1) + ' .slAdd'); pg.wait_for_timeout(1200)
        n = pg.evaluate("e=>document.querySelectorAll('#presBody tr:has(button[data-e=\"'+e+'\"][data-s=\"PRESENT\"]) .slv').length", E1)
        ck('«+ Άλλη ολιγόωρη»: προστίθεται ΑΛΛΟ κελί (πολλές την ίδια μέρα)', n == 2, str(n))
    while pg.evaluate("e=>document.querySelectorAll('#presBody tr:has(button[data-e=\"'+e+'\"][data-s=\"PRESENT\"]) .slX').length", E1):
        pg.click(row(E1) + ' .slX'); pg.wait_for_timeout(900)
    ck('το × διαγράφει· χωρίς κελιά το κουμπί γυρνά σε ανενεργό', pg.evaluate("e=>document.querySelector('#presBody button[data-e=\"'+e+'\"][data-s=\"SHORT\"]').getAttribute('aria-pressed')", E1) == 'false' and chip() == c0)
    # ---------- «Δεν επέστρεψε → Πρόωρη αποχώρηση» ----------
    put(base(E2, short_leaves=[{'from': '10:00', 'to': None}]))
    pg.click('#presBack'); pg.evaluate('clearApiCache()'); pg.click('#openPresence'); pg.wait_for_selector('#presBody tr'); pg.wait_for_timeout(1200)
    pg.click(row(E2) + ' .slNr'); pg.wait_for_timeout(1500)
    pg.evaluate('clearApiCache()')
    a2 = pg.evaluate("d=>api('/production/attendance/effective?date='+d).then(r=>r.find(x=>x.employee_id==='%s'))" % E2, DAY)
    lv = pg.evaluate("iso=>deltioTimeStr(iso)", a2['since_at'])
    ck('«Δεν επέστρεψε»: κατάσταση LEFT με ώρα αποχώρησης = «Έφυγε» του κελιού, το κελί διαγράφεται', a2['status'] == 'LEFT' and lv == '10:00' and a2['short_leaves'] == [], f"{a2['status']} {lv} {a2['short_leaves']}")
    shown = pg.inner_text(row(E2) + ' .presNet').strip()
    exp = pg.evaluate("([e,att,sched,groups,emps])=>{const em=emps.find(x=>x.id===e),u=att.org_unit_id||em.default_org_unit_id||((em.org_unit_ids||[])[0]),g=groups&&groups[u]==='B'?'B':'A';const sm=scheduleToMinutes(sched,null,g);const m=attendanceNetMinutes({absent:false,late:!!att.late,arrived:att.arrived_at?tfToM(deltioTimeStr(att.arrived_at)):null,left:true,leave:tfToM(deltioTimeStr(att.since_at))},sm);return fmtNetHours(m)}",
                      [E2, a2, pg.evaluate("api('/settings/schedule')"), pg.evaluate("api('/settings/break-groups')"), pg.evaluate("api('/master/employees')")])
    ck('μετά την πρόωρη αποχώρηση οι καθαρές ώρες βγαίνουν από την ΥΠΑΡΧΟΥΣΑ συνάρτηση (αποχώρηση)', shown == exp, f'{shown} / {exp}')
    # αργοπορία + «Δεν επέστρεψε»
    put(base(E3, status='PRESENT', late=True, arrived_at=datetime.datetime.combine(datetime.date.today(), datetime.time(8, 0)).astimezone(datetime.timezone.utc).isoformat(), short_leaves=[{'from': '10:00', 'to': None}]))
    pg.click('#presBack'); pg.evaluate('clearApiCache()'); pg.click('#openPresence'); pg.wait_for_selector('#presBody tr'); pg.wait_for_timeout(1200)
    pg.click(row(E3) + ' .slNr'); pg.wait_for_timeout(1500)
    pg.evaluate('clearApiCache()')
    a3 = pg.evaluate("d=>api('/production/attendance/effective?date='+d).then(r=>r.find(x=>x.employee_id==='%s'))" % E3, DAY)
    shown3 = pg.inner_text(row(E3) + ' .presNet').strip()
    ck('αργοπορία + «Δεν επέστρεψε»: μένει η αργοπορία και η αποχώρηση 10:00 (προσέλευση ΚΑΙ αποχώρηση)', a3['status'] == 'LEFT' and a3['late'] and a3['arrived_at'] and 'ω' in shown3, f"{a3['status']} late={a3['late']} {shown3}")
    ck('σφάλματα σελίδας', not errs, str(errs[:3]))
    b.close()
print('ΑΠΟΤΥΧΙΕΣ:', bad)
sys.exit(1 if bad else 0)
