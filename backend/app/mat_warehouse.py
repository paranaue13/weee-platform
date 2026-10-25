"""Android → ΥΛΙΚΑ: Εξαγωγή / Αποθήκη / Απογραφή υλικών.

Κάθε εξαγωγή = ένα ReadyMaterialLot (ίδιο σύστημα με την «+ Εξαγωγή υλικών» των Windows), κάθε ζύγιση απογραφής = μία
MaterialInventoryEntry. Η απογραφή ΔΕΝ προσμετράται ποτέ στα «διαθέσιμα προς αποστολή».

DEMO: με επικεφαλίδα X-Demo: 1 οι εγγραφές δημιουργούνται με ετικέτα DEMO (is_demo, status «DEMO», κωδικοί «DEMO-P-/DEMO-S-»,
ξεχωριστή αρίθμηση) και ΔΕΝ μπαίνουν σε πραγματικά ισοζύγια/λίστες (εκτός αν ζητηθούν ρητά με X-Demo: 1). Σβήνονται με
backend/scripts/demo_data.py delete.
"""
from datetime import datetime, timezone, timedelta
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


def material_content_code(db: Session, mat) -> str:
    """Κωδικός περιεχομένου (3 γράμματα) από την κατηγορία αποθήκης του υλικού· χωρίς κατηγορία -> NCT."""
    sg = db.get(StorageGroup, mat.storage_group_id) if mat is not None and getattr(mat, "storage_group_id", None) else None
    m = db.get(models.ContentCodeMap, ("SGROUP", sg.name)) if sg is not None else None
    if not m:
        m = db.get(models.ContentCodeMap, ("SGROUP", "Χωρίς κατηγορία"))
    return m.code if m else "NCT"


def _demo_seq_code(db: Session, code3: str, consume: bool) -> str:
    """DEMO: χωριστή αρίθμηση ώστε να μη «χάνονται» αριθμοί των πραγματικών· ίδια μορφή με πρόθεμα DEMO-."""
    yy = datetime.now().year % 100
    key = f"matmedium.seq.DEMO-{code3}"
    row = db.scalar(select(AppSetting).where(AppSetting.key == key).with_for_update()) if consume else db.scalar(select(AppSetting).where(AppSetting.key == key))
    if consume and not row:
        row = AppSetting(key=key, value="0"); db.add(row); db.flush()
    n = int(row.value or 0) if row else 0
    while True:
        n += 1
        code = f"DEMO-{yy:02d}-{code3}-{n:04d}"
        if not db.scalar(select(CollectionMedium.id).where(CollectionMedium.code == code)):
            break
    if consume:
        row.value = str(n)
    return code


def next_medium_code(db: Session, form: str, demo: bool, content_code: str = "NCT") -> str:
    """Μοναδικός κωδικός μέσου μιας χρήσης: P-000231 (παλέτα) / S-000187 (σάκος 1 και 2 kg). Η αρίθμηση δεν επαναχρησιμοποιείται·
    τα DEMO έχουν ξεχωριστό πρόθεμα και δική τους αρίθμηση ώστε να μη «χάνονται» αριθμοί των πραγματικών."""
    if demo:
        return _demo_seq_code(db, content_code, True)
    from . import codes as _codes
    return _codes.next_code_for(db, content_code)       # κοινός μετρητής (έτος, κωδικός περιεχομένου)


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


def _new_medium(db: Session, form: str, tare, demo: bool, status: str, mat=None):
    if form == "BULK":
        return None
    t = _types(db)[FORMS[form]]
    m = CollectionMedium(type_id=t.id, code=next_medium_code(db, form, demo, material_content_code(db, mat)), tare_weight=tare, status=status, active=True)
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
    is_bale: bool = False                 # παλέτα που εξάγεται ως ΜΠΑΛΑ (μόνο υλικά με can_bale)


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
            "materials": [{"id": x.id, "name": x.official_description or x.internal_name, "code": x.galaxy_code, "category_id": x.storage_group_id, "available_kg": avail.get(x.id, 0.0), "can_bale": bool(x.can_bale)} for x in mats],
            "forms": forms, "period": {"year": y, "quarter": q, "month": m, "month_name": MONTHS[m - 1], "quarter_month_name": MONTHS[QUARTER_MONTH[q] - 1]}}


