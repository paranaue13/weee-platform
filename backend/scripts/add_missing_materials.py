# -*- coding: utf-8 -*-
"""One-off (already run 28-29/9/2026): added the materials found in the real September operational
file (tabs 3/4/5 of "ΕΙΣΕΡΧΟΜΕΝΑ-ΕΠΕΞΕΡΓΑΣΜΕΝΑ ΥΛΙΚΑ-ΠΡΕΣΑ (ΣΕΠΤΕΜΒΡΙΟΣ 2026).xlsx" on the GALSRV
share) that had never existed in this app's `materials` master table -- 32 were genuinely new,
codes 00209-00240 (26 others in that file turned out to already exist under the same name; ΦΕΛΙΖΟΛ
was merged into ΣΚΟΥΠΙΔΙΑ separately, and "...ΑΠΟ ΠΑΡΑΛΑΒΕΣ" ones excluded per the user's instruction).
her_description assigned from the same Ylika.xlsx HER-group taxonomy used for the Απογραφή report;
two are left blank pending the user (ΙΝΟΧ/ΑΛΟΥΜΙΝΙΟ, ΑΚΕΡΑΙΟΙ ΛΑΜΠΤΗΡΕΣ (TV/MONITOR LCD)).
Re-running is safe -- it skips any internal_name that already exists.
See import_inventory_report.py, which now also reads materials.her_description as a fallback source,
so newly added rows like these feed the Απογραφή report automatically without a manual override.
"""
import sqlite3, sys
sys.stdout.reconfigure(encoding="utf-8")

PLAKETES = "Πλακέτες τυπ/νων κυκλωμάτων >10cm²"
XYDIN = "Ημιέτοιμα Χύδην"

