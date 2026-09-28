"""One-time seed import for the Απογραφή (τρέχον έτος) report.

Run manually whenever the source files change (they live outside the repo, on the user's Desktop):
    .venv\\Scripts\\python.exe scripts\\import_inventory_report.py

Sources:
  - "ΑΠΟΓΡΑΦΗ 2026.xlsm", sheet "Αποθήκη": the report's row structure (group/subcategory/reptool
    code/description/HER name/EKA code/2025 baseline stock), including which rows are hidden.
  - "Ylika.xlsx", sheet "ΑΝΑΦΟΡΑ ΕΠΕΞΕΡΓΑΣΙΑΣ": row 4 ("Περιγραφή HER", merged per group) + row 5
    ("Περιγραφή ERP", one column per granular material) -- this is the material_label -> HER group
    mapping that lets the report sum production/shipment/inventory-count entries live.

Both imports are idempotent (delete-then-insert), safe to re-run.
"""
import sys
from pathlib import Path
import openpyxl

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.db import SessionLocal, engine
from app.models import Base, InventoryReportRow, MaterialHerGroup

APOGRAFI_PATH = Path(r"C:\Users\paran\Desktop\HER app\ΑΠΟΓΡΑΦΗ 2026.xlsm")
YLIKA_PATH = Path(r"C:\Users\paran\Desktop\HER app\Ylika.xlsx")