@router.get("/next-code")
def next_code_preview(form: str, material_id: str | None = None, db: Session = Depends(get_db), user=Depends(require_permission("production.view")), x_demo: str | None = Header(default=None)):
    """Ο κωδικός που θα δοθεί στο επόμενο μέσο μιας χρήσης (προεπισκόπηση, δεν δεσμεύεται)."""
    if form not in ("PALLET", "SACK_1KG", "SACK_2KG"):
        return {"code": None}
    mat = db.get(Material, material_id) if material_id else None
    cc = material_content_code(db, mat)
    if is_demo(x_demo):
        return {"code": _demo_seq_code(db, cc, False)}
    from . import codes as _codes
    return {"code": _codes.preview_code_for(db, cc)}


@router.post("/export")
def export_material(data: ExportIn, db: Session = Depends(get_db), user: User = Depends(require_permission("production.move")), x_demo: str | None = Header(default=None)):
    demo = is_demo(x_demo)
    if data.form not in FORMS:
        raise HTTPException(422, "Άγνωστο μέσο αποθήκευσης")
    mat = _material(db, data.material_id)
    if data.is_bale and (data.form != "PALLET" or data.inventory_id or not mat.can_bale):
        raise HTTPException(422, "Μπάλα μπορεί να γίνει μόνο παλέτα υλικού που επιτρέπεται να γίνει μπάλα")
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
        medium = _new_medium(db, form, tare, demo, "READY_STORAGE", mat)
    lot = ReadyMaterialLot(lot_number=_lot_number(db, mat, demo), material_id=mat.id, output_form=("CONTAINER" if medium else "BULK"),
                           collection_medium_id=medium.id if medium else None, gross_weight=gross, tare_weight=tare, net_weight=net,
                           location_id=_location(db).id, status=("DEMO" if demo else "AVAILABLE"), created_by=user.id,
                           notes=("DEMO" if demo else None), entry_type="EXPORT", period_year=y, period_quarter=q, period_month=mo,
                           counted_kg=counted, storage_group_id=mat.storage_group_id, source_inventory_id=inv.id if inv else None, is_demo=demo, is_bale=bool(data.is_bale))
    db.add(lot); db.flush()
    db.add(ReadyMaterialMovement(lot_id=lot.id, movement_type="PRODUCTION_OUT", weight=net, user_id=user.id, reason=("DEMO" if demo else "Εξαγωγή από Android")))
    if medium:
        medium.status = "READY_STORAGE"
    if inv:
        inv.status = "EXPORTED"; inv.exported_lot_id = lot.id
    write_audit(db, user, "ready_material_lot", lot.id, "CREATE", new={"lot_number": lot.lot_number, "material": mat.internal_code, "net": str(net), "counted": str(counted), "form": form, "demo": demo, "is_bale": bool(data.is_bale)})
    db.commit()
    return {"id": lot.id, "lot_number": lot.lot_number, "form": form, "medium_code": medium.code if medium else None, "net": float(net), "counted_kg": float(counted)}


