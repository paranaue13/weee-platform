"""Android → ΥΛΙΚΑ: Εξαγωγή / Αποθήκη / Απογραφή υλικών.

Κάθε εξαγωγή = ένα ReadyMaterialLot (ίδιο σύστημα με την «+ Εξαγωγή υλικών» των Windows), κάθε ζύγιση απογραφής = μία
MaterialInventoryEntry. Η απογραφή ΔΕΝ προσμετράται ποτέ στα «διαθέσιμα προς αποστολή».

DEMO: με επικεφαλίδα X-Demo: 1 οι εγγραφές δημιουργούνται με ετικέτα DEMO (is_demo, status «DEMO», κωδικοί «DEMO-P-/DEMO-S-»,
ξεχωριστή αρίθμηση) και ΔΕΝ μπαίνουν σε πραγματικά ισοζύγια/λίστες (εκτός αν ζητηθούν ρητά με X-Demo: 1). Σβήνονται με
backend/scripts/demo_data.py delete.
"""
from datetime import datetime, timezone
from decimal import Decimal
from fastapi import APIRouter, Depends, HTTPException, Header, Query
from pydantic import BaseModel
from sqlalchemy import select, func
from sqlalchemy.orm import Session
from .db import get_db
from .security import require_permission
from . import models
from .models import (Material, StorageGroup, CollectionMedium, CollectionMediumType, ReadyMaterialLot, ReadyMaterialMovement,
                     MaterialInventoryEntry, MaterialOutputEntry, MaterialShipmentEntry, MaterialCorrectionEntry, InventoryLocation, AppSetting, User)
from .audit import write_audit

router = APIRouter(prefix="/mat", tags=["materials-warehouse"])

FORMS = {"PALLET": "PALLET", "SACK_1KG": "SACK_1KG", "SACK_2KG": "SACK_2KG_UN", "BULK": None}   # φόρμα -> κωδικός τύπου μέσου
FORM_LABELS = {"PALLET": "Παλέτα", "SACK_1KG": "Σάκος 1 kg", "SACK_2KG": "Σάκος 2 kg", "BULK": "Χύμα"}
MONTHS = ["Ιανουάριος", "Φεβρουάριος", "Μάρτιος", "Απρίλιος", "Μάιος", "Ιούνιος", "Ιούλιος", "Αύγουστος", "Σεπτέμβριος", "Οκτώβριος", "Νοέμβριος", "Δεκέμβριος"]
QUARTER_MONTH = {1: 3, 2: 6, 3: 9, 4: 12}


def is_demo(x_demo: str | None) -> bool:
    return (x_demo or "").strip() in ("1", "true", "yes")


def _norm(s) -> str:
    return " ".join(str(s or "").strip().upper().split())


def _period(now: datetime | None = None):
    n = now or datetime.now()
    return n.year, (n.month - 1) // 3 + 1, n.month


def next_medium_code(db: Session, form: str, demo: bool) -> str:
    """Μοναδικός κωδικός μέσου μιας χρήσης: P-000231 (παλέτα) / S-000187 (σάκος 1 και 2 kg). Η αρίθμηση δεν επαναχρησιμοποιείται·
    τα DEMO έχουν ξεχωριστό πρόθεμα και δική τους αρίθμηση ώστε να μη «χάνονται» αριθμοί των πραγματικών."""
    kind = "P" if form == "PALLET" else "S"
    prefix = ("DEMO-" if demo else "") + kind
    key = f"matmedium.seq.{prefix}"
    row = db.scalar(select(AppSetting).where(AppSetting.key == key).with_for_update())
    if not row:
        row = AppSetting(key=key, value="0"); db.add(row); db.flush()
    n = int(row.value or 0)
    while True:
        n += 1
        code = f"{prefix}-{n:06d}"
        if not db.scalar(select(CollectionMedium.id).where(CollectionMedium.code == code)):
            break
    row.value = str(n)
    return code


def _types(db: Session) -> dict:
    return {t.code: t for t in db.scalars(select(CollectionMediumType)).all()}


