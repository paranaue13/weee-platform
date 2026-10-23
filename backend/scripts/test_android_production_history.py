"""Δοκιμή Android › Παραγωγή › Ιστορικό καταχωρήσεων + ΥΠΟΛΟΙΠΟ (360×640).
Χρήση: python backend/scripts/test_android_production_history.py http://127.0.0.1:PORT C:/ΑΝΤΙΓΡΑΦΟ.db [φάκελος screenshots]   (ΜΟΝΟ σε ΑΝΤΙΓΡΑΦΟ βάσης!)"""
import sys, os, sqlite3, datetime
sys.path.insert(0, os.path.dirname(__file__))
sys.stdout.reconfigure(encoding='utf-8')
from playwright.sync_api import sync_playwright
from _browser import launch
B, DB = sys.argv[1], sys.argv[2]; S = (sys.argv[3] if len(sys.argv) > 3 else '.') + '/h_'
bad = []
def ck(name, ok, info=''):
    print(('✓ ' if ok else '✗ ') + name, info)
    if not ok: bad.append(name)
c = sqlite3.connect(DB)
lots = c.execute("select l.id,l.weee_category_id,m.tare_weight from weee_stock_lots l join collection_media m on m.id=l.collection_medium_id where l.available_weight>=120 and m.tare_weight>0 order by l.id limit 2").fetchall()
(LA, CA, TA), (LB, CB, TB) = lots
units = [r[0] for r in c.execute("select id from organizational_units where active=1 and profile='PRODUCTION' order by id limit 2").fetchall()]
U1, U2 = units
today = datetime.date.today().isoformat()
with sync_playwright() as p:
    b = launch(p); errs = []
    pg = b.new_page(viewport={'width': 360, 'height': 640}, is_mobile=True, has_touch=True, device_scale_factor=1)
    pg.on('pageerror', lambda e: errs.append(str(e)))
    pg.goto(B + '/mobile', wait_until='networkidle'); pg.click('#loginBtn'); pg.wait_for_selector('#app:not(.hidden)'); pg.wait_for_timeout(2500)
    def call(m, path, body=None):
        return pg.evaluate("([m,p,b])=>fetch(p,{method:m,headers:{'Content-Type':'application/json','Authorization':'Bearer '+token},body:b?JSON.stringify(b):undefined}).then(async r=>[r.status,await r.json().catch(()=>null)])", [m, path, body])
    def send(lot, cat, w, unit):
        st, j = call('POST', '/production/transfers', {'destination_org_unit_id': unit, 'items': [{'stock_lot_id': lot, 'weight': w}]})
        call('POST', '/production/work-entries', {'work_date': today + 'T00:00:00', 'org_unit_id': unit, 'weee_category_id': cat, 'weight_kg': w, 'source': 'ANDROID', 'transfer_id': j['id']})
        return j['id']
    tA = send(LA, CA, 100, U1); tB = send(LB, CB, 60, U2)
    # παλαιότερη ημέρα: μετακίνηση της ημερομηνίας της B στο χθες (αντίγραφο βάσης)
    y = (datetime.date.today() - datetime.timedelta(days=1)).isoformat()
    c2 = sqlite3.connect(DB); c2.execute("update production_transfers set created_at=? where id=?", (y + ' 10:00:00.000000', tB)); c2.commit(); c2.close()
    pg.tap('.secBtn[data-section=production]'); pg.wait_for_timeout(1500)
    pg.evaluate("loadProdToday()"); pg.wait_for_timeout(1500)
    ck('τίτλος «Ιστορικό καταχωρήσεων»', 'Ιστορικό καταχωρήσεων' in pg.inner_text('#secProduction'))
    days = pg.locator('.ptDay').all_inner_texts()
    ck('ομαδοποίηση ανά ημέρα, πιο πρόσφατη πρώτα (Σήμερα, μετά Χθες)', len(days) >= 2 and days[0].upper().startswith('ΣΗΜΕΡΑ') and days[1].upper().startswith('ΧΘΕΣ'), str(days[:3]))
    ck('καταχωρήσεις και των δύο ημερών', pg.locator('.ptItem').count() >= 2)
    # φίλτρο τμήματος
    pg.select_option('#ptUnitFilter', U1); pg.wait_for_timeout(1500)
    u1name = pg.evaluate("prodUnits.find(u=>u.id==='%s').name_el" % U1)
    items = pg.locator('.ptItem').all_inner_texts()
    ck('φίλτρο τμήματος: μόνο δικές του καταχωρήσεις', len(items) > 0 and all(u1name in t for t in items) and pg.locator('.ptDay').count() == 1, f'{len(items)} καταχωρήσεις')
    pg.select_option('#ptUnitFilter', ''); pg.wait_for_timeout(1500)
    # πάτημα καταχώρησης
    pg.locator('.ptTap').first.tap(); pg.wait_for_timeout(300)
    btns = pg.locator('.ptBtns3 button').all_inner_texts()
    ck('πάτημα: ΔΙΟΡΘΩΣΗ / ΥΠΟΛΟΙΠΟ / ΔΙΑΓΡΑΦΗ', btns == ['ΔΙΟΡΘΩΣΗ', 'ΥΠΟΛΟΙΠΟ', 'ΔΙΑΓΡΑΦΗ'], str(btns))
    ck('χρώμα στο ΟΝΟΜΑ του μέσου (κεχριμπάρι), όχι στα kg', pg.locator('.ptPill.a').count() >= 1 and pg.evaluate("getComputedStyle(document.querySelector('.ptKg')).color") == 'rgb(47, 95, 196)')
    pg.screenshot(path=S + 'sel.png')
    pg.locator('.ptRemBtn').tap(); pg.wait_for_timeout(300)
    ck('ΥΠΟΛΟΙΠΟ: ΜΙΚΤΑ / ΚΑΘΑΡΑ και κιλά', pg.locator('.ptRM').count() == 2 and pg.locator('#ptRemKg').count() == 1)
    pg.locator('#ptRemKg').fill(str(float(TA) + 30)); pg.wait_for_timeout(300)
    prev = pg.inner_text('#ptRemPrev')
    ck('ζωντανή προεπισκόπηση: καθαρό υπόλοιπο 30 / καθαρή παραγωγή 70', 'Καθαρό υπόλοιπο' in prev and '30' in prev and '70' in prev, prev.replace('\n', ' '))
    pg.locator('.ptRM[data-m="NET"]').tap(); pg.wait_for_timeout(200); pg.locator('#ptRemKg').fill('500'); pg.locator('.ptRemSave').tap(); pg.wait_for_timeout(1000)
    ck('υπόλοιπο > στάλθηκαν → μήνυμα', 'δεν μπορεί να είναι μεγαλύτερο' in pg.inner_text('#ptMsg'), pg.inner_text('#ptMsg'))
    pg.locator('#ptRemKg').fill('30'); pg.locator('.ptRemSave').tap(); pg.wait_for_timeout(2000)
    ck('κεχριμπάρι μέσο με «περίσσεψαν 30 kg»', 'περίσσεψαν 30' in pg.inner_text('#prodTodayList'))
    ck('kg που φαίνονται = καθαρή παραγωγή 70', '70 kg' in pg.inner_text('#prodTodayList'))
    pg.screenshot(path=S + 'rem.png')
    # το Windows/server βλέπει το ίδιο
    dev = call('GET', f'/production/device-list?date={today}')[1]
    ck('κοινά δεδομένα: ο server έχει υπόλοιπο 30', any(d['transfer_id'] == tA and d['remainder_kg'] == 30 for d in dev))
    # διόρθωση kg με υπόλοιπο → οδηγία
    pg.locator('.ptItem', has=pg.locator('.ptRem')).first.tap(); pg.wait_for_timeout(300)
    pg.locator('.ptEdit').tap(); pg.wait_for_timeout(500)
    ck('ΔΙΟΡΘΩΣΗ με υπόλοιπο → ζητά πρώτα ΑΝΑΙΡΕΣΗ ΥΠΟΛΟΙΠΟΥ', 'ΑΝΑΙΡΕΣΗ ΥΠΟΛΟΙΠΟΥ' in pg.inner_text('#flToast') and pg.locator('#ptKg').count() == 0, pg.inner_text('#flToast'))
    pg.locator('.ptRemBtn').tap(); pg.wait_for_timeout(300)
    ck('με υπάρχον υπόλοιπο: κουμπί ΑΝΑΙΡΕΣΗ ΥΠΟΛΟΙΠΟΥ', pg.locator('.ptRemUndo').count() == 1)
    pg.locator('.ptRemUndo').tap(); pg.wait_for_timeout(2000)
    ck('μετά την αναίρεση: χωρίς «περίσσεψαν», 100 kg ξανά', 'περίσσεψαν' not in pg.inner_text('#prodTodayList') and '100 kg' in pg.inner_text('#prodTodayList'), pg.inner_text('#prodTodayList')[:300].replace(chr(10),' | '))
    # ΔΙΑΓΡΑΦΗ με δεύτερο πάτημα
    pg.locator('.ptTap').first.tap(); pg.wait_for_timeout(300)
    n0 = pg.locator('.ptItem').count()
    pg.locator('.ptDel').tap(); pg.wait_for_timeout(300)
    ck('ΔΙΑΓΡΑΦΗ: πρώτο πάτημα ζητά επιβεβαίωση', 'ΣΙΓΟΥΡΑ' in pg.locator('.ptDel').inner_text() and pg.locator('.ptItem').count() == n0)
    pg.locator('.ptDel').tap(); pg.wait_for_timeout(2000)
    ck('ΔΙΑΓΡΑΦΗ: δεύτερο πάτημα διαγράφει την καταχώρηση', pg.locator('.ptItem').count() == n0 - 1)
    ck('σφάλματα σελίδας', not errs, str(errs[:2]))
    call('POST', f'/production/transfers/{tB}/cancel')
    b.close()
print('ΑΠΟΤΥΧΙΕΣ:', bad)
sys.exit(1 if bad else 0)
