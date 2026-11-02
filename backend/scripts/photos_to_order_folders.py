"""Μία φορά: μεταφέρει τις φωτογραφίες φορτίων στη δομή
Έγγραφα/WEEE Platform/Φωτογραφίες/<έτος>/<ΜΜ - Μήνας>/<ημέρα-μήνας>/<αριθμός container ή αριθμός εντολής>
(ημέρα = ημερομηνία παραλαβής της εντολής) και ενημερώνει τη διαδρομή στη βάση (file_attachments.stored_path).
Χρήση:  python backend/scripts/photos_to_order_folders.py [--dry] [διαδρομή βάσης]   (χωρίς διαδρομή = η πραγματική βάση)
Κάθε αρχείο πρώτα αντιγράφεται και ελέγχεται (μέγεθος + ανοίγει ως εικόνα), μετά ενημερώνεται η βάση, μετά σβήνεται το παλιό·
οι παλιοί φάκελοι σβήνονται μόνο αν έμειναν άδειοι. Στο τέλος ελέγχεται ότι κάθε φωτογραφία της βάσης ανοίγει."""
import os, re, shutil, sqlite3, sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app import docs_storage  # noqa: E402

sys.stdout.reconfigure(encoding="utf-8")
args = [a for a in sys.argv[1:] if not a.startswith("--")]
dry = "--dry" in sys.argv
db = args[0] if args else os.path.expandvars(r"%LOCALAPPDATA%\WEEE Platform\data\weee_dev.db")
con = sqlite3.connect(db)
root = docs_storage.photos_root() if not dry else docs_storage.documents_dir() / docs_storage.APP_DIR / docs_storage.PHOTOS
RE_Y, RE_M, RE_D = re.compile(r"^\d{4}$"), re.compile(r"^\d\d - \D+$"), re.compile(r"^\d{1,2}-\d{1,2}$")


def in_new_structure(p: Path) -> bool:
    try:
        parts = p.relative_to(root).parts
    except ValueError:
        return False
    return len(parts) >= 4 and bool(RE_Y.match(parts[0]) and RE_M.match(parts[1]) and RE_D.match(parts[2]))


def opens(p) -> bool:
    try:
        from PIL import Image
        with Image.open(p) as im:
            im.load()
        return Path(p).stat().st_size > 0
    except Exception:
        return False


rows = con.execute(
    "select a.id,a.stored_path,l.order_number,l.incoming_container_number,t.receipt_date,l.id "
    "from file_attachments a join inbound_loads l on l.id=a.entity_id join inbound_trips t on t.id=l.trip_id "
    "where a.entity_type='INBOUND_LOAD' order by a.created_at").fetchall()
parents = {r[0]: str(Path(r[1]).parent).lower() for r in rows}   # φάκελος κάθε φωτογραφίας (για τις συγκρούσεις)
owner = {r[0]: r[5] for r in rows}
before = len(rows)
print("φωτογραφίες στη βάση:", before, "· υπάρχουν στον δίσκο:", sum(1 for r in rows if Path(r[1]).exists()))
moved = 0
for aid, path, order_no, container, rdate, load_id in rows:
    src = Path(path)
    if in_new_structure(src.parent):
        continue
    if not src.exists():
        print("ΛΕΙΠΕΙ το αρχείο:", src); continue
    day = datetime.fromisoformat(str(rdate)[:19])
    others = lambda d: any(p == str(d).lower() and owner[k] != load_id for k, p in parents.items())
    target = docs_storage.photo_dir(order_no or load_id[:8], container, day, others, create=not dry)
    dest = target / src.name
    print(("ΘΑ ΜΕΤΑΦΕΡΘΕΙ" if dry else "μεταφέρεται"), src, "->", dest)
    if dry:
        continue
    shutil.copyfile(src, dest)
    if dest.stat().st_size != src.stat().st_size or not opens(dest):
        print("ΣΦΑΛΜΑ: η αντιγραφή δεν είναι σωστή, δεν μεταφέρθηκε"); dest.unlink(missing_ok=True); continue
    con.execute("update file_attachments set stored_path=? where id=?", (str(dest), aid)); con.commit()
    parents[aid] = str(dest.parent).lower()
    src.unlink(); moved += 1
    d = src.parent    # άδειοι παλιοί φάκελοι δεν μένουν πίσω
    while d != root and root in d.parents and d.exists() and not any(d.iterdir()):
        d.rmdir(); d = d.parent
print("μεταφέρθηκαν:", moved)
if not dry:
    after = [p[0] for p in con.execute("select stored_path from file_attachments where entity_type='INBOUND_LOAD'").fetchall()]
    bad = [p for p in after if not opens(p)]
    print("ΕΛΕΓΧΟΣ: πριν", before, "· μετά", len(after), "· ανοίγουν", len(after) - len(bad))
    for p in bad:
        print("ΔΕΝ ΑΝΟΙΓΕΙ:", p)