@router.get("/exports")
def list_exports(days: int = Query(default=60, ge=1, le=400), db: Session = Depends(get_db), user=Depends(require_permission("production.view")), x_demo: str | None = Header(default=None)):
    """Ιστορικό εξαγωγών (Android Υλικά → Εξαγωγή) ανά ημέρα, πιο πρόσφατη πρώτη: υλικό, μέσο αποθήκευσης, καθαρά κιλά, ώρα. Μόνο ανάγνωση."""
    demo = is_demo(x_demo)
    since = datetime.utcnow() - timedelta(days=days)
    rows = db.execute(select(ReadyMaterialLot, Material).join(Material, Material.id == ReadyMaterialLot.material_id)
                      .where(ReadyMaterialLot.entry_type == "EXPORT", ReadyMaterialLot.is_demo == demo, ReadyMaterialLot.status != "CANCELLED", ReadyMaterialLot.created_at >= since)
                      .order_by(ReadyMaterialLot.created_at.desc())).all()
    types = {t.id: t for t in db.scalars(select(CollectionMediumType)).all()}
    days_map: dict = {}
    for lot, mat in rows:
        ts = lot.created_at
        loc = ts.replace(tzinfo=timezone.utc).astimezone() if ts.tzinfo is None else ts.astimezone()
        med = db.get(CollectionMedium, lot.collection_medium_id) if lot.collection_medium_id else None
        label = (types[med.type_id].name_el if med and med.type_id in types else "Μέσο") if med else "Χύμα"
        if lot.is_bale:
            label = "Μπάλα"
        days_map.setdefault(loc.strftime("%Y-%m-%d"), []).append({
            "id": lot.id, "lot_number": lot.lot_number, "material": mat.official_description or mat.internal_name, "material_id": mat.id,
            "form_label": label, "medium_code": med.code if med else None, "net_kg": float(lot.net_weight), "counted_kg": float(lot.counted_kg) if lot.counted_kg is not None else None,
            "time": loc.strftime("%H:%M"), "created_at": ts, "from_inventory": bool(lot.source_inventory_id),
            "form": ("BULK" if not med else next((k for k, v in FORMS.items() if v and types.get(med.type_id) and types[med.type_id].code == v), "PALLET")),
            "gross_kg": float(lot.gross_weight) if lot.gross_weight is not None else None, "tare_kg": float(lot.tare_weight) if lot.tare_weight is not None else None,
            "inv_net_kg": (lambda i: float(i.net_weight) if i else None)(db.get(MaterialInventoryEntry, lot.source_inventory_id) if lot.source_inventory_id else None),
            "locked": _export_lock(db, lot), "is_bale": bool(lot.is_bale)})
    return [{"date": d, "items": days_map[d]} for d in sorted(days_map, reverse=True)]


@router.get("/bales-summary")
def bales_summary(start: str | None = None, end: str | None = None, db: Session = Depends(get_db), user=Depends(require_permission("production.view"))):
    """Μπάλες (εξαγωγές παλέτας με is_bale) ανά στήλη Πρέσας για την περίοδο: καθαρά κιλά και πλήθος. Πρόσθετες γραμμές στον πίνακα Πρέσα· δεν προστίθενται στα «Κιλά/Δέματα» του Excel."""
    rows = db.execute(select(ReadyMaterialLot, Material).join(Material, Material.id == ReadyMaterialLot.material_id)
                      .where(ReadyMaterialLot.entry_type == "EXPORT", ReadyMaterialLot.is_bale == True, ReadyMaterialLot.is_demo == False, ReadyMaterialLot.status != "CANCELLED")).all()
    d0 = datetime.fromisoformat(start).date() if start else None
    d1 = datetime.fromisoformat(end).date() if end else None
    out: dict = {}
    for lot, mat in rows:
        ts = lot.created_at
        day = (ts.replace(tzinfo=timezone.utc).astimezone() if ts.tzinfo is None else ts.astimezone()).date()
        if (d0 and day < d0) or (d1 and day > d1):
            continue
        key = (mat.press_label or "").strip() or mat.official_description or mat.internal_name
        g = out.setdefault(key, {"material_group": key, "kg": 0.0, "count": 0})
        g["kg"] += float(lot.net_weight); g["count"] += 1
    return sorted(out.values(), key=lambda g: -g["kg"])


