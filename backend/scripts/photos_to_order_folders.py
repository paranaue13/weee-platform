"""Μία φορά: μεταφέρει τις φωτογραφίες φορτίων που υπάρχουν ήδη στον φάκελο της εντολής τους
(Έγγραφα\\WEEE Platform\\Φωτογραφίες\\YYYY-MM\\Εντολή <αριθμός>) και ενημερώνει τη διαδρομή στη βάση (file_attachments.stored_path).
Χρήση:  python backend/scripts/photos_to_order_folders.py [--dry] [διαδρομή βάσης]   (χωρίς διαδρομή = η πραγματική βάση)
Κάθε αρχείο μεταφέρεται μόνο αν βρεθεί· πρώτα αντιγράφεται και ελέγχεται, μετά σβήνεται το παλιό."""
import os, shutil, sqlite3, sys
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app import docs_storage  # noqa: E402

args = [a for a in sys.argv[1:] if not a.startswith("--")]
dry = "--dry" in sys.argv
db = args[0] if args else os.path.expandvars(r"%LOCALAPPDATA%\WEEE Platform\data\weee_dev.db")
con = sqlite3.connect(db)
rows = con.execute("select a.id,a.stored_path,a.created_at,l.order_number,l.id from file_attachments a join inbound_loads l on l.id=a.entity_id where a.entity_type='INBOUND_LOAD'").fetchall()
moved = 0
for aid, path, created, order_no, load_id in rows:
    src = Path(path)
    if src.parent.name.startswith("Εντολή "):
        continue
    if not src.exists():
        print("ΛΕΙΠΕΙ το αρχείο:", src); continue
    d = datetime.fromisoformat(str(created)).replace(tzinfo=timezone.utc).astimezone(ZoneInfo("Europe/Athens"))
    target_dir = docs_storage.photo_dir(order_no or load_id[:8], d) if not dry else Path(f"<{d.year}-{d.month:02d}>/Εντολή {order_no}")
    dest = target_dir / src.name
    print(("ΘΑ ΜΕΤΑΦΕΡΘΕΙ" if dry else "μεταφέρεται"), src, "->", dest)
    if dry:
        continue
    shutil.copyfile(src, dest)
    if dest.stat().st_size != src.stat().st_size:
        print("ΣΦΑΛΜΑ μεγέθους, δεν μεταφέρθηκε"); dest.unlink(missing_ok=True); continue
    con.execute("update file_attachments set stored_path=? where id=?", (str(dest), aid)); con.commit()
    src.unlink(); moved += 1
print("τέλος, μεταφέρθηκαν:", moved)
