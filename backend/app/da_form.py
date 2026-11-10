"""Φόρμα ολοκληρωμένης φόρτωσης (Δ.Α.) και ακύρωση φόρτωσης (K3/K4).

Ένα Δ.Α. = όλες οι γραμμές του Ιστορικού Δελτίων Αποστολής με τον ίδιο αριθμό και έτος. Αλλάζουν όλα εκτός από τον αριθμό.
Ό,τι αλλάζει γράφεται σε ΟΛΕΣ τις γραμμές του Δ.Α. (και στη φόρτωση, όταν το δελτίο προήλθε από φόρτωση της εφαρμογής).
Ποτέ αποστολή στο Galaxy. Οι αλλαγές καταγράφονται στο Αναίρεση/Επανάληψη μέσω του γενικού «ιστορικού γραμμών» (history_rows)."""
from datetime import datetime
from decimal import Decimal
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select, or_
from sqlalchemy.orm import Session
from .db import get_db
from . import models
from .models import (Organization, LoadingOrder, LoadingActual, LoadingBulkItem, ReadyMaterialLot, ReadyMaterialMovement, MaterialShipmentEntry,
                     ShipmentHistoryEntry as H, SyncEvent, User, Material, organization_roles)
from .security import require_permission
from .audit import write_audit

router = APIRouter(tags=["da-form"])

TEXT_FIELDS = ("customer_address", "vehicle_registration", "weighbridge_number", "container_number", "dispatch_reason", "destination_country",
               "mgmt_operation", "tracking_document", "gr_notification_no", "bill_of_lading", "notes")
GALAXY_NOTE = "Η αλλαγή δεν στάλθηκε στο Galaxy"


class DaEditIn(BaseModel):
    date: str | None = None
    carrier: str | None = None
    customer: str | None = None
    customer_address: str | None = None
    vehicle_registration: str | None = None
    weighbridge_number: str | None = None
    container_number: str | None = None
    dispatch_reason: str | None = None
    destination_country: str | None = None
    mgmt_operation: str | None = None
    tracking_document: str | None = None
    gr_notification_no: str | None = None
    bill_of_lading: str | None = None
    notes: str | None = None
    max_weight: Decimal | None = None
    confirm_date_change: bool = False


class DaCancelIn(BaseModel):
    reason: str


def _orgname(o):
    return (o.trade_name or o.legal_name) if o else None


def _rows(db: Session, year: int, da: str, cancelled=None):
    q = select(H).where(H.da_number == da, H.work_date >= datetime(year, 1, 1), H.work_date < datetime(year + 1, 1, 1))
    rows = db.scalars(q.order_by(H.created_at, H.id)).all()
    if cancelled is None:
        return rows
    return [r for r in rows if (r.cancelled_at is not None) == cancelled]


def _order(db: Session, year: int, da: str):
    for o in db.scalars(select(LoadingOrder).where(LoadingOrder.dispatch_document_number == da, LoadingOrder.status.in_(["COMPLETED", "CANCELLED"]))).all():
        try:
            y = int((o.delivery_date or "")[:4]) if o.delivery_date else o.created_at.year
        except Exception:
            y = o.created_at.year
        if y == year:
            return o
    return None


def _galaxy_sent(db: Session, o) -> bool:
    if not o:
        return False
    return db.scalar(select(SyncEvent.id).where(SyncEvent.system == "GALAXY", SyncEvent.entity_type == "LOADING_ORDER", SyncEvent.entity_id == o.id, SyncEvent.status == "SYNCED").limit(1)) is not None


def _find(db: Session, year: int, da: str):
    rows = _rows(db, year, da)
    if not rows:
        raise HTTPException(404, "Δεν βρέθηκε Δ.Α. " + da)
    return rows


