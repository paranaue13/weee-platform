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


_LATIN_TWIN = str.maketrans("ABEZHIKMNOPTYX", "ΑΒΕΖΗΙΚΜΝΟΡΤΥΧ")   # λατινικά γράμματα που μοιάζουν με ελληνικά = το ίδιο γράμμα


def _norm(s) -> str:
    """Κλειδί σύγκρισης ονομάτων: κεφαλαία, χωρίς πολλαπλά κενά, και τα λατινικά γράμματα που μοιάζουν με ελληνικά (Α Β Ε Ζ Η Ι Κ Μ Ν Ο Ρ Τ Υ Χ) θεωρούνται ίδια
    (π.χ. «ΙΝΟΧ» ελληνικά = «INOX» λατινικά). Τα αποθηκευμένα ονόματα δεν αλλάζουν."""
    return " ".join(str(s or "").strip().upper().split()).translate(_LATIN_TWIN)


def _fold_key(s) -> str:
    """Όπως το _norm αλλά και χωρίς τόνους/σημεία (ίδιο με τη σύγκριση της σύντομης περιγραφής στις οθόνες· το «+» μένει σημαντικό)."""
    import unicodedata, re as _re
    t = unicodedata.normalize("NFD", _norm(s))
    t = "".join(ch for ch in t if not unicodedata.combining(ch)).replace("+", " PLUS ")
    return _re.sub(r"[^0-9A-ZΑ-Ω]+", " ", t).strip()


def _commercial_group_id(db: Session):
    """Κατηγορία αποθήκης «Εμπορικά» (αν υπάρχει στα Μητρώα): εκεί εμφανίζονται όλα τα υλικά με το τσεκ «Εμπορικό υλικό» (Android εξαγωγή + Αποθήκη)."""
    for g in db.scalars(select(StorageGroup)).all():
        if _fold_key(g.name) == _fold_key("Εμπορικά"):
            return g.id
    return None


def _eff_group(m, comm_gid):
    return comm_gid if (comm_gid and getattr(m, "is_commercial", False)) else m.storage_group_id


def _commercial_exports_map(db: Session) -> dict:
    """Εξαγωγές εμπορικών ανά υλικό: {material_id: {"kg","pieces","rows":[...]}} (μόνο ενεργές)."""
    out: dict = {}
    for e in db.scalars(select(models.CommercialExport).where(models.CommercialExport.active == True).order_by(models.CommercialExport.export_date, models.CommercialExport.created_at)).all():
        g = out.setdefault(e.material_id, {"kg": 0.0, "pieces": 0, "rows": []})
        g["kg"] = round(g["kg"] + float(e.kg or 0), 3); g["pieces"] += int(e.pieces or 0); g["rows"].append(e)
    return out


def _apply_commercial_exports(db: Session, out: dict, entry):
    """Αφαιρεί τις εξαγωγές των εμπορικών από κιλά/τεμάχια του υλικού και τις προσθέτει ως γραμμές «Εξαγωγή» (αρνητικά κιλά) στην ανάλυση."""
    for mid, g in _commercial_exports_map(db).items():
        try:
            row = entry(mid)
        except KeyError:
            continue
        row["kg"] = round(row["kg"] - g["kg"], 3); row["pieces"] -= g["pieces"]; row["commercial"] = True
        for e in g["rows"]:
            row["items"].append({"kind": "commercial_export", "label": "Εξαγωγή", "code": None, "kg": -float(e.kg or 0), "pieces": -int(e.pieces or 0), "counted_kg": None,
                                 "date": e.export_date.isoformat() if e.export_date else None, "demo": False, "note": e.note})


def _free_kg(db: Session, lot) -> float:
    """Διαθέσιμα kg παρτίδας = υπόλοιπο μείον ό,τι έχει δεσμευτεί/φορτωθεί σε ανοικτές φορτώσεις."""
    r = db.scalar(select(func.coalesce(func.sum(models.LoadingReservation.reserved_weight), 0)).join(models.LoadingOrder, models.LoadingOrder.id == models.LoadingReservation.loading_order_id)
                  .where(models.LoadingReservation.ready_material_lot_id == lot.id, models.LoadingReservation.status == "RESERVED", models.LoadingOrder.status == "OPEN")) or 0
    a = db.scalar(select(func.coalesce(func.sum(models.LoadingActual.loaded_weight), 0)).join(models.LoadingOrder, models.LoadingOrder.id == models.LoadingActual.loading_order_id)
                  .where(models.LoadingActual.ready_material_lot_id == lot.id, models.LoadingOrder.status == "OPEN")) or 0
    return max(float(lot.net_weight) - float(r) - float(a), 0.0)


def _period(now: datetime | None = None):
    n = now or datetime.now()
    return n.year, (n.month - 1) // 3 + 1, n.month


def _pick_date(d: str | None):
    """Επιλεγμένη ημερομηνία κίνησης -> (datetime για την περίοδο, created_at ή None αν είναι σήμερα)."""
    if not d:
        return None, None
    try:
        day = datetime.strptime(d[:10], "%Y-%m-%d")
    except ValueError:
        raise HTTPException(422, "Μη έγκυρη ημερομηνία")
    if day.date() == datetime.now().date():
        return None, None
    return day, day.replace(hour=9)   # 09:00 UTC = μεσημέρι τοπικά: η ημέρα μένει ίδια σε κάθε ζώνη


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


