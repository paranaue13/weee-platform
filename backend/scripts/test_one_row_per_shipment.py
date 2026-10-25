"""Δοκιμή server › ΜΙΑ γραμμή ανά αποστολή (ίδια αποστολή + ίδιο μέσο + ίδιο ΑΗΗΕ) σε Δελτίο, ιστορικό, επιστροφές, Υπόλοιπο/Αναίρεση.
Χρήση: python backend/scripts/test_one_row_per_shipment.py http://127.0.0.1:PORT C:/ΑΝΤΙΓΡΑΦΟ.db   (ΜΟΝΟ σε ΑΝΤΙΓΡΑΦΟ βάσης!)"""
import sys, os, sqlite3, datetime
sys.path.insert(0, os.path.dirname(__file__)); sys.stdout.reconfigure(encoding='utf-8')
from playwright.sync_api import sync_playwright
from _browser import launch
B, DB = sys.argv[1], sys.argv[2]
bad = []
def ck(n, ok, i=''):
    print(('✓ ' if ok else '✗ ') + n, i)
    if not ok: bad.append(n)
c = sqlite3.connect(DB)
# κατηγορία με ≥3 μερίδια χύμα (χωρίς μέσο) ώστε να έχουμε 2 μερίδια για την 1η αποστολή και 1 για τη 2η
cat = c.execute("select weee_category_id from weee_stock_lots where collection_medium_id is null and available_weight>=10 group by weee_category_id having count(*)>=3 order by count(*) desc limit 1").fetchone()[0]
L = [r[0] for r in c.execute("select id from weee_stock_lots where collection_medium_id is null and available_weight>=10 and weee_category_id=? order by id limit 3", (cat,)).fetchall()]
U = c.execute("select id from organizational_units where active=1 and profile='PRODUCTION' order by id limit 1").fetchone()[0]
today = datetime.date.today().isoformat()
db = lambda q, *a: sqlite3.connect(DB).execute(q, a).fetchall()
with sync_playwright() as p:
    b = launch(p); pg = b.new_page()
    pg.goto(B + '/', wait_until='networkidle'); pg.wait_for_selector('#loginBtn', state='visible'); pg.click('#loginBtn'); pg.wait_for_selector('#metrics .card', timeout=20000); pg.wait_for_timeout(800)
    def call(m, path, body=None):
        return pg.evaluate("([m,p,b])=>fetch(p,{method:m,headers:{'Content-Type':'application/json','Authorization':'Bearer '+token},body:b?JSON.stringify(b):undefined}).then(async r=>[r.status,await r.json().catch(()=>null)])", [m, path, body])
    rows = lambda: call('GET', f'/production/device-list?date={today}')[1]
    av_orig = {l: db("select available_weight from weee_stock_lots where id=?", l)[0][0] for l in L}
    # ---- ΑΠΟΣΤΟΛΗ 1: 2 μερίδια (4 + 6 = 10 kg) ----
    st, j = call('POST', '/production/transfers', {'destination_org_unit_id': U, 'items': [{'stock_lot_id': L[0], 'weight': 4}, {'stock_lot_id': L[1], 'weight': 6}], 'work_entry': {'weee_category_id': cat, 'source': 'ANDROID'}})
    t1 = j['id']
    # ---- ΑΠΟΣΤΟΛΗ 2: το ΙΔΙΟ ΑΗΗΕ, ΞΕΧΩΡΙΣΤΗ αποστολή ----
    st, j = call('POST', '/production/transfers', {'destination_org_unit_id': U, 'items': [{'stock_lot_id': L[2], 'weight': 5}], 'work_entry': {'weee_category_id': cat, 'source': 'ANDROID'}})
    t2 = j['id']
    r = rows(); r1 = [x for x in r if x['transfer_id'] == t1]; r2 = [x for x in r if x['transfer_id'] == t2]
    ck('αποστολή με 2 μερίδια → ΜΙΑ γραμμή των 10 kg', len(r1) == 1 and r1[0]['weight_kg'] == 10 and len(r1[0]['item_ids']) == 2, str([(x['weight_kg'], len(x['item_ids'])) for x in r1]))
    ck('δύο ξεχωριστές αποστολές του ίδιου ΑΗΗΕ ΔΕΝ ενώνονται', len(r2) == 1 and r2[0]['weight_kg'] == 5 and r1[0]['item_id'] != r2[0]['item_id'])
    h = call('GET', '/production/device-history?days=2')[1]
    ck('ιστορικό: οι ίδιες 2 γραμμές', sum(1 for d in h for x in d['items'] if x['transfer_id'] in (t1, t2)) == 2)
    # ---- ΥΠΟΛΟΙΠΟ ανά γραμμή: 7 kg καθαρά → μοιράζεται εσωτερικά ----
    av0 = {l: db("select available_weight from weee_stock_lots where id=?", l)[0][0] for l in L}
    st, rj = call('POST', f"/production/transfer-items/{r1[0]['item_id']}/remainder", {'mode': 'NET', 'kg': 7})
    ck('Υπόλοιπο 7 kg σε ΜΙΑ γραμμή (χωρίς χειροκίνητο μοίρασμα)', st == 200 and rj['remainder_net'] == 7 and rj['net_production'] == 3, str(rj))
    rr = [x for x in rows() if x['transfer_id'] == t1][0]
    ck('η γραμμή δείχνει υπόλοιπο 7 και καθαρή παραγωγή 3 (ΜΙΑ γραμμή)', rr['remainder_kg'] == 7 and rr['weight_kg'] == 3 and rr['sent_kg'] == 10 and rr['state'] == 'PARTIAL' and len([x for x in rows() if x['transfer_id'] == t1]) == 1)
    parts = db("select remainder_net,weight from production_transfer_items where transfer_id=? order by rowid", t1)
    ck('εσωτερικά: μοιράστηκε στα 2 μερίδια (6 στο τελευταίο, 1 στο πρώτο)', [p[0] for p in parts] == [1, 6] and [p[1] for p in parts] == [3, 0], str(parts))
    ck('το απόθεμα γύρισε: +7 συνολικά στα μερίδια', round(sum(db("select available_weight from weee_stock_lots where id=?", l)[0][0] for l in L[:2]) - sum(av0[l] for l in L[:2]), 3) == 7)
    ck('η καταχώρηση παραγωγής = 3 (καθαρή)', db("select weight_kg from production_work_entries where transfer_id=? and active=1", t1)[0][0] == 3)
    ret = call('GET', f'/production/returns?date={today}')[1]; rt = [x for x in ret if x['transfer_id'] == t1]
    ck('λωρίδα επιστροφών: ΜΙΑ γραμμή των 7 kg για την αποστολή', len(rt) == 1 and rt[0]['returned_net_kg'] == 7, str(rt and rt[0]['returned_net_kg']))
    # διόρθωση του υπολοίπου (αντικατάσταση, όχι πρόσθεση)
    st, rj = call('POST', f"/production/transfer-items/{r1[0]['item_id']}/remainder", {'mode': 'NET', 'kg': 2})
    ck('διόρθωση σε 2 kg: αντικαθιστά (καθαρή παραγωγή 8)', st == 200 and rj['net_production'] == 8 and db("select weight_kg from production_work_entries where transfer_id=? and active=1", t1)[0][0] == 8, str(rj))
    st, rj = call('POST', f"/production/transfer-items/{r1[0]['item_id']}/remainder", {'mode': 'NET', 'kg': 11})
    ck('υπόλοιπο μεγαλύτερο από τα 10 της αποστολής → σφάλμα', st == 422 and '10' in rj['detail'], rj['detail'])
    st, rj = call('POST', f"/production/transfer-items/{r1[0]['item_id']}/remainder/undo")
    ck('Αναίρεση: ΟΛΑ τα μερίδια επανέρχονται (10 kg, απόθεμα όπως πριν)', st == 200 and rj['net_production'] == 10 and all(abs(db("select available_weight from weee_stock_lots where id=?", l)[0][0] - av0[l]) < 0.001 for l in L[:2]), str(rj))
    # ---- Διόρθωση kg / Διαγραφή: ολόκληρη η αποστολή ----
    st, rj = call('PUT', f'/production/transfers/{t1}/weight', {'weight': 8})
    rr = [x for x in rows() if x['transfer_id'] == t1]
    ck('Διόρθωση kg αποστολής (10→8): μία γραμμή των 8', st == 200 and len(rr) == 1 and rr[0]['weight_kg'] == 8, str(rj))
    st, _ = call('POST', f'/production/transfers/{t1}/cancel')
    ck('Διαγραφή: φεύγει ολόκληρη η αποστολή (και τα 2 μερίδια)', st == 200 and not [x for x in rows() if x['transfer_id'] == t1] and all(abs(db("select available_weight from weee_stock_lots where id=?", l)[0][0] - av_orig[l]) < 0.001 for l in L[:2]))
    ck('η άλλη αποστολή δεν επηρεάστηκε', len([x for x in rows() if x['transfer_id'] == t2]) == 1)
    call('POST', f'/production/transfers/{t2}/cancel')
    # ---- ΔΥΟ διαφορετικά μέσα στην ίδια αποστολή → ΔΥΟ γραμμές (στο ΑΝΤΙΓΡΑΦΟ δίνουμε σε 2 μερίδια 2 διαφορετικά μέσα) ----
    ms = [r[0] for r in c.execute("select id from collection_media where active=1 order by id limit 2").fetchall()]
    ls = [r[0] for r in c.execute("select id from weee_stock_lots where collection_medium_id is null and available_weight>=10 and weee_category_id=? order by id desc limit 2", (cat,)).fetchall()]
    c2 = sqlite3.connect(DB)
    for m_, l_ in zip(ms, ls): c2.execute("update weee_stock_lots set collection_medium_id=? where id=?", (m_, l_))
    c2.commit(); c2.close()
    st, j = call('POST', '/production/transfers', {'destination_org_unit_id': U, 'items': [{'stock_lot_id': ls[0], 'weight': 5}, {'stock_lot_id': ls[1], 'weight': 5}], 'work_entry': {'weee_category_id': cat, 'source': 'ANDROID'}})
    rw = [x for x in rows() if x['transfer_id'] == j['id']]
    ck('δύο διαφορετικά μέσα σε μία αποστολή → ΔΥΟ γραμμές (υπόλοιπο ανά φυσικό μέσο)', len(rw) == 2 and sorted(x['weight_kg'] for x in rw) == [5, 5], str([(x['medium_code'], x['weight_kg']) for x in rw]))
    st, rj = call('POST', f"/production/transfer-items/{rw[0]['item_id']}/remainder", {'mode': 'NET', 'kg': 2})
    rw2 = {x['item_id']: x for x in rows() if x['transfer_id'] == j['id']}
    ck('Υπόλοιπο σε ΜΙΑ γραμμή (μέσο) δεν αγγίζει το άλλο μέσο', st == 200 and rw2[rw[0]['item_id']]['remainder_kg'] == 2 and rw2[rw[1]['item_id']]['remainder_kg'] is None)
    call('POST', f"/production/transfers/{j['id']}/cancel")
    b.close()
print('ΑΠΟΤΥΧΙΕΣ:', bad)
sys.exit(1 if bad else 0)
