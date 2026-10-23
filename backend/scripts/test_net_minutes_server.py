"""Δοκιμή server › ΚΟΙΝΕΣ καθαρές ώρες (ζωντανές) + κανόνας αφαίρεσης από τμήμα.
Χρήση: python backend/scripts/test_net_minutes_server.py http://127.0.0.1:PORT   (server σε ΑΝΤΙΓΡΑΦΟ βάσης: γράφει παρουσίες/τμήματα!)"""
import sys, os, datetime
os.environ.setdefault('DATABASE_URL', 'sqlite:///:memory:')
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
sys.stdout.reconfigure(encoding='utf-8')
sys.path.insert(0, os.path.dirname(__file__))
from playwright.sync_api import sync_playwright
from _browser import launch
import app.main as M
B = sys.argv[1]
bad = []
def ck(name, ok, info=''):
    print(('✓ ' if ok else '✗ ') + name, info)
    if not ok: bad.append(name)
SCH = {'s': 435, 'e': 935}              # 07:15–15:35
BA = [(570, 575), (710, 725)]            # Τμήμα Α: 09:30–09:35, 11:50–12:05
core = lambda **k: M._net_minutes_core(SCH, k.pop('breaks', BA), k.pop('status', 'PRESENT'), k.pop('late', False), k.pop('arrived', None), k.pop('since', None), k.pop('shorts', None), k.pop('live', None))
hm = lambda h, m: h * 60 + m
ck('ολόκληρη ημέρα (παλαιότερη): 07:15–15:35 με διαλείμματα 5+15΄ = 8ω 00λ', core() == 480, str(core()))
ck('με άφιξη 07:39: 7ω 36λ', core(late=True, arrived=hm(7, 39)) == 456, str(core(late=True, arrived=hm(7, 39))))
ck('ζωντανά στις 10:00: 165΄ − διάλειμμα 5΄ = 160΄', core(live=hm(10, 0)) == 160, str(core(live=hm(10, 0))))
ck('διάλειμμα που τρέχει (11:57): αφαιρείται μόνο το κομμάτι που πέρασε (7΄ από τα 15΄)', core(live=hm(11, 57)) == (hm(11, 57) - 435) - 5 - 7, str(core(live=hm(11, 57))))
ck('πριν την έναρξη βάρδιας (06:00) = 0', core(live=hm(6, 0)) == 0)
ck('όποιος φτάνει ΜΕΤΑ από διάλειμμα δεν χάνει ώρες γι\' αυτό (άφιξη 12:30, τώρα 13:00 = 30΄)', core(late=True, arrived=hm(12, 30), live=hm(13, 0)) == 30)
ck('ΕΦΥΓΕ 14:00 (σήμερα, τώρα 15:00): μέχρι την ώρα ΕΦΥΓΕ, όχι ως τώρα', core(status='LEFT', since=hm(14, 0), live=hm(15, 0)) == (hm(14, 0) - 435) - 20)
ck('ΑΠΩΝ = 0', core(status='ABSENT') == 0 and core(status='ABSENT', shorts=[(700, 740)]) == 0)
ck('ΑΡΓΟΠΟΡΙΑ χωρίς ώρα άφιξης → None (δεν υπολογίζεται ακόμα)', core(late=True) is None)
ck('ΠΑΡΑΔΕΙΓΜΑ ολιγόωρης: διάλειμμα 11:50–12:05, ολιγόωρη 11:40–12:20 → −25΄ (όχι 40΄)', core(shorts=[(hm(11, 40), hm(12, 20))]) == 480 - 25)
ck('ολιγόωρη μέσα στο διάλειμμα → δεν αφαιρείται', core(shorts=[(712, 720)]) == 480)
ck('ανοιχτή ολιγόωρη → None («—»)', core(shorts=[(700, None)]) is None)
ck('ολιγόωρη εκτός [προσέλευση, αποχώρηση] περιορίζεται (άφιξη 08:00, ολιγόωρη 07:30–08:30 → −30΄)', core(late=True, arrived=480, shorts=[(450, 510)]) == core(late=True, arrived=480) - 30)
ck('Τμήμα Β (άλλα διαλείμματα) χωρίς διαλείμματα: 500΄', core(breaks=[]) == 500)
ctx = {'s': 435, 'e': 935, 'A': BA, 'B': [(580, 590)], 'groups': {'uB': 'B'}, 'emp_units': {}}
class E: id = 'e1'; default_org_unit_id = 'uB'
ck('ομάδα διαλειμμάτων Β από τη ρύθμιση Τμήμα → Α/Β', M._row_net(ctx, E, 'PRESENT', False, None, None, [], None, datetime.date(2026, 1, 5)) == 500 - 10)
ck('μελλοντική ημέρα = 0', M._row_net(ctx, E, 'PRESENT', False, None, None, [], None, datetime.date.today() + datetime.timedelta(days=3)) == 0)
# ---------- API + διασταύρωση με τη συνάρτηση του browser ----------
with sync_playwright() as p:
    b = launch(p)
    pg = b.new_page(viewport={'width': 1400, 'height': 800}); errs = []
    pg.on('pageerror', lambda e: errs.append(str(e)))
    pg.goto(B + '/', wait_until='networkidle'); pg.wait_for_selector('#loginBtn', state='visible'); pg.click('#loginBtn'); pg.wait_for_selector('#metrics .card', timeout=20000); pg.wait_for_timeout(1000)
    today = datetime.date.today().isoformat()
    eff = pg.evaluate("d=>api('/production/attendance/effective?date='+d)", today)
    ck('server: /effective επιστρέφει net_minutes (αριθμό ή null) για κάθε εργαζόμενο', all('net_minutes' in x for x in eff) and len(eff) > 0)
    rg = pg.evaluate("api('/production/attendance/effective-range?start=2026-10-01&end=2026-10-14')")
    ck('server: /effective-range (Αναφορές) επιστρέφει net_minutes', len(rg) > 50 and all('net_minutes' in x for x in rg), str(len(rg)))
    cmp = pg.evaluate("""async rows=>{
      const sc=await api('/settings/schedule'),grp=await api('/settings/break-groups'),emps=await api('/master/employees'),em={};emps.forEach(e=>em[e.id]=e);
      let bad=[],n=0;
      rows.forEach(a=>{
        const e=em[a.employee_id];if(!e)return;
        const unit=a.org_unit_id||e.default_org_unit_id||((e.org_unit_ids||[])[0]),g=(grp&&grp[unit])==='B'?'B':'A',sm=scheduleToMinutes(sc,null,g),t=x=>x?tfToM(deltioTimeStr(x)):null;
        const js=a.status==='ABSENT'?0:attendanceNetMinutes({absent:false,late:!!a.late,arrived:t(a.arrived_at),left:a.status==='LEFT',leave:t(a.since_at),shorts:shortsToMinutes(a.short_leaves)},sm);
        n++;if((js===null?null:js)!==a.net_minutes)bad.push([e.full_name,a.work_date.slice(0,10),a.status,js,a.net_minutes]);
      });return {n,bad:bad.slice(0,6),nb:bad.length}}""", rg)
    print('σύγκριση browser ↔ server:', cmp['n'], 'γραμμές,', cmp['nb'], 'διαφορές', cmp['bad'])
    ck('ΙΔΙΟ αποτέλεσμα: η συνάρτηση του browser και του server συμφωνούν σε όλες τις γραμμές της περιόδου', cmp['n'] > 50 and cmp['nb'] == 0)
    # κανόνας αφαίρεσης από τμήμα
    emps = pg.evaluate("api('/master/employees').then(r=>r.filter(e=>e.active!==false).map(e=>({id:e.id,u:e.org_unit_ids||[]})))")
    one = next(e for e in emps if len(e['u']) == 1); two = next((e for e in emps if len(e['u']) >= 2), None)
    units = pg.evaluate("api('/master/org-units').then(r=>r.filter(u=>u.active!==false&&u.profile==='PRODUCTION').map(u=>u.id))")
    call = lambda body: pg.evaluate("b=>fetch('/production/attendance/units',{method:'POST',headers:{'Content-Type':'application/json','Authorization':'Bearer '+token},body:JSON.stringify(b)}).then(async r=>[r.status,await r.json()])", body)
    st, d = call({'work_date': today, 'employee_id': one['id'], 'action': 'remove', 'unit_id': one['u'][0]})
    ck('αφαίρεση από το ΜΟΝΑΔΙΚΟ τμήμα απορρίπτεται (409)', st == 409, str(d)[:90])
    other = next(u for u in units if u not in one['u'])
    st, d = call({'work_date': today, 'employee_id': one['id'], 'action': 'add', 'unit_id': other})
    ck('«Προσθήκη και σε άλλο τμήμα»: δέχεται (200) και ο εργαζόμενος έχει 2 τμήματα', st == 200 and len(d['org_unit_ids']) == 2, str(d))
    st, d = call({'work_date': today, 'employee_id': one['id'], 'action': 'remove', 'unit_id': other})
    ck('με 2 τμήματα η αφαίρεση επιτρέπεται (200) και μένει 1', st == 200 and len(d['org_unit_ids']) == 1, str(d))
    ck('σφάλματα σελίδας', not errs, str(errs[:2]))
    b.close()
print('ΑΠΟΤΥΧΙΕΣ:', bad)
sys.exit(1 if bad else 0)