def _export_lock(db: Session, lot: ReadyMaterialLot) -> str | None:
    """Λόγος για τον οποίο μια εξαγωγή ΔΕΝ διορθώνεται/διαγράφεται (δεσμευμένη, σε πρόχειρο ή φορτωμένη), αλλιώς None."""
    if lot.entry_type != "EXPORT":
        return "Αυτή η εγγραφή δεν είναι εξαγωγή"
    if lot.status == "CANCELLED":
        return "Η εξαγωγή έχει ήδη διαγραφεί"
    if db.scalar(select(models.LoadingActual.id).where(models.LoadingActual.ready_material_lot_id == lot.id).limit(1)) or lot.status in ("DISPATCHED", "LOADED"):
        return "Η εξαγωγή έχει ήδη φορτωθεί και δεν αλλάζει"
    if db.scalar(select(models.LoadingReservation.id).where(models.LoadingReservation.ready_material_lot_id == lot.id, models.LoadingReservation.status == "RESERVED").limit(1)) or lot.status in ("RESERVED", "LOADING"):
        return "Η εξαγωγή είναι δεσμευμένη για φόρτωση και δεν αλλάζει"
    if db.scalar(select(models.LoadingPlanItem.id).where(models.LoadingPlanItem.ready_material_lot_id == lot.id).limit(1)):
        return "Η εξαγωγή είναι σε πρόχειρο φόρτωσης· αφαίρεσέ την πρώτα από εκεί"
    if lot.status not in ("AVAILABLE", "DEMO"):
        return "Η εξαγωγή δεν είναι πια διαθέσιμη και δεν αλλάζει"
    return None


class ExportEditIn(BaseModel):
    gross: Decimal | None = None          # μέσο (παλέτα/σάκος): νέο μικτό
    net: Decimal | None = None            # Χύμα: νέα καθαρά κιλά
    new_total: Decimal | None = None      # εξαγωγή από απογραφή: νέο συνολικό βάρος του μέσου


@router.put("/exports/{lot_id}")
def edit_export(lot_id: str, data: ExportEditIn, db: Session = Depends(get_db), user: User = Depends(require_permission("production.move"))):
    lot = db.get(ReadyMaterialLot, lot_id)
    if not lot:
        raise HTTPException(404, "Η εξαγωγή δεν βρέθηκε")
    why = _export_lock(db, lot)
    if why:
        raise HTTPException(409, why)
    old = {"net": str(lot.net_weight), "gross": str(lot.gross_weight) if lot.gross_weight is not None else None, "counted": str(lot.counted_kg) if lot.counted_kg is not None else None}
    inv = db.get(MaterialInventoryEntry, lot.source_inventory_id) if lot.source_inventory_id else None
    if inv:
        if data.new_total is None or Decimal(str(data.new_total)) <= 0:
            raise HTTPException(422, "Βάλε το νέο συνολικό βάρος του μέσου")
        total = Decimal(str(data.new_total)); counted = total - Decimal(str(inv.net_weight))
        if counted < 0:
            raise HTTPException(422, "Το νέο συνολικό βάρος δεν μπορεί να είναι μικρότερο από της απογραφής")
        lot.net_weight = total; lot.counted_kg = counted
    elif lot.collection_medium_id is None:
        net = _net("BULK", None, None, data.net)
        lot.net_weight = net; lot.counted_kg = net
    else:
        tare = Decimal(str(lot.tare_weight if lot.tare_weight is not None else 0))
        net = _net("PALLET", data.gross, tare, None)
        lot.gross_weight = Decimal(str(data.gross)); lot.net_weight = net; lot.counted_kg = net
    db.add(ReadyMaterialMovement(lot_id=lot.id, movement_type="EXPORT_EDIT", weight=lot.net_weight - Decimal(old["net"]), user_id=user.id, reason="Διόρθωση εξαγωγής από Android"))
    write_audit(db, user, "ready_material_lot", lot.id, "UPDATE", old=old, new={"net": str(lot.net_weight), "gross": str(lot.gross_weight) if lot.gross_weight is not None else None, "counted": str(lot.counted_kg)}, reason="Διόρθωση εξαγωγής")
    db.commit()
    return {"id": lot.id, "net": float(lot.net_weight), "counted_kg": float(lot.counted_kg)}


