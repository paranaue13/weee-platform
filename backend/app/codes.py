"""Κοινός μετρητής κωδικών μέσων: ΕΝΑΣ μετρητής ανά (έτος, κωδικός 3 χαρακτήρων) για όλες τις πηγές
(κωδικοί τύπων, κωδικοί περιεχομένου, Φόρμα Ταξινόμησης, Αποθήκη υλικών). Δεν μειώνεται ποτέ· μοναδικότητα από τη βάση."""
from datetime import datetime
from sqlalchemy import select, text
from sqlalchemy.orm import Session
from . import models


def next_code_for(db: Session, code3: str, year: int | None = None) -> str:
    """Ατομική αύξηση του μετρητή: το UPDATE παίρνει το κλείδωμα εγγραφής της βάσης, άρα ταυτόχρονες αιτήσεις περιμένουν η μία την άλλη
    και ποτέ δεν παίρνουν τον ίδιο αριθμό. Η μοναδικότητα του κωδικού επιβάλλεται επιπλέον από το ευρετήριο της βάσης."""
    year = year or datetime.now().year
    yy = year % 100
    p = {"y": year, "c": code3}
    db.execute(text("INSERT INTO code_counters (year, code, last_no) VALUES (:y, :c, 0) ON CONFLICT (year, code) DO NOTHING"), p)
    while True:
        db.execute(text("UPDATE code_counters SET last_no = last_no + 1 WHERE year = :y AND code = :c"), p)
        n = int(db.execute(text("SELECT last_no FROM code_counters WHERE year = :y AND code = :c"), p).scalar())
        c = f"{yy:02d}-{code3}-{n:04d}"
        if not db.scalar(select(models.CollectionMedium.id).where(models.CollectionMedium.code == c)):
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