# (internal_name, her_description or None)
NEW_MATERIALS = [
    # Αξιοποιήσιμα Υλικά (tab 3)
    ("ΜΑΝΤΕΜΙ (ΧΥΤΟΣΙΔΗΡΟΣ)", "Σίδηρος"),
    ("ΙΝΟΧ/ ΑΛΟΥΜΙΝΙΟ", None),  # uncertain -- mixed inox/aluminium, ask
    ("ΚΑΛΩΔΙΑ EQUATORS ΑΛΟΥΜΙΝΙΟΥ", "Εσωτερικά Καλώδια"),
    ("ΜΟΛΥΒΙ", "Μέταλλο μη σιδηρούχο"),
    ("ELECTROGUN", "Electron guns"),
    ("ΘΥΡΕΣ CD-ROM", "Θύρες / Drivers / Σκληροί Δίσκοι"),
    ("ΚΑΛΩΔΙΑ ΚΕΡΑΙΕΣ", "Εσωτερικά Καλώδια"),
    ("ΤΡΟΦΟΔΟΤΙΚΑ ΧΩΡΙΣ ΚΑΛΩΔΙΑ (ΕΚΤΥΠΩΤΩΝ)", "Τροφοδοτικά"),
    # Υλικά Ειδικής Διαχείρισης (tab 4) -- plaketes category grades
    ("ΚΑΤΗΓΟΡΙΑΣ ΑA1", PLAKETES),
    ("ΚΑΤΗΓΟΡΙΑΣ ΑA2 (ΕΠΙΧΡΥΣΕΣ)", PLAKETES),
    ("ΚΑΤΗΓΟΡΙΑΣ ΑA3", PLAKETES),
    ("ΚΑΤΗΓΟΡΙΑΣ ΑA4", PLAKETES),
    ("ΚΑΤΗΓΟΡΙΑΣ ΑA5 (ΧΑΛΚΙΝΕΣ)", PLAKETES),
    ("ΚΑΤΗΓΟΡΙΑΣ ΑA6", PLAKETES),
    ("ΠΛΑΚΕΤΕΣ ΚΑΤΗΓΟΡΙΑΣ C ΜΗΤΡΙΚΕΣ ΠΑΛΙΑΣ ΓΕΝΙΑΣ", PLAKETES),
    ("ΠΛΑΚΕΤΕΣ ΚΑΤΗΓΟΡΙΑΣ C ΜΗΤΡΙΚΕΣ ΝΕΑΣ ΓΕΝΙΑΣ 0", PLAKETES),
    ("ΠΛΑΚΕΤΕΣ ΚΑΤΗΓΟΡΙΑΣ C ΜΗΤΡΙΚΕΣ ΝΕΑΣ ΓΕΝΙΑΣ 1 PLASTIC", PLAKETES),
    ("ΠΛΑΚΕΤΕΣ ΚΑΤΗΓΟΡΙΑΣ C ΜΗΤΡΙΚΕΣ ΝΕΑΣ ΓΕΝΙΑΣ 1 METAL", PLAKETES),
    ("ΠΛΑΚΕΤΕΣ ΚΑΤΗΓΟΡΙΑΣ C ΜΗΤΡΙΚΕΣ ΝΕΑΣ ΓΕΝΙΑΣ 2", PLAKETES),
    ("ΚΑΤΗΓΟΡΙΑΣ Α", PLAKETES),
    ("ΚΑΤΗΓΟΡΙΑΣ Α (LCD ΕΠΙΧΡΥΣΩΜΕΝΕΣ)", PLAKETES),
    ("ΚΑΤΗΓΟΡΙΑΣ Α (LCD ΕΠΙΧΑΛΚΩΜΕΝΕΣ)", PLAKETES),
    ("ΚΑΤΗΓΟΡΙΑΣ Α (ΚΑΡΤΕΣ ΓΡΑΦΙΚΩΝ)", PLAKETES),
    ("ΚΑΤΗΓΟΡΙΑΣ Α (ΣΚΛΗΡΩΝ ΔΙΣΚΩΝ)", PLAKETES),
    ("ΠΛΑΚΕΤΕΣ ΚΑΤΗΓΟΡΙΑΣ A (HDD MIX)", PLAKETES),
    ("ΠΛΑΚΕΤΕΣ ΚΑΤΗΓΟΡΙΑΣ Β+", PLAKETES),
    ("ΠΛΑΚΕΤΕΣ ΚΑΤΗΓΟΡΙΑΣ Β", PLAKETES),
    ("ΠΛΑΚΕΤΕΣ ΚΑΤΗΓΟΡΙΑΣ G ΓΡΑΦΙΚΩΝ", PLAKETES),
    ("ΠΛΑΚΕΤΕΣ ΚΑΤΗΓΟΡΙΑΣ K ΕΠΙΧΡΥΣΕΣ", PLAKETES),
    ("ΠΛΑΚΕΤΕΣ ΜΕΤΑΛΛΙΚΕΣ ΑΛΟΥΜΙΝΙΟΥ", PLAKETES),
    ("ΠΛΑΚΕΤΕΣ ΚΑΤΗΓΟΡΙΑΣ S+ SERVER ΠΑΛΙΑΣ ΓΕΝΙΑΣ", PLAKETES),
    ("ΠΛΑΚΕΤΕΣ ΚΑΤΗΓΟΡΙΑΣ S SERVER ΝΕΑΣ ΓΕΝΙΑΣ", PLAKETES),
    ("ΠΛΑΚΕΤΕΣ ΚΑΤΗΓΟΡΙΑΣ N ONE SIDE GOLD", PLAKETES),
    ("ΠΛΑΚΕΤΕΣ ΚΑΤΗΓΟΡΙΑΣ D", PLAKETES),
    ("ΠΛΑΚΕΤΕΣ ΚΑΤΗΓΟΡΙΑΣ Η", PLAKETES),
    # Υλικά Ειδικής Διαχείρισης -- Ημιέτοιμα Χύδην (bulk whole-appliance, same family as Κουζίνες/Πλυντήρια)
    ("ΘΕΡΜΟΣΙΦΩΝΕΣ", XYDIN),
    ("ΚΟΥΖΙΝΑΚΙΑ", XYDIN),
    ("ΣΚΟΥΠΕΣ ΜΕΓΑΛΕΣ", XYDIN),
    ("ΠΑΡΑΚΟΛΟΥΘΗΣΗ & ΕΛΕΓΧΟΣ ΜΙΚΡΑ", XYDIN),
    ("ΦΩΤΙΣΤΙΚΑ ΜΙΚΡΑ", XYDIN),
    ("ΕΡΓΑΛΕΙΑ ΜΙΚΡΑ", XYDIN),
    ("ΙΑΤΡΙΚΑ ΜΙΚΡΑ", XYDIN),
    ("ΠΑΙΧΝΙΔΟΜΗΧΑΝΕΣ (ΚΟΝΣΟΛΕΣ)", XYDIN),
    # Υλικά προς Απόρριψη (tab 5)
    ("ΑΚΟΥΣΤΙΚΑ", "Ακουστικά, μηχανικές κεφαλές, πληκτρολόγια, CD-DVD-Floppy discs, κασσέτες"),
    ("FLOPPY DISCS", "Ακουστικά, μηχανικές κεφαλές, πληκτρολόγια, CD-DVD-Floppy discs, κασσέτες"),
    ("CD / DVD DISCS", "Ακουστικά, μηχανικές κεφαλές, πληκτρολόγια, CD-DVD-Floppy discs, κασσέτες"),
    ("ΠΥΚΝΩΤΕΣ ΜΕ PCB", "Πυκνωτές με PCB"),
    ("ΠΥΚΝΩΤΕΣ", "Πυκνωτές"),
    ("ΜΕΛΑΝΟΤΑΙΝΙΕΣ", "Μελανοδοχεία"),
    ("ΠΟΥΔΡΑ", "Πούδρα"),
    ("ΑΚΕΡΑΙΟΙ ΛΑΜΠΤΗΡΕΣ (TV / MONITOR LCD)", None),  # uncertain -- CRT/LCD-monitor lamps, ask
    ("ΛΑΜΠΤΗΡΕΣ LED", "Διάφορες Λυχνίες"),
    ("ΡΑΔΙΕΝΕΡΓΑ ΣΤΟΙΧΕΙΑ", "Ραδιενεργές συσκευές"),
    ("ΥΑΛΟΒΑΜΒΑΚΑΣ", None),  # uncertain -- no clear Ylika match, ask
    ("ΚΑΤΑΣΚΕΥΑΣΤΙΚΑ ΣΤΟΙΧΕΙΑ ΜΕ Hg", "Κατασκευαστικά στοιχεία με Hg"),
    ("ΜΠΕΤΟΝ", "Μπετόν"),
    ("ΛΑΣΤΙΧΑ - ΚΑΟΥΤΣΟΥΚ", "Λαστιχα - Καουτσούκ"),
    ("ΔΙΑΦΟΡΕΣ ΛΥΧΝΙΕΣ", "Διάφορες Λυχνίες"),
]