@router.delete("/exports/{lot_id}")
def delete_export(lot_id: str, db: Session = Depends(get_db), user: User = Depends(require_permission("production.move"))):
    """Διαγραφή εξαγωγής: η εγγραφή ακυρώνεται (μένει στο ιστορικό αλλαγών), το μέσο μένει ΕΛΕΥΘΕΡΟ για επαναχρησιμοποίηση,
    και αν προήλθε από απογραφή, η εγγραφή της απογραφής γίνεται ξανά διαθέσιμη."""
    lot = db.get(ReadyMaterialLot, lot_id)
    if not lot:
        raise HTTPException(404, "Η εξαγωγή δεν βρέθηκε")
    why = _export_lock(db, lot)
    if why:
        raise HTTPException(409, why)
    med = db.get(CollectionMedium, lot.collection_medium_id) if lot.collection_medium_id else None
    inv = db.get(MaterialInventoryEntry, lot.source_inventory_id) if lot.source_inventory_id else None
    if inv:
        inv.status = "COUNTED"; inv.exported_lot_id = None
        if med:
            med.status = "INVENTORY"
    elif med:
        med.status = "AVAILABLE"
    lot.status = "CANCELLED"
    db.add(ReadyMaterialMovement(lot_id=lot.id, movement_type="EXPORT_CANCELLED", weight=-lot.net_weight, user_id=user.id, reason="Διαγραφή εξαγωγής από Android"))
    write_audit(db, user, "ready_material_lot", lot.id, "UPDATE", old={"status": "AVAILABLE"}, new={"status": "CANCELLED"}, reason="Διαγραφή εξαγωγής" + (" (η απογραφή έγινε ξανά διαθέσιμη)" if inv else ""))
    db.commit()
    return {"id": lot.id, "cancelled": True, "inventory_restored": bool(inv), "medium_code": med.code if med else None}


@router.post("/inventory")
def add_inventory(data: InventoryIn, db: Session = Depends(get_db), user: User = Depends(require_permission("production.move")), x_demo: str | None = Header(default=None)):
    demo = is_demo(x_demo)
    if data.form not in FORMS:
        raise HTTPException(422, "Άγνωστο μέσο αποθήκευσης")
    mat = _material(db, data.material_id)
    tare = _tare_for(db, data.form, data.tare)
    net = _net(data.form, data.gross, tare, data.net)
    y, q, mo = _period()
    medium = _new_medium(db, data.form, tare, demo, "INVENTORY", mat)
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
        g["items"].append({"label": ("Μπάλα" if l.is_bale else label), "code": md.code if md else None, "kg": float(l.net_weight), "demo": bool(l.is_demo)})
    groups = sorted(out.values(), key=lambda g: g["material"])
    return {"materials": groups, "pieces": sum(g["pieces"] for g in groups), "kg": round(sum(g["kg"] for g in groups), 3)}


