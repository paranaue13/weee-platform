"""B10 (14/11/2026): καθαρό βάρος παραλαβής = κιλά παραλαβής, και ξένα υλικά (ΜΗ ΑΗΗΕ) από τα ημερήσια Excel στην ταξινόμηση.
Πηγή: C:\\Users\\paran\\Desktop\\HER app\\Files\\2026\\2026\\<μήνας>\\ηη.μμ.2026.xlsx, ένα φύλλο ανά ΔΠΠ (φόρμα «ΑΝΑΦΟΡΑ ΚΑΤΑΓΡΑΦΗΣ
ΠΑΡΑΛΗΦΘΕΝΤΩΝ Α.Η.Η.Ε.»): D2 εντολή, D4 καθαρό ΑΗΗΕ, D5 ξένα ΝΑΙ/ΟΧΙ, D6 καθαρό ξένων, B9 ΔΠΠ.
Κανόνας: κιλά παραλαβής = ΑΗΗΕ (D4) + ξένα (D6)· όπου υπάρχουν ζυγίσεις στη βάση, = 1η − 2η ζύγιση (Container ± απόβαρα).
Τα ξένα μπαίνουν ως καταχώρηση ταξινόμησης στην 119999 (η φόρμα δεν γράφει κατηγορία), με τμήμα αποθήκης και κίνηση SORTING_IN
με την ημερομηνία της παραλαβής (όπως οι υπάρχουσες ιστορικές)· συμπληρώνεται και το πεδίο ελέγχου «Καθαρό βάρος ξένων υλικών».
Χρήση: python b10_foreign_from_excel.py <βάση> [--apply] [--report αρχείο.csv]   (χωρίς --apply: μόνο αναφορά)"""
import sys, os, re, glob, csv, json, uuid, sqlite3
from datetime import datetime, timezone
import openpyxl

ROOT = r'C:/Users/paran/Desktop/HER app/Files/2026/2026'
ADMIN = 'a448f4d4-b94d-4287-87f2-144e85113901'
args = sys.argv[1:]
DB = args[0]; APPLY = '--apply' in args
REPORT = args[args.index('--report') + 1] if '--report' in args else None


def num(v):
    if v is None or v == '' or v == '-': return 0.0
    if isinstance(v, (int, float)): return float(v)
    s = str(v).strip().replace('.', '').replace(',', '.') if re.search(r'\d,\d', str(v)) else str(v).strip()
    try: return float(s)
    except ValueError: return None


def read_excel():
    out, bad = [], []
    files = [f for f in glob.glob(ROOT + '/*/*.xlsx') if re.fullmatch(r'\d{2}\.\d{2}\.2026\.xlsx', os.path.basename(f))]
    for f in sorted(files):
        d, m, y = os.path.basename(f)[:10].split('.')
        day = f'{y}-{m}-{d}'
        wb = openpyxl.load_workbook(f, data_only=True, read_only=True)
        for sh in wb.sheetnames:
            ws = wb[sh]
            v = {k: ws[k].value for k in ('B2', 'C2', 'D2', 'C4', 'D4', 'C5', 'D5', 'C6', 'D6', 'A9', 'B9', 'C8', 'D8')}
            if not (isinstance(v['C6'], str) and 'Ξένων' in v['C6'] and isinstance(v['C4'], str) and 'A.H.H.E' in v['C4'].replace('Α', 'A').replace('Η', 'H').replace('Ε', 'E')):
                continue
            if v['D4'] in (None, '') and v['B2'] in (None, ''): continue
            rec = {'file': os.path.basename(f), 'sheet': sh, 'day': day, 'supplier': v['B2'], 'order': (str(v['D2']).strip() if v['D2'] not in (None, '', '-') else None),
                   'dpp': v['B9'], 'aee': num(v['D4']), 'foreign_yn': v['D5'], 'foreign': num(v['D6']), 'special': num(v['D8'])}
            if rec['aee'] is None or rec['foreign'] is None: bad.append((rec['file'], sh, 'μη αριθμητική τιμή', v['D4'], v['D6'])); continue
            if isinstance(rec['order'], str) and rec['order'].endswith('.0'): rec['order'] = rec['order'][:-2]
            out.append(rec)
        wb.close()
    return out, bad


