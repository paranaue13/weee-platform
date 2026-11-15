"""B11 (15/11/2026): οι παραλαβές της 14/10/2026 (XL-20261014-01..09) παίρνουν τα στοιχεία της εντολής από το ημερήσιο Excel
(10.ΟΚΤΩΒΡΙΟΣ\\14.10.2026.xlsx, ένα φύλλο ανά ΔΠΠ): D2 αριθμός εντολής, B9 ΔΠΠ, D3 αρ. δελτίου (αν όχι «-»), D9 όχημα.
Αντιστοίχιση: ίδια ημέρα + ίδια κιλά (D4+D6 = καθαρό) + ίδιο πρώτο όνομα προμηθευτή. Ο αριθμός παραλαβής γίνεται ο αριθμός
εντολής, όπως σε όλες τις άλλες παραλαβές. Τίποτε άλλο δεν αλλάζει (κιλά, ταξινομήσεις, αποθήκη).
Χρήση: python b11_orders_14_10_from_excel.py <βάση> [--apply]"""
import sys, glob, sqlite3
from datetime import datetime, timezone
import openpyxl

sys.stdout.reconfigure(encoding='utf-8')
DB = sys.argv[1]; APPLY = '--apply' in sys.argv
F = glob.glob(r'C:/Users/paran/Desktop/HER app/Files/2026/2026/*/14.10.2026.xlsx')[0]


def first(s): return (s or '').replace('Β.', '').replace('.', ' ').split()[0].upper()


wb = openpyxl.load_workbook(F, data_only=True, read_only=True)
xs = []
for sh in wb.sheetnames:
    ws = wb[sh]
    if not isinstance(ws['D2'].value, (int, float)) or not ws['B9'].value: continue
    d3 = ws['D3'].value
    xs.append({'order': str(int(ws['D2'].value)), 'dpp': int(ws['B9'].value), 'kg': float(ws['D4'].value or 0) + float(ws['D6'].value or 0),
               'sup': ws['B2'].value, 'dn': (str(int(d3)) if isinstance(d3, (int, float)) else None), 'veh': ws['D9'].value})
wb.close()
c = sqlite3.connect(DB); c.row_factory = sqlite3.Row
loads = c.execute("""select l.id, l.trip_id, l.net_weight, t.receipt_number, o.legal_name sup from inbound_loads l join inbound_trips t on t.id=l.trip_id
  left join organizations o on o.id=l.supplier_id where t.deleted_at is null and t.receipt_number like 'XL-20261014-%' and l.order_number is null""").fetchall()
pairs, used = [], set()
for x in xs:
    m = [l for l in loads if l['id'] not in used and abs((l['net_weight'] or 0) - x['kg']) < 0.5 and first(l['sup']) == first(x['sup'])]
    if len(m) != 1: print('ΧΩΡΙΣ ΜΟΝΑΔΙΚΗ ΑΝΤΙΣΤΟΙΧΙΣΗ', x, len(m)); continue
    used.add(m[0]['id']); pairs.append((m[0], x))
    if c.execute("select 1 from inbound_trips where receipt_number=?", (x['order'],)).fetchone() or c.execute("select 1 from inbound_loads where order_number=?", (x['order'],)).fetchone():
        sys.exit('υπάρχει ήδη ' + x['order'])
for l, x in pairs: print(l['receipt_number'], '→', x['order'], 'ΔΠΠ', x['dpp'], x['dn'], x['veh'], l['sup'], l['net_weight'])
print(len(pairs), 'από', len(xs), 'φύλλα,', len(loads), 'παραλαβές XL')
if APPLY:
    if len(pairs) != len(loads): sys.exit('δεν αντιστοιχίστηκαν όλες· τίποτα δεν άλλαξε')
    now = datetime.now(timezone.utc).isoformat()
    with c:
        for l, x in pairs:
            c.execute("update inbound_loads set order_number=?, dpp_number=?, dispatch_note_number=coalesce(dispatch_note_number,?), updated_at=? where id=?",
                      (x['order'], x['dpp'], x['dn'], now, l['id']))
            c.execute("update inbound_trips set receipt_number=?, vehicle_registration=coalesce(vehicle_registration,?), updated_at=? where id=?",
                      (x['order'], x['veh'], now, l['trip_id']))
    print('εφαρμόστηκε')