def _detail(db: Session, year: int, da: str) -> dict:
    rows = _find(db, year, da)
    o = _order(db, year, da)
    f = rows[0]
    cancelled = f.cancelled_at is not None
    sent = _galaxy_sent(db, o)

    def pick(name, order_attr=None):
        for r in rows:
            v = getattr(r, name)
            if v not in (None, ""):
                return v
        return getattr(o, order_attr or name, None) if o else None
    kind_purpose = "Ενδοδιακίνηση" if f.kind == "WEEE_TO_UNIT" else "Πώληση"
    reason = pick("dispatch_reason") or (kind_purpose if f.source != "LOADING" else "")
    total = sum((r.weight_kg or Decimal("0")) for r in rows)
    block = None
    if cancelled:
        block = "Η φόρτωση έχει ήδη ακυρωθεί."
    elif o is None:
        block = "Δελτίο από το ιστορικό αρχείο Excel: δεν έχει κινήσεις αποθήκης και δεν ακυρώνεται από εδώ."
    elif sent:
        block = "Το Δ.Α. έχει σταλεί στο Galaxy: η ακύρωση δεν επιτρέπεται."
    return {
        "da_number": da, "year": year, "date": f.work_date.date().isoformat(), "carrier": f.transporter, "customer": f.recipient,
        "customer_address": pick("customer_address"), "vehicle_registration": pick("vehicle_registration"), "weighbridge_number": pick("weighbridge_number"),
        "container_number": pick("container_number"), "dispatch_reason": reason, "destination_country": pick("destination_country"),
        "mgmt_operation": pick("mgmt_operation"), "tracking_document": pick("tracking_document"), "gr_notification_no": pick("gr_notification_no"),
        "bill_of_lading": pick("bill_of_lading"), "notes": pick("notes"),
        "weight_kg": float(total), "max_weight": (float(o.max_allowed_weight) if o else None),
        "status": "CANCELLED" if cancelled else "COMPLETED", "cancel_reason": f.cancel_reason, "cancelled_at": (f.cancelled_at.isoformat() if f.cancelled_at else None),
        "galaxy_sent": sent, "galaxy_label": "Galaxy: στάλθηκε" if sent else "Galaxy: δεν στάλθηκε",
        "source": "LOADING" if o else "HISTORICAL", "loading_order_id": o.id if o else None, "loading_number": o.loading_number if o else None,
        "lines": [{"id": r.id, "description": r.description, "weight_kg": float(r.weight_kg or 0), "eka_code": r.eka_code, "reptool_code": r.reptool_code} for r in rows],
        "lines_editable": False, "can_cancel": block is None, "cancel_block": block,
    }


@router.get("/loading/da/{year}/{da}")
def da_detail(year: int, da: str, db: Session = Depends(get_db), user=Depends(require_permission("loading.view"))):
    return _detail(db, year, da)


def _org_by_name(db: Session, name: str, role: str):
    k = (name or "").strip().casefold()
    for og in db.scalars(select(Organization).join(organization_roles, organization_roles.c.organization_id == Organization.id).where(organization_roles.c.role == role)).all():
        if k in {(og.trade_name or "").strip().casefold(), (og.legal_name or "").strip().casefold()}:
            return og
    return None


