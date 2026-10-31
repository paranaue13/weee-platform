"""Εφάπαξ: (α) σβήνει τις πινακίδες TEST-1234 και TEST-123, (β) βάζει τις 3 πινακίδες που ανήκουν σε δύο μεταφορείς και στους δύο.
Χρήση: python vehicles_fix2.py <βάση.db> [--apply]  (χωρίς --apply μόνο αναφορά)"""
import sqlite3, sys, uuid, datetime
sys.stdout.reconfigure(encoding='utf-8')
db, apply = sys.argv[1], '--apply' in sys.argv
c = sqlite3.connect(db)
import unicodedata
def _n(x): return ' '.join(''.join(ch for ch in unicodedata.normalize('NFD', (x or '').upper()) if not unicodedata.combining(ch)).split())
_M = str.maketrans('ΑΒΕΖΗΙΚΜΝΟΡΤΥΧ', 'ABEZHIKMNOPTYX')
def _key(p): return ''.join(ch for ch in (p or '').upper().translate(_M) if ch.isalnum())
def carrier(part, plate):
    """Ο μεταφορέας που έχει ΠΑΡΑΛΑΒΕΣ με αυτή την πινακίδα και ταιριάζει στο όνομα."""
    ids = {r[0] for r in c.execute("select carrier_id,vehicle_registration from inbound_trips where carrier_id is not null and vehicle_registration is not null") if _key(r[1]) == _key(plate)}
    r = []
    for cid in ids:
        nm = c.execute("select coalesce(trade_name,'')||' '||coalesce(legal_name,'') from organizations where id=?", (cid,)).fetchone()[0]
        if _n(part) in _n(nm): r.append(cid)
    assert len(r) == 1, (part, plate, r)
    return r[0]
PAIRS = [('PPI 9342', 'ECO TRANS'), ('PPI 9342', 'ΣΑΪΤΗΣ ΑΝΑΚΥΚΛΩΣΗ'), ('EKE 1742', 'ΣΟΥΛΤΑΝΟΓΛΟΥ'), ('EKE 1742', 'ΟΙΚΟΝΟΜΟΠΟΥΛΟΣ'), ('EKB 7660', 'ΣΟΥΛΤΑΝΟΓΛΟΥ'), ('EKB 7660', 'ΟΙΚΟΝΟΜΟΠΟΥΛΟΣ')]
test = c.execute("select id,plate_number from carrier_vehicles where upper(plate_number) in ('TEST-1234','TEST-123')").fetchall()
print('προς διαγραφή:', [t[1] for t in test])
todo = []
for plate, part in PAIRS:
    try: cid = carrier(part, plate)
    except AssertionError: print(plate, '→', part, 'ΔΕΝ βρέθηκε μεταφορέας με παραλαβές αυτής της πινακίδας· παραλείπεται'); continue
    have = c.execute("select 1 from carrier_vehicles where carrier_id=? and plate_number=?", (cid, plate)).fetchone()
    print(plate, '→', part, 'υπάρχει ήδη' if have else 'προστίθεται')
    if not have: todo.append((cid, plate))
if apply:
    now = datetime.datetime.now(datetime.timezone.utc).replace(tzinfo=None).isoformat(sep=' ')
    for tid, _ in test: c.execute('delete from carrier_vehicles where id=?', (tid,))
    for cid, plate in todo: c.execute("insert into carrier_vehicles(id,carrier_id,plate_number,active,created_at,updated_at) values(?,?,?,?,?,?)", (str(uuid.uuid4()), cid, plate, 1, now, now))
    c.commit(); print('ΕΦΑΡΜΟΣΤΗΚΕ. Οχήματα τώρα:', c.execute('select count(*) from carrier_vehicles').fetchone()[0])
