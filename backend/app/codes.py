"""Κοινός μετρητής κωδικών μέσων: ΕΝΑΣ μετρητής ανά (έτος, κωδικός 3 χαρακτήρων) για όλες τις πηγές
(κωδικοί τύπων, κωδικοί περιεχομένου, Φόρμα Ταξινόμησης, Αποθήκη υλικών). Δεν μειώνεται ποτέ· μοναδικότητα από τη βάση."""
from datetime import datetime
from sqlalchemy import select
from sqlalchemy.orm import Session
from . import models


def next_code_for(db: Session, code3: str, year: int | None = None) -> str:
    year = year or datetime.now().year
    yy = year % 100
    row = db.get(models.CodeCounter, (year, code3))
    if not row:
        row = models.CodeCounter(year=year, code=code3, last_no=0)
        db.add(row); db.flush()
    while True:
        row.last_no = int(row.last_no or 0) + 1
        c = f"{yy:02d}-{code3}-{row.last_no:04d}"
        if not db.scalar(select(models.CollectionMedium.id).where(models.CollectionMedium.code == c)):
            break
    db.flush()
    return c


def preview_code_for(db: Session, code3: str, year: int | None = None) -> str:
    """Ο επόμενος κωδικός χωρίς δέσμευση (προεπισκόπηση)."""
    year = year or datetime.now().year
    yy = year % 100
    row = db.get(models.CodeCounter, (year, code3))
    n = int(row.last_no or 0) if row else 0
    while True:
        n += 1
        c = f"{yy:02d}-{code3}-{n:04d}"
        if not db.scalar(select(models.CollectionMedium.id).where(models.CollectionMedium.code == c)):
            return c