def next_bale_code(db: Session, mat, demo: bool, consume: bool) -> str:
    """Κωδικός ΜΠΑΛΑΣ: ΜΙΑ σειρά ανά κατηγορία αποθήκης (κωδικός περιεχομένου) και ανά έτος, με «Β» μέσα στον κωδικό (26-MTL-B0001, B0002, B0003 για όλα τα υλικά
    της κατηγορίας). Η σειρά ξεκινά από το 1 κάθε χρονιά και δεν αφορά τις παλέτες/σάκους (έχουν δικό τους μετρητή). Ο κωδικός είναι πάντα μοναδικός:
    ο μετρητής αυξάνεται με ΕΝΑ ατομικό UPDATE (παίρνει το κλείδωμα εγγραφής) και αν ο κωδικός υπάρχει ήδη προχωρά στον επόμενο ελεύθερο."""
    import re
    from sqlalchemy import text
    now = datetime.now(); yy = now.year % 100
    cc = material_content_code(db, mat)
    pre = f"{'DEMO-' if demo else ''}{yy:02d}-{cc}-B"
    key = f"matbale.cat.{'DEMO.' if demo else ''}{now.year}.{cc}"
    row = db.scalar(select(AppSetting).where(AppSetting.key == key))
    if not row:
        # πρώτη χρήση: ξεκινά μετά τον μεγαλύτερο ήδη υπάρχοντα αριθμό «Β» της κατηγορίας (αν υπάρχει)
        mx = 0
        for (c,) in db.execute(select(CollectionMedium.code).where(CollectionMedium.code.like(pre + "%"))).all():
            m = re.fullmatch(re.escape(pre) + r"(\d+)", c or "")
            if m:
                mx = max(mx, int(m.group(1)))
        if not consume:
            n = mx
            while True:
                n += 1
                code = f"{pre}{n:04d}"
                if not db.scalar(select(CollectionMedium.id).where(CollectionMedium.code == code)):
                    return code
        row = AppSetting(key=key, value=str(mx)); db.add(row); db.flush()
    if not consume:
        n = int(row.value or 0)
        while True:
            n += 1
            code = f"{pre}{n:04d}"
            if not db.scalar(select(CollectionMedium.id).where(CollectionMedium.code == code)):
                return code
    while True:
        db.execute(text("UPDATE app_settings SET value = CAST(value AS INTEGER) + 1 WHERE key = :k"), {"k": key})
        n = int(db.execute(text("SELECT value FROM app_settings WHERE key = :k"), {"k": key}).scalar())
        code = f"{pre}{n:04d}"
        if not db.scalar(select(CollectionMedium.id).where(CollectionMedium.code == code)):
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


def _new_medium(db: Session, form: str, tare, demo: bool, status: str, mat=None, bale: bool = False):
    if form == "BULK":
        return None
    t = _types(db)[FORMS[form]]
    code = next_bale_code(db, mat, demo, True) if bale else next_medium_code(db, form, demo, material_content_code(db, mat))
    m = CollectionMedium(type_id=t.id, code=code, tare_weight=tare, status=status, active=True)
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
    for lb, w in db.execute(select(models.MaterialOpeningStock.material_label, func.sum(models.MaterialOpeningStock.kg)).where(models.MaterialOpeningStock.active == True).group_by(models.MaterialOpeningStock.material_label)).all():
        bal[_norm(lb)] = bal.get(_norm(lb), 0.0) + float(w or 0)
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


def _commercial_stock(db: Session) -> dict:
    """Απόθεμα εμπορικών ανά ΥΛΙΚΟ (id/ERP, όχι όνομα): κιλά των εξαγωγών (παρτίδων) − εξαγωγές εμπορικών."""
    rows = db.execute(select(ReadyMaterialLot.material_id, func.sum(ReadyMaterialLot.net_weight)).where(ReadyMaterialLot.entry_type == "EXPORT", ReadyMaterialLot.is_demo == False,
                      ReadyMaterialLot.status == "AVAILABLE").group_by(ReadyMaterialLot.material_id)).all()
    ex = _commercial_exports_map(db)
    return {m: round(float(w or 0) - ex.get(m, {}).get("kg", 0.0), 3) for m, w in rows}


def _ledger_raw(db: Session) -> dict:
    """Τρέχον απόθεμα ανά ΑΚΡΙΒΗ ετικέτα (παραγωγή − αποστολές + διορθώσεις), για τις ρητές αντιστοιχίσεις ετικέτας → υλικό."""
    bal: dict = {}
    for lb, w in db.execute(select(models.MaterialOpeningStock.material_label, func.sum(models.MaterialOpeningStock.kg)).where(models.MaterialOpeningStock.active == True).group_by(models.MaterialOpeningStock.material_label)).all():
        bal[lb] = bal.get(lb, 0.0) + float(w or 0)
    for t, sg in ((MaterialOutputEntry, 1), (MaterialShipmentEntry, -1)):
        for lb, w in db.execute(select(t.material_label, func.sum(t.weight_kg)).where(t.active == True).group_by(t.material_label)).all():
            bal[lb] = bal.get(lb, 0.0) + sg * float(w or 0)
    for lb, w in db.execute(select(MaterialCorrectionEntry.material_label, func.sum(MaterialCorrectionEntry.weight_kg_delta)).group_by(MaterialCorrectionEntry.material_label)).all():
        bal[lb] = bal.get(lb, 0.0) + float(w or 0)
    return bal


def _explicit_excel_maps(db: Session) -> dict:
    return {r.label_key: r for r in db.scalars(select(models.MaterialLabelMap).where(models.MaterialLabelMap.source == "EXCEL")).all()}


def available_by_material(db: Session, materials) -> dict:
    maps = _explicit_excel_maps(db)
    bal = _ledger_balance(db) if not maps else {}
    owner_sum: dict = {}
    if maps:
        raw = _ledger_raw(db)
        claimed = set(maps)                           # ετικέτες με ρητή αντιστοίχιση ΔΕΝ ταυτίζονται πια με το όνομα
        for lb, kg in raw.items():
            k = _fold_key(lb)
            r = maps.get(k)
            if r is not None:
                if r.kind in ("MATERIAL", "BULK_SUB") and r.material_id:
                    owner_sum[r.material_id] = owner_sum.get(r.material_id, 0.0) + kg
            else:
                bal[_norm(lb)] = bal.get(_norm(lb), 0.0) + kg
    exp = _exported_counted(db); out = {}
    cstock = None
    for m in materials:
        if getattr(m, "is_commercial", False):      # εμπορικό: δικό του απόθεμα (ανά υλικό), όχι το ισοζύγιο ετικέτας
            if cstock is None:
                cstock = _commercial_stock(db)
            out[m.id] = round(cstock.get(m.id, 0.0), 3)
            continue
        key = _norm(m.official_description or m.internal_name)
        b = bal.get(key)
        if b is None:
            b = bal.get(_norm(m.internal_name), bal.get(_norm(m.galaxy_description), 0.0))
        b = (b or 0.0) + owner_sum.get(m.id, 0.0)
        out[m.id] = round(max(0.0, b - exp.get(m.id, 0.0)), 3)
    return out


