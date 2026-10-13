r"""Καθαρισμός ορφανών: όχημα μεταφορέα και πρόσθετα στοιχεία μητρώου οργανισμών που δεν υπάρχουν πια.

  Έλεγχος:  backend\.venv\Scripts\python.exe backend\scripts\clean_orphan_misc.py
  Εφαρμογή: backend\.venv\Scripts\python.exe backend\scripts\clean_orphan_misc.py --apply
Διαγράφεται εγγραφή ΜΟΝΟ αν ούτε το id της ούτε το id του ανύπαρκτου οργανισμού αναφέρονται πουθενά αλλού. Κάνε πρώτα αντίγραφο της βάσης."""
import sys, os, re, sqlite3
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..'))
from sqlalchemy import select
from app.db import SessionLocal, engine
from app.models import CarrierVehicle, OrganizationRegistryDetail, Organization
from app.audit import write_audit
APPLY = '--apply' in sys.argv
with SessionLocal() as db:
    orgs = {o.id for o in db.scalars(select(Organization)).all()}
    items = []
    for v in db.scalars(select(CarrierVehicle)).all():
        if v.carrier_id not in orgs: items.append(('carrier_vehicle', v, v.id, v.carrier_id, f'πινακίδα {v.plate_number}'))
    for d in db.scalars(select(OrganizationRegistryDetail)).all():
        if d.organization_id not in orgs: items.append(('organization_registry_detail', d, d.id, d.organization_id, 'πρόσθετα στοιχεία μητρώου'))
    print('ορφανά:', len(items))
    con = sqlite3.connect(engine.url.database)
    tables = [r[0] for r in con.execute("select name from sqlite_master where type='table' and name not like 'sqlite_%'")]
    ok = []
    for kind, obj, rid, oid, label in items:
        refs = []
        pat = re.compile(re.escape(rid) + '|' + re.escape(oid))
        for t in tables:
            cols = [(r[1], (r[2] or '').upper()) for r in con.execute(f'pragma table_info("{t}")')]
            for col in [c for c, ty in cols if any(k in ty for k in ('CHAR', 'TEXT', 'CLOB')) or ty == '']:
                for (val,) in con.execute(f'select "{col}" from "{t}" where "{col}" is not null'):
                    if isinstance(val, str) and pat.search(val):
                        if (t == 'carrier_vehicles' and col in ('id', 'carrier_id')) or (t == 'organization_registry_details' and col in ('id', 'organization_id')): continue
                        refs.append(f'{t}.{col}')
        print(f'  {kind} {rid[:8]}… ({label}, οργανισμός {oid[:8]}…): αναφορές αλλού: {sorted(set(refs)) or "καμία"}')
        if not refs: ok.append((kind, obj, rid, oid, label))
    print('διαγράφονται:', len(ok), '| μένουν:', len(items) - len(ok))
    if not APPLY: print('(έλεγχος μόνο)'); sys.exit(0)
    for kind, obj, rid, oid, label in ok:
        write_audit(db, None, kind, rid, 'PURGE_ORPHAN', old={'organization_id': oid, 'label': label}, reason='Ορφανή εγγραφή (οργανισμός που δεν υπάρχει πια)')
        db.delete(obj)
    db.commit(); print('Διαγράφηκαν', len(ok))