def _tare_for(db: Session, form: str, tare) -> Decimal | None:
    if form == "BULK":
        return None
    if form == "PALLET":
        if tare is None:
            raise HTTPException(422, "Βάλε απόβαρο παλέτας")
        t = Decimal(str(tare))
        if t < 0:
            raise HTTPException(422, "Το απόβαρο δεν μπορεί να είναι αρνητικό")
        return t
    t = _types(db).get(FORMS[form])
    if not t or t.default_tare_weight is None:
        raise HTTPException(422, "Λείπει το σταθερό απόβαρο του σάκου από το Μητρώο μέσων συλλογής")
    return Decimal(str(t.default_tare_weight))


def _location(db: Session):
    loc = db.scalar(select(InventoryLocation).where(InventoryLocation.code == "READY_MAIN"))
    if not loc:
        loc = InventoryLocation(code="READY_MAIN", name_el="Αποθήκη Υλικών προς Φόρτωση", domain="READY_MATERIAL"); db.add(loc); db.flush()
    return loc


def _net(form: str, gross, tare, net):
    if form == "BULK":
        if net is None or Decimal(str(net)) <= 0:
            raise HTTPException(422, "Βάλε κιλά μεγαλύτερα από 0")
        return Decimal(str(net))
    if gross is None:
        raise HTTPException(422, "Βάλε μικτό βάρος")
    n = Decimal(str(gross)) - tare
    if n <= 0:
        raise HTTPException(422, "Τα καθαρά κιλά πρέπει να είναι μεγαλύτερα από 0")
    return n


def _new_medium(db: Session, form: str, tare, demo: bool, status: str):
    if form == "BULK":
        return None
    t = _types(db)[FORMS[form]]
    m = CollectionMedium(type_id=t.id, code=next_medium_code(db, form, demo), tare_weight=tare, status=status, active=True)
    db.add(m); db.flush()
    return m


def _lot_number(db: Session, mat: Material, demo: bool) -> str:
    year = datetime.now().year
    prefix = "".join(ch for ch in (mat.internal_code or "") if ch.isalnum())[:12] or "MAT"
    base = f"{'DEMO-' if demo else ''}RM-{prefix}-{year}-"
    n = db.scalar(select(func.count()).select_from(ReadyMaterialLot).where(ReadyMaterialLot.lot_number.like(base + "%"))) or 0
    while True:
        n += 1
        num = f"{base}{n:06d}"
        if not db.scalar(select(ReadyMaterialLot.id).where(ReadyMaterialLot.lot_number == num)):
            return num


def _ledger_balance(db: Session) -> dict:
    """Τρέχον απόθεμα ανά ετικέτα υλικού (όπως στα Windows): παραγωγή − αποστολές + διορθώσεις."""
    bal: dict = {}
    for lb, w in db.execute(select(MaterialOutputEntry.material_label, func.sum(MaterialOutputEntry.weight_kg)).where(MaterialOutputEntry.active == True).group_by(MaterialOutputEntry.material_label)).all():
        bal[_norm(lb)] = bal.get(_norm(lb), 0.0) + float(w or 0)
    for lb, w in db.execute(select(MaterialShipmentEntry.material_label, func.sum(MaterialShipmentEntry.weight_kg)).where(MaterialShipmentEntry.active == True).group_by(MaterialShipmentEntry.material_label)).all():
        bal[_norm(lb)] = bal.get(_norm(lb), 0.0) - float(w or 0)
    for lb, w in db.execute(select(MaterialCorrectionEntry.material_label, func.sum(MaterialCorrectionEntry.weight_kg_delta)).group_by(MaterialCorrectionEntry.material_label)).all():
        bal[_norm(lb)] = bal.get(_norm(lb), 0.0) + float(w or 0)
    return bal


def _exported_counted(db: Session) -> dict:
    """Κιλά που ήδη εξήχθησαν από την Android (πραγματικά, όχι DEMO) ανά υλικό."""
    rows = db.execute(select(ReadyMaterialLot.material_id, func.sum(func.coalesce(ReadyMaterialLot.counted_kg, ReadyMaterialLot.net_weight)))
                      .where(ReadyMaterialLot.entry_type == "EXPORT", ReadyMaterialLot.is_demo == False, ReadyMaterialLot.status != "CANCELLED").group_by(ReadyMaterialLot.material_id)).all()
    return {m: float(w or 0) for m, w in rows}


def available_by_material(db: Session, materials) -> dict:
    bal = _ledger_balance(db); exp = _exported_counted(db); out = {}
    for m in materials:
        key = _norm(m.official_description or m.internal_name)
        b = bal.get(key)
        if b is None:
            b = bal.get(_norm(m.internal_name), bal.get(_norm(m.galaxy_description), 0.0))
        out[m.id] = round(max(0.0, b - exp.get(m.id, 0.0)), 3)
    return out