def umbrella_subs(db: Session) -> dict:
    """{material_id: [ενεργά υποπροϊόντα (ετικέτες BULK_SUB) με τη σειρά τους]} για υλικά-ομπρέλες (ομάδες)· η ομάδα «ισχύει» όσο έχει ενεργά υποπροϊόντα."""
    out: dict = {}
    for x in db.scalars(select(models.MaterialLabelMap).where(models.MaterialLabelMap.source == "EXCEL", models.MaterialLabelMap.kind == "BULK_SUB", models.MaterialLabelMap.active == True).order_by(models.MaterialLabelMap.sort_order, models.MaterialLabelMap.label)).all():
        if x.material_id:
            out.setdefault(x.material_id, []).append(x.label)
    return out


def _sub_available(db: Session, label: str, material_id: str) -> float:
    """Διαθέσιμα κιλά υποπροϊόντος για εξαγωγή: ισοζύγιο της ετικέτας του (παραγωγή − αποστολές) μείον ό,τι έχει ήδη εξαχθεί από το Android με αυτό το υποπροϊόν."""
    k = _fold_key(label)
    raw = sum(kg for lb, kg in _ledger_raw(db).items() if _fold_key(lb) == k)
    rows = db.execute(select(ReadyMaterialLot.sub_label, func.sum(func.coalesce(ReadyMaterialLot.counted_kg, ReadyMaterialLot.net_weight)))
                      .where(ReadyMaterialLot.material_id == material_id, ReadyMaterialLot.entry_type == "EXPORT", ReadyMaterialLot.is_demo == False, ReadyMaterialLot.status != "CANCELLED", ReadyMaterialLot.sub_label.is_not(None)).group_by(ReadyMaterialLot.sub_label)).all()
    exp = sum(float(w or 0) for s, w in rows if s and _fold_key(s) == k)
    return round(max(0.0, raw - exp), 3)


class ExportIn(BaseModel):
    material_id: str
    form: str
    gross: Decimal | None = None
    tare: Decimal | None = None
    net: Decimal | None = None            # Χύμα
    inventory_id: str | None = None       # εξαγωγή από μέσο απογραφής
    new_total: Decimal | None = None      # νέο συνολικό βάρος του μέσου απογραφής (φυσικό)
    is_bale: bool = False                 # παλέτα που εξάγεται ως ΜΠΑΛΑ (μόνο υλικά με can_bale)
    date: str | None = None               # ημερομηνία εξαγωγής YYYY-MM-DD (ορίζει την περίοδο)· χωρίς τιμή = σήμερα
    sub_label: str | None = None          # υποπροϊόν ομάδας (μόνο υλικά-ομπρέλες)· τα κιλά καταχωρούνται ΠΑΝΤΑ στο υποπροϊόν


class InventoryIn(BaseModel):
    material_id: str
    form: str
    gross: Decimal | None = None
    tare: Decimal | None = None
    net: Decimal | None = None


# ---- Κανόνας «κάθε ενεργό υλικό έχει στήλη»: καμία κίνηση υλικού (εξαγωγή, φόρτωση, απογραφή, παραγωγή) αν το υλικό δεν έχει στήλη σε καρτέλα Υλικών ----
LABEL_GROUP_TAB = {"Συσκευές για επαναχρησιμοποίηση": "EIDIKIS_DIACHEIRISIS", "Σιδηρούχα": "AXIOPOIISIMA"}   # καρτέλα όπου φαίνεται η ομάδα ετικέτας (ίδιο με την οθόνη Υλικά)
# Οι 4 καρτέλες-σύστημα (σπόρος του πίνακα material_tabs). Οι καρτέλες που φτιάχνει ο χρήστης διαβάζονται ΜΟΝΟ από τη βάση.
SYSTEM_TABS = (("AXIOPOIISIMA", "Αξιοποιήσιμα Υλικά", 10), ("EIDIKIS_DIACHEIRISIS", "Υλικά Ειδικής Διαχείρισης", 20), ("PLAKETES", "Πλακέτες", 30), ("APORRIPSI", "Υλικά προς Απόρριψη", 40))
DEFAULT_TAB = "AXIOPOIISIMA"


def ensure_material_tabs(db: Session) -> None:
    """Ο πίνακας material_tabs περιέχει πάντα τις 4 καρτέλες-σύστημα (idempotent· δεν πειράζει υπάρχουσες γραμμές)."""
    have = {t.code for t in db.scalars(select(models.MaterialTab)).all()}
    add = [models.MaterialTab(code=c, name=n, sort_order=o, is_system=True, active=True) for c, n, o in SYSTEM_TABS if c not in have]
    if add:
        db.add_all(add)
        db.commit()


def active_tabs(db: Session) -> list:
    """Ενεργές καρτέλες με τη σειρά τους: [{code, name, is_system}]. Αν ο πίνακας λείπει/είναι κενός, επιστρέφονται οι 4 σημερινές (ποτέ σφάλμα)."""
    try:
        rows = db.scalars(select(models.MaterialTab).where(models.MaterialTab.active == True).order_by(models.MaterialTab.sort_order, models.MaterialTab.name)).all()
    except Exception:
        rows = []
    if not rows:
        return [{"code": c, "name": n, "is_system": True} for c, n, o in SYSTEM_TABS]
    return [{"code": r.code, "name": r.name, "is_system": bool(r.is_system)} for r in rows]