c = sqlite3.connect(r"C:\Users\paran\AppData\Local\WEEE Platform\data\weee_dev.db")
existing = {r[0].strip().upper() for r in c.execute("select internal_name from materials")}
next_num = max(int(__import__("re").match(r"\D*(\d{5})", r[0]).group(1))
               for r in c.execute("select internal_code from materials")
               if __import__("re").match(r"\D*(\d{5})", r[0])) + 1

added, skipped, uncertain = [], [], []
import uuid
from datetime import datetime, timezone
now = datetime.now(timezone.utc).isoformat()
for name, her in NEW_MATERIALS:
    if name.strip().upper() in existing:
        skipped.append(name)
        continue
    code = f"{next_num:05d}"
    next_num += 1
    mid = str(uuid.uuid4())
    c.execute(
        "insert into materials (id, internal_code, internal_name, her_description, is_precious, export_step_kg, active, created_at, updated_at) "
        "values (?,?,?,?,0,0.5,1,?,?)",
        (mid, code, name, her, now, now),
    )
    added.append((code, name, her))
    if her is None:
        uncertain.append(name)
c.commit()
print(f"added {len(added)} materials, skipped {len(skipped)} already-existing")
for code, name, her in added:
    print(f"  {code}  {name!r:60s} -> {her}")
if uncertain:
    print("\nUNCERTAIN her_description (left blank, please confirm):")
    for u in uncertain:
        print("  -", u)
if skipped:
    print("\nalready existed, skipped:", skipped)