@router.put("/loading/da/{year}/{da}")
def da_edit(year: int, da: str, data: DaEditIn, db: Session = Depends(get_db), user: User = Depends(require_permission("loading.execute"))):
    rows = _rows(db, year, da)
    if not rows:
        raise HTTPException(404, "Δεν βρέθηκε Δ.Α. " + da)
    if rows[0].cancelled_at is not None:
        raise HTTPException(409, "Το ακυρωμένο δελτίο δεν αλλάζει.")
    o = _order(db, year, da)
    sent = set(data.model_fields_set)
    old = _detail(db, year, da)
    clean = lambda v: ((v or "").strip() or None)
    # ---- ημερομηνία: το έτος δεν αλλάζει (ο αριθμός Δ.Α. είναι ανά έτος)· αλλαγή μόνο με ρητή επιβεβαίωση ----
    new_dt = None
    if "date" in sent and data.date:
        try:
            nd = datetime.fromisoformat(data.date[:10])
        except Exception:
            raise HTTPException(422, "Μη έγκυρη ημερομηνία")
        if nd.year != year:
            raise HTTPException(422, "Η αλλαγή έτους δεν επιτρέπεται: ο αριθμός Δ.Α. ισχύει ανά έτος.")
        if nd.date().isoformat() != old["date"]:
            if not data.confirm_date_change:
                raise HTTPException(409, "Η αλλαγή ημερομηνίας χρειάζεται επιβεβαίωση.")
            new_dt = nd
    # ---- έλεγχοι για φόρτωση της εφαρμογής ----
    cust_org = car_org = None
    if o is not None:
        if "customer" in sent and clean(data.customer):
            cust_org = _org_by_name(db, data.customer, "CLIENT")
            if not cust_org:
                raise HTTPException(422, "Ο πελάτης δεν υπάρχει στο μητρώο πελατών")
        elif "customer" in sent:
            raise HTTPException(422, "Ο πελάτης είναι υποχρεωτικός")
        if "carrier" in sent and clean(data.carrier):
            car_org = _org_by_name(db, data.carrier, "CARRIER")
            if not car_org:
                raise HTTPException(422, "Ο μεταφορέας δεν υπάρχει στο μητρώο μεταφορέων")
        if "max_weight" in sent and data.max_weight is not None:
            loaded = sum((r.weight_kg or Decimal("0")) for r in rows)
            if data.max_weight <= 0:
                raise HTTPException(422, "Το βάρος πρέπει να είναι θετικό")
            if data.max_weight < loaded:
                raise HTTPException(422, "Το βάρος δεν μπορεί να είναι μικρότερο από τα φορτωμένα κιλά (%s kg)" % loaded)
    # ---- εφαρμογή ----
    for r in rows:
        if new_dt is not None:
            r.work_date = new_dt.replace(hour=r.work_date.hour, minute=r.work_date.minute, second=r.work_date.second, microsecond=r.work_date.microsecond)
        if "carrier" in sent:
            r.transporter = _orgname(car_org) if car_org else clean(data.carrier)
        if "customer" in sent:
            r.recipient = _orgname(cust_org) if cust_org else clean(data.customer)
        for f in TEXT_FIELDS:
            if f in sent:
                setattr(r, f, clean(getattr(data, f)))
    if o is not None:
        if new_dt is not None:
            o.delivery_date = new_dt.date().isoformat()
            for e in db.scalars(select(MaterialShipmentEntry).where(MaterialShipmentEntry.source == "LOADING", MaterialShipmentEntry.notes == "LOADING:" + o.id)).all():
                e.work_date = new_dt.replace(hour=e.work_date.hour, minute=e.work_date.minute, second=e.work_date.second, microsecond=e.work_date.microsecond)
        if cust_org:
            o.customer_id = cust_org.id
        if "carrier" in sent:
            o.carrier_id = car_org.id if car_org else None
        for f in TEXT_FIELDS:
            if f in sent and hasattr(o, f):
                setattr(o, f, clean(getattr(data, f)))
        if "max_weight" in sent and data.max_weight is not None:
            o.max_allowed_weight = data.max_weight
    db.flush()
    new = _detail(db, year, da)
    ch = {k: [old.get(k), new.get(k)] for k in new if k not in ("lines", "cancel_block", "can_cancel") and old.get(k) != new.get(k)}
    write_audit(db, user, "shipment_da", da, "EDIT_DA_FORM", old={k: v[0] for k, v in ch.items()}, new={k: v[1] for k, v in ch.items()}, reason="year=%s" % year)
    db.info["hist_label"] = "Αλλαγή στοιχείων Δ.Α. " + da
    db.commit()
    out = _detail(db, year, da)
    out["note"] = GALAXY_NOTE
    out["changed"] = sorted(ch)
    return out


