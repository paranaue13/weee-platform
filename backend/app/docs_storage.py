"""Φάκελος της εφαρμογής μέσα στα Έγγραφα του χρήστη: Έγγραφα/WEEE Platform/Φωτογραφίες/ΕΤΟΣ/ΜΗΝΑΣ/ΗΜΕΡΑ/<container> και Αναφορές/YYYY-MM.

Ο φάκελος «Έγγραφα» ζητείται από τα Windows (Known Folder), ώστε να δουλεύει και όταν είναι μέσα σε OneDrive,
και είναι ο ίδιος είτε τρέχει η εφαρμογή από τον κώδικα είτε από το .exe. Η μεταβλητή WEEE_DOCS_DIR
(μόνο για δοκιμές) αντικαθιστά τον φάκελο «Έγγραφα»."""
import os, shutil, logging
from datetime import date, datetime
from pathlib import Path

from fastapi import HTTPException

log = logging.getLogger("docs_storage")

APP_DIR = "WEEE Platform"
PHOTOS = "Φωτογραφίες"
REPORTS = "Αναφορές"


DOCS_KEY = "app.docs_dir"
_custom_dir = None   # φάκελος που επέλεξε ο χρήστης (αντί για τα Έγγραφα)· ορίζεται στην εκκίνηση και όταν τον αλλάζει


def set_custom_dir(p) -> None:
    global _custom_dir
    _custom_dir = Path(p) if p else None


def load_custom_dir(db) -> None:
    from sqlalchemy import select
    from . import models
    row = db.scalar(select(models.AppSetting).where(models.AppSetting.key == DOCS_KEY))
    set_custom_dir((row.value or "").strip() if row else None)


def documents_dir() -> Path:
    override = os.environ.get("WEEE_DOCS_DIR")
    if override:
        return Path(override)
    if _custom_dir:
        return _custom_dir
    if os.name == "nt":
        try:
            import ctypes
            from ctypes import wintypes

            class GUID(ctypes.Structure):
                _fields_ = [("a", wintypes.DWORD), ("b", wintypes.WORD), ("c", wintypes.WORD), ("d", ctypes.c_ubyte * 8)]

            # FOLDERID_Documents = {FDD39AD0-238F-46AF-ADB4-6C85480369C7}
            g = GUID(0xFDD39AD0, 0x238F, 0x46AF, (ctypes.c_ubyte * 8)(0xAD, 0xB4, 0x6C, 0x85, 0x48, 0x03, 0x69, 0xC7))
            out = ctypes.c_wchar_p()
            if ctypes.windll.shell32.SHGetKnownFolderPath(ctypes.byref(g), 0, None, ctypes.byref(out)) == 0:
                p = out.value
                ctypes.windll.ole32.CoTaskMemFree(out)
                if p:
                    return Path(p)
        except Exception:
            log.exception("δεν βρέθηκε ο φάκελος Έγγραφα από τα Windows")
    return Path.home() / "Documents"


def _now() -> datetime:
    try:
        from zoneinfo import ZoneInfo
        return datetime.now(ZoneInfo("Europe/Athens"))
    except Exception:
        return datetime.now()


def month_dir(kind: str, when=None) -> Path:
    """Έγγραφα\\WEEE Platform\\<kind>\\YYYY-MM — δημιουργείται μόνος του· αν δεν γράφεται, καθαρό μήνυμα."""
    when = when or _now()
    d = documents_dir() / APP_DIR / kind / f"{when.year}-{when.month:02d}"
    try:
        d.mkdir(parents=True, exist_ok=True)
        probe = d / ".write_test"
        probe.write_bytes(b"")
        probe.unlink()
    except OSError as e:
        raise HTTPException(507, f"Δεν μπορώ να γράψω στον φάκελο «{d}» ({e.strerror or e}). "
                                 f"Έλεγξε ότι ο φάκελος είναι προσβάσιμος και ότι υπάρχει δικαίωμα εγγραφής, ή επίλεξε άλλον φάκελο αποθήκευσης.")
    return d


def safe_name(x: str) -> str:
    return "".join(c for c in str(x or "") if c not in '<>:"/' + chr(92) + '|?*').strip(" .") or "χωρίς αριθμό"


