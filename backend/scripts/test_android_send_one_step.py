"""Δοκιμή Android › Αποστολή σε παραγωγή σε ΕΝΑ βήμα (μεταφορά + καταχώρηση παραγωγής + μετακίνηση εργαζομένου), 360×640.
Χρήση: python backend/scripts/test_android_send_one_step.py http://127.0.0.1:PORT C:/ΑΝΤΙΓΡΑΦΟ.db   (ΜΟΝΟ σε ΑΝΤΙΓΡΑΦΟ βάσης!)"""
import sys, os, sqlite3, datetime
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
    b = launch(p); pg = b.new_page(viewport={'width': 360, 'height': 640}, is_mobile=True, has_touch=True)
    errs = []; pg.on('pageerror', lambda e: errs.append(str(e)))
    pg.goto(B + '/mobile', wait_until='networkidle'); pg.click('#loginBtn'); pg.wait_for_selector('#app:not(.hidden)'); pg.wait_for_timeout(2500)
    pg.tap('.secBtn[data-section=production]'); pg.wait_for_timeout(1500); pg.evaluate("flLoad(true)"); pg.wait_for_timeout(4000)
    info = pg.evaluate("""()=>{let m=flMedia.find(g=>g.categories&&g.categories.length);if(!m)return null;let cid=m.categories[0].category_id;let u=prodUnits[0];let w=prodEmps.find(e=>!(e.org_unit_ids||[]).includes(u.id));return {mid:m.medium_id,cid,uid:u.id,wid:w.id}}""")
    n0 = db("select count(*) from production_transfers")[0][0]
    pg.evaluate("""i=>{let m=flMedia.find(g=>(g.medium_id||null)===(i.mid||null)),cat=flCat(i.cid),u=prodUnits.find(x=>x.id===i.uid),w=prodEmps.find(x=>x.id===i.wid);fl.busy=true;prodForm.emp=null;flDoSend({unit:u,medium:m,cat,worker:w,kg:5},'δοκιμή')}""", info)
    pg.wait_for_function("!fl.busy", timeout=30000); pg.wait_for_timeout(1500)
    ck('δημιουργήθηκε ΜΙΑ μεταφορά', db("select count(*) from production_transfers")[0][0] == n0 + 1)
    t = db("select id from production_transfers order by created_at desc limit 1")[0][0]
    ck('και η καταχώρηση παραγωγής (5 kg, ΑΝΔΡΟΙΔ) ίδια μεταφορά', db("select weight_kg,source from production_work_entries where transfer_id=?", t) == [(5, 'ANDROID')])
    ck('ο εργαζόμενος μετακινήθηκε στο τμήμα (μαζί με την αποστολή)', db("select default_org_unit_id from employees where id=?", info['wid'])[0][0] == info['uid'])
    ck('μήνυμα επιτυχίας με ΑΝΑΙΡΕΣΗ ΜΕΤΑΦΟΡΑΣ', 'Εστάλη' in pg.inner_text('#flToastMsg'), pg.inner_text('#flToastMsg')[:60])
    pg.evaluate("t=>api('/production/transfers/'+t+'/cancel',{method:'POST'})", t); pg.wait_for_function("!OB.pending()", timeout=20000)
    ck('σφάλματα σελίδας', not errs, str(errs[:2]))
    b.close()
print('ΑΠΟΤΥΧΙΕΣ:', bad)
sys.exit(1 if bad else 0)
