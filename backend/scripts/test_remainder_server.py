"""Δοκιμή server › ΥΠΟΛΟΙΠΟ μέσου (μικτά/καθαρά, απόβαρο αποστολής, αυτόματο «άδειασε», επιστροφή «μισού», αναίρεση, ιστορικό).
Χρήση: python backend/scripts/test_remainder_server.py http://127.0.0.1:PORT C:/path/ΑΝΤΙΓΡΑΦΟ.db   (server ΜΟΝΟ σε ΑΝΤΙΓΡΑΦΟ βάσης!)"""
import sys, os, sqlite3, datetime
sys.path.insert(0, os.path.dirname(__file__))
sys.stdout.reconfigure(encoding='utf-8')
from playwright.sync_api import sync_playwright
from _browser import launch
B, DB = sys.argv[1], sys.argv[2]
bad = []
def ck(name, ok, info=''):
    print(('✓ ' if ok else '✗ ') + name, info)
    if not ok: bad.append(name)
from _testdata import ensure_medium_lots; ensure_medium_lots(DB)
c = sqlite3.connect(DB)
lots = c.execute("select l.id,l.collection_medium_id,l.available_weight,m.tare_weight from weee_stock_lots l join collection_media m on m.id=l.collection_medium_id where l.available_weight>=120 and m.tare_weight is not null and m.tare_weight>0 order by l.id limit 2").fetchall()
assert len(lots) == 2, lots
(LA, MA, AVA, TA), (LB, MB, AVB, TB) = lots
unit = c.execute("select id from organizational_units where active=1 and profile='PRODUCTION' order by id limit 1").fetchone()[0]
today = datetime.date.today().isoformat()
with sync_playwright() as p:
    b = launch(p); pg = b.new_page(viewport={'width': 1300, 'height': 900})
    pg.goto(B + '/', wait_until='networkidle'); pg.wait_for_selector('#loginBtn', state='visible'); pg.click('#loginBtn'); pg.wait_for_selector('#metrics .card', timeout=20000); pg.wait_for_timeout(800)
    def call(method, path, body=None):
        return pg.evaluate("([m,p,b])=>fetch(p,{method:m,headers:{'Content-Type':'application/json','Authorization':'Bearer '+token},body:b?JSON.stringify(b):undefined}).then(async r=>{let t=await r.text();let j=null;try{j=JSON.parse(t)}catch(e){};return [r.status,j,t]})", [method, path, body])
    dev = lambda: call('GET', f'/production/device-list?date={today}')[1]
    row = lambda tid: next(r for r in dev() if r['transfer_id'] == tid)
    def lot_av(l): return float(sqlite3.connect(DB).execute("select available_weight from weee_stock_lots where id=?", (l,)).fetchone()[0])
    def med_status(m): return sqlite3.connect(DB).execute("select status from collection_media where id=?", (m,)).fetchone()[0]
    def entry_w(tid): return float(sqlite3.connect(DB).execute("select weight_kg from production_work_entries where transfer_id=? and active=1", (tid,)).fetchone()[0])
    def send(lot, w):
        st, j, _ = call('POST', '/production/transfers', {'destination_org_unit_id': unit, 'items': [{'stock_lot_id': lot, 'weight': w}]})
        cat = sqlite3.connect(DB).execute("select weee_category_id from weee_stock_lots where id=?", (lot,)).fetchone()[0]
        call('POST', '/production/work-entries', {'work_date': today + 'T00:00:00', 'org_unit_id': unit, 'weee_category_id': cat, 'weight_kg': w, 'source': 'WINDOWS', 'transfer_id': j['id']})   # όπως κάνουν οι οθόνες
        return st, j
    # --- αποστολή Α ---
    SENT = 100
    st, j = send(LA, SENT)
    ck('αποστολή μέσου Α στο τμήμα', st == 200, str(st)); tidA = j['id']
    r = row(tidA); itemA = r['item_id']; avA0 = lot_av(LA)
    ck('απόβαρο αποθηκεύτηκε τη στιγμή της αποστολής', r['tare_kg'] == float(TA) and r['tare_source'] == 'shipment', str(r['tare_kg']))
    ck('τελευταίο μέσο = «σε εξέλιξη»', r['state'] == 'IN_PROGRESS' and r['weight_kg'] == SENT and r['sent_kg'] == SENT)
    # αλλαγή απόβαρου στο μητρώο ΜΕΤΑ την αποστολή -- δεν πρέπει να επηρεάσει το υπόλοιπο
    c2 = sqlite3.connect(DB); c2.execute("update collection_media set tare_weight=? where id=?", (float(TA) + 50, MA)); c2.commit(); c2.close()
    # --- σφάλματα ---
    st, j, _ = call('POST', f'/production/transfer-items/{itemA}/remainder', {'mode': 'NET', 'kg': SENT + 1})
    ck('υπόλοιπο > kg που στάλθηκαν → σφάλμα', st == 422 and 'δεν μπορεί να είναι μεγαλύτερο' in (j or {}).get('detail', ''), str(j))
    st, j, _ = call('POST', f'/production/transfer-items/{itemA}/remainder', {'mode': 'GROSS', 'kg': float(TA) - 1})
    ck('μικτά < απόβαρο → σφάλμα', st == 422, str(j))
    st, j, _ = call('POST', f'/production/transfer-items/{itemA}/remainder', {'mode': 'NET', 'kg': -5})
    ck('αρνητικά κιλά → σφάλμα', st == 422)
    # --- ΜΙΚΤΑ: καθαρό = μικτά − απόβαρο ΑΠΟΣΤΟΛΗΣ ---
    st, j, _ = call('POST', f'/production/transfer-items/{itemA}/remainder', {'mode': 'GROSS', 'kg': float(TA) + 30})
    ck('υπόλοιπο ΜΙΚΤΑ → καθαρό 30 (με το παλιό απόβαρο, όχι το νέο του μητρώου)', st == 200 and j['remainder_net'] == 30 and j['net_production'] == SENT - 30, str(j))
    r = row(tidA)
    ck('κατάσταση «μισό» (κεχριμπάρι) + «περίσσεψαν 30»', r['state'] == 'PARTIAL' and r['remainder_kg'] == 30 and r['remainder_gross'] == float(TA) + 30 and r['remainder_mode'] == 'GROSS')
    ck('καθαρή παραγωγή = στάλθηκαν − υπόλοιπο, και στην καταχώρηση παραγωγής', r['weight_kg'] == SENT - 30 and r['sent_kg'] == SENT and entry_w(tidA) == SENT - 30)
    ck('το υπόλοιπο γύρισε στο απόθεμα ΑΗΗΕ', lot_av(LA) == avA0 + 30, f'{avA0} → {lot_av(LA)}')
    ck('το μέσο γύρισε στην Αποθήκη ΑΗΗΕ (WEEE_STORAGE)', med_status(MA) == 'WEEE_STORAGE', med_status(MA))
    ret = call('GET', f'/production/returns?date={today}')[1]
    x = next((q for q in ret if q['item_id'] == itemA), None)
    ck('λίστα «Επιστροφές στην Αποθήκη ΑΗΗΕ σήμερα» με καθαρό και μικτά', x and x['returned_net_kg'] == 30 and x['returned_gross_kg'] == float(TA) + 30, str(x and (x['returned_net_kg'], x['returned_gross_kg'])))
    # --- διόρθωση: ΚΑΘΑΡΑ 10 (αντικαθιστά, δεν προστίθεται) ---
    st, j, _ = call('POST', f'/production/transfer-items/{itemA}/remainder', {'mode': 'NET', 'kg': 10})
    ck('διόρθωση σε ΚΑΘΑΡΑ 10', st == 200 and j['net_production'] == SENT - 10 and lot_av(LA) == avA0 + 10 and entry_w(tidA) == SENT - 10, str(j))
    # --- επόμενο μέσο στο ίδιο τμήμα χωρίς υπόλοιπο ---
    st, j = send(LB, 60); tidB = j['id']
    ck('το νέο μέσο B είναι «σε εξέλιξη»', row(tidB)['state'] == 'IN_PROGRESS')
    ck('το Α με υπόλοιπο ΜΕΝΕΙ κεχριμπάρι (μισό)', row(tidA)['state'] == 'PARTIAL')
    st, j, _ = call('POST', f'/production/transfer-items/{itemA}/remainder/undo')
    ck('αναίρεση υπολοίπου: ξανά πλήρης παραγωγή', st == 200 and j['net_production'] == SENT and lot_av(LA) == avA0 and entry_w(tidA) == SENT, str(j))
    r = row(tidA)
    ck('Α χωρίς υπόλοιπο + στάλθηκε επόμενο μέσο στο ίδιο τμήμα → «άδειασε» (πράσινο)', r['state'] == 'EMPTIED' and r['weight_kg'] == SENT, r['state'])
    st, _, _ = call('POST', f'/production/transfers/{tidB}/cancel')
    ck('αναίρεση του επόμενου μέσου → το Α ξανά «σε εξέλιξη»', st == 200 and row(tidA)['state'] == 'IN_PROGRESS')
    # --- υπόλοιπο 0 ---
    st, j, _ = call('POST', f'/production/transfer-items/{itemA}/remainder', {'mode': 'NET', 'kg': 0})
    ck('υπόλοιπο 0 → άδειασε (πράσινο), τίποτα δεν επιστρέφει', st == 200 and row(tidA)['state'] == 'EMPTIED' and lot_av(LA) == avA0 and row(tidA)['weight_kg'] == SENT)
    st, _, _ = call('POST', f'/production/transfer-items/{itemA}/remainder/undo')
    ck('αναίρεση του 0', st == 200 and row(tidA)['state'] == 'IN_PROGRESS')
    # --- ιστορικό ---
    h = call('GET', '/production/device-history?days=30')[1]
    ck('ιστορικό ανά ημέρα, πιο πρόσφατη πρώτα', isinstance(h, list) and h and h[0]['date'] == today and [d['date'] for d in h] == sorted([d['date'] for d in h], reverse=True))
    hf = call('GET', f'/production/device-history?days=30&unit_id={unit}')[1]
    ck('φίλτρο τμήματος: μόνο δικές του καταχωρήσεις', all(i['org_unit_id'] == unit for d in hf for i in d['items']) and len(hf) > 0)
    # καθαρισμός: ακύρωση της δοκιμαστικής μεταφοράς Α
    call('POST', f'/production/transfers/{tidA}/cancel')
    ck('καθαρισμός: το απόθεμα γύρισε όπως ήταν', lot_av(LA) == avA0 + SENT, str(lot_av(LA)))
    b.close()
print('ΑΠΟΤΥΧΙΕΣ:', bad)
sys.exit(1 if bad else 0)