def column_tab_codes(db: Session) -> set:
    """Κωδικοί καρτελών όπου μπορεί να έχει στήλη ένα υλικό (οι 4 σύστημα + οι ενεργές του χρήστη)."""
    return {t["code"] for t in active_tabs(db)} | {c for c, n, o in SYSTEM_TABS}


def materials_with_column(db: Session) -> set:
    """Κωδικοί (id) υλικών που έχουν στήλη: αντιστοίχιση Excel με καρτέλα (υλικό ή υποκατηγορία ομάδας-ομπρέλας)· μέλος ομάδας ετικέτας με στήλη (άθροισμα Excel ή ομάδα με άνοιγμα)· ενεργό εμπορικό υλικό (η καρτέλα Εμπορικά έχει στήλη για κάθε ένα)."""
    ids, sum_groups, groups = set(), set(), {}
    tab_codes_ = column_tab_codes(db)
    for x in db.scalars(select(models.MaterialLabelMap).where(models.MaterialLabelMap.source == "EXCEL")).all():
        if x.kind in ("MATERIAL", "BULK_SUB") and x.material_id and x.sheet in tab_codes_:
            ids.add(x.material_id)
        if x.kind == "SUM" and x.group_name:
            sum_groups.add(x.group_name)
    for m in db.scalars(select(Material)).all():
        if m.is_commercial and m.active:
            ids.add(m.id)
        if m.label_group:
            groups.setdefault(m.label_group, []).append(m.id)
    lg_tabs = {r.material_label[3:]: r.category_group for r in db.scalars(select(models.MaterialGroupOverride).where(models.MaterialGroupOverride.material_label.like('LG:%'))).all()}   # ετικέτες χρήστη με καρτέλα (Καρτέλες Υλικών)
    for g, l in groups.items():
        if g in sum_groups or (g in LABEL_GROUP_TAB and len(l) > 1) or (len(l) > 1 and lg_tabs.get(g) in tab_codes_):
            ids.update(l)
    return ids


def ensure_column(db: Session, mat: Material):
    if mat.id not in materials_with_column(db):
        raise HTTPException(422, "Το υλικό «" + (mat.official_description or mat.internal_name or mat.galaxy_code or "") + "» δεν έχει στήλη στις καρτέλες Υλικών, οπότε δεν γίνεται κίνηση. Αντιστοίχισέ το πρώτα σε στήλη.")


def _android_name(db: Session, mat: Material, mode: str) -> str:
    """Όνομα υλικού στο Android με βάση την ρύθμιση «Εμφάνιση περιγραφής» (Επίσημη / Σύντομη / HER)."""
    base = mat.official_description or mat.internal_name
    if mode == "short" and (mat.short_description or "").strip():
        return mat.short_description.strip()
    if mode == "her" and (mat.her_description or "").strip():
        return mat.her_description.strip()
    return base


def _android_mode(db: Session) -> str:
    import json
    row = db.scalar(select(AppSetting).where(AppSetting.key == "app.material_desc_modes"))
    try:
        v = (json.loads(row.value) if row else {}).get("android")
    except Exception:
        v = None
    return v if v in ("official", "short", "her") else "official"


def _material(db: Session, mid: str) -> Material:
    mat = db.get(Material, mid)
    if not mat or not mat.active:
        raise HTTPException(422, "Άγνωστο ή ανενεργό υλικό")
    return mat


@router.get("/catalog")
def catalog(db: Session = Depends(get_db), user=Depends(require_permission("production.view"))):
    cats = db.scalars(select(StorageGroup).where(StorageGroup.active == True).order_by(StorageGroup.sort_order, StorageGroup.name)).all()
    with_col = materials_with_column(db)
    mats = [x for x in db.scalars(select(Material).where(Material.active == True).order_by(Material.internal_name)).all() if x.id in with_col]
    avail = available_by_material(db, mats)
    dmode = _android_mode(db)
    comm_gid = _commercial_group_id(db)
    types = _types(db)
    forms = []
    for f in ("PALLET", "SACK_1KG", "SACK_2KG", "BULK"):
        t = types.get(FORMS[f]) if FORMS[f] else None
        forms.append({"form": f, "label": FORM_LABELS[f], "tare": float(t.default_tare_weight) if (t and t.default_tare_weight is not None) else None,
                      "asks_tare": f == "PALLET", "has_code": f != "BULK"})
    y, q, m = _period()
    usubs = umbrella_subs(db)
    mat_rows = []
    for x in mats:
        subs = usubs.get(x.id, []) if x.is_umbrella else []
        mat_rows.append({"id": x.id, "key": x.id, "name": _android_name(db, x, dmode), "code": x.galaxy_code, "category_id": _eff_group(x, comm_gid), "available_kg": avail.get(x.id, 0.0), "can_bale": bool(x.can_bale), "is_commercial": bool(x.is_commercial),
                         "group_active": bool(subs)})   # ομάδα που ισχύει: στην Εξαγωγή εμφανίζονται ΜΟΝΟ τα υποπροϊόντα και ο Parent κρύβεται
        for lb in subs:
            mat_rows.append({"id": x.id, "key": x.id + "::" + lb, "sub": lb, "name": lb, "code": None, "category_id": _eff_group(x, comm_gid), "available_kg": _sub_available(db, lb, x.id), "can_bale": False, "is_commercial": False, "group_active": False})
    return {"categories": [{"id": c.id, "name": c.name, "count": sum(1 for x in mats if _eff_group(x, comm_gid) == c.id)} for c in cats],
            "materials": mat_rows,
            "forms": forms, "period": {"year": y, "quarter": q, "month": m, "month_name": MONTHS[m - 1], "quarter_month_name": MONTHS[QUARTER_MONTH[q] - 1]}}


