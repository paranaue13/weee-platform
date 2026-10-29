"""Δοκιμή Android › Υλικά → Εξαγωγή: ΔΙΟΡΘΩΣΗ και ΔΙΑΓΡΑΦΗ εξαγωγής (ιστορικό → φύλλο), μπλοκάρισμα όταν είναι δεσμευμένη/φορτωμένη, ελεύθερο μέσο,
επαναφορά απογραφής, ουρά εγγραφών (χωρίς σύνδεση). 360×700.
Χρήση: python backend/scripts/test_android_export_edit.py http://127.0.0.1:PORT C:/ΑΝΤΙΓΡΑΦΟ.db   (ΜΟΝΟ σε ΑΝΤΙΓΡΑΦΟ βάσης!)"""
import sys, os, sqlite3, uuid
sys.path.insert(0, os.path.dirname(__file__)); sys.stdout.reconfigure(encoding='utf-8')
from playwright.sync_api import sync_playwright
from _browser import launch
B, DB = sys.argv[1], sys.argv[2]
bad = []
def ck(n, ok, i=''):
    print(('✓ ' if ok else '✗ ') + n, i)
    if not ok: bad.append(n)
def db(q, *a, w=False):
    c = sqlite3.connect(DB); r = c.execute(q, a).fetchall()
    if w: c.commit()
    c.close(); return r