def main():
    xs, bad = read_excel()
    c = sqlite3.connect(DB); c.row_factory = sqlite3.Row
    loads = c.execute("""select l.*, t.receipt_type, t.receipt_date, t.receipt_number, o.legal_name sup,
        s.id sid, s.foreign_weight, s.foreign_materials, s.status sst,
        (select coalesce(sum(coalesce(e.approved_weight,e.raw_weight)),0) from sorting_entries e where e.session_id=s.id) sorted_kg,
        (select count(*) from sorting_entries e join weee_categories w on w.id=e.weee_category_id where e.session_id=s.id and w.code='119999') has_x
        from inbound_loads l join inbound_trips t on t.id=l.trip_id left join organizations o on o.id=l.supplier_id
        left join sorting_sessions s on s.inbound_load_id=l.id where t.deleted_at is null""").fetchall()
    by_order = {}
    for l in loads: by_order.setdefault((l['receipt_date'][:10], str(l['order_number'] or '')), []).append(l)
    by_dpp = {}
    for l in loads:
        if l['dpp_number'] is not None: by_dpp.setdefault((l['receipt_date'][:10], int(l['dpp_number'])), []).append(l)
    cat = c.execute("select id from weee_categories where code='119999'").fetchone()['id']
    loc = c.execute("select id from inventory_locations where code='WEEE_MAIN'").fetchone()['id']
    rows, used = [], set()

    def rk(l):
        if l['gross_weight'] is None or l['tare_weight'] is None: return None
        if l['receipt_type'] == 'CONTAINER':
            if l['incoming_container_tare'] is None or l['outgoing_container_tare'] is None: return None
            return float(l['gross_weight'] - l['tare_weight'] - l['incoming_container_tare'] + l['outgoing_container_tare'])
        return float(l['gross_weight'] - l['tare_weight'])

    for x in xs:
        cand = by_order.get((x['day'], x['order'] or ''), []) if x['order'] else []
        how = 'εντολή'
        if len(cand) != 1:
            try: cand = by_dpp.get((x['day'], int(x['dpp'])), [])
            except (TypeError, ValueError): cand = []
            how = 'ΔΠΠ'
        r = dict(x, how=how, status='', load_id=None, db_net=None, new_net=None, sorted_kg=None, add_x=0)
        if len(cand) != 1:
            r['status'] = 'ΔΕΝ ΒΡΕΘΗΚΕ' if not cand else 'ΠΟΛΛΑΠΛΑ'; rows.append(r); continue
        l = cand[0]
        if l['id'] in used: r['status'] = 'ΔΙΠΛΟ ΦΥΛΛΟ'; rows.append(r); continue
        used.add(l['id'])
        w = rk(l); target = x['aee'] + x['foreign']
        r.update(load_id=l['id'], db_order=l['order_number'], db_net=float(l['net_weight'] or 0), sorted_kg=float(l['sorted_kg'] or 0), weigh=w)
        notes = []
        if w is not None and abs(w - target) > 0.01: notes.append(f'ζυγίσεις {w:g} ≠ Excel ΑΗΗΕ+ξένα {target:g}')
        r['new_net'] = w if w is not None else target
        r['add_x'] = x['foreign'] if (x['foreign'] > 0 and not l['has_x']) else 0
        if l['has_x']: notes.append('έχει ήδη 119999')
        if l['sid'] is None and r['add_x']: notes.append('χωρίς ταξινόμηση: τα ξένα ΔΕΝ προστίθενται'); r['add_x'] = 0
        final_sorted = r['sorted_kg'] + r['add_x']
        if abs(r['sorted_kg'] - x['aee']) > 0.01: notes.append(f'ταξινόμηση ΑΗΗΕ {r["sorted_kg"]:g} ≠ Excel ΑΗΗΕ {x["aee"]:g}')
        r['final_sorted'] = final_sorted
        r['match'] = abs(final_sorted - r['new_net']) <= 0.01
        r['status'] = 'ΟΚ' if not notes else '; '.join(notes)
        r['_l'] = l
        rows.append(r)

    import collections
    cnt = collections.Counter()
    for r in rows:
        k = r['status'] if r['status'] in ('ΟΚ', 'ΔΕΝ ΒΡΕΘΗΚΕ', 'ΠΟΛΛΑΠΛΑ', 'ΔΙΠΛΟ ΦΥΛΛΟ') else 'με σημείωση'
        cnt[k] += 1
    ch_net = [r for r in rows if r.get('new_net') is not None and abs(r['new_net'] - r['db_net']) > 0.01]
    add = [r for r in rows if r.get('add_x')]
    print(f'Excel φύλλα: {len(xs)} · μη αναγνώσιμα: {len(bad)} · φορτία βάσης: {len(loads)} · αντιστοιχισμένα: {len(used)}')
    print('Κατάσταση:', dict(cnt))
    print(f'Αλλαγή καθαρού βάρους: {len(ch_net)} φορτία ({sum(r["new_net"] - r["db_net"] for r in ch_net):+.0f} kg)')
    print(f'Νέες καταχωρήσεις 119999: {len(add)} ({sum(r["add_x"] for r in add):.0f} kg)')
    nomatch = [r for r in rows if r.get('match') is False]
    print(f'Μετά τη διόρθωση, ταξινόμηση ≠ παραλαβή: {len(nomatch)}')
    unm = [l for l in loads if l['id'] not in used]
    print(f'Φορτία βάσης χωρίς φύλλο Excel: {len(unm)}', collections.Counter(l['receipt_date'][:7] for l in unm).most_common(12))
    if REPORT:
        with open(REPORT, 'w', newline='', encoding='utf-8-sig') as fh:
            wr = csv.writer(fh, delimiter=';')
            wr.writerow(['Ημέρα', 'Αρχείο', 'Φύλλο', 'Εντολή Excel', 'Εντολή βάσης', 'ΔΠΠ', 'Προμηθευτής', 'ΑΗΗΕ Excel', 'Ξένα Excel', 'Καθαρό πριν', 'Καθαρό μετά', 'Ταξινόμηση πριν', '+119999', 'Ταξινόμηση μετά', 'Ίσο με παραλαβή', 'Κατάσταση'])
            for r in rows:
                wr.writerow([r['day'], r['file'], r['sheet'], r['order'], r.get('db_order'), r['dpp'], r['supplier'], r['aee'], r['foreign'], r.get('db_net'), r.get('new_net'), r.get('sorted_kg'), r.get('add_x'), r.get('final_sorted'), {True: 'ΝΑΙ', False: 'ΟΧΙ'}.get(r.get('match'), ''), r['status']])
            for l in unm:
                wr.writerow([l['receipt_date'][:10], '', '', '', l['order_number'], l['dpp_number'], l['sup'], '', '', l['net_weight'], '', l['sorted_kg'], '', '', '', 'ΧΩΡΙΣ ΦΥΛΛΟ EXCEL'])
            for b in bad: wr.writerow(['', b[0], b[1], '', '', '', '', b[3], b[4], '', '', '', '', '', '', 'ΜΗ ΑΝΑΓΝΩΣΙΜΟ'])
        print('αναφορά:', REPORT)
    if not APPLY:
        return
    now = datetime.now(timezone.utc).isoformat(sep=' ')
    log = []
    with c:
        for r in rows:
            if not r.get('load_id'): continue
            l = r['_l']; ch = {}
            if abs(r['new_net'] - r['db_net']) > 0.01:
                c.execute("update inbound_loads set net_weight=? where id=?", (r['new_net'], l['id'])); ch['net'] = [r['db_net'], r['new_net']]
            if l['sid'] and r['foreign'] > 0 and abs(float(l['foreign_weight'] or 0) - r['foreign']) > 0.01:
                c.execute("update sorting_sessions set foreign_weight=?, foreign_materials='ΝΑΙ' where id=?", (r['foreign'], l['sid'])); ch['foreign_weight'] = [float(l['foreign_weight'] or 0), r['foreign']]
            if r['add_x']:
                ts = l['receipt_date']; eid, lid = str(uuid.uuid4()), str(uuid.uuid4())
                c.execute("insert into sorting_entries(id,session_id,weee_category_id,collection_medium_id,entry_type,raw_weight,approved_weight,piece_count,created_by,notes,created_at,updated_at,source) values(?,?,?,?,?,?,?,?,?,?,?,?,?)",
                          (eid, l['sid'], cat, None, 'HISTORICAL', r['add_x'], r['add_x'], None, ADMIN, 'Ξένα υλικά (Μη ΑΗΗΕ) από το Excel ' + r['file'], ts, ts, None))
                c.execute("insert into weee_stock_lots(id,source_sorting_entry_id,inbound_load_id,weee_category_id,collection_medium_id,location_id,original_weight,available_weight,piece_count,status,created_at,updated_at) values(?,?,?,?,?,?,?,?,?,?,?,?)",
                          (lid, eid, l['id'], cat, None, loc, r['add_x'], r['add_x'], None, 'AVAILABLE', ts, ts))
                c.execute("insert into stock_movements(id,domain,lot_id,movement_type,from_location_id,to_location_id,weight,org_unit_id,user_id,reason,created_at,transfer_id) values(?,?,?,?,?,?,?,?,?,?,?,?)",
                          (str(uuid.uuid4()), 'WEEE', lid, 'SORTING_IN', None, loc, r['add_x'], None, ADMIN, 'Ξένα υλικά από Excel', ts, None))
                ch['119999'] = r['add_x']
            if ch: log.append({'load': l['id'], 'order': l['order_number'], 'day': r['day'], **ch})
        c.execute("insert into audit_events(id,user_id,entity_type,entity_id,action,old_values,new_values,reason,created_at) values(?,?,?,?,?,?,?,?,?)",
                  (str(uuid.uuid4()), ADMIN, 'inbound_load', None, 'FIX_NET_AND_FOREIGN_FROM_EXCEL', None, json.dumps(log, ensure_ascii=False),
                   'Καθαρό βάρος = κιλά παραλαβής (ΑΗΗΕ + ξένα)· ξένα υλικά από τα ημερήσια Excel στην 119999', now))
    print('ΕΓΙΝΕ:', len(log), 'φορτία άλλαξαν · integrity:', c.execute('pragma integrity_check').fetchone()[0])


main()