# Live material_label spellings that don't exact-match Ylika.xlsx's "Περιγραφή ERP" row, reviewed and
# confirmed by the user (27-28/9/2026) label by label. Applied on top of the Ylika import so the
# report's live sums include them too. Deliberately NOT included here (confirmed with the user to stay
# excluded from the materials-from-processing report entirely):
#   ΡΑΔΙΕΝΕΡΓΑ ΣΤΟΙΧΕΙΑ (ΠΑΡΑΛΑΒΕΣ), ΛΑΜΠΤΗΡΕΣ ΦΘΟΡΙΣΜΟΥ ΑΠΟ ΠΑΡΑΛΑΒΕΣ, TONER ΑΠΟ ΠΑΡΑΛΑΒΕΣ
#     -- these are ΑΗΗΕ categories sorted straight to inter-unit transfer, not processed materials.
#   ΠΛΥΝΤΗΡΙΑ, ΚΟΥΖΙΝΕΣ -- bulk whole-appliance categories, not materials.
#   ΦΕΛΙΖΟΛ -- still pending the user's call.
# ΚΙΝΗΤΑ / LAPTOPS / ΚΙΝΗΤΩΝ ΤΗΛΕΦΩΝΩΝ: a WEEE category can yield either a whole-device material
# output (e.g. "ΚΙΝΗΤΑ") or a PCB-only output from the same devices (e.g. "ΚΙΝΗΤΩΝ ΤΗΛΕΦΩΝΩΝ") -- these
# are two DIFFERENT materials, not spelling variants of one, confirmed against the app's own existing
# PLAKETES_LABELS set (desktop_v11.html) which already lists "ΚΙΝΗΤΩΝ ΤΗΛΕΦΩΝΩΝ" and "LAPTOPS" as PCB
# labels, bare, no "ΠΛΑΚΕΤΕΣ" prefix -- so no rename needed, just the right HER group each.
MANUAL_OVERRIDES = {
    "ΚΙΝΗΤΑ": "Κινητά - Tablet - Laptop",
    "ΚΙΝΗΤΩΝ ΤΗΛΕΦΩΝΩΝ": "Πλακέτες τυπ/νων κυκλωμάτων >10cm²",
    "LAPTOPS": "Πλακέτες τυπ/νων κυκλωμάτων >10cm²",
    "ΜΠΡΟΥΤΖΟΣ / ΧΑΛΚΟΣ": "Μέταλλο μη σιδηρούχο",
    "ΙΝΟΧ ΑΝΑΜΕΙΚΤΟ": "Μέταλλο μη σιδηρούχο",
    "ΚΑΛΩΔΙΑ ΑΠΛΑ": "Εσωτερικά Καλώδια",
    "ΓΥΑΛΙ": "Γυαλί Καθαρό",
    "ΣΚΟΥΠΕΣ ΜΙΚΡΕΣ": "Ημιέτοιμα Χύδην",
    "ΕΙΚΟΝΑ & ΗΧΟΣ ΜΙΚΡΑ": "Ημιέτοιμα Χύδην",
    "ΠΑΙΧΝΙΔΙΑ ΜΙΚΡΑ": "Ημιέτοιμα Χύδην",
    "ΒΑΡΥ ΣΙΔΗΡΟ": "Σίδηρος",
    "ΜΕΤΑΛΛΟ ΣΙΔΗΡΟΥΧΟ": "Σίδηρος",
    "MODEM & ROOTER": "Modem",
    "ΜΕΤΑΣΧΗΜΑΤΙΣΤΕΣ": "Μετασχηματιστές",
    "ΜΕΛΑΜΙΝΗ ΞΥΛΟ": "Μελαμίνη - Ξύλο",
    "ΦΙΣ/ ΠΡΙΖΕΣ": "Φις - Πρίζες",
    "ΟΘΟΝΕΣ ΥΓΡΩΝ ΚΡΥΣΤΑΛΛΩΝ": "Οθόνες υγρών κρυστάλλων  >100cm²",
    "ΣΥΣΣΩΡΕΥΤΕΣ ΜΟΛΥΒΔΟΥ": "Μπαταρίες Μολύβδου",
    "ΟΙΚΙΑΚΕΣ ΜΠΑΤΑΡΙΕΣ": "Μπαταρίες Απλές",
    "ΜΠΑΤΑΡΙΕΣ ΛΙΘΙΟΥ (ΚΙΝΗΤΩΝ)": "Μπαταρίες Απλές",
    "ΝΑΫΛΟΝ": "Νάυλον",
    "ΗΛΕΚΤΡΟΛΥΤΙΚΟΙ ΠΥΚΝΩΤΕΣ": "Hλεκτρολυτικοί πυκνωτές",
    "ΠΛΑΣΤΙΚΑ ΜΕΡΗ ΜΕ ΒΡΩΜΙΟ": "Πλαστικά με βρωμιούχους  φλογοεπιβραδυντές  ",
    "ΤΡΟΦΟΔΟΤΙΚΑ ΜΕ ΚΑΛΩΔΙΑ (Η/Υ)": "Τροφοδοτικά",
    "CD-DVD DRIVERS": "Θύρες / Drivers / Σκληροί Δίσκοι",
    "TONER (ΚΑΙΝΟΥΡΙΑ)": "Μελανοδοχεία",
    "ΜΕΛΑΝΟΔΟΧΕΙΑ INKJET": "Μελανοδοχεία",
    "ΚΑΛΩΔΙΑ EQUATORS": "Εσωτερικά Καλώδια",
    "ΚΑΛΩΔΙΑ ΧΡΙΣΤΟΥΓΕΝΝΙΑΤΙΚΑ": "Εσωτερικά Καλώδια",
    "ΠΛΕΞΙ ΓΚΛΑΣ": "Πλαστικά Μέρη",
    "ΠΛΑΣΤΙΚΟ LCD - ΔΙΑΦΑΝΟ & ΑΣΠΡΟ ΦΥΛΛΟ": "Πλαστικά Μέρη",
    "ΚΑΤΗΓΟΡΙΑΣ Β": "Πλακέτες τυπ/νων κυκλωμάτων >10cm²",
    "ΚΑΤΗΓΟΡΙΑΣ Β+": "Πλακέτες τυπ/νων κυκλωμάτων >10cm²",
    "ΚΑΤΗΓΟΡΙΑΣ Γ": "Πλακέτες τυπ/νων κυκλωμάτων >10cm²",
    "ΚΑΤΗΓΟΡΙΑΣ D": "Πλακέτες τυπ/νων κυκλωμάτων >10cm²",
    "ΚΑΤΗΓΟΡΙΑΣ Η": "Πλακέτες τυπ/νων κυκλωμάτων >10cm²",
    "ΚΑΤΗΓΟΡΙΑΣ G ΓΡΑΦΙΚΩΝ": "Πλακέτες τυπ/νων κυκλωμάτων >10cm²",
    "ΚΑΤΗΓΟΡΙΑΣ K ΕΠΙΧΡΥΣΕΣ": "Πλακέτες τυπ/νων κυκλωμάτων >10cm²",
    "ΚΑΤΗΓΟΡΙΑΣ N ONE SIDE GOLD": "Πλακέτες τυπ/νων κυκλωμάτων >10cm²",
    "ΚΑΤΗΓΟΡΙΑΣ S SERVER ΝΕΑΣ ΓΕΝΙΑΣ": "Πλακέτες τυπ/νων κυκλωμάτων >10cm²",
    "ΚΑΤΗΓΟΡΙΑΣ S+ SERVER ΠΑΛΙΑΣ ΓΕΝΙΑΣ": "Πλακέτες τυπ/νων κυκλωμάτων >10cm²",
    "ΚΑΤΗΓΟΡΙΑΣ A (HDD MIX)": "Πλακέτες τυπ/νων κυκλωμάτων >10cm²",
    "ΚΑΤΗΓΟΡΙΑΣ C ΜΗΤΡΙΚΕΣ ΝΕΑΣ ΓΕΝΙΑΣ 0": "Πλακέτες τυπ/νων κυκλωμάτων >10cm²",
    "ΚΑΤΗΓΟΡΙΑΣ C ΜΗΤΡΙΚΕΣ ΝΕΑΣ ΓΕΝΙΑΣ 1 METAL": "Πλακέτες τυπ/νων κυκλωμάτων >10cm²",
    "ΚΑΤΗΓΟΡΙΑΣ C ΜΗΤΡΙΚΕΣ ΝΕΑΣ ΓΕΝΙΑΣ 1 PLASTIC": "Πλακέτες τυπ/νων κυκλωμάτων >10cm²",
    "ΚΑΤΗΓΟΡΙΑΣ C ΜΗΤΡΙΚΕΣ ΝΕΑΣ ΓΕΝΙΑΣ 2": "Πλακέτες τυπ/νων κυκλωμάτων >10cm²",
    "ΚΑΤΗΓΟΡΙΑΣ C ΜΗΤΡΙΚΕΣ ΠΑΛΙΑΣ ΓΕΝΙΑΣ": "Πλακέτες τυπ/νων κυκλωμάτων >10cm²",
    "Η/Υ ΜΗΤΡΙΚΕΣ ΝΕΑΣ ΓΕΝΙΑΣ": "Πλακέτες τυπ/νων κυκλωμάτων >10cm²",
    "ΠΛΑΚΕΤΕΣ ROOTER": "Πλακέτες τυπ/νων κυκλωμάτων >10cm²",
    "ΜΕΤΑΛΛΙΚΕΣ ΑΛΟΥΜΙΝΙΟΥ": "Πλακέτες τυπ/νων κυκλωμάτων >10cm²",
    "ΜΗ ΑΚΕΡΑΙΟΙ ΛΑΜΠΤΗΡΕΣ": "Λαμπτήρες εκκένωσης αερίων",
    "ΑΝΕΜΙΣΤΗΡΕΣ": "Ανεμιστήρες",
}