@router.get("/next-code")
def next_code_preview(form: str, material_id: str | None = None, bale: bool = False, db: Session = Depends(get_db), user=Depends(require_permission("production.view")), x_demo: str | None = Header(default=None)):
    """Ο κωδικός που θα δοθεί στο επόμενο μέσο μιας χρήσης (προεπισκόπηση, δεν δεσμεύεται)."""
    if form not in ("PALLET", "SACK_1KG", "SACK_2KG"):
        return {"code": None}
    mat = db.get(Material, material_id) if material_id else None
    if bale and mat is not None and form == "PALLET":
        return {"code": next_bale_code(db, mat, is_demo(x_demo), False)}
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
    ensure_column(db, mat)
    sub_label = (data.sub_label or "").strip() or None
    if mat.is_umbrella:
        subs = umbrella_subs(db).get(mat.id, [])
        if sub_label:
            hit = next((s for s in subs if _fold_key(s) == _fold_key(sub_label)), None)
            if not hit:
                raise HTTPException(422, "Το υποπροϊόν «" + sub_label + "» δεν ισχύει για το υλικό")
            sub_label = hit
        elif subs and not data.inventory_id:
            raise HTTPException(422, "Η ομάδα έχει υποπροϊόντα: διάλεξε υποπροϊόν για την εξαγωγή")
    elif sub_label:
        raise HTTPException(422, "Το υλικό δεν είναι ομάδα με υποπροϊόντα")
    if data.is_bale and (data.form != "PALLET" or data.inventory_id or not mat.can_bale):
        raise HTTPException(422, "Μπάλα μπορεί να γίνει μόνο παλέτα υλικού που επιτρέπεται να γίνει μπάλα")
    pick, pick_at = _pick_date(data.date)
    y, q, mo = _period(pick)
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
        medium = _new_medium(db, form, tare, demo, "READY_STORAGE", mat, bale=bool(data.is_bale))
    lot = ReadyMaterialLot(lot_number=_lot_number(db, mat, demo), material_id=mat.id, output_form=("CONTAINER" if medium else "BULK"),
                           collection_medium_id=medium.id if medium else None, gross_weight=gross, tare_weight=tare, net_weight=net, original_weight=net,
                           location_id=_location(db).id, status=("DEMO" if demo else "AVAILABLE"), created_by=user.id,
                           notes=("DEMO" if demo else None), entry_type="EXPORT", period_year=y, period_quarter=q, period_month=mo,
                           counted_kg=counted, storage_group_id=mat.storage_group_id, source_inventory_id=inv.id if inv else None, is_demo=demo, is_bale=bool(data.is_bale), sub_label=sub_label)
    if pick_at:
        lot.created_at = pick_at
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
            "id": lot.id, "lot_number": lot.lot_number, "material": (lot.sub_label or mat.official_description or mat.internal_name), "sub_label": lot.sub_label, "material_id": mat.id,
            "form_label": label, "medium_code": med.code if med else None, "net_kg": float(lot.net_weight), "counted_kg": float(lot.counted_kg) if lot.counted_kg is not None else None,
            "time": loc.strftime("%H:%M"), "created_at": ts, "from_inventory": bool(lot.source_inventory_id),
            "form": ("BULK" if not med else next((k for k, v in FORMS.items() if v and types.get(med.type_id) and types[med.type_id].code == v), "PALLET")),
            "gross_kg": float(lot.gross_weight) if lot.gross_weight is not None else None, "tare_kg": float(lot.tare_weight) if lot.tare_weight is not None else None,
            "inv_net_kg": (lambda i: float(i.net_weight) if i else None)(db.get(MaterialInventoryEntry, lot.source_inventory_id) if lot.source_inventory_id else None),
            "locked": _export_lock(db, lot), "is_bale": bool(lot.is_bale),
            "asks_tare": bool(med and med.type_id in types and types[med.type_id].code == "PALLET"), "date": loc.strftime("%d/%m/%Y")})
    return [{"date": d, "items": days_map[d]} for d in sorted(days_map, reverse=True)]


