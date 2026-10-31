"""Εφάπαξ μεταφορά πινακίδων στους μεταφορείς (carrier_vehicles) από τις παραλαβές.
Χρήση:  python migrate_vehicles.py <βάση.db> [--apply]      (χωρίς --apply: μόνο αναφορά, δεν γράφει τίποτα)
- Ελληνικά/λατινικά που μοιάζουν = η ίδια πινακίδα· κρατιέται η λατινική μορφή (π.χ. IAZ 9740).
- Πινακίδα που εμφανίζεται σε ΠΑΝΩ από έναν μεταφορέα ΔΕΝ μεταφέρεται (αναφέρεται).
- Οι 2 δοκιμαστικές εγγραφές του πίνακα (ZZZ 1234, ΕΚΒ 7660) σβήνονται.
- Το κείμενο της πινακίδας στις παραλαβές ΔΕΝ αλλάζει ποτέ."""
import sqlite3, sys, uuid, datetime
sys.stdout.reconfigure(encoding='utf-8')
M = str.maketrans('ΑΒΕΖΗΙΚΜΝΟΡΤΥΧ', 'ABEZHIKMNOPTYX')
norm = lambda p: ' '.join(str(p or '').strip().upper().translate(M).split())
key = lambda p: ''.join(ch for ch in norm(p) if ch.isalnum())
db, apply = sys.argv[1], '--apply' in sys.argv
c = sqlite3.connect(db)
names = {r[0]: (r[1] or r[2]) for r in c.execute("select id,trade_name,legal_name from organizations")}
pairs = {}
for pl, car in c.execute("select vehicle_registration,carrier_id from inbound_trips where vehicle_registration is not null and trim(vehicle_registration)!='' and carrier_id is not null"):
    pairs.setdefault(key(pl), {}).setdefault(car, norm(pl))
no_carrier = [r[0] for r in c.execute("select distinct vehicle_registration from inbound_trips where vehicle_registration is not null and trim(vehicle_registration)!='' and carrier_id is null")]
test = [r for r in c.execute("select id,plate_number from carrier_vehicles where upper(replace(plate_number,' ','')) in ('ZZZ1234','ΕΚΒ7660')")]
add, conflicts = [], []
for k, cars in pairs.items():
    if len(cars) > 1: conflicts.append((k, [names.get(x, x) for x in cars])); continue
    (car, plate), = cars.items(); add.append((car, plate))
exist = {(r[0], key(r[1])) for r in c.execute("select carrier_id,plate_number from carrier_vehicles") if r[1] not in [t[1] for t in test]}
new = [(car, pl) for car, pl in add if (car, key(pl)) not in exist]
print('μεταφέρονται:', len(new), '| υπάρχουν ήδη:', len(add) - len(new), '| δοκιμαστικές προς διαγραφή:', [t[1] for t in test])
print('ΔΕΝ μεταφέρονται (πάνω από έναν μεταφορέας):', conflicts)
print('ΔΕΝ μεταφέρονται (παραλαβές χωρίς μεταφορέα):', no_carrier)
if apply:
    now = datetime.datetime.utcnow().isoformat(sep=' ')
    for tid, _ in test: c.execute('delete from carrier_vehicles where id=?', (tid,))
    for car, pl in new: c.execute("insert into carrier_vehicles(id,carrier_id,plate_number,active,created_at,updated_at) values(?,?,?,?,?,?)", (str(uuid.uuid4()), car, pl, 1, now, now))
    c.commit()
    print('ΕΦΑΡΜΟΣΤΗΚΕ. Πλήθος οχημάτων τώρα:', c.execute('select count(*) from carrier_vehicles').fetchone()[0])