with sync_playwright() as p:
    b = launch(p); errs = []
    pg = b.new_page(viewport={'width': 360, 'height': 700}, is_mobile=True, has_touch=True); pg.on('pageerror', lambda e: errs.append(str(e)))
    pg.goto(B + '/mobile', wait_until='networkidle'); pg.click('#loginBtn'); pg.wait_for_selector('#app:not(.hidden)'); pg.wait_for_timeout(2500)
    call = lambda m, path, body=None: pg.evaluate("""async([m,p,b])=>{let r=await fetch(p,{method:m,headers:{'Content-Type':'application/json',Authorization:'Bearer '+token},body:b?JSON.stringify(b):undefined});return [r.status,await r.json().catch(()=>null)]}""", [m, path, body])
    cat = pg.evaluate("api('/mat/catalog')"); mats = [m for m in cat['materials'] if m['available_kg'] >= 20]
    m0 = mats[0]['id']
    avail = lambda: pg.evaluate("m=>api('/mat/catalog').then(c=>c.materials.find(x=>x.id===m).available_kg)", m0)
    a0 = avail()
    # ---------- χύμα: διόρθωση ----------
    st, r = call('POST', '/mat/export', {'material_id': m0, 'form': 'BULK', 'net': 5}); lot_bulk = r['id']
    pg.tap('.secBtn[data-section=materials]'); pg.wait_for_selector('.matStart'); pg.tap('.matStart[data-m="export"]'); pg.wait_for_selector('#matHist .ptItem', timeout=15000); pg.wait_for_timeout(500)
    pg.evaluate("loadMatHist()"); pg.wait_for_timeout(1200)
    pg.locator(f'[data-xid="{lot_bulk}"]').tap(); pg.wait_for_selector('#enSheetBody [data-sh="edit"]')
    ck('πάτημα σε εξαγωγή του ιστορικού: κουμπιά ΔΙΟΡΘΩΣΗ και ΔΙΑΓΡΑΦΗ', 'ΔΙΟΡΘΩΣΗ' in pg.inner_text('#enSheetBody') and 'ΔΙΑΓΡΑΦΗ' in pg.inner_text('#enSheetBody'))
    pg.tap('#enSheetBody [data-sh="edit"]'); pg.wait_for_selector('#mtExpKg')
    ck('χύμα: μόνο «Καθαρά κιλά» (χωρίς μικτό/απόβαρο)', pg.query_selector('#mtExpTare') is None and 'Καθαρά κιλά' in pg.inner_text('#enSheetBody'))
    pg.tap('#enSheetBody [data-sh="back"]'); pg.wait_for_selector('#enSheetBody [data-sh="edit"]')
    pg.tap('#enSheetBody [data-sh="edit"]'); pg.wait_for_selector('#mtExpKg'); pg.fill('#mtExpKg', '7'); pg.tap('#enSheetBody [data-sh="save"]'); pg.wait_for_timeout(2000)
    ck('διόρθωση χύμα 5→7 kg: αποθηκεύτηκε και στο ιστορικό', float(db("select net_weight from ready_material_lots where id=?", lot_bulk)[0][0]) == 7 and '7 kg' in pg.inner_text(f'[data-xid="{lot_bulk}"]'))
    ck('το διαθέσιμο απόθεμα ακολούθησε (−2 kg)', abs((a0 - avail()) - 7) < 0.01, f'{a0}→{avail()}')
    # ---------- παλέτα: διόρθωση + διαγραφή → ελεύθερο μέσο ----------
    st, r = call('POST', '/mat/export', {'material_id': m0, 'form': 'PALLET', 'gross': 40, 'tare': 20}); lot_p = r['id']; mcode = r['medium_code']
    pg.evaluate("loadMatHist()"); pg.wait_for_timeout(1200)
    pg.locator(f'[data-xid="{lot_p}"]').tap(); pg.tap('#enSheetBody [data-sh="edit"]'); pg.wait_for_selector('#mtExpKg')
    t = pg.inner_text('#enSheetBody')
    ck('φύλλο: πίνακας Υλικό / Μέσο / Ώρα εξαγωγής / Τώρα καταχωρημένο', all(h in t for h in ['Υλικό', 'Μέσο', 'Ώρα εξαγωγής', 'Τώρα καταχωρημένο']) and mcode in t, t.replace(chr(10), ' | ')[:200])
    ck('μικτό 40, απόβαρο παλέτας 20, καθαρό 20 υπολογισμένο', pg.input_value('#mtExpKg') == '40' and pg.input_value('#mtExpTare') == '20' and pg.inner_text('#mtExpNet').startswith('20'))
    pg.fill('#mtExpKg', '50'); pg.wait_for_timeout(100)
    ck('καθαρό ενημερώνεται μόνο του (50−20=30)', pg.inner_text('#mtExpNet').startswith('30'))
    pg.fill('#mtExpTare', '25'); pg.wait_for_timeout(100)
    ck('και με αλλαγή αποβάρου (50−25=25)', pg.inner_text('#mtExpNet').startswith('25'))
    pg.tap('#enSheetBody [data-sh="save"]'); pg.wait_for_timeout(2000)
    r_ = db("select net_weight,gross_weight,tare_weight from ready_material_lots where id=?", lot_p)[0]
    ck('διόρθωση παλέτας: μικτά 50, απόβαρο 25 → καθαρά 25 (και το απόβαρο του μέσου)', (float(r_[0]), float(r_[1]), float(r_[2])) == (25, 50, 25) and float(db("select tare_weight from collection_media where code=?", mcode)[0][0]) == 25, str(r_))
    pg.locator(f'[data-xid="{lot_p}"]').tap(); pg.tap('#enSheetBody [data-sh="del"]'); pg.wait_for_selector('#enSheetBody [data-sh="yes"]')
    ck('η επιβεβαίωση λέει ότι το μέσο μένει ελεύθερο', 'ελεύθερο' in pg.inner_text('#enSheetBody') and mcode in pg.inner_text('#enSheetBody'))
    pg.tap('#enSheetBody [data-sh="yes"]'); pg.wait_for_timeout(2000)
    ck('διαγραφή: η εγγραφή ακυρώνεται και φεύγει από το ιστορικό', db("select status from ready_material_lots where id=?", lot_p)[0][0] == 'CANCELLED' and pg.query_selector(f'[data-xid="{lot_p}"]') is None)
    ck('το μέσο (παλέτα) μένει ΕΛΕΥΘΕΡΟ και ενεργό για νέα χρήση', db("select status,active from collection_media where code=?", mcode)[0] == ('AVAILABLE', 1), str(db("select status,active from collection_media where code=?", mcode)))
    # ---------- μπλοκάρισμα όταν είναι δεσμευμένη ----------
    st, r = call('POST', '/mat/export', {'material_id': m0, 'form': 'BULK', 'net': 1}); lot_r = r['id']
    db("insert into loading_reservations(id,loading_order_id,ready_material_lot_id,reserved_weight,status,created_by,created_at) select ?,?,?,1,'RESERVED',(select id from users limit 1),datetime('now')", str(uuid.uuid4()), str(uuid.uuid4()), lot_r, w=True)
    pg.evaluate("loadMatHist()"); pg.wait_for_timeout(1200)
    pg.locator(f'[data-xid="{lot_r}"]').tap(); pg.wait_for_selector('#enSheetBody .shM')
    t = pg.inner_text('#enSheetBody')
    ck('δεσμευμένη εξαγωγή: καθαρό ελληνικό μήνυμα και ΚΑΝΕΝΑ κουμπί αλλαγής', 'δεσμευμένη για φόρτωση' in t and 'ΔΙΑΓΡΑΦΗ' not in t and 'ΔΙΟΡΘΩΣΗ' not in t, t.replace('\n', ' | '))
    pg.tap('#enSheetBody [data-sh="close"]')
    st1, r1 = call('DELETE', '/mat/exports/' + lot_r); st2, r2 = call('PUT', '/mat/exports/' + lot_r, {'net': 3})
    ck('και στον server: διαγραφή/διόρθωση δεσμευμένης → 409', st1 == 409 and st2 == 409, f'{st1}/{st2} {r1}')
    # ---------- φορτωμένη ----------
    st, r = call('POST', '/mat/export', {'material_id': m0, 'form': 'BULK', 'net': 1}); lot_l = r['id']
    db("insert into loading_actuals(id,loading_order_id,ready_material_lot_id,loaded_weight,loaded_by,created_at) select ?,?,?,1,(select id from users limit 1),datetime('now')", str(uuid.uuid4()), str(uuid.uuid4()), lot_l, w=True)
    st1, r1 = call('DELETE', '/mat/exports/' + lot_l)
    ck('φορτωμένη εξαγωγή → 409 «έχει ήδη φορτωθεί»', st1 == 409 and 'φορτωθεί' in str(r1), str(r1))
    # ---------- από απογραφή ----------
    st, inv = call('POST', '/mat/inventory', {'material_id': m0, 'form': 'PALLET', 'gross': 30, 'tare': 20}); inv_id = inv['id']; icode = inv['medium_code']
    st, ex = call('POST', '/mat/export', {'material_id': m0, 'form': 'PALLET', 'inventory_id': inv_id, 'new_total': 25}); lot_i = ex['id']
    ck('(προϋπόθεση) εξαγωγή από απογραφή: η απογραφή γίνεται EXPORTED', db("select status from material_inventory_entries where id=?", inv_id)[0][0] == 'EXPORTED')
    pg.evaluate("loadMatHist()"); pg.wait_for_timeout(1200)
    pg.locator(f'[data-xid="{lot_i}"]').tap(); pg.tap('#enSheetBody [data-sh="edit"]'); pg.wait_for_selector('#mtExpKg')
    ck('εξαγωγή από απογραφή: μικτό = 25+20 = 45, απόβαρο 20', pg.input_value('#mtExpKg') == '45' and pg.input_value('#mtExpTare') == '20', pg.input_value('#mtExpKg'))
    pg.fill('#mtExpKg', '48'); pg.tap('#enSheetBody [data-sh="save"]'); pg.wait_for_timeout(2000)
    ck('διόρθωση: νέο σύνολο 28, μετρημένα = 28 − απογραφή(10)', float(db("select net_weight from ready_material_lots where id=?", lot_i)[0][0]) == 28 and float(db("select counted_kg from ready_material_lots where id=?", lot_i)[0][0]) == 18, str(db("select net_weight,counted_kg from ready_material_lots where id=?", lot_i)))
    pg.locator(f'[data-xid="{lot_i}"]').tap(); pg.tap('#enSheetBody [data-sh="del"]'); pg.wait_for_selector('#enSheetBody [data-sh="yes"]')
    ck('η επιβεβαίωση λέει ότι η απογραφή γίνεται ξανά διαθέσιμη', 'απογραφής θα γίνει ξανά διαθέσιμη' in pg.inner_text('#enSheetBody'))
    pg.tap('#enSheetBody [data-sh="yes"]'); pg.wait_for_timeout(2000)
    ck('διαγραφή: η ζύγιση της απογραφής ξανά COUNTED, χωρίς σύνδεση με την εξαγωγή', db("select status,exported_lot_id from material_inventory_entries where id=?", inv_id)[0] == ('COUNTED', None), str(db("select status,exported_lot_id from material_inventory_entries where id=?", inv_id)))
    ck('το μέσο της απογραφής ξανά «INVENTORY» (δεν χάθηκε)', db("select status from collection_media where code=?", icode)[0][0] == 'INVENTORY')
    # ---------- ουρά (χωρίς σύνδεση) ----------
    st, r = call('POST', '/mat/export', {'material_id': m0, 'form': 'BULK', 'net': 2}); lot_q = r['id']
    pg.evaluate("loadMatHist()"); pg.wait_for_timeout(1200)
    pg.locator(f'[data-xid="{lot_q}"]').tap(); pg.tap('#enSheetBody [data-sh="del"]'); pg.wait_for_selector('#enSheetBody [data-sh="yes"]')
    pg.context.set_offline(True)
    pg.tap('#enSheetBody [data-sh="yes"]'); pg.wait_for_timeout(2500)
    ck('χωρίς σύνδεση: η διαγραφή μπαίνει στην ουρά (δεν χάνεται)', pg.evaluate("OB.pending()") and db("select status from ready_material_lots where id=?", lot_q)[0][0] != 'CANCELLED')
    pg.context.set_offline(False); pg.wait_for_function("!OB.pending()", timeout=60000); pg.wait_for_timeout(500)
    ck('με την επαναφορά: η διαγραφή εφαρμόζεται (μία φορά)', db("select status from ready_material_lots where id=?", lot_q)[0][0] == 'CANCELLED')
    ck('σφάλματα σελίδας', not errs, str(errs[:2]))
    b.close()
print('ΑΠΟΤΥΧΙΕΣ:', bad)
sys.exit(1 if bad else 0)