@router.get("/warehouse-grouped")
def warehouse_grouped(include_inventory: bool = False, db: Session = Depends(get_db), user=Depends(require_permission("production.view")), x_demo: str | None = Header(default=None)):
    """Android → Υλικά → Αποθήκη στη δομή των Windows (ανά Κατηγορία αποθήκης). ΙΔΙΟΙ αριθμοί/κανόνες με το /mat/warehouse (μόνο εξαγωγές, χωρίς υπόλοιπο ισοζυγίου)·
    οι ποσότητες απογραφής προστίθενται ΜΟΝΟ με include_inventory=true (όπως στα Windows)."""
    stat = ["AVAILABLE"] + (["DEMO"] if is_demo(x_demo) else [])
    lots = db.scalars(select(ReadyMaterialLot).where(ReadyMaterialLot.status.in_(stat), ReadyMaterialLot.entry_type == "EXPORT").order_by(ReadyMaterialLot.created_at)).all()
    invs = (_inv_rows(db, False, status="COUNTED") + (_inv_rows(db, True, status="COUNTED") if is_demo(x_demo) else [])) if include_inventory else []
    mats = {m.id: m for m in db.scalars(select(Material)).all()}
    media_ids = [x.collection_medium_id for x in list(lots) + list(invs) if x.collection_medium_id]
    media = {m.id: m for m in db.scalars(select(CollectionMedium).where(CollectionMedium.id.in_(media_ids))).all()} if media_ids else {}
    types = {t.id: t for t in _types(db).values()}
    groups = {g.id: g for g in db.scalars(select(StorageGroup)).all()}
    labels = {"PALLET": "Παλέτα", "SACK_1KG": "Σάκος 1 kg", "SACK_2KG_UN": "Σάκος 2 kg"}
    def label_of(md):
        t = types.get(md.type_id) if md else None
        return labels.get(t.code if t else "", "Χύμα")
    out: dict = {}
    def entry(mid):
        m = mats[mid]
        return out.setdefault(mid, {"material_id": mid, "material": m.official_description or m.internal_name, "short": getattr(m, "short_description", None), "erp": m.galaxy_code,
                                    "category_id": m.storage_group_id, "category": (groups[m.storage_group_id].name if m.storage_group_id in groups else "Χωρίς κατηγορία"),
                                    "pieces": 0, "kg": 0.0, "inv_pieces": 0, "inv_kg": 0.0, "items": []})
    for l in lots:
        if l.material_id not in mats: continue
        g = entry(l.material_id); md = media.get(l.collection_medium_id) if l.collection_medium_id else None
        g["kg"] = round(g["kg"] + float(l.net_weight), 3)
        if md: g["pieces"] += 1
        g["items"].append({"kind": "export", "label": ("Μπάλα" if l.is_bale else label_of(md)), "code": md.code if md else None, "kg": float(l.net_weight),
                           "counted_kg": float(l.counted_kg) if l.source_inventory_id and l.counted_kg is not None else None,
                           "date": l.created_at.isoformat() if l.created_at else None, "demo": bool(l.is_demo)})
    for i in invs:
        if i.material_id not in mats: continue
        g = entry(i.material_id); md = media.get(i.collection_medium_id) if i.collection_medium_id else None
        g["inv_kg"] = round(g["inv_kg"] + float(i.net_weight), 3)
        if md: g["inv_pieces"] += 1
        g["items"].append({"kind": "inventory", "label": label_of(md), "code": md.code if md else None, "kg": float(i.net_weight), "counted_kg": None,
                           "date": i.created_at.isoformat() if i.created_at else None, "demo": bool(i.is_demo)})
    rows = [g for g in out.values() if g["kg"] > 0 or g["inv_kg"] > 0]
    for g in rows:
        g["total_pieces"] = g["pieces"] + g["inv_pieces"]; g["total_kg"] = round(g["kg"] + g["inv_kg"], 3)
    cats: dict = {}
    for g in rows:
        c = cats.setdefault(g["category"], {"category": g["category"], "sort": groups[g["category_id"]].sort_order if g["category_id"] in groups else 9999, "materials": []})
        c["materials"].append(g)
    result = []
    for c in sorted(cats.values(), key=lambda c: (c["sort"], c["category"])):
        c["materials"].sort(key=lambda g: g["material"])
        c["pieces"] = sum(g["pieces"] for g in c["materials"]); c["kg"] = round(sum(g["kg"] for g in c["materials"]), 3)
        c["inv_pieces"] = sum(g["inv_pieces"] for g in c["materials"]); c["inv_kg"] = round(sum(g["inv_kg"] for g in c["materials"]), 3)
        c["total_pieces"] = c["pieces"] + c["inv_pieces"]; c["total_kg"] = round(c["kg"] + c["inv_kg"], 3)
        result.append(c)
    return {"include_inventory": include_inventory, "categories": result, "n_categories": len(result), "n_materials": len(rows),
            "pieces": sum(c["pieces"] for c in result), "kg": round(sum(c["kg"] for c in result), 3),
            "inv_pieces": sum(c["inv_pieces"] for c in result), "inv_kg": round(sum(c["inv_kg"] for c in result), 3),
            "total_pieces": sum(c["total_pieces"] for c in result), "total_kg": round(sum(c["total_kg"] for c in result), 3)}


