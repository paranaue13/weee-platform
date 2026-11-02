"""Shared 'where do generated reports get archived' setting.

Used by both main.py's own workbook builder (_received_workbook_response, used by the
daily/monthly Παραληφθέντων ΑΗΗΕ exports) and report_generators.py's template-based
reports (Ημερήσιο Συγκεντρωτικό, Υλικά ΜΗ ΑΗΗΕ ανά προμηθευτή). Kept in its own module
so both can import it without main.py <-> report_generators.py becoming circular.
"""
import json, logging, shutil
from datetime import date
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from . import models

log = logging.getLogger("export")

EXPORT_DIR_KEY = "app.export_directory"
DEFAULT_EXPORT_SETTINGS = {"path": None, "group_by_month": True}

MONTHS_EL = ["Ιανουάριος", "Φεβρουάριος", "Μάρτιος", "Απρίλιος", "Μάιος", "Ιούνιος",
             "Ιούλιος", "Αύγουστος", "Σεπτέμβριος", "Οκτώβριος", "Νοέμβριος", "Δεκέμβριος"]


def get_export_settings(db: Session) -> dict:
    row = db.scalar(select(models.AppSetting).where(models.AppSetting.key == EXPORT_DIR_KEY))
    if not row:
        return dict(DEFAULT_EXPORT_SETTINGS)
    try:
        d = json.loads(row.value)
        return {"path": d.get("path") or None, "group_by_month": bool(d.get("group_by_month", True))}
    except Exception:
        return dict(DEFAULT_EXPORT_SETTINGS)


def archive_export_copy(db: Session, tmp_path, filename: str, when: date) -> None:
    """Best-effort copy of a just-generated report into the configured export folder
    (year/<NN - Μήνας> subfolders when grouping is on). Never raises: the browser
    download this runs alongside must still succeed even if the folder is briefly
    unreachable (removable drive unplugged, network share down, ...)."""
    from . import docs_storage
    docs_storage.save_report(tmp_path, filename)   # Έγγραφα\WEEE Platform\Αναφορές\YYYY-MM (αν δεν γράφεται: καθαρό σφάλμα)
    cfg = get_export_settings(db)
    if not cfg.get("path"):
        return
    try:
        dest_dir = Path(cfg["path"])
        if cfg.get("group_by_month"):
            dest_dir = dest_dir / f"{when.year}" / f"{when.month:02d} - {MONTHS_EL[when.month - 1]}"
        dest_dir.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(str(tmp_path), str(dest_dir / filename))
    except Exception:
        log.exception("failed to archive export copy to configured folder")