def photos_root() -> Path:
    """Έγγραφα/WEEE Platform/Φωτογραφίες — δημιουργείται μόνος του· αν δεν γράφεται, καθαρό μήνυμα (507)."""
    d = documents_dir() / APP_DIR / PHOTOS
    try:
        d.mkdir(parents=True, exist_ok=True)
        probe = d / ".write_test"
        probe.write_bytes(b"")
        probe.unlink()
    except OSError as e:
        raise HTTPException(507, f"Δεν μπορώ να γράψω στον φάκελο «{d}» ({e.strerror or e}). "
                                 f"Έλεγξε ότι ο φάκελος είναι προσβάσιμος και ότι υπάρχει δικαίωμα εγγραφής, ή επίλεξε άλλον φάκελο αποθήκευσης.")
    return d


def photo_dir(order_no, container, day, taken_by_other=None) -> Path:
    """Φωτογραφίες/ΕΤΟΣ/ΜΗΝΑΣ/ΗΜΕΡΑ/<αριθμός container> — ημέρα = ημερομηνία παραλαβής της εντολής.
    Χωρίς container: ο αριθμός της εντολής. Αν τον ίδιο φάκελο τον έχει ήδη άλλη εντολή (ίδιο container, ίδια ημέρα),
    ο φάκελος γίνεται «<container> - Εντολή <αριθμός>» ώστε τα αρχεία να μη ανακατεύονται."""
    day = day or _now()
    name = safe_name(container) if str(container or "").strip() else safe_name(order_no)
    base = photos_root() / f"{day.year}" / f"{day.month:02d}" / f"{day.day:02d}"
    d = base / name
    if taken_by_other and taken_by_other(d):
        d = base / f"{name} - Εντολή {safe_name(order_no)}"
    try:
        d.mkdir(parents=True, exist_ok=True)
    except OSError as e:
        raise HTTPException(507, f"Δεν μπορώ να δημιουργήσω τον φάκελο «{d}» ({e.strerror or e}). Επίλεξε άλλον φάκελο αποθήκευσης.")
    return d


def to_recycle_bin(path) -> bool:
    """Στέλνει αρχείο στον Κάδο ανακύκλωσης των Windows (όχι οριστική διαγραφή). True αν έγινε."""
    p = str(Path(path))
    if os.name != "nt" or not os.path.exists(p):
        return False
    import ctypes
    from ctypes import wintypes

    class SHFILEOPSTRUCTW(ctypes.Structure):
        _fields_ = [("hwnd", wintypes.HWND), ("wFunc", wintypes.UINT), ("pFrom", wintypes.LPCWSTR), ("pTo", wintypes.LPCWSTR),
                    ("fFlags", ctypes.c_ushort), ("fAnyOperationsAborted", wintypes.BOOL), ("hNameMappings", ctypes.c_void_p),
                    ("lpszProgressTitle", wintypes.LPCWSTR)]

    # FO_DELETE=3, FOF_SILENT|FOF_NOCONFIRMATION|FOF_ALLOWUNDO|FOF_NOERRORUI = 0x0004|0x0010|0x0040|0x0400
    op = SHFILEOPSTRUCTW(None, 3, p + "\0", None, 0x0004 | 0x0010 | 0x0040 | 0x0400, False, None, None)
    rc = ctypes.windll.shell32.SHFileOperationW(ctypes.byref(op))
    return rc == 0 and not op.fAnyOperationsAborted and not os.path.exists(p)


def ensure_folders() -> None:
    """Στην εκκίνηση: φτιάχνει τους φακέλους του τρέχοντος μήνα· αν δεν γίνει, γράφεται στο log (η εκκίνηση συνεχίζει)."""
    try:
        photos_root()
        month_dir(REPORTS)
    except HTTPException as e:
        log.error(e.detail)


def unique_path(d: Path, name: str) -> Path:
    p = d / name
    n = 1
    while p.exists():
        p = d / f"{Path(name).stem} ({n}){Path(name).suffix}"
        n += 1
    return p


def save_report(tmp_path, filename: str, when=None) -> Path:
    """Αντίγραφο ενός αρχείου που παρήγαγε η εφαρμογή (Excel, PDF…) στο Αναφορές\\<μήνας>."""
    d = month_dir(REPORTS, when if isinstance(when, (date, datetime)) else None)
    dest = unique_path(d, "".join(c for c in filename if c not in '<>:"/\\|?*') or "report")
    try:
        shutil.copyfile(str(tmp_path), str(dest))
    except OSError as e:
        raise HTTPException(507, f"Δεν μπόρεσα να αποθηκεύσω την αναφορά στο «{dest}» ({e.strerror or e}). Επίλεξε άλλον φάκελο αποθήκευσης.")
    return dest