class ExportIn(BaseModel):
    material_id: str
    form: str
    gross: Decimal | None = None
    tare: Decimal | None = None
    net: Decimal | None = None            # Χύμα
    inventory_id: str | None = None       # εξαγωγή από μέσο απογραφής
    new_total: Decimal | None = None      # νέο συνολικό βάρος του μέσου απογραφής (φυσικό)


class InventoryIn(BaseModel):
    material_id: str
    form: str
    gross: Decimal | None = None
    tare: Decimal | None = None
    net: Decimal | None = None


def _material(db: Session, mid: str) -> Material:
    mat = db.get(Material, mid)
    if not mat or not mat.active:
        raise HTTPException(422, "Άγνωστο ή ανενεργό υλικό")
    return mat


@router.get("/catalog")
def catalog(db: Session = Depends(get_db), user=Depends(require_permission("production.view"))):
    cats = db.scalars(select(StorageGroup).where(StorageGroup.active == True).order_by(StorageGroup.sort_order, StorageGroup.name)).all()
    mats = db.scalars(select(Material).where(Material.active == True).order_by(Material.internal_name)).all()
    avail = available_by_material(db, mats)
    types = _types(db)
    forms = []
    for f in ("PALLET", "SACK_1KG", "SACK_2KG", "BULK"):
        t = types.get(FORMS[f]) if FORMS[f] else None
        forms.append({"form": f, "label": FORM_LABELS[f], "tare": float(t.default_tare_weight) if (t and t.default_tare_weight is not None) else None,
                      "asks_tare": f == "PALLET", "has_code": f != "BULK"})
    y, q, m = _period()
    return {"categories": [{"id": c.id, "name": c.name, "count": sum(1 for x in mats if x.storage_group_id == c.id)} for c in cats],
            "materials": [{"id": x.id, "name": x.official_description or x.internal_name, "code": x.galaxy_code, "category_id": x.storage_group_id, "available_kg": avail.get(x.id, 0.0)} for x in mats],
            "forms": forms, "period": {"year": y, "quarter": q, "month": m, "month_name": MONTHS[m - 1], "quarter_month_name": MONTHS[QUARTER_MONTH[q] - 1]}}


@router.get("/next-code")
def next_code_preview(form: str, db: Session = Depends(get_db), user=Depends(require_permission("production.view")), x_demo: str | None = Header(default=None)):
    """Ο κωδικός που θα δοθεί στο επόμενο μέσο μιας χρήσης (προεπισκόπηση, δεν δεσμεύεται)."""
    if form not in ("PALLET", "SACK_1KG", "SACK_2KG"):
        return {"code": None}
    prefix = ("DEMO-" if is_demo(x_demo) else "") + ("P" if form == "PALLET" else "S")
    row = db.scalar(select(AppSetting).where(AppSetting.key == f"matmedium.seq.{prefix}"))
    n = int(row.value or 0) if row else 0
    while True:
        n += 1
        code = f"{prefix}-{n:06d}"
        if not db.scalar(select(CollectionMedium.id).where(CollectionMedium.code == code)):
            return {"code": code}