# ---------------------------------------------------------------------------------------------------------------------
# Windows → Υλικά → Αποθήκη (προβολή). Ίδια δεδομένα με το Android, ομαδοποιημένα ανά Κατηγορία αποθήκης.
# ---------------------------------------------------------------------------------------------------------------------
_TYPE_LABELS = {"PALLET": "Παλέτα", "SACK_1KG": "Σάκος 1 kg", "SACK_2KG_UN": "Σάκος 2 kg"}


@router.get("/warehouse-desktop")
def warehouse_desktop(include_inventory: bool = False, db: Session = Depends(get_db), user=Depends(require_permission("production.view"))):
    """Διαθέσιμα προς αποστολή = εξαγωγές (παλέτες/σάκοι/χύμα) + υπόλοιπο ισοζυγίου που δεν έχει μέσο (θεωρείται Χύμα).
    Οι ποσότητες απογραφής προστίθενται ΜΟΝΟ με include_inventory=true."""
    lots = db.scalars(select(ReadyMaterialLot).where(ReadyMaterialLot.status.in_(["AVAILABLE", "DEMO"]), ReadyMaterialLot.entry_type == "EXPORT").order_by(ReadyMaterialLot.created_at)).all()
    invs = db.scalars(select(MaterialInventoryEntry).where(MaterialInventoryEntry.status == "COUNTED").order_by(MaterialInventoryEntry.created_at)).all() if include_inventory else []
    mats = db.scalars(select(Material)).all()
    mat_by_id = {m.id: m for m in mats}
    avail = available_by_material(db, mats)
    media_ids = [x.collection_medium_id for x in list(lots) + list(invs) if x.collection_medium_id]
    media = {m.id: m for m in db.scalars(select(CollectionMedium).where(CollectionMedium.id.in_(media_ids))).all()} if media_ids else {}
    types = {t.id: t for t in _types(db).values()}
    groups = {g.id: g for g in db.scalars(select(StorageGroup)).all()}

    def label_of(md):
        t = types.get(md.type_id) if md else None
        return _TYPE_LABELS.get(t.code if t else "", "Χύμα")

    out: dict = {}

    def entry(mid):
        m = mat_by_id[mid]
        return out.setdefault(mid, {"material_id": mid, "material": m.official_description or m.internal_name, "erp": m.galaxy_code,
                                    "category_id": m.storage_group_id, "category": (groups[m.storage_group_id].name if m.storage_group_id in groups else "Χωρίς κατηγορία"),
                                    "pieces": 0, "kg": 0.0, "inv_kg": 0.0, "inv_pieces": 0, "items": []})
    # ποσότητα χωρίς δεδομένα μέσου = Χύμα· μία φορά ανά ετικέτα υλικού (πολλά υλικά μπορεί να μοιράζονται το ίδιο ισοζύγιο)
    seen: set = set()
    for m in sorted(mats, key=lambda m: (m.storage_group_id is None, m.id)):
        key = _norm(m.official_description or m.internal_name)
        kg = avail.get(m.id, 0.0)
        if kg >= 0.01 and key not in seen:
            seen.add(key)
            g = entry(m.id); g["kg"] = round(g["kg"] + kg, 3)
            g["items"].append({"kind": "bulk", "label": "Χύμα", "code": None, "kg": kg, "counted_kg": None, "date": None, "demo": False})
    for l in lots:
        if l.material_id not in mat_by_id:
            continue
        g = entry(l.material_id); md = media.get(l.collection_medium_id) if l.collection_medium_id else None
        g["kg"] = round(g["kg"] + float(l.net_weight), 3)
        if md:
            g["pieces"] += 1
        counted = float(l.counted_kg) if l.source_inventory_id and l.counted_kg is not None else None
        g["items"].append({"kind": "export", "label": ("Μπάλα" if l.is_bale else label_of(md)), "code": md.code if md else None, "kg": float(l.net_weight), "counted_kg": counted,
                           "date": l.created_at.isoformat() if l.created_at else None, "demo": bool(l.is_demo)})
    for i in invs:
        if i.material_id not in mat_by_id:
            continue
        g = entry(i.material_id); md = media.get(i.collection_medium_id) if i.collection_medium_id else None
        g["inv_kg"] = round(g["inv_kg"] + float(i.net_weight), 3)
        if md:
            g["inv_pieces"] += 1
        g["items"].append({"kind": "inventory", "label": label_of(md), "code": md.code if md else None, "kg": float(i.net_weight), "counted_kg": None,
                           "date": i.created_at.isoformat() if i.created_at else None, "demo": bool(i.is_demo)})
    rows = [g for g in out.values() if g["kg"] > 0 or g["inv_kg"] > 0]
    for g in rows:
        g["total_pieces"] = g["pieces"] + g["inv_pieces"]
        g["total_kg"] = round(g["kg"] + g["inv_kg"], 3)
    cats: dict = {}
    for g in rows:
        c = cats.setdefault(g["category"], {"category": g["category"], "sort": groups[g["category_id"]].sort_order if g["category_id"] in groups else 9999, "materials": []})
        c["materials"].append(g)
    result = []
    for c in sorted(cats.values(), key=lambda c: (c["sort"], c["category"])):
        c["materials"].sort(key=lambda g: g["material"])
        c["pieces"] = sum(g["pieces"] for g in c["materials"]); c["kg"] = round(sum(g["kg"] for g in c["materials"]), 3)
        c["inv_pieces"] = sum(g["inv_pieces"] for g in c["materials"]); c["inv_kg"] = round(sum(g["inv_kg"] for g in c["materials"]), 3)
        c["total_pieces"] = c["pieces"] + c["inv_pieces"]; c["total_kg"] = round(c["kg"] + c["inv_kg"], 3)
        result.append(c)
    return {"include_inventory": include_inventory, "categories": result,
            "n_categories": len(result), "n_materials": len(rows),
            "pieces": sum(c["pieces"] for c in result), "kg": round(sum(c["kg"] for c in result), 3),
            "inv_pieces": sum(c["inv_pieces"] for c in result), "inv_kg": round(sum(c["inv_kg"] for c in result), 3),
            "total_pieces": sum(c["total_pieces"] for c in result), "total_kg": round(sum(c["total_kg"] for c in result), 3),
            "demo_count": sum(1 for g in rows for it in g["items"] if it["demo"])}