def merged_value(ws, row, col):
    """Return the cell's own value, or -- if it's a follower cell inside a merged range (vertical,
    horizontal, or both) -- the anchor cell's value (openpyxl leaves follower cells as None)."""
    v = ws.cell(row=row, column=col).value
    if v is not None:
        return v
    for rng in ws.merged_cells.ranges:
        if rng.min_row <= row <= rng.max_row and rng.min_col <= col <= rng.max_col:
            return ws.cell(row=rng.min_row, column=rng.min_col).value
    return None


def import_apografi(db):
    wb = openpyxl.load_workbook(APOGRAFI_PATH, data_only=True)
    ws = wb["Αποθήκη"]
    db.query(InventoryReportRow).delete()
    n = 0
    for r in range(8, ws.max_row + 1):
        code = ws.cell(row=r, column=3).value  # C: reptool code
        if code is None:
            continue  # blank separator row
        group_name = merged_value(ws, r, 1)     # A
        subcategory = merged_value(ws, r, 2)    # B
        desc_en = ws.cell(row=r, column=4).value  # D
        her_group = ws.cell(row=r, column=5).value  # E
        eka = ws.cell(row=r, column=6).value    # F
        baseline = ws.cell(row=r, column=7).value or 0  # G
        hidden = bool(ws.row_dimensions[r].hidden) if r in ws.row_dimensions else False
        db.add(InventoryReportRow(
            sort_order=n, group_name=group_name, subcategory=subcategory,
            reptool_code=str(code), description_en=desc_en,
            her_group=her_group, eka_code=eka, baseline_stock_2025=baseline,
            frozen_hidden=hidden,
        ))
        n += 1
    db.commit()
    print(f"[import_apografi] imported {n} rows")


def import_ylika(db):
    wb = openpyxl.load_workbook(YLIKA_PATH, data_only=True)
    ws = wb["ΑΝΑΦΟΡΑ ΕΠΕΞΕΡΓΑΣΙΑΣ"]
    db.query(MaterialHerGroup).delete()
    seen = {}
    for c in range(1, ws.max_column + 1):
        her = merged_value(ws, 4, c)
        erp = ws.cell(row=5, column=c).value
        if her and erp:
            seen[str(erp).strip()] = str(her).strip()
    for label, group in seen.items():
        db.add(MaterialHerGroup(material_label=label, her_group=group))
    for label, group in MANUAL_OVERRIDES.items():
        if label not in seen:
            db.add(MaterialHerGroup(material_label=label, her_group=group))
    db.commit()
    print(f"[import_ylika] imported {len(seen)} + {len(MANUAL_OVERRIDES)} manual = {len(seen)+len(MANUAL_OVERRIDES)} material -> HER group mappings")


def main():
    Base.metadata.create_all(bind=engine)  # safe no-op if the server already created these tables
    db = SessionLocal()
    try:
        import_apografi(db)
        import_ylika(db)
    finally:
        db.close()


if __name__ == "__main__":
    main()