@router.post("/export")
def export_material(data: ExportIn, db: Session = Depends(get_db), user: User = Depends(require_permission("production.move")), x_demo: str | None = Header(default=None)):
    demo = is_demo(x_demo)
    if data.form not in FORMS:
        raise HTTPException(422, "Άγνωστο μέσο αποθήκευσης")
    mat = _material(db, data.material_id)
    y, q, mo = _period()
    inv = None
    if data.inventory_id:
        inv = db.get(MaterialInventoryEntry, data.inventory_id)
        if not inv or inv.status != "COUNTED" or inv.material_id != mat.id:
            raise HTTPException(409, "Το μέσο της απογραφής δεν είναι διαθέσιμο για εξαγωγή")
        if data.new_total is None or Decimal(str(data.new_total)) <= 0:
            raise HTTPException(422, "Βάλε το νέο συνολικό βάρος του μέσου")
        total = Decimal(str(data.new_total))
        counted = total - Decimal(str(inv.net_weight))
        if counted < 0:
            raise HTTPException(422, "Το νέο συνολικό βάρος δεν μπορεί να είναι μικρότερο από της απογραφής")
        medium = db.get(CollectionMedium, inv.collection_medium_id) if inv.collection_medium_id else None
        form, tare, gross, net = inv.form, inv.tare_weight, None, total
        demo = bool(inv.is_demo)
    else:
        form = data.form
        tare = _tare_for(db, form, data.tare)
        net = _net(form, data.gross, tare, data.net)
        gross = data.gross if form != "BULK" else None
        counted = net
        medium = _new_medium(db, form, tare, demo, "READY_STORAGE")
    lot = ReadyMaterialLot(lot_number=_lot_number(db, mat, demo), material_id=mat.id, output_form=("CONTAINER" if medium else "BULK"),
                           collection_medium_id=medium.id if medium else None, gross_weight=gross, tare_weight=tare, net_weight=net,
                           location_id=_location(db).id, status=("DEMO" if demo else "AVAILABLE"), created_by=user.id,
                           notes=("DEMO" if demo else None), entry_type="EXPORT", period_year=y, period_quarter=q, period_month=mo,
                           counted_kg=counted, storage_group_id=mat.storage_group_id, source_inventory_id=inv.id if inv else None, is_demo=demo)
    db.add(lot); db.flush()
    db.add(ReadyMaterialMovement(lot_id=lot.id, movement_type="PRODUCTION_OUT", weight=net, user_id=user.id, reason=("DEMO" if demo else "Εξαγωγή από Android")))
    if medium:
        medium.status = "READY_STORAGE"
    if inv:
        inv.status = "EXPORTED"; inv.exported_lot_id = lot.id
    write_audit(db, user, "ready_material_lot", lot.id, "CREATE", new={"lot_number": lot.lot_number, "material": mat.internal_code, "net": str(net), "counted": str(counted), "form": form, "demo": demo})
    db.commit()
    return {"id": lot.id, "lot_number": lot.lot_number, "form": form, "medium_code": medium.code if medium else None, "net": float(net), "counted_kg": float(counted)}


@router.post("/inventory")
def add_inventory(data: InventoryIn, db: Session = Depends(get_db), user: User = Depends(require_permission("production.move")), x_demo: str | None = Header(default=None)):
    demo = is_demo(x_demo)
    if data.form not in FORMS:
        raise HTTPException(422, "Άγνωστο μέσο αποθήκευσης")
    mat = _material(db, data.material_id)
    tare = _tare_for(db, data.form, data.tare)
    net = _net(data.form, data.gross, tare, data.net)
    y, q, mo = _period()
    medium = _new_medium(db, data.form, tare, demo, "INVENTORY")
    e = MaterialInventoryEntry(material_id=mat.id, storage_group_id=mat.storage_group_id, collection_medium_id=medium.id if medium else None, form=data.form,
                               gross_weight=data.gross if data.form != "BULK" else None, tare_weight=tare, net_weight=net, year=y, quarter=q, month=mo,
                               status="COUNTED", is_demo=demo, created_by=user.id)
    db.add(e); db.flush()
    write_audit(db, user, "material_inventory", e.id, "CREATE", new={"material": mat.internal_code, "form": data.form, "net": str(net), "code": medium.code if medium else None, "demo": demo})
    db.commit()
    return {"id": e.id, "form": data.form, "medium_code": medium.code if medium else None, "net": float(net)}


def _inv_rows(db: Session, demo: bool, **flt):
    q = select(MaterialInventoryEntry)
    for k, v in flt.items():
        q = q.where(getattr(MaterialInventoryEntry, k) == v)
    q = q.where(MaterialInventoryEntry.is_demo == True) if demo else q.where(MaterialInventoryEntry.is_demo == False)
    return db.scalars(q.order_by(MaterialInventoryEntry.created_at)).all()


