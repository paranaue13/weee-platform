"""Δοκιμή Windows › Αρχική › κάρτα «Ταξινόμηση σε εξέλιξη»: ο αριθμός και η εντολή που ανοίγει βασίζονται στον ίδιο ορισμό «ανοιχτή».
Χρήση: python backend/scripts/test_dashboard_open_sorting.py http://127.0.0.1:PORT <αρχείο-βάσης-ΑΝΤΙΓΡΑΦΟ.db>
ΠΡΟΣΟΧΗ: τροποποιεί τη βάση που δίνεται (μόνο αντίγραφο!). Ο server πρέπει να τρέχει πάνω στο ίδιο αντίγραφο."""
import sys, os, sqlite3, uuid
sys.path.insert(0, os.path.dirname(__file__))
sys.stdout.reconfigure(encoding='utf-8')
from playwright.sync_api import sync_playwright
from _browser import launch
B = sys.argv[1]; DB = sys.argv[2]
if 'LOCALAPPDATA' in DB.upper() and 'weee_dev.db' in DB: sys.exit('ΑΡΝΗΣΗ: δώσε αντίγραφο, όχι την πραγματική βάση')
bad = []
def ck(name, ok, info=''):
    print(('✓ ' if ok else '✗ ') + name, info)
    if not ok: bad.append(name)
db = sqlite3.connect(DB)
# τρεις εντολές από τα υπάρχοντα δεδομένα: A (παλιά), B (νεότερη), και μια ΟΛΟΚΛΗΡΩΜΕΝΗ ακόμα παλιότερη
rows = db.execute("""select s.id,l.order_number,t.id from sorting_sessions s join inbound_loads l on l.id=s.inbound_load_id join inbound_trips t on t.id=l.trip_id
  where t.deleted_at is null and s.status='IN_PROGRESS' order by t.receipt_date,l.order_number""").fetchall()
assert len(rows) >= 2, 'χρειάζονται ≥2 συνεδρίες IN_PROGRESS στο αντίγραφο'
done = db.execute("""select s.id,l.order_number,t.id from sorting_sessions s join inbound_loads l on l.id=s.inbound_load_id join inbound_trips t on t.id=l.trip_id
  where t.deleted_at is null and s.status='CLOSED' order by t.receipt_date limit 1""").fetchone()
A = rows[0]
Bn = next(r for r in rows if r[2] != A[2])      # άλλη παραλαβή (άλλη ημέρα)
OTHERS = [r for r in rows if r not in (A, Bn)]
ENTRY = db.execute("select weee_category_id,entry_type,raw_weight from sorting_entries limit 1").fetchone()
def set_date(trip, d): db.execute("update inbound_trips set receipt_date=? where id=?", (d + ' 08:50:00.000000', trip))
def entries(ses, n):
    db.execute("delete from sorting_entries where session_id=?", (ses,))
    for _ in range(n):
        db.execute("insert into sorting_entries(id,session_id,weee_category_id,entry_type,raw_weight,created_at,updated_at) values(?,?,?,?,?,datetime('now'),datetime('now'))", (str(uuid.uuid4()), ses, ENTRY[0], ENTRY[1], ENTRY[2]))
def status(ses, st): db.execute("update sorting_sessions set status=? where id=?", (st, ses))
# η ολοκληρωμένη να είναι η πιο παλιά ημερομηνία
set_date(done[2], '2026-01-05')

def scenario(name, setup, expect_count, expect_order):
    setup(); db.commit()
    with sync_playwright() as p:
        b = launch(p); errs = []
        pg = b.new_page(viewport={'width': 1600, 'height': 900}); pg.on('pageerror', lambda e: errs.append(str(e)))
        pg.goto(B + '/', wait_until='networkidle'); pg.wait_for_selector('#loginBtn', state='visible'); pg.click('#loginBtn'); pg.wait_for_selector('#metrics .card', timeout=20000); pg.wait_for_timeout(1500)
        cards = pg.evaluate("[...document.querySelectorAll('#metrics .metric')].map(c=>c.innerText.replace(/\\s+/g,' ').trim())")
        cnt = [c for c in cards if 'εξέλιξη' in c]
        print(name, '→ κάρτες:', cards)
        ck(name + ': ο αριθμός της κάρτας', cnt and cnt[0].endswith(' ' + str(expect_count)), str(cnt))
        pg.evaluate("[...document.querySelectorAll('#metrics .metric')].find(c=>/εξέλιξη/.test(c.innerText)).click()"); pg.wait_for_timeout(7000)
        txt = pg.evaluate("[...document.querySelectorAll('#sortingDetail,#receiptPopup,.receiptPopup,.sortingPopup,#receiptBody')].map(e=>e.innerText).join(' ')")
        import re
        opened = list(dict.fromkeys(re.findall(r'Εντολή\s+(\d+)', txt)))
        print('   κείμενο:', txt[:160].replace(chr(10),' '))
        print('   άνοιξε:', opened, '| popup chars:', len(txt))
        if expect_order is None:
            ck(name + ': δεν ανοίγει καμία εντολή', not opened)
        else:
            ck(name + f': ανοίγει η εντολή {expect_order}', opened[:1] == [expect_order], str(opened))
        ck(name + ': σφάλματα σελίδας', not errs, str(errs))
        b.close()

# (1) δύο ανοιχτές σε διαφορετικές ημέρες → η παλαιότερη (A)
def s1():
    for o in OTHERS: status(o[0], 'CLOSED')
    set_date(A[2], '2026-02-10'); set_date(Bn[2], '2026-03-15'); status(A[0], 'IN_PROGRESS'); status(Bn[0], 'IN_PROGRESS'); entries(A[0], 1); entries(Bn[0], 2)
    status(done[0], 'CLOSED')
scenario('Σενάριο 1 (δύο ανοιχτές)', s1, 2, A[1])
# (2) ολοκληρωμένη πιο παλιά (done, 05/01) + μία μόνο ανοιχτή (B): ανοίγει η B
def s2():
    status(A[0], 'CLOSED')
scenario('Σενάριο 2 (ολοκληρωμένη παλιά + ανοιχτή νεότερη)', s2, 1, Bn[1])
# (3) καμία ανοιχτή
def s3():
    status(Bn[0], 'CLOSED')
scenario('Σενάριο 3 (καμία ανοιχτή)', s3, 0, None)
print('ΑΠΟΤΥΧΙΕΣ:', bad)
sys.exit(1 if bad else 0)