# ---------- ακύρωση φόρτωσης ----------
def _cancel_plan(db: Session, o: LoadingOrder):
    """Τι επιστρέφει στα αποθέματα: χύμα κιλά (ανά ετικέτα) και παρτίδες υλικών (ανά υλικό), με πριν/μετά."""
    from . import main as M
    out = []
    bal = M._bulk_balances(db)
    for b in db.scalars(select(LoadingBulkItem).where(LoadingBulkItem.loading_order_id == o.id).order_by(LoadingBulkItem.material_label)).all():
        before = float(bal.get(b.material_label, {"kg": Decimal("0")})["kg"])
        out.append({"material": b.material_label, "kg": float(b.weight_kg), "before": before, "after": before + float(b.weight_kg), "kind": "χύμα"})
    per = {}
    for a in db.scalars(select(LoadingActual).where(LoadingActual.loading_order_id == o.id)).all():
        lot = db.get(ReadyMaterialLot, a.ready_material_lot_id)
        mat = db.get(Material, lot.material_id) if lot else None
        key = (mat.id if mat else (lot.id if lot else a.id))
        d = per.setdefault(key, {"material": ((mat.her_description or mat.official_description or mat.internal_name) if mat else "Υλικό"), "kg": 0.0, "mat": mat.id if mat else None})
        d["kg"] += float(a.loaded_weight)
    for d in per.values():
        before = 0.0
        if d["mat"]:
            before = float(sum((l.net_weight for l in db.scalars(select(ReadyMaterialLot).where(ReadyMaterialLot.material_id == d["mat"], ReadyMaterialLot.status == "AVAILABLE")).all()), Decimal("0")))
        out.append({"material": d["material"], "kg": d["kg"], "before": before, "after": before + d["kg"], "kind": "παρτίδες"})
    return out


@router.get("/loading/da/{year}/{da}/cancel-preview")
def da_cancel_preview(year: int, da: str, db: Session = Depends(get_db), user=Depends(require_permission("loading.view"))):
    d = _detail(db, year, da)
    o = _order(db, year, da)
    return {"can_cancel": d["can_cancel"], "block": d["cancel_block"], "da_number": da, "weight_kg": d["weight_kg"], "items": _cancel_plan(db, o) if o else []}


@router.post("/loading/da/{year}/{da}/cancel")
def da_cancel(year: int, da: str, data: DaCancelIn, db: Session = Depends(get_db), user: User = Depends(require_permission("loading.execute"))):
    from . import main as M
    reason = (data.reason or "").strip()
    if not reason:
        raise HTTPException(422, "Ο λόγος ακύρωσης είναι υποχρεωτικός")
    d = _detail(db, year, da)
    if not d["can_cancel"]:
        raise HTTPException(409, d["cancel_block"])
    o = _order(db, year, da)
    rows = _rows(db, year, da, cancelled=False)
    now = datetime.now()
    plan = _cancel_plan(db, o)
    # παρτίδες υλικών: ό,τι είχε φορτωθεί επιστρέφει στη διαθέσιμη ποσότητα
    for a in db.scalars(select(LoadingActual).where(LoadingActual.loading_order_id == o.id)).all():
        lot = db.get(ReadyMaterialLot, a.ready_material_lot_id)
        if not lot:
            continue
        if lot.status == "DISPATCHED":
            lot.status = "AVAILABLE"
        else:
            lot.net_weight = lot.net_weight + a.loaded_weight
            lot.status = "AVAILABLE"
        db.add(ReadyMaterialMovement(lot_id=lot.id, movement_type="DISPATCH_CANCEL", weight=a.loaded_weight, user_id=user.id, reason=(o.loading_number or "") + " ακύρωση Δ.Α. " + da))
    M._release_bulk(db, o)            # χύμα κιλά: οι εγγραφές αποστολής της φόρτωσης γίνονται ανενεργές
    o.status = "CANCELLED"; o.cancelled_at = now; o.cancel_reason = reason; o.cancelled_by = user.id
    for r in rows:
        r.active = False; r.cancelled_at = now; r.cancel_reason = reason; r.cancelled_by = user.id
    db.flush()
    write_audit(db, user, "loading_order", o.id, "CANCEL_DA", old={"status": "COMPLETED", "da": da}, new={"status": "CANCELLED", "items": plan}, reason=reason)
    db.info["hist_label"] = ("Ακύρωση φόρτωσης Δ.Α. " + da + " · " + reason)[:290]
    db.commit()
    out = _detail(db, year, da)
    out["note"] = "Η φόρτωση ακυρώθηκε. Δεν στάλθηκε στο Galaxy."
    return out
