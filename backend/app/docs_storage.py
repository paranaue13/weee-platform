"""Φάκελος της εφαρμογής μέσα στα Έγγραφα του χρήστη: Έγγραφα\\WEEE Platform\\{Φωτογραφίες,Αναφορές}\\YYYY-MM.

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


def documents_dir() -> Path:
    override = os.environ.get("WEEE_DOCS_DIR")
    if override:
        return Path(override)
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
        raise HTTPException(500, f"Δεν μπορώ να γράψω στον φάκελο «{d}» ({e.strerror or e}). "
                                 f"Έλεγξε ότι ο φάκελος Έγγραφα είναι προσβάσιμος και ότι ο χρήστης έχει δικαίωμα εγγραφής.")
    return d


def ensure_folders() -> None:
    """Στην εκκίνηση: φτιάχνει τους φακέλους του τρέχοντος μήνα· αν δεν γίνει, γράφεται στο log (η εκκίνηση συνεχίζει)."""
    for kind in (PHOTOS, REPORTS):
        try:
            month_dir(kind)
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
        raise HTTPException(500, f"Δεν μπόρεσα να αποθηκεύσω την αναφορά στο «{dest}» ({e.strerror or e}).")
    return dest