@router.get("/press-columns")
def press_columns(db: Session = Depends(get_db), user=Depends(require_permission("production.view"))):
    """Στήλες που εμφανίζει ΠΑΝΤΑ η Πρέσα (με 0 όταν δεν υπάρχει κίνηση): τα ενεργά, μη εμπορικά υλικά με «Μπορεί να γίνει μπάλα» (όνομα στήλης = «Όνομα στήλης Πρέσας» ή επίσημη περιγραφή)
    και οι στήλες που προέκυψαν από τα Excel της Πρέσας (οποιουδήποτε μήνα), ακόμα κι αν το υλικό δεν έχει το τσεκ."""
    mats = db.scalars(select(Material).where(Material.active == True, Material.can_bale == True, Material.is_commercial == False).order_by(Material.internal_name)).all()
    excel = [g for (g,) in db.execute(select(models.BaleEntry.material_group).where(models.BaleEntry.active == True).distinct()).all() if g]
    return {"materials": [{"id": m.id, "erp": m.galaxy_code, "name": (m.press_label or "").strip() or m.official_description or m.internal_name} for m in mats], "excel": sorted(excel)}


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
        if getattr(mat, "is_commercial", False):
            continue
        key = (mat.press_label or "").strip() or mat.official_description or mat.internal_name
        g = out.setdefault(key, {"material_group": key, "kg": 0.0, "count": 0, "days": {}})
        g["kg"] += float(lot.net_weight); g["count"] += 1
        dd = g["days"].setdefault(day.isoformat(), {"kg": 0.0, "count": 0})
        dd["kg"] += float(lot.net_weight); dd["count"] += 1
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
    tare: Decimal | None = None           # παλέτα/μπάλα: νέο απόβαρο (οι σάκοι έχουν σταθερό)
    net: Decimal | None = None            # Χύμα: νέα καθαρά κιλά
    new_total: Decimal | None = None      # εξαγωγή από απογραφή: νέο συνολικό (καθαρό) βάρος του μέσου


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
    med = db.get(CollectionMedium, lot.collection_medium_id) if lot.collection_medium_id else None
    mtype = db.get(CollectionMediumType, med.type_id) if med else None
    is_pallet = bool(mtype and mtype.code == "PALLET")
    old["tare"] = str(lot.tare_weight) if lot.tare_weight is not None else None
    def _tare():
        if is_pallet and data.tare is not None:
            t = Decimal(str(data.tare))
            if t < 0:
                raise HTTPException(422, "Το απόβαρο δεν μπορεί να είναι αρνητικό")
            return t
        return Decimal(str(lot.tare_weight if lot.tare_weight is not None else 0))
    if med is None:
        net = _net("BULK", None, None, data.net)
        lot.net_weight = net; lot.counted_kg = net
    elif inv and data.gross is None:
        if data.new_total is None or Decimal(str(data.new_total)) <= 0:
            raise HTTPException(422, "Βάλε το νέο συνολικό βάρος του μέσου")
        total = Decimal(str(data.new_total)); counted = total - Decimal(str(inv.net_weight))
        if counted < 0:
            raise HTTPException(422, "Το νέο συνολικό βάρος δεν μπορεί να είναι μικρότερο από της απογραφής")
        lot.net_weight = total; lot.counted_kg = counted
    else:
        tare = _tare()
        net = _net("PALLET", data.gross, tare, None)
        lot.gross_weight = Decimal(str(data.gross)); lot.tare_weight = tare; lot.net_weight = net
        if inv:
            counted = net - Decimal(str(inv.net_weight))
            if counted < 0:
                raise HTTPException(422, "Το νέο συνολικό βάρος δεν μπορεί να είναι μικρότερο από της απογραφής")
            lot.counted_kg = counted
        else:
            lot.counted_kg = net
        if is_pallet:
            med.tare_weight = tare
    lot.original_weight = Decimal(str(lot.original_weight if lot.original_weight is not None else old["net"])) + (lot.net_weight - Decimal(old["net"]))   # η διόρθωση μετακινεί και το αρχικό βάρος
    db.add(ReadyMaterialMovement(lot_id=lot.id, movement_type="EXPORT_EDIT", weight=lot.net_weight - Decimal(old["net"]), user_id=user.id, reason="Διόρθωση εξαγωγής από Android"))
    write_audit(db, user, "ready_material_lot", lot.id, "UPDATE", old=old, new={"net": str(lot.net_weight), "gross": str(lot.gross_weight) if lot.gross_weight is not None else None, "tare": str(lot.tare_weight) if lot.tare_weight is not None else None, "counted": str(lot.counted_kg)}, reason="Διόρθωση εξαγωγής")
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
    ensure_column(db, mat)
    if getattr(mat, "is_commercial", False):
        raise HTTPException(422, "Το εμπορικό υλικό δεν μετρά σε απογραφή")
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
    rows = [r for r in rows if not getattr(mats.get(r.material_id), "is_commercial", False)]      # τα εμπορικά δεν μετρούν σε απογραφή
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
        g["kg"] = round(g["kg"] + _free_kg(db, l), 3)
        md = media.get(l.collection_medium_id) if l.collection_medium_id else None
        if md:
            g["pieces"] += 1
        t = types.get(md.type_id) if md else None
        label = {"PALLET": "Παλέτα", "SACK_1KG": "Σάκος 1 kg", "SACK_2KG_UN": "Σάκος 2 kg"}.get(t.code if t else "", "Χύμα")
        g["items"].append({"label": ("Μπάλα" if l.is_bale else label), "code": md.code if md else None, "kg": _free_kg(db, l), "demo": bool(l.is_demo)})
    def _entry_old(mid):
        m = db.get(Material, mid)
        if not m: raise KeyError(mid)
        return out.setdefault(mid, {"material_id": mid, "material": m.official_description or m.internal_name, "pieces": 0, "kg": 0.0, "items": []})
    _apply_commercial_exports(db, out, _entry_old)
    out = {k: v for k, v in out.items() if v["kg"] != 0 or v["pieces"] != 0 or not v.get("commercial")}
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
    invs = [i for i in invs if not getattr(mats.get(i.material_id), "is_commercial", False)]      # τα εμπορικά δεν μετρούν σε απογραφή
    media_ids = [x.collection_medium_id for x in list(lots) + list(invs) if x.collection_medium_id]
    media = {m.id: m for m in db.scalars(select(CollectionMedium).where(CollectionMedium.id.in_(media_ids))).all()} if media_ids else {}
    types = {t.id: t for t in _types(db).values()}
    groups = {g.id: g for g in db.scalars(select(StorageGroup)).all()}
    comm_gid = _commercial_group_id(db)
    labels = {"PALLET": "Παλέτα", "SACK_1KG": "Σάκος 1 kg", "SACK_2KG_UN": "Σάκος 2 kg"}
    def label_of(md):
        t = types.get(md.type_id) if md else None
        return labels.get(t.code if t else "", "Χύμα")
    out: dict = {}
    def entry(mid):
        m = mats[mid]
        return out.setdefault(mid, {"material_id": mid, "material": m.official_description or m.internal_name, "short": getattr(m, "short_description", None), "erp": m.galaxy_code,
                                    "category_id": _eff_group(m, comm_gid), "category": (groups[_eff_group(m, comm_gid)].name if _eff_group(m, comm_gid) in groups else "Χωρίς κατηγορία"),
                                    "pieces": 0, "kg": 0.0, "inv_pieces": 0, "inv_kg": 0.0, "items": []})
    for l in lots:
        if l.material_id not in mats: continue
        g = entry(l.material_id); md = media.get(l.collection_medium_id) if l.collection_medium_id else None
        g["kg"] = round(g["kg"] + _free_kg(db, l), 3)
        if md: g["pieces"] += 1
        g["items"].append({"kind": "export", "label": ("Μπάλα" if l.is_bale else label_of(md)), "code": md.code if md else None, "kg": _free_kg(db, l),
                           "counted_kg": float(l.counted_kg) if l.source_inventory_id and l.counted_kg is not None else None,
                           "date": l.created_at.isoformat() if l.created_at else None, "demo": bool(l.is_demo)})
    for i in invs:
        if i.material_id not in mats: continue
        g = entry(i.material_id); md = media.get(i.collection_medium_id) if i.collection_medium_id else None
        g["inv_kg"] = round(g["inv_kg"] + float(i.net_weight), 3)
        if md: g["inv_pieces"] += 1
        g["items"].append({"kind": "inventory", "label": label_of(md), "code": md.code if md else None, "kg": float(i.net_weight), "counted_kg": None,
                           "date": i.created_at.isoformat() if i.created_at else None, "demo": bool(i.is_demo)})
    _apply_commercial_exports(db, out, entry)
    rows = [g for g in out.values() if g["kg"] > 0 or g["inv_kg"] > 0 or (g.get("commercial") and g["kg"] != 0)]
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
    invs = [i for i in invs if not getattr(mat_by_id.get(i.material_id), "is_commercial", False)]      # τα εμπορικά δεν μετρούν σε απογραφή
    avail = available_by_material(db, mats)
    media_ids = [x.collection_medium_id for x in list(lots) + list(invs) if x.collection_medium_id]
    media = {m.id: m for m in db.scalars(select(CollectionMedium).where(CollectionMedium.id.in_(media_ids))).all()} if media_ids else {}
    types = {t.id: t for t in _types(db).values()}
    groups = {g.id: g for g in db.scalars(select(StorageGroup)).all()}
    comm_gid = _commercial_group_id(db)

    def label_of(md):
        t = types.get(md.type_id) if md else None
        return _TYPE_LABELS.get(t.code if t else "", "Χύμα")

    out: dict = {}

    def entry(mid):
        m = mat_by_id[mid]
        return out.setdefault(mid, {"material_id": mid, "material": m.official_description or m.internal_name, "erp": m.galaxy_code,
                                    "category_id": _eff_group(m, comm_gid), "category": (groups[_eff_group(m, comm_gid)].name if _eff_group(m, comm_gid) in groups else "Χωρίς κατηγορία"),
                                    "pieces": 0, "kg": 0.0, "inv_kg": 0.0, "inv_pieces": 0, "items": []})
    # ποσότητα χωρίς δεδομένα μέσου = Χύμα· μία φορά ανά ετικέτα υλικού (πολλά υλικά μπορεί να μοιράζονται το ίδιο ισοζύγιο)
    seen: set = set()
    _owner_ids = {r.material_id for r in _explicit_excel_maps(db).values() if r.kind in ("MATERIAL", "BULK_SUB") and r.material_id}
    for m in sorted(mats, key=lambda m: (m.storage_group_id is None, m.id)):
        if getattr(m, "is_commercial", False):       # τα εμπορικά δεν παίρνουν «χύμα» από το ισοζύγιο ετικέτας (έχουν δικό τους απόθεμα ανά υλικό)
            continue
        key = _norm(m.official_description or m.internal_name)
        if m.id in _owner_ids:                       # υλικό με ρητές ετικέτες: ξεχωριστό από τα δίδυμα ίδιου ονόματος
            key = "ID:" + m.id
        kg = avail.get(m.id, 0.0)
        if kg >= 0.01 and key not in seen:
            seen.add(key)
            g = entry(m.id); g["kg"] = round(g["kg"] + kg, 3)
            g["items"].append({"kind": "bulk", "label": "Χύμα", "code": None, "kg": kg, "counted_kg": None, "date": None, "demo": False})
    for l in lots:
        if l.material_id not in mat_by_id:
            continue
        g = entry(l.material_id); md = media.get(l.collection_medium_id) if l.collection_medium_id else None
        g["kg"] = round(g["kg"] + _free_kg(db, l), 3)
        if md:
            g["pieces"] += 1
        counted = float(l.counted_kg) if l.source_inventory_id and l.counted_kg is not None else None
        g["items"].append({"kind": "export", "label": ("Μπάλα" if l.is_bale else label_of(md)), "code": md.code if md else None, "kg": _free_kg(db, l), "counted_kg": counted,
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
    _apply_commercial_exports(db, out, entry)
    rows = [g for g in out.values() if g["kg"] > 0 or g["inv_kg"] > 0 or (g.get("commercial") and g["kg"] != 0)]
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


# ---------------------------------------------------------------------------------------------------------------------
# ΕΜΠΟΡΙΚΑ υλικά (αγοράζονται από την εταιρεία): καρτέλα Windows → Υλικά → Εμπορικά
# ---------------------------------------------------------------------------------------------------------------------
class CommercialExportIn(BaseModel):
    material_id: str
    kg: Decimal = Decimal("0")
    pieces: int = 0
    date: str | None = None
    note: str | None = None


def _commercial_materials(db: Session):
    return db.scalars(select(Material).where(Material.is_commercial == True, Material.active == True).order_by(Material.internal_name)).all()


@router.get("/commercial")
def commercial_table(start: str | None = None, end: str | None = None, db: Session = Depends(get_db), user=Depends(require_permission("production.view"))):
    """Πίνακας καρτέλας «Εμπορικά»: στήλες = εμπορικά υλικά (τσεκ «Εμπορικό υλικό»). Ημερήσιες ποσότητες = οι εξαγωγές (παρτίδες) που καταχωρούνται από το Android
    (η μόνη πηγή ποσοτήτων σήμερα), εξαγωγές Windows ανά ημέρα και τρέχον απόθεμα (παρτίδες − εξαγωγές). Δεν υπάρχει απογραφή/αποστολές."""
    mats = _commercial_materials(db)
    ids = [m.id for m in mats]
    d0 = datetime.fromisoformat(start).date() if start else None
    d1 = datetime.fromisoformat(end).date() if end else None
    stock = _commercial_stock(db)
    lots_all = db.scalars(select(ReadyMaterialLot).where(ReadyMaterialLot.material_id.in_(ids), ReadyMaterialLot.entry_type == "EXPORT", ReadyMaterialLot.is_demo == False,
                                                          ReadyMaterialLot.status == "AVAILABLE")).all() if ids else []
    pieces_all: dict = {}
    days: dict = {}
    for l in lots_all:
        ts = l.created_at
        day = (ts.replace(tzinfo=timezone.utc).astimezone() if ts.tzinfo is None else ts.astimezone()).date()
        if l.collection_medium_id:
            pieces_all[l.material_id] = pieces_all.get(l.material_id, 0) + 1
        if (d0 and day < d0) or (d1 and day > d1):
            continue
        c = days.setdefault((day.isoformat(), l.material_id), {"work_date": day.isoformat(), "material_id": l.material_id, "kg": 0.0, "pieces": 0})
        c["kg"] = round(c["kg"] + float(l.net_weight), 3)
        if l.collection_medium_id:
            c["pieces"] += 1
    ex = _commercial_exports_map(db)
    q = select(models.CommercialExport).where(models.CommercialExport.active == True, models.CommercialExport.material_id.in_(ids)) if ids else None
    exports = []
    if q is not None:
        for e in db.scalars(q.order_by(models.CommercialExport.export_date, models.CommercialExport.created_at)).all():
            if (d0 and e.export_date < d0) or (d1 and e.export_date > d1):
                continue
            exports.append({"id": e.id, "material_id": e.material_id, "work_date": e.export_date.isoformat(), "kg": float(e.kg or 0), "pieces": int(e.pieces or 0), "note": e.note})
    adj = {}   # Απογραφή › Αποθέματα: διορθωμένα 31-12-Χ (Χ≥2026) μεταφέρονται στο απόθεμα
    for c in db.scalars(select(models.InventoryYearCorrection).where(models.InventoryYearCorrection.kind == 'COMM', models.InventoryYearCorrection.year >= 2026)).all():
        a = adj.setdefault(c.key, [0.0, 0]); a[0] += float(c.applied_kg or 0); a[1] += int(c.applied_pieces or 0)
    return {"materials": [{"id": m.id, "name": m.official_description or m.internal_name, "erp": m.galaxy_code, "short": m.short_description,
                           "stock_kg": round(stock.get(m.id, 0.0) + adj.get(m.id, [0, 0])[0], 3), "stock_pieces": pieces_all.get(m.id, 0) - ex.get(m.id, {}).get("pieces", 0) + adj.get(m.id, [0, 0])[1]} for m in mats],
            "entries": sorted(days.values(), key=lambda x: (x["work_date"], x["material_id"])), "exports": exports}


@router.post("/commercial-exports")
def add_commercial_export(data: CommercialExportIn, db: Session = Depends(get_db), user: User = Depends(require_permission("production.move"))):
    mat = db.get(Material, data.material_id)
    if not mat or not mat.active:
        raise HTTPException(422, "Άγνωστο ή ανενεργό υλικό")
    if not mat.is_commercial:
        raise HTTPException(422, "Το υλικό δεν είναι εμπορικό")
    kg = Decimal(str(data.kg or 0)); pcs = int(data.pieces or 0)
    if kg < 0 or pcs < 0:
        raise HTTPException(422, "Τα κιλά και τα τεμάχια δεν μπορεί να είναι αρνητικά")
    if kg == 0 and pcs == 0:
        raise HTTPException(422, "Βάλε κιλά ή τεμάχια")
    try:
        d = datetime.fromisoformat(data.date).date() if data.date else datetime.now().date()
    except ValueError:
        raise HTTPException(422, "Μη έγκυρη ημερομηνία")
    e = models.CommercialExport(material_id=mat.id, export_date=d, kg=kg, pieces=pcs, note=(data.note or "").strip() or None, created_by=user.id)
    db.add(e); db.flush()
    write_audit(db, user, "commercial_export", e.id, "CREATE", new={"material": mat.internal_code, "kg": str(kg), "pieces": pcs, "date": d.isoformat(), "note": e.note})
    db.commit()
    return {"id": e.id, "material_id": mat.id, "work_date": d.isoformat(), "kg": float(kg), "pieces": pcs, "note": e.note}


@router.delete("/commercial-exports/{export_id}")
def delete_commercial_export(export_id: str, db: Session = Depends(get_db), user: User = Depends(require_permission("production.move"))):
    e = db.get(models.CommercialExport, export_id)
    if not e or not e.active:
        raise HTTPException(404, "Η εξαγωγή δεν βρέθηκε")
    e.active = False
    write_audit(db, user, "commercial_export", e.id, "DELETE", old={"kg": str(e.kg), "pieces": e.pieces, "date": e.export_date.isoformat()})
    db.commit()
    return {"id": e.id, "deleted": True}


@router.get("/commercial-names")
def commercial_names(db: Session = Depends(get_db), user=Depends(require_permission("production.view"))):
    """Ονόματα που ανήκουν ΜΟΝΟ σε εμπορικά υλικά (κανένα μη εμπορικό υλικό δεν έχει το ίδιο όνομα). Οι οθόνες Υλικά/Απογραφής αφαιρούν τις ετικέτες με αυτά τα ονόματα."""
    mats = db.scalars(select(Material)).all()
    non = set()
    for m in mats:
        if not m.is_commercial and m.active:
            for n in (m.official_description, m.internal_name, m.galaxy_description):
                if n: non.add(_fold_key(n))
    maps = _explicit_excel_maps(db)
    byid = {m.id: m for m in mats}
    names = []
    for m in mats:
        if m.is_commercial and m.active:
            for n in (m.official_description, m.internal_name, m.galaxy_description):
                if n and _fold_key(n) not in non and n not in names:
                    r = maps.get(_fold_key(n))
                    if r is not None and r.kind in ("MATERIAL", "BULK_SUB", "SUM", "RECEIPTS", "NONE") and not (r.material_id and byid.get(r.material_id) is not None and byid[r.material_id].is_commercial):
                        continue                         # ρητά αντιστοιχισμένη αλλού: δεν εξαιρείται λόγω ονόματος
                    names.append(n)
    for r in maps.values():                              # ετικέτες που ρητά ανήκουν σε εμπορικό υλικό
        mm = byid.get(r.material_id) if r.material_id else None
        if r.kind == "MATERIAL" and mm is not None and mm.is_commercial and r.label not in names:
            names.append(r.label)
    return {"names": names}


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
