"""Καθολική Αναίρεση / Επανάληψη (Windows). Φάση 1: μόνο ασφαλείς ενέργειες.
Κανόνες: ΜΙΑ ενέργεια κάθε φορά, μόνο δικές του του χρήστη, μέχρι 50 βήματα ανά χρήστη, όλα ατομικά (σε αποτυχία δεν αλλάζει τίποτα).
Τα κλεισίματα (φόρτωσης/παραλαβής/ΔΠΠ) καταγράφονται ως φραγμοί και ΔΕΝ αναιρούνται ποτέ από εδώ."""
import json
from datetime import datetime
from decimal import Decimal
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select, delete
from sqlalchemy.orm import Session
from .db import get_db
from . import models
from .models import ActionHistory, User
from .security import current_user
from .audit import write_audit

router = APIRouter()
MAX_STEPS = 50
NOTHING_MSG = "Δεν υπάρχει τίποτα που μπορεί να αναιρεθεί: έχουν μείνει μόνο κλεισίματα ή ενέργειες που άλλαξε άλλος χρήστης."
NOTHING_REDO_MSG = "Δεν υπάρχει τίποτα που μπορεί να επαναληφθεί: έχουν μείνει μόνο κλεισίματα ή ενέργειες που άλλαξε άλλος χρήστης."


def record(db: Session, user: User | None, kind: str, label: str, subjects, payload=None, undoable: bool = True):
    """Καταγραφή στην ΙΔΙΑ συναλλαγή με την ενέργεια (ή όλα ή τίποτα). Δεν κάνει commit."""
    if user is None:
        return
    if undoable:
        # νέα ενέργεια => σβήνει η «Επανάληψη» του χρήστη (όπως σε κάθε πρόγραμμα)
        db.execute(delete(ActionHistory).where(ActionHistory.user_id == user.id, ActionHistory.status == "UNDONE"))
    db.add(ActionHistory(user_id=user.id, username=user.username, kind=kind, label=label[:300],
                         subjects=json.dumps(sorted(set(subjects)), ensure_ascii=False),
                         payload=json.dumps(payload or {}, ensure_ascii=False, default=str), undoable=undoable, status="DONE"))
    db.flush()
    if undoable:   # όριο βημάτων: κρατάμε τα 50 πιο πρόσφατα αναιρέσιμα ανά χρήστη
        ids = db.scalars(select(ActionHistory.id).where(ActionHistory.user_id == user.id, ActionHistory.undoable == True).order_by(ActionHistory.id.desc())).all()  # noqa: E712
        old = ids[MAX_STEPS:]
        if old:
            db.execute(delete(ActionHistory).where(ActionHistory.id.in_(old)))


def _subj(e: ActionHistory) -> set:
    try:
        return set(json.loads(e.subjects or "[]"))
    except Exception:
        return set()


def _conflict(db: Session, e: ActionHistory, user: User):
    """Μη ασφαλές αν ΝΕΟΤΕΡΗ ενέργεια (κλείσιμο ή άλλου χρήστη) αγγίζει το ίδιο στοιχείο."""
    mine = _subj(e)
    for n in db.scalars(select(ActionHistory).where(ActionHistory.id > e.id, ActionHistory.status == "DONE")).all():
        if n.kind != "closing" and n.user_id == user.id:
            continue
        if mine & _subj(n):
            return "closing" if n.kind == "closing" else "other_user"
    return None


def _valid(db: Session, e: ActionHistory, redo: bool) -> bool:
    """Η τρέχουσα κατάσταση των δεδομένων πρέπει να είναι ακριβώς αυτή που περιμένει η αναίρεση/επανάληψη."""
    p = json.loads(e.payload or "{}")
    if e.kind == "rows":
        from . import history_rows as HR
        why = HR.check(db, p, redo)
        _WHY[e.id] = why
        return why is None
    if e.kind in ("mat_corr_add", "mat_corr_del"):
        exists = db.get(models.MaterialCorrectionEntry, p["id"]) is not None
        after = (e.kind == "mat_corr_add")      # μετά την ενέργεια η εγγραφή υπάρχει (add) ή όχι (del)
        return exists == (after if not redo else not after)
    if e.kind in ("receipt_delete", "receipt_cancel"):
        t = db.get(models.InboundTrip, p["id"])
        if not t:
            return False
        return (t.deleted_at is not None) if not redo else (t.deleted_at is None)
    return False


_WHY: dict = {}
_LAST_WHY: dict = {}


