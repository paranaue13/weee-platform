"""B9 (14/11/2026): συγχώνευση της εντολής 812143 (ΔΠΠ 1220, Μικρά Σημεία 22/09/2026, χωρίς ταξινόμηση)
με την XL-20260922-01 (ΔΗΜΟΣ ΤΥΡΝΑΒΟΥ, ταξινομημένη 245 kg).
Μένει ΜΙΑ εντολή 812143 με όλα τα στοιχεία παραλαβής της 812143 (παραλαβή, ΔΠΠ, ζυγίσεις, μεταφορέας),
προμηθευτή ΔΗΜΟΣ ΤΥΡΝΑΒΟΥ και την ταξινόμηση (και τα 12 τμήματα αποθήκης) της XL. Η κενή XL διαγράφεται.
Μία συναλλαγή (όλα ή τίποτα) + εγγραφή στο audit_events με τα παλιά στοιχεία.
Χρήση: python b9_merge_812143_xl.py <διαδρομή βάσης> [--apply]   (χωρίς --apply: μόνο έλεγχος)"""
import sqlite3, sys, json, uuid
from datetime import datetime, timezone

A = '745467eb-7ce2-4a83-8dce-54de6a3ddad5'   # 812143
X = '2fd99560-9a7f-4ec8-be32-f19fa7e4e3ab'   # XL-20260922-01 (φορτίο)
XT = 'c88ade83-9f0f-4d9e-83f3-a625632add0c'  # XL-20260922-01 (παραλαβή)
ADMIN = 'a448f4d4-b94d-4287-87f2-144e85113901'

db, apply = sys.argv[1], '--apply' in sys.argv
c = sqlite3.connect(db); c.row_factory = sqlite3.Row
row = lambda q, *a: c.execute(q, a).fetchone()
a = row("select * from inbound_loads where id=?", A); x = row("select * from inbound_loads where id=?", X); xt = row("select * from inbound_trips where id=?", XT)
assert a and x and xt, 'δεν βρέθηκαν οι εγγραφές (ίσως έχει ήδη γίνει)'
assert a['order_number'] == '812143' and a['dpp_number'] == 1220 and xt['receipt_number'] == 'XL-20260922-01'
assert not row("select 1 from sorting_sessions where inbound_load_id=?", A), 'η 812143 έχει ήδη ταξινόμηση'
assert not row("select 1 from weee_stock_lots where inbound_load_id=?", A)
assert row("select count(*) n from inbound_loads where trip_id=?", XT)['n'] == 1
ses = row("select * from sorting_sessions where inbound_load_id=?", X)
nlots = row("select count(*) n, sum(original_weight) w from weee_stock_lots where inbound_load_id=?", X)
print('812143:', a['net_weight'], 'kg · XL ταξινόμηση', row("select sum(coalesce(approved_weight,raw_weight)) w from sorting_entries where session_id=?", ses['id'])['w'], 'kg ·', nlots['n'], 'τμήματα αποθήκης', nlots['w'], 'kg')
if not apply:
    print('έλεγχος ΟΚ (χωρίς αλλαγές)'); sys.exit(0)
now = datetime.now(timezone.utc).isoformat(sep=' ')
old = {'812143': dict(a), 'XL_load': dict(x), 'XL_trip': dict(xt), 'session_id': ses['id']}
with c:
    c.execute("update inbound_loads set supplier_id=?, status='CLOSED', updated_at=? where id=?", (x['supplier_id'], now, A))
    c.execute("update sorting_sessions set inbound_load_id=?, updated_at=? where id=?", (A, now, ses['id']))
    c.execute("update weee_stock_lots set inbound_load_id=?, updated_at=? where inbound_load_id=?", (A, now, X))
    c.execute("delete from inbound_loads where id=?", (X,))
    c.execute("delete from inbound_trips where id=?", (XT,))
    c.execute("insert into audit_events(id,user_id,entity_type,entity_id,action,old_values,new_values,reason,created_at) values(?,?,?,?,?,?,?,?,?)",
              (str(uuid.uuid4()), ADMIN, 'inbound_load', A, 'MERGE_LOAD', json.dumps(old, ensure_ascii=False, default=str),
               json.dumps({'order_number': '812143', 'supplier': 'ΔΗΜΟΣ ΤΥΡΝΑΒΟΥ', 'sorting_session': ses['id'], 'deleted_receipt': 'XL-20260922-01'}, ensure_ascii=False),
               'Η XL-20260922-01 (ΔΗΜΟΣ ΤΥΡΝΑΒΟΥ) πήρε τα στοιχεία παραλαβής και τον αριθμό εντολής της 812143· η κενή διαγράφηκε', now))
print('ΕΓΙΝΕ:', row("select order_number, net_weight, status from inbound_loads where id=?", A)[:], '· XL υπάρχει:', bool(row("select 1 from inbound_trips where id=?", XT)))
print('integrity:', c.execute('pragma integrity_check').fetchone()[0])
