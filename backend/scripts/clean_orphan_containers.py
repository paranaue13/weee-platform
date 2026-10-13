r"""Καθαρισμός ορφανών containers (ιδιοκτήτης που δεν υπάρχει πια στους οργανισμούς).

  Έλεγχος:  backend\.venv\Scripts\python.exe backend\scripts\clean_orphan_containers.py
  Εφαρμογή: backend\.venv\Scripts\python.exe backend\scripts\clean_orphan_containers.py --apply

Διαγράφεται ένα ορφανό ΜΟΝΟ αν: (1) υπάρχει container με τον ίδιο κωδικό ΚΑΙ ίδιο απόβαρο σε υπαρκτό μεταφορέα και (2) δεν αναφέρεται πουθενά
στη βάση (ούτε σε παραλαβές, ούτε στο ιστορικό, ούτε σε άλλον πίνακα). Τα υπόλοιπα μένουν και εκτυπώνονται. Κάνε πρώτα αντίγραφο της βάσης."""
import sys, os, re, sqlite3
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..'))
from sqlalchemy import select
from app.db import SessionLocal, engine
from app.models import ContainerAsset, Organization
from app.audit import write_audit

APPLY = '--apply' in sys.argv
def display(x):
    n = x.notes or ''
    return n.split('REGISTRY_CODE=', 1)[1].split('\n', 1)[0].strip() if 'REGISTRY_CODE=' in n else x.container_number

with SessionLocal() as db:
    orgs = {o.id: o for o in db.scalars(select(Organization)).all()}
    allc = db.scalars(select(ContainerAsset)).all()
    orphans = [c for c in allc if c.owner_organization_id and c.owner_organization_id not in orgs]
    real = {}
    for c in allc:
        if c.owner_organization_id in orgs:
            real.setdefault((display(c), float(c.tare_weight or 0)), []).append(orgs[c.owner_organization_id].legal_name)
    print(f'Σύνολο containers: {len(allc)} | ορφανά: {len(orphans)}')
    # αναφορές οπουδήποτε: ακριβής τιμή σε οποιαδήποτε στήλη κειμένου + εμφάνιση μέσα σε κείμενο/JSON
    ids = {c.id for c in orphans}
    refs = {i: [] for i in ids}
    con = sqlite3.connect(engine.url.database)
    tables = [r[0] for r in con.execute("select name from sqlite_master where type='table' and name not like 'sqlite_%'")]
    pat = re.compile('|'.join(re.escape(i) for i in ids)) if ids else None
    for t in tables:
        cols = [(r[1], (r[2] or '').upper()) for r in con.execute(f'pragma table_info("{t}")')]
        textcols = [c for c, ty in cols if any(k in ty for k in ('CHAR', 'TEXT', 'CLOB')) or ty == '']
        if not textcols or not pat: continue
        pk = [r[1] for r in con.execute(f'pragma table_info("{t}")') if r[5]]
        for col in textcols:
            for (rowid, val) in con.execute(f'select rowid, "{col}" from "{t}" where "{col}" is not null'):
                if isinstance(val, str):
                    for m in pat.findall(val):
                        if t == 'containers' and col == 'id': continue
                        refs[m].append(f'{t}.{col}')
    ok, bad = [], []
    for c in orphans:
        match = [n for n in real.get((display(c), float(c.tare_weight or 0)), []) if n in ('KYKΛΟΣ Α.Β.Ε.Ε.', 'ΚΥΚΛΟΣ Α.Β.Ε.Ε.', 'STAR ECO Ε.Ε.')]   # ΚΥΚΛΟΣ ή STAR ECO
        r = refs[c.id]
        if match and not r: ok.append(c)
        else: bad.append((c, 'ΔΕΝ υπάρχει ίδιος κωδικός+απόβαρο σε υπαρκτό μεταφορέα' if not match else '', r))
    print(f'Περνούν τους ελέγχους: {len(ok)} | δεν περνούν: {len(bad)}')
    for c, why, r in bad: print('  ΜΕΝΕΙ', display(c), float(c.tare_weight or 0), why, r[:3])
    by = {}
    for c in ok:
        by[c.owner_organization_id[:8]] = by.get(c.owner_organization_id[:8], {})
        for n in set(real[(display(c), float(c.tare_weight or 0))]):
            if n in ('KYKΛΟΣ Α.Β.Ε.Ε.', 'ΚΥΚΛΟΣ Α.Β.Ε.Ε.', 'STAR ECO Ε.Ε.'): by[c.owner_organization_id[:8]][n] = by[c.owner_organization_id[:8]].get(n, 0) + 1
    print('Αντιστοιχούν (ορφανός ιδιοκτήτης -> υπαρκτός μεταφορέας με ίδιο κωδικό+απόβαρο):', by)
    if not APPLY:
        print('(έλεγχος μόνο — πρόσθεσε --apply)'); sys.exit(0)
    for c in ok:
        write_audit(db, None, 'container', c.id, 'PURGE_ORPHAN', old={'container_number': c.container_number, 'owner_organization_id': c.owner_organization_id, 'code': display(c), 'tare': str(c.tare_weight)}, reason='Ορφανό διπλότυπο container (ιδιοκτήτης που δεν υπάρχει)')
        db.delete(c)
    db.commit()
    print(f'Διαγράφηκαν {len(ok)}. Σύνολο τώρα: {len(allc) - len(ok)}')