@router.get("/inventory")
def list_inventory(year: int | None = None, quarter: int | None = None, db: Session = Depends(get_db), user=Depends(require_permission("production.view")), x_demo: str | None = Header(default=None)):
    y, q, _ = _period()
    year, quarter = year or y, quarter or q
    rows = _inv_rows(db, False, year=year, quarter=quarter) + (_inv_rows(db, True, year=year, quarter=quarter) if is_demo(x_demo) else [])
    media = {m.id: m for m in db.scalars(select(CollectionMedium).where(CollectionMedium.id.in_([r.collection_medium_id for r in rows if r.collection_medium_id]))).all()} if rows else {}
    mats = {m.id: m for m in db.scalars(select(Material).where(Material.id.in_([r.material_id for r in rows]))).all()} if rows else {}
    out: dict = {}
    for r in rows:
        g = out.setdefault(r.material_id, {"material_id": r.material_id, "material": (mats[r.material_id].official_description or mats[r.material_id].internal_name), "total_kg": 0.0, "items": []})
        g["total_kg"] = round(g["total_kg"] + float(r.net_weight), 3)
        g["items"].append({"id": r.id, "form": r.form, "label": FORM_LABELS.get(r.form, r.form), "code": media[r.collection_medium_id].code if r.collection_medium_id in media else None,
                           "net": float(r.net_weight), "status": r.status, "demo": bool(r.is_demo)})
    return {"year": year, "quarter": quarter, "month_name": MONTHS[QUARTER_MONTH[quarter] - 1], "materials": sorted(out.values(), key=lambda g: g["material"]),
            "total_kg": round(sum(g["total_kg"] for g in out.values()), 3)}


@router.get("/inventory/open")
def open_inventory(material_id: str, db: Session = Depends(get_db), user=Depends(require_permission("production.view")), x_demo: str | None = Header(default=None)):
    """Μέσα απογραφής του υλικού που δεν έχουν ακόμα εξαχθεί (για το βήμα «Μέσο αποθήκευσης» της Εξαγωγής)."""
    rows = [r for r in (_inv_rows(db, False, material_id=material_id, status="COUNTED") + (_inv_rows(db, True, material_id=material_id, status="COUNTED") if is_demo(x_demo) else [])) if r.collection_medium_id]
    media = {m.id: m for m in db.scalars(select(CollectionMedium).where(CollectionMedium.id.in_([r.collection_medium_id for r in rows]))).all()} if rows else {}
    return [{"id": r.id, "form": r.form, "label": FORM_LABELS.get(r.form, r.form), "code": media[r.collection_medium_id].code, "net": float(r.net_weight),
             "month_name": MONTHS[QUARTER_MONTH[r.quarter] - 1], "year": r.year} for r in rows]


@router.get("/warehouse")
def warehouse(db: Session = Depends(get_db), user=Depends(require_permission("production.view")), x_demo: str | None = Header(default=None)):
    """Αποθήκη = έτοιμο προς αποστολή (μόνο προβολή). Οι ποσότητες απογραφής δεν περιλαμβάνονται."""
    stat = ["AVAILABLE"] + (["DEMO"] if is_demo(x_demo) else [])
    lots = db.scalars(select(ReadyMaterialLot).where(ReadyMaterialLot.status.in_(stat), ReadyMaterialLot.entry_type == "EXPORT").order_by(ReadyMaterialLot.created_at)).all()
    mats = {m.id: m for m in db.scalars(select(Material).where(Material.id.in_([l.material_id for l in lots]))).all()} if lots else {}
    media = {m.id: m for m in db.scalars(select(CollectionMedium).where(CollectionMedium.id.in_([l.collection_medium_id for l in lots if l.collection_medium_id]))).all()} if lots else {}
    types = {t.id: t for t in _types(db).values()}
    out: dict = {}
    for l in lots:
        m = mats[l.material_id]
        g = out.setdefault(l.material_id, {"material_id": l.material_id, "material": m.official_description or m.internal_name, "pieces": 0, "kg": 0.0, "items": []})
        g["kg"] = round(g["kg"] + float(l.net_weight), 3)
        md = media.get(l.collection_medium_id) if l.collection_medium_id else None
        if md:
            g["pieces"] += 1
        t = types.get(md.type_id) if md else None
        label = {"PALLET": "Παλέτα", "SACK_1KG": "Σάκος 1 kg", "SACK_2KG_UN": "Σάκος 2 kg"}.get(t.code if t else "", "Χύμα")
        g["items"].append({"label": label, "code": md.code if md else None, "kg": float(l.net_weight), "demo": bool(l.is_demo)})
    groups = sorted(out.values(), key=lambda g: g["material"])
    return {"materials": groups, "pieces": sum(g["pieces"] for g in groups), "kg": round(sum(g["kg"] for g in groups), 3)}