@router.post("/demo/delete")
def delete_demo(db: Session = Depends(get_db), user: User = Depends(require_permission("production.move"))):
    """«Σβήσιμο DEMO»: σβήνει ΜΟΝΟ τα DEMO των ΥΛΙΚΩΝ (εξαγωγές, ζυγίσεις απογραφής, μέσα DEMO-P-/DEMO-S-)."""
    lot_ids = [l.id for l in db.scalars(select(ReadyMaterialLot).where(ReadyMaterialLot.is_demo == True)).all()]
    if lot_ids:
        db.execute(models.ReadyMaterialMovement.__table__.delete().where(ReadyMaterialMovement.lot_id.in_(lot_ids)))
        db.execute(ReadyMaterialLot.__table__.delete().where(ReadyMaterialLot.id.in_(lot_ids)))
    n_inv = db.execute(MaterialInventoryEntry.__table__.delete().where(MaterialInventoryEntry.is_demo == True)).rowcount or 0
    db.execute(AppSetting.__table__.delete().where(AppSetting.key.like("matmedium.seq.DEMO-%")))
    db.flush()
    n_media = 0
    for m in db.scalars(select(CollectionMedium).where((CollectionMedium.code.like("DEMO-P-%")) | (CollectionMedium.code.like("DEMO-S-%")) | (CollectionMedium.code.op("GLOB")("DEMO-[0-9][0-9]-*")))).all():
        db.delete(m); n_media += 1
    db.commit()
    return {"lots": len(lot_ids), "inventory": n_inv, "media": n_media}