def _pick(db: Session, user: User, redo: bool):
    """Επιστρέφει (πρώτη εφαρμόσιμη ενέργεια ή None, υπάρχουν_υποψήφιες)."""
    st = "UNDONE" if redo else "DONE"
    q = select(ActionHistory).where(ActionHistory.user_id == user.id, ActionHistory.undoable == True, ActionHistory.status == st)  # noqa: E712
    # Αναίρεση: από την πιο πρόσφατη. Επανάληψη: από την πιο παλιά αναιρεμένη (η ενέργεια που αναιρέθηκε πιο πρόσφατα είναι η παλαιότερη των αναιρεμένων)
    rows = db.scalars(q.order_by(ActionHistory.id.desc() if not redo else ActionHistory.id.asc())).all()
    for e in rows:
        c = _conflict(db, e, user)
        if c is None and _valid(db, e, redo):
            return e, True
        _WHY[e.id] = _WHY.get(e.id) if c is None else ("Η αλλαγή αφορά κλεισμένα δεδομένα (φόρτωση/παραλαβή/ΔΠΠ) και δεν αναιρείται από εδώ." if c == "closing" else "Την ίδια εγγραφή την άλλαξε στο μεταξύ άλλος χρήστης.")
        _LAST_WHY[(user.id, redo)] = _WHY.get(e.id)
    return None, bool(rows)


def _state(db: Session, user: User):
    u, hu = _pick(db, user, False)
    r, hr = _pick(db, user, True)
    return {"can_undo": hu, "undo_label": (u.label if u else None), "undo_msg": ((NOTHING_MSG + " " + (_LAST_WHY.get((user.id, False)) or "")).strip() if (hu and not u) else None),
            "can_redo": hr, "redo_label": (r.label if r else None), "redo_msg": ((NOTHING_REDO_MSG + " " + (_LAST_WHY.get((user.id, True)) or "")).strip() if (hr and not r) else None)}


def _recreate_correction(db: Session, p: dict, user: User):
    obj = models.MaterialCorrectionEntry(id=p["id"], work_date=datetime.fromisoformat(p["work_date"]), material_label=p["material_label"],
                                         weight_kg_delta=Decimal(str(p["kg"])), piece_delta=int(p["pieces"]), reason=p.get("reason"), created_by_user_id=p.get("created_by"))
    db.add(obj); db.flush()
    write_audit(db, user, "material_correction", obj.id, "CREATE", new={"material": obj.material_label, "kg": str(obj.weight_kg_delta), "pieces": obj.piece_delta, "via": "undo/redo"})


def _delete_correction(db: Session, p: dict, user: User):
    obj = db.get(models.MaterialCorrectionEntry, p["id"])
    write_audit(db, user, "material_correction", obj.id, "DELETE", old={"material": obj.material_label, "kg": str(obj.weight_kg_delta), "pieces": obj.piece_delta, "via": "undo/redo"})
    db.delete(obj); db.flush()


def _run(db: Session, user: User, redo: bool):
    e, has = _pick(db, user, redo)
    if not e:
        if has:
            raise HTTPException(409, ((NOTHING_REDO_MSG if redo else NOTHING_MSG) + " " + (_LAST_WHY.get((user.id, redo)) or "")).strip())
        raise HTTPException(409, "Δεν υπάρχει τίποτα για επανάληψη." if redo else "Δεν υπάρχει τίποτα για αναίρεση.")
    p = json.loads(e.payload or "{}")
    if e.kind in ("mat_corr_add", "mat_corr_del"):
        make = (e.kind == "mat_corr_del") != redo      # undo(add)=διαγραφή · undo(del)=επαναδημιουργία · redo = αντίστροφα
        (_recreate_correction if make else _delete_correction)(db, p, user)
        e.status = "DONE" if redo else "UNDONE"
        db.commit()
    elif e.kind == "rows":
        from . import history_rows as HR
        HR.apply(db, p, redo)
        e.status = "DONE" if redo else "UNDONE"
        db.commit()
    elif e.kind == "receipt_delete":
        from . import main as M
        e.status = "DONE" if redo else "UNDONE"
        db.flush()
        # οι συναρτήσεις του server κάνουν δικό τους commit -> μαζί και η αλλαγή κατάστασης του ιστορικού (ατομικά)
        (M.delete_receipt if redo else M.restore_receipt)(p["id"], db, user)
    elif e.kind == "receipt_cancel":
        from . import main as M
        e.status = "DONE" if redo else "UNDONE"
        db.flush()
        if redo: M.cancel_receipt(p["id"], M.ReceiptCancelIn(reason=p.get("reason") or "—"), db, user)
        else: M.restore_receipt(p["id"], db, user)
    return e


@router.get("/history/state")
def history_state(db: Session = Depends(get_db), user: User = Depends(current_user)):
    return _state(db, user)


def _do(redo: bool, db: Session, user: User):
    try:
        e = _run(db, user, redo)
    except HTTPException:
        db.rollback()
        raise
    except Exception as ex:
        db.rollback()
        raise HTTPException(500, "Η ενέργεια δεν ολοκληρώθηκε και δεν άλλαξε τίποτα: " + str(ex)[:200])
    return {"ok": True, "message": ("Επαναλήφθηκε: " if redo else "Αναιρέθηκε: ") + e.label, "state": _state(db, user)}


@router.post("/history/undo")
def history_undo(db: Session = Depends(get_db), user: User = Depends(current_user)):
    return _do(False, db, user)


@router.post("/history/redo")
def history_redo(db: Session = Depends(get_db), user: User = Depends(current_user)):
    return _do(True, db, user)
