"""One-off data fix: some historical material_output_entries / material_shipment_entries rows were
imported with ambiguous plain names ("ΚΙΝΗΤΑ", "ΚΙΝΗΤΩΝ ΤΗΛΕΦΩΝΩΝ", "LAPTOPS") that actually represent
PCB material dismantled FROM those devices (confirmed by weight -- a few hundred kg total, not
thousands, matching board weight not whole-device weight -- and by the user, 28/9/2026), not whole
devices. Renamed here to match Ylika.xlsx's own "Περιγραφή ERP" spelling exactly ("ΠΛΑΚΕΤΕΣ ΚΙΝΗΤΩΝ
ΤΗΛΕΦΩΝΩΝ" / "ΠΛΑΚΕΤΕΣ LAPTOPS"), so they auto-map to the "Πλακέτες τυπ/νων κυκλωμάτων >10cm²" HER
group without needing a manual override in import_inventory_report.py.

Distinct from the already-correct whole-device entries "LAPTOP" (singular) and "ΤΗΛΕΦΩΝΑ", which stay
as-is (those genuinely are whole processed devices exported as material, per the "Κινητά - Tablet -
Laptop" HER group).

Safe to re-run: renames only rows still under the old labels, so running it twice is a no-op the
second time.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.db import SessionLocal
from app.models import MaterialOutputEntry, MaterialShipmentEntry

RENAMES = {
    "ΚΙΝΗΤΑ": "ΠΛΑΚΕΤΕΣ ΚΙΝΗΤΩΝ ΤΗΛΕΦΩΝΩΝ",
    "ΚΙΝΗΤΩΝ ΤΗΛΕΦΩΝΩΝ": "ΠΛΑΚΕΤΕΣ ΚΙΝΗΤΩΝ ΤΗΛΕΦΩΝΩΝ",
    "LAPTOPS": "ΠΛΑΚΕΤΕΣ LAPTOPS",
}


def main():
    db = SessionLocal()
    try:
        for model in (MaterialOutputEntry, MaterialShipmentEntry):
            for old, new in RENAMES.items():
                rows = db.query(model).filter(model.material_label == old).all()
                for r in rows:
                    r.material_label = new
                if rows:
                    print(f"[rename_pcb] {model.__tablename__}: {old!r} -> {new!r} ({len(rows)} rows)")
        db.commit()
    finally:
        db.close()


if __name__ == "__main__":
    main()
