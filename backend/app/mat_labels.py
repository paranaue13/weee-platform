"""Αντιστοίχιση ετικετών Excel → υλικά Μητρώων (μόνιμη), υποκατηγορίες χύδην (00195), ομάδες ετικετών (ΠΛΑΣΤΙΚΑ ΜΕΡΗ), «Πού χρησιμοποιείται» υλικού.

Κανόνας: αν μια ετικέτα έχει ΡΗΤΗ αντιστοίχιση (πίνακας material_label_maps), ισχύει αυτή· αλλιώς ισχύει η παλιά ταύτιση με το όνομα του υλικού.
Μία ετικέτα (ανά πηγή EXCEL/PRESS) έχει ένα υλικό· ένα υλικό μπορεί να έχει πολλές ετικέτες."""
from datetime import datetime, timezone
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select, func
from sqlalchemy.orm import Session
from .db import get_db
from .security import require_permission
from . import models
from .models import Material, MaterialLabelMap, User
from .audit import write_audit
from .mat_warehouse import _fold_key, _norm, materials_with_column, LABEL_GROUP_TAB

router = APIRouter(prefix="/mat", tags=["material-labels"])
KINDS = {"MATERIAL", "BULK_SUB", "RECEIPTS", "SUM", "NONE"}


def explicit_maps(db: Session, source: str = "EXCEL") -> dict:
    """{label_key: MaterialLabelMap} για την πηγή (EXCEL = καρτέλες Υλικών, PRESS = στήλες Πρέσας)."""
    return {m.label_key: m for m in db.scalars(select(MaterialLabelMap).where(MaterialLabelMap.source == source)).all()}


def explicit_labels_of(db: Session) -> dict:
    """{material_id: [ετικέτες EXCEL που ανήκουν ρητά σε αυτό (MATERIAL ή BULK_SUB)]}"""
    out: dict = {}
    for m in db.scalars(select(MaterialLabelMap).where(MaterialLabelMap.source == "EXCEL", MaterialLabelMap.kind.in_(["MATERIAL", "BULK_SUB"]))).all():
        if m.material_id:
            out.setdefault(m.material_id, []).append(m.label)
    return out


def _count_labels(db: Session) -> dict:
    cnt: dict = {}
    for t in (models.MaterialOutputEntry, models.MaterialShipmentEntry, models.MaterialOpeningStock):
        for lb, n in db.execute(select(t.material_label, func.count()).where(t.active == True).group_by(t.material_label)).all():
            if lb:
                cnt[lb] = cnt.get(lb, 0) + n
    return cnt


def _mat_brief(m: Material, twins: list) -> dict:
    return {"id": m.id, "erp": m.galaxy_code, "name": (m.official_description or m.internal_name or "").strip(), "active": bool(m.active), "comm": bool(m.is_commercial),
            "umbrella": bool(m.is_umbrella), "label_group": m.label_group, "twins": twins, "genre": m.genre}


@router.get("/label-universe")
def label_universe(excel: int = 0, db: Session = Depends(get_db), user=Depends(require_permission("production.view"))):
    """Όλα όσα χρειάζεται η σελίδα αντιστοίχισης: ετικέτες Excel (με πλήθος εγγραφών και ομάδα), στήλες Πρέσας, ΟΛΑ τα υλικά (και ανενεργά), κατηγορίες ΑΗΗΕ και τρέχουσες ρητές αντιστοιχίσεις."""
    cnt = _count_labels(db)
    first_group: dict = {}
    for t in (models.MaterialOpeningStock, models.MaterialOutputEntry, models.MaterialShipmentEntry):
        for lb, g in db.execute(select(t.material_label, t.category_group).where(t.active == True)).all():
            if lb and lb not in first_group:
                first_group[lb] = g
    months: dict = {}; groups: dict = {}
    for t, dc in ((models.MaterialOpeningStock, models.MaterialOpeningStock.as_of_date), (models.MaterialOutputEntry, models.MaterialOutputEntry.work_date), (models.MaterialShipmentEntry, models.MaterialShipmentEntry.work_date)):
        for lb, g, d in db.execute(select(t.material_label, t.category_group, dc).where(t.active == True).distinct()).all():
            if lb and d:
                months.setdefault(lb, set()).add(d.strftime("%Y-%m"))
            if lb and g:
                groups.setdefault(lb, set()).add(g)
    pmonths: dict = {}
    for g, d in db.execute(select(models.BaleEntry.material_group, models.BaleEntry.period).where(models.BaleEntry.active == True).distinct()).all():
        if g and d:
            pmonths.setdefault(g, set()).add(d.strftime("%Y-%m"))
    ov = {r.material_label: r.category_group for r in db.scalars(select(models.MaterialGroupOverride)).all()}
    maps = explicit_maps(db, "EXCEL"); pmaps = explicit_maps(db, "PRESS")
    mats = db.scalars(select(Material)).all()
    by_name: dict = {}
    for m in mats:
        for n in (m.official_description, m.internal_name, m.galaxy_description):
            if n:
                by_name.setdefault(_fold_key(n), set()).add(m.id)
    byid = {m.id: m for m in mats}
    def twins_of(m):
        s = set()
        for n in (m.official_description, m.internal_name, m.galaxy_description):
            if n:
                s |= by_name.get(_fold_key(n), set())
        s.discard(m.id)
        return sorted(byid[i].galaxy_code or "—" for i in s if byid[i].active)
    def mp(x):
        return None if not x else {"kind": x.kind, "material_id": x.material_id, "weee_category_id": x.weee_category_id, "group_name": x.group_name, "active": bool(x.active), "sort_order": x.sort_order}
    labels = []
    for lb in sorted(first_group, key=lambda l: (-cnt.get(l, 0), l)):
        k = _fold_key(lb)
        derived = sorted(by_name.get(k, set()), key=lambda i: (not byid[i].active, byid[i].galaxy_code or ""))
        labels.append({"source": "EXCEL", "label": lb, "n": cnt.get(lb, 0), "group": ov.get(lb) or first_group[lb], "raw_group": first_group[lb], "map": mp(maps.get(k)), "derived": derived, "months": sorted(months.get(lb, [])), "groups": sorted(groups.get(lb, []))})
    press = []
    pc: dict = {}
    for g, n in db.execute(select(models.BaleEntry.material_group, func.count()).where(models.BaleEntry.active == True).group_by(models.BaleEntry.material_group)).all():
        pc[g] = n
    for g, n in sorted(pc.items(), key=lambda x: -x[1]):
        k = _fold_key(g)
        derived = sorted(by_name.get(k, set()) | {m.id for m in mats if m.press_label and _fold_key(m.press_label) == k}, key=lambda i: (not byid[i].active, byid[i].galaxy_code or ""))
        press.append({"source": "PRESS", "label": g, "n": n, "group": "Πρέσα", "map": mp(pmaps.get(k)), "derived": derived, "months": sorted(pmonths.get(g, [])), "groups": ["Πρέσα"]})
    # Στήλες που η Πρέσα εμφανίζει ΠΑΝΤΑ από υλικά με «Μπορεί να γίνει μπάλα» (δεν υπάρχουν σε Excel Πρέσας)
    have = {_fold_key(p["label"]) for p in press}
    for m in mats:
        if m.active and m.can_bale and not m.is_commercial:
            nm = (m.press_label or "").strip() or m.official_description or m.internal_name
            if nm and _fold_key(nm) not in have:
                have.add(_fold_key(nm))
                press.append({"source": "PRESS", "label": nm, "n": 0, "group": "Πρέσα", "map": mp(pmaps.get(_fold_key(nm))), "derived": [m.id], "months": [], "groups": ["Πρέσα"], "from_app": True})
    xl_info = None
    if excel:
        # ΠΡΟΣΩΡΙΝΟ εργαλείο «Εισαγωγή από Excel»: οι ετικέτες προέρχονται ΚΑΙ από τα Excel (μόνο ανάγνωση), σε όλους τους μήνες και όλες τις καρτέλες
        from .excel_labels_tool import scan
        sc = scan()
        press = [p for p in press if not p.get("from_app")]
        by_key = {_fold_key(l["label"]): l for l in labels}
        added = []
        for e in sorted(sc["labels"], key=lambda e: (-e["n"], e["label"])):
            k = _fold_key(e["label"]); ex = by_key.get(k)
            sheets = e["sheets"]
            prim = max(sheets, key=lambda g: sheets[g]["n"]) if sheets else "AXIOPOIISIMA"
            if ex:
                ex["months"] = sorted(set(ex["months"]) | set(e["months"])); ex["xl_sheets"] = sorted(set(ex.get("xl_sheets", [])) | set(sheets)); ex["xl_n"] = ex.get("xl_n", 0) + e["n"]
                if e["plaketes"]: ex["plaketes"] = True
                continue
            derived = sorted(by_name.get(k, set()), key=lambda i: (not byid[i].active, byid[i].galaxy_code or ""))
            nl = {"source": "EXCEL", "label": e["label"], "n": e["n"], "group": ov.get(e["label"]) or ("PLAKETES" if e["plaketes"] else prim), "raw_group": prim, "map": mp(maps.get(k)), "derived": derived,
                  "months": e["months"], "groups": sorted(sheets), "xl_only": True, "xl_sheets": sorted(sheets), "xl_n": e["n"], "empty": e["n"] == 0, "plaketes": e["plaketes"]}
            labels.append(nl); by_key[k] = nl; added.append(e["label"])
        pk = {_fold_key(p["label"]): p for p in press}
        added_press = []
        for e in sc["press"]:
            k = _fold_key(e["label"])
            if k in pk:
                pk[k]["months"] = sorted(set(pk[k]["months"]) | set(e["months"])); pk[k]["xl_n"] = e["n"]; continue
            derived = sorted(by_name.get(k, set()) | {m.id for m in mats if m.press_label and _fold_key(m.press_label) == k}, key=lambda i: (not byid[i].active, byid[i].galaxy_code or ""))
            np_ = {"source": "PRESS", "label": e["label"], "n": e["n"], "group": "Πρέσα", "map": mp(pmaps.get(k)), "derived": derived, "months": e["months"], "groups": ["Πρέσα"], "xl_only": True, "xl_n": e["n"], "empty": e["n"] == 0}
            press.append(np_); added_press.append(e["label"])
        xl_info = {"folder": sc["folder"], "files": sc["files"], "warnings": sc["warnings"], "added": added, "added_press": added_press}
    return {"labels": labels, "press": press, "materials": [_mat_brief(m, twins_of(m)) for m in sorted(mats, key=lambda m: (not m.active, m.galaxy_code or "ΖΖΖ", m.internal_name or ""))],
            "weee": _weee_stock(db), "excel": xl_info}


def _weee_stock(db: Session) -> list:
    """Κατηγορίες ΑΗΗΕ (κωδικοί Αποθήκης ΑΗΗΕ) με το απόθεμα προς αποστολή (διαθέσιμο βάρος παρτίδων), για στήλες «από παραλαβές»."""
    stock = {cid: float(w or 0) for cid, w in db.execute(select(models.WEEEStockLot.weee_category_id, func.sum(models.WEEEStockLot.available_weight)).group_by(models.WEEEStockLot.weee_category_id)).all()}
    cats = db.scalars(select(models.WEEECategory).where(models.WEEECategory.active == True, models.WEEECategory.is_internal_subcategory == False).order_by(models.WEEECategory.code)).all()
    return [{"id": c.id, "code": c.code, "name": c.description_el, "her": c.her_description, "stock_kg": round(stock.get(c.id, 0.0), 3)} for c in cats]


class MapItem(BaseModel):
    source: str = "EXCEL"
    label: str
    kind: str                                  # MATERIAL | BULK_SUB | RECEIPTS | SUM | NONE | CLEAR
    material_id: str | None = None
    weee_category_id: str | None = None
    group_name: str | None = None
    active: bool = True
    sort_order: int = 0
    sheet: str | None = None


class MapSave(BaseModel):
    items: list[MapItem]


@router.post("/label-maps/save")
def save_label_maps(data: MapSave, db: Session = Depends(get_db), user: User = Depends(require_permission("master.edit"))):
    """Αποθηκεύει (upsert) ρητές αντιστοιχίσεις· kind=CLEAR αφαιρεί την αντιστοίχιση της ετικέτας (επιστρέφει στην ταύτιση με το όνομα)."""
    n_set = n_del = 0
    for it in data.items:
        if it.source not in ("EXCEL", "PRESS", "COMMERCIAL"):
            raise HTTPException(422, "Άγνωστη πηγή ετικέτας")
        lb = (it.label or "").strip()
        if not lb:
            raise HTTPException(422, "Κενή ετικέτα")
        key = _fold_key(lb)
        row = db.scalar(select(MaterialLabelMap).where(MaterialLabelMap.source == it.source, MaterialLabelMap.label_key == key))
        if it.kind == "CLEAR":
            if row:
                write_audit(db, user, "material_label_map", row.id, "DELETE", old={"label": row.label, "kind": row.kind, "material_id": row.material_id})
                db.delete(row); n_del += 1
            continue
        if it.kind not in KINDS:
            raise HTTPException(422, "Άγνωστο είδος αντιστοίχισης")
        if it.kind in ("MATERIAL", "BULK_SUB"):
            m = db.get(Material, it.material_id) if it.material_id else None
            if not m:
                raise HTTPException(422, "Διάλεξε υλικό για την ετικέτα «" + lb + "»")
            if it.kind == "BULK_SUB" and not m.is_umbrella:
                raise HTTPException(422, "Το υλικό " + (m.galaxy_code or m.internal_name or "") + " δεν έχει ενεργή την ομαδοποίηση υποπροϊόντων (Προφίλ Υλικού)")
        if it.kind == "SUM" and not (it.group_name or "").strip():
            raise HTTPException(422, "Γράψε το όνομα της ομάδας για την ετικέτα «" + lb + "»")
        if it.kind == "RECEIPTS" and not it.weee_category_id:
            raise HTTPException(422, "Διάλεξε κωδικό ΑΗΗΕ για την ετικέτα «" + lb + "»")
        old = None
        if row:
            old = {"kind": row.kind, "material_id": row.material_id, "weee_category_id": row.weee_category_id, "group_name": row.group_name}
        else:
            row = MaterialLabelMap(source=it.source, label=lb, label_key=key); db.add(row)
        row.label = lb; row.kind = it.kind
        row.material_id = it.material_id if it.kind in ("MATERIAL", "BULK_SUB") else None
        row.weee_category_id = it.weee_category_id if it.kind == "RECEIPTS" else None
        row.group_name = (it.group_name or "").strip() or None if it.kind == "SUM" else None
        row.active = bool(it.active); row.sort_order = int(it.sort_order or 0)
        if "sheet" in it.model_fields_set:
            row.sheet = (it.sheet or "").strip() or None
        db.flush()
        write_audit(db, user, "material_label_map", row.id, "UPSERT", old=old, new={"label": lb, "source": it.source, "kind": it.kind, "material_id": row.material_id, "weee_category_id": row.weee_category_id, "group_name": row.group_name})
        n_set += 1
    db.commit()
    return {"saved": n_set, "cleared": n_del}


@router.get("/label-maps/effective")
def label_maps_effective(db: Session = Depends(get_db), user=Depends(require_permission("production.view"))):
    """Ό,τι χρειάζονται οι καρτέλες Υλικών: ρητές αντιστοιχίσεις, υλικά-ομπρέλες με υποκατηγορίες, ομάδες ετικετών με μέλη, ανενεργά υλικά (για ταύτιση με το όνομα)."""
    mats = {m.id: m for m in db.scalars(select(Material)).all()}
    maps = db.scalars(select(MaterialLabelMap).order_by(MaterialLabelMap.sort_order, MaterialLabelMap.label)).all()
    rows = [{"source": x.source, "label": x.label, "key": x.label_key, "kind": x.kind, "material_id": x.material_id, "weee_category_id": x.weee_category_id, "group_name": x.group_name, "active": bool(x.active), "sort_order": x.sort_order, "sheet": x.sheet,
             "material_active": bool(mats[x.material_id].active) if x.material_id in mats else None,
             "material_name": ((mats[x.material_id].official_description or mats[x.material_id].internal_name) if x.material_id in mats else None)} for x in maps]
    umbrellas = []
    for m in sorted([m for m in mats.values() if m.is_umbrella], key=lambda m: m.galaxy_code or ""):
        subs = [{"label": x.label, "active": bool(x.active), "sort_order": x.sort_order} for x in maps if x.kind == "BULK_SUB" and x.material_id == m.id and x.source == "EXCEL"]
        umbrellas.append({"id": m.id, "erp": m.galaxy_code, "name": (m.official_description or m.internal_name or "").strip(), "active": bool(m.active), "subs": subs})
    groups: dict = {}
    for m in mats.values():
        if m.label_group:
            groups.setdefault(m.label_group, []).append({"id": m.id, "erp": m.galaxy_code, "name": (m.official_description or m.internal_name or "").strip(), "active": bool(m.active),
                                                          "order": m.label_group_order or 0, "short": (m.short_description or "").strip(), "can_bale": bool(m.can_bale), "press_column": (m.press_label or "").strip() or (m.official_description or m.internal_name or "").strip()})
    return {"group_tabs": LABEL_GROUP_TAB, "maps": rows, "umbrellas": umbrellas, "weee_stock": {w["id"]: w["stock_kg"] for w in _weee_stock(db)}, "groups": [{"name": k, "members": sorted(v, key=lambda x: (x["order"], x["name"]))} for k, v in sorted(groups.items())],
            "inactive_names": sorted({n for m in mats.values() if not m.active for n in (m.official_description, m.internal_name, m.galaxy_description) if n})}


class SubItem(BaseModel):
    label: str
    active: bool = True


class SubsSave(BaseModel):
    subs: list[SubItem]


@router.put("/umbrella/{material_id}/subs")
def save_umbrella_subs(material_id: str, data: SubsSave, db: Session = Depends(get_db), user: User = Depends(require_permission("master.edit"))):
    """Λίστα υποκατηγοριών χύδην ενός υλικού-ομπρέλας: σειρά = σειρά της λίστας, Ενεργό/Μη ενεργό ανά υποκατηγορία. Υποκατηγορία που λείπει από τη λίστα αποσυνδέεται."""
    m = db.get(Material, material_id)
    if not m:
        raise HTTPException(404, "Το υλικό δεν βρέθηκε")
    if not m.is_umbrella:
        raise HTTPException(422, "Ενεργοποίησε πρώτα την ομαδοποίηση υποπροϊόντων στο υλικό")
    keep = set()
    for i, s in enumerate(data.subs):
        lb = (s.label or "").strip()
        if not lb:
            continue
        key = _fold_key(lb); keep.add(key)
        row = db.scalar(select(MaterialLabelMap).where(MaterialLabelMap.source == "EXCEL", MaterialLabelMap.label_key == key))
        if row and row.kind == "BULK_SUB" and row.material_id != m.id:
            raise HTTPException(409, "Η υποκατηγορία «" + lb + "» ανήκει ήδη σε άλλο υλικό-ομπρέλα")
        if row and row.kind != "BULK_SUB":
            row.kind = "BULK_SUB"
        if not row:
            row = MaterialLabelMap(source="EXCEL", label=lb, label_key=key, kind="BULK_SUB"); db.add(row)
        row.material_id = m.id; row.active = bool(s.active); row.sort_order = i; row.label = lb
    for row in db.scalars(select(MaterialLabelMap).where(MaterialLabelMap.source == "EXCEL", MaterialLabelMap.kind == "BULK_SUB", MaterialLabelMap.material_id == m.id)).all():
        if row.label_key not in keep:
            db.delete(row)
    write_audit(db, user, "material", m.id, "UPDATE", new={"umbrella_subs": [s.label for s in data.subs]}, reason="Υποκατηγορίες χύδην")
    db.commit()
    return {"ok": True, "count": len(data.subs)}


class OrderSave(BaseModel):
    material_ids: list[str]


@router.put("/label-group/{name}/order")
def save_group_order(name: str, data: OrderSave, db: Session = Depends(get_db), user: User = Depends(require_permission("master.edit"))):
    for i, mid in enumerate(data.material_ids):
        m = db.get(Material, mid)
        if m and (m.label_group or "") == name:
            m.label_group_order = i
    db.commit()
    return {"ok": True}


def history_reasons(db: Session, m: Material) -> list:
    """Λόγοι για τους οποίους το υλικό ΔΕΝ διαγράφεται οριστικά: ιστορικό κινήσεων ή αντιστοιχίσεις."""
    why = []
    q = lambda stmt: db.scalar(stmt) or 0
    n = q(select(func.count()).select_from(models.ReadyMaterialLot).where(models.ReadyMaterialLot.material_id == m.id))
    if n: why.append(f"{n} παρτίδες/εξαγωγές")
    n = q(select(func.count()).select_from(models.MaterialInventoryEntry).where(models.MaterialInventoryEntry.material_id == m.id))
    if n: why.append(f"{n} ζυγίσεις απογραφής")
    n = q(select(func.count()).select_from(models.CommercialExport).where(models.CommercialExport.material_id == m.id))
    if n: why.append(f"{n} εξαγωγές εμπορικού")
    n = q(select(func.count()).select_from(MaterialLabelMap).where(MaterialLabelMap.material_id == m.id))
    if n: why.append(f"{n} αντιστοιχίσεις ετικετών")
    n = q(select(func.count()).select_from(models.DirectProcessingMapping).where(models.DirectProcessingMapping.output_material_id == m.id))
    if n: why.append(f"{n} αντιστοιχίσεις επεξεργασίας")
    keys = {_fold_key(x) for x in (m.official_description, m.internal_name, m.galaxy_description) if x}
    cnt = 0
    for t in (models.MaterialOutputEntry, models.MaterialShipmentEntry):
        for (lb,) in db.execute(select(t.material_label).where(t.active == True).distinct()).all():
            if lb and _fold_key(lb) in keys:
                cnt += db.scalar(select(func.count()).select_from(t).where(t.material_label == lb, t.active == True)) or 0
    if cnt: why.append(f"{cnt} εγγραφές Excel με το ίδιο όνομα")
    return why


@router.get("/usage/{material_id}")
def material_usage(material_id: str, db: Session = Depends(get_db), user=Depends(require_permission("production.view"))):
    """«Πού χρησιμοποιείται» (μόνο ανάγνωση): κινήσεις, τρέχον απόθεμα, ετικέτες Excel που ανήκουν στο υλικό, λόγοι κλειδώματος της οριστικής διαγραφής."""
    from .mat_warehouse import available_by_material
    m = db.get(Material, material_id)
    if not m:
        raise HTTPException(404, "Το υλικό δεν βρέθηκε")
    lots = db.scalar(select(func.count()).select_from(models.ReadyMaterialLot).where(models.ReadyMaterialLot.material_id == m.id, models.ReadyMaterialLot.status != "CANCELLED")) or 0
    inv = db.scalar(select(func.count()).select_from(models.MaterialInventoryEntry).where(models.MaterialInventoryEntry.material_id == m.id)) or 0
    cex = db.scalar(select(func.count()).select_from(models.CommercialExport).where(models.CommercialExport.material_id == m.id, models.CommercialExport.active == True)) or 0
    stock = available_by_material(db, [m]).get(m.id, 0.0)
    wh = 0.0
    try:
        from .mat_warehouse import _commercial_stock
        wh = _commercial_stock(db).get(m.id, 0.0) if m.is_commercial else 0.0
    except Exception:
        pass
    labels = [x.label for x in db.scalars(select(MaterialLabelMap).where(MaterialLabelMap.material_id == m.id, MaterialLabelMap.source == "EXCEL")).all()]
    why = history_reasons(db, m)
    return {"id": m.id, "lots": lots, "inventory": inv, "commercial_exports": cex, "moves": lots + inv + cex, "stock_kg": round(wh if m.is_commercial else stock, 3),
            "mapped_labels": labels, "delete_locked": bool(why), "delete_reasons": why}


@router.get("/label-maps/uncovered")
def uncovered_materials(db: Session = Depends(get_db), user=Depends(require_permission("production.view"))):
    """Ενεργά υλικά του μητρώου που ΔΕΝ έχουν στήλη σε καρτέλα Υλικών (καμία κίνηση δεν γίνεται δεκτή γι' αυτά)."""
    ok = materials_with_column(db)
    return [{"id": m.id, "code": m.galaxy_code, "name": (m.official_description or m.internal_name or "").strip(), "commercial": bool(m.is_commercial)}
            for m in db.scalars(select(Material).where(Material.active == True).order_by(Material.galaxy_code)).all() if m.id not in ok]


# ===== Καρτέλες Υλικών: σε ποια από τις καρτέλες της σελίδας Υλικά (και με ποια σειρά) φαίνεται κάθε υλικό =====
# Χρησιμοποιεί ΜΟΝΟ ό,τι υπάρχει ήδη: αντικατάσταση ομάδας ανά ετικέτα (material_group_overrides: ομάδα + σειρά ανά στήλη) και καρτέλα ετικέτας (material_label_maps.sheet).
# Οι καρτέλες ορίζονται στον πίνακα material_tabs (οι 4 σύστημα + του χρήστη)· τίποτα δεν είναι γραμμένο εδώ.
import re as _re
import uuid as _uuid
from .mat_warehouse import active_tabs, column_tab_codes, ensure_material_tabs, DEFAULT_TAB, SYSTEM_TABS

# ονόματα που δεν επιτρέπονται σε νέα/μετονομασμένη καρτέλα: οι άλλες καρτέλες της σελίδας Υλικά και η στήλη «Χωρίς καρτέλα»
RESERVED_TAB_NAMES = ["Πρέσα", "Εμπορικά", "Υλικά από εμπόριο", "Αποθήκη", "Χωρίς καρτέλα", "Όλες"]


def _label_tab(lb, x, g, ov, codes):
    """Καρτέλα μιας ετικέτας όπως τη βρίσκει η σελίδα Υλικά: «Πλακέτες» από την καρτέλα της αντιστοίχισης, αλλιώς αντικατάσταση ομάδας ή πρώτη ομάδα καταχώρησης.
    Δίχτυ ασφαλείας: ομάδα που δεν είναι ενεργή καρτέλα (π.χ. διαγραμμένη) πέφτει στα Αξιοποιήσιμα, δεν εξαφανίζεται."""
    if x.sheet == "PLAKETES":
        return "PLAKETES"
    grp = ov[lb].category_group if lb in ov else g
    return grp if grp in codes else DEFAULT_TAB


def _tab_cards_state(db: Session) -> dict:
    mats = {m.id: m for m in db.scalars(select(Material)).all()}
    maps = db.scalars(select(MaterialLabelMap)).all()
    ov = {r.material_label: r for r in db.scalars(select(models.MaterialGroupOverride)).all()}
    tabs = active_tabs(db)
    codes = {t["code"] for t in tabs}
    raw: dict = {}
    for t in (models.MaterialOpeningStock, models.MaterialOutputEntry, models.MaterialShipmentEntry):
        for lb, g in db.execute(select(t.material_label, t.category_group).where(t.active == True)).all():
            if lb and lb not in raw:
                raw[lb] = g
    xl = {x.label_key: x for x in maps if x.source == "EXCEL"}
    labels_of: dict = {}
    seen_keys = set()
    for lb, g in raw.items():
        k = _fold_key(lb)
        x = xl.get(k)
        if x and x.material_id and x.kind in ("MATERIAL", "BULK_SUB"):
            labels_of.setdefault(x.material_id, []).append((lb, x, g))
            seen_keys.add(k)
    for k, x in xl.items():
        if x.material_id and x.kind in ("MATERIAL", "BULK_SUB") and k not in seen_keys and x.sheet and x.sheet != "COMMERCIAL":
            labels_of.setdefault(x.material_id, []).append((x.label, x, "EIDIKIS_DIACHEIRISIS" if x.sheet == "PLAKETES" else x.sheet))
    other_src: dict = {}
    for x in maps:
        if x.source in ("PRESS", "COMMERCIAL") and x.material_id:
            other_src.setdefault(x.material_id, set()).add(x.source)
    rows = []
    for m in mats.values():
        name = (m.official_description or m.internal_name or "").strip()
        ls = labels_of.get(m.id, [])
        row = {"id": m.id, "erp": m.galaxy_code or "", "name": name, "active": bool(m.active), "tab": None, "ord": 0, "locked": None, "mixed": False, "key": None, "labels": [x[0] for x in ls]}
        if m.is_commercial or "COMMERCIAL" in other_src.get(m.id, set()):
            row["locked"] = "Εμπορικό υλικό: η καρτέλα του ορίζεται από τα Εμπορικά"
        elif (m.label_group or "").strip():
            row["locked"] = "Ανήκει στην ομάδα ετικέτας «" + m.label_group + "»: μετακινείται μόνο από το Προφίλ Υλικού"
        elif not ls and ("PRESS" in other_src.get(m.id, set()) or m.can_bale or (m.press_label or "").strip()):
            row["locked"] = "Υλικό Πρέσας: η στήλη του ορίζεται από την Πρέσα"
        if ls:
            tabs_l = [_label_tab(lb, x, g, ov, codes) for lb, x, g in ls]
            cnt: dict = {}
            for t in tabs_l:
                cnt[t] = cnt.get(t, 0) + 1
            row["tab"] = max(cnt, key=lambda t: cnt[t])
            row["mixed"] = len(cnt) > 1
            in_tab = [(lb, x) for (lb, x, g), t in zip(ls, tabs_l) if t == row["tab"]]
            if any(x.kind == "BULK_SUB" for lb, x in in_tab):
                row["key"] = "UMB:" + m.id
            elif len(in_tab) > 1:
                row["key"] = "MAT:" + m.id
            else:
                row["key"] = in_tab[0][0]
            row["title"] = name if row["key"].startswith(("UMB:", "MAT:")) else row["key"]
            if row["key"] in ov:
                row["ord"] = ov[row["key"]].sort_order or 0
            elif row["key"].startswith("UMB:"):
                row["ord"] = min([(ov[lb].sort_order or 0) for lb, x in in_tab if lb in ov] or [0])
        if row["tab"] not in codes:
            row["tab"] = None
        rows.append(row)
    return {"rows": rows, "mats": mats, "ov": ov, "xl": xl, "labels_of": labels_of, "tabs": tabs, "codes": codes}


@router.get("/tabs")
def mat_tabs(db: Session = Depends(get_db), user=Depends(require_permission("production.view"))):
    """Οι ενεργές καρτέλες της σελίδας Υλικά με τη σειρά τους."""
    return {"tabs": active_tabs(db)}


@router.get("/tab-cards")
def tab_cards(db: Session = Depends(get_db), user=Depends(require_permission("production.view"))):
    """Υλικά με την καρτέλα της σελίδας Υλικά όπου φαίνονται σήμερα και τη σειρά τους εκεί (μόνο ανάγνωση)."""
    st = _tab_cards_state(db)
    rows = st["rows"]
    rows.sort(key=lambda r: (r["ord"], _fold_key(r["labels"][0] if r["labels"] else r["name"]), r["erp"]))
    return {"tabs": [{"key": t["code"], "name": t["name"], "is_system": t["is_system"]} for t in st["tabs"]],
            "materials": [{**{k: v for k, v in r.items() if k != "labels"}, "n_labels": len(r["labels"])} for r in rows]}


class TabMove(BaseModel):
    material_id: str
    tab: str
    order: list[str]            # τα υλικά της στήλης-προορισμού (μαζί με αυτό που μετακινείται) με τη νέα σειρά· τα κλειδωμένα αγνοούνται


@router.put("/tab-cards/move")
def tab_cards_move(data: TabMove, db: Session = Depends(get_db), user: User = Depends(require_permission("master.edit"))):
    """Μετακίνηση υλικού σε καρτέλα και/ή αλλαγή σειράς. Δεν πειράζει υλικά με δικό τους κανόνα (Πρέσα, Εμπορικά, ομάδες ετικετών)."""
    st = _tab_cards_state(db)
    if data.tab not in st["codes"]:
        raise HTTPException(422, "Άγνωστη καρτέλα")
    byid = {r["id"]: r for r in st["rows"]}
    mv = byid.get(data.material_id)
    if not mv:
        raise HTTPException(404, "Το υλικό δεν βρέθηκε")
    if mv["locked"]:
        raise HTTPException(409, mv["locked"])
    if data.material_id not in data.order:
        raise HTTPException(422, "Λείπει το υλικό από τη σειρά")
    ov, xl, mats = st["ov"], st["xl"], st["mats"]
    group = "EIDIKIS_DIACHEIRISIS" if data.tab == "PLAKETES" else data.tab
    m = mats[data.material_id]
    labs = list(st["labels_of"].get(m.id, []))
    if not labs:
        name = (m.official_description or m.internal_name or "").strip()
        if not name:
            raise HTTPException(422, "Το υλικό δεν έχει περιγραφή για να δημιουργηθεί στήλη")
        k = _fold_key(name)
        if k in xl:
            raise HTTPException(409, "Υπάρχει ήδη ετικέτα «" + xl[k].label + "» που ανήκει σε άλλο υλικό")
        row = MaterialLabelMap(source="EXCEL", label=name, label_key=k, kind="MATERIAL", material_id=m.id, active=True, sort_order=0, sheet=data.tab)
        db.add(row)
        db.flush()
        write_audit(db, user, "material_label_map", row.id, "UPSERT", new={"label": name, "kind": "MATERIAL", "material_id": m.id, "sheet": data.tab}, reason="Καρτέλες Υλικών: νέα στήλη")
        labs = [(name, row, group)]
        xl[k] = row
    for lb, x, g in labs:
        if x.sheet != data.tab:
            old = x.sheet
            x.sheet = data.tab
            write_audit(db, user, "material_label_map", x.id, "UPSERT", old={"sheet": old}, new={"sheet": data.tab}, reason="Καρτέλες Υλικών: αλλαγή καρτέλας")
        o = ov.get(lb)
        if o:
            o.category_group = group
        else:
            ov[lb] = models.MaterialGroupOverride(material_label=lb, category_group=group, sort_order=0)
            db.add(ov[lb])

    def colkey(mat, ls_):
        if any(x.kind == "BULK_SUB" for lb, x, g in ls_):
            return "UMB:" + mat.id
        return "MAT:" + mat.id if len(ls_) > 1 else ls_[0][0]

    # σειρά: μόνο τα μη κλειδωμένα της στήλης-προορισμού· μπαίνουν ΜΕΤΑ από τα κλειδωμένα της ίδιας στήλης (ώστε η σειρά της οθόνης = σειρά της σελίδας)
    base = max([r["ord"] for r in st["rows"] if r["tab"] == data.tab and r["locked"]] or [0])
    for i, mid in enumerate(data.order):
        mt = mats.get(mid)
        if not mt or byid[mid]["locked"]:
            continue
        if mid == m.id:
            ls = labs
        elif byid[mid]["tab"] == data.tab:
            ls = st["labels_of"].get(mid, [])
        else:
            continue
        if not ls:
            continue
        key = colkey(mt, ls)
        o = ov.get(key)
        if o:
            o.sort_order = base + 1 + i
        else:
            ov[key] = models.MaterialGroupOverride(material_label=key, category_group=group, sort_order=base + 1 + i)
            db.add(ov[key])
    write_audit(db, user, "material", m.id, "UPDATE", new={"tab": data.tab, "order": data.order}, reason="Καρτέλες Υλικών")
    db.commit()
    return {"ok": True}


# ----- Καρτέλες του χρήστη: δημιουργία / μετονομασία / διαγραφή (απενεργοποίηση) -----
class TabName(BaseModel):
    name: str


def _clean_tab_name(db: Session, raw: str, exclude_code: str | None = None) -> str:
    name = _re.sub(r"\s+", " ", (raw or "").strip())
    if not name:
        raise HTTPException(422, "Γράψε όνομα καρτέλας")
    if len(name) > 60:
        raise HTTPException(422, "Το όνομα είναι πολύ μεγάλο (έως 60 χαρακτήρες)")
    k = _fold_key(name)
    for r in RESERVED_TAB_NAMES:
        if _fold_key(r) == k:
            raise HTTPException(409, "Το όνομα «" + name + "» χρησιμοποιείται ήδη")
    for t in db.scalars(select(models.MaterialTab).where(models.MaterialTab.active == True)).all():
        if t.code != exclude_code and _fold_key(t.name) == k:
            raise HTTPException(409, "Υπάρχει ήδη καρτέλα με όνομα «" + t.name + "»")
    return name


def _custom_tab(db: Session, code: str) -> "models.MaterialTab":
    t = db.scalar(select(models.MaterialTab).where(models.MaterialTab.code == code))
    if not t or not t.active:
        raise HTTPException(404, "Η καρτέλα δεν βρέθηκε")
    if t.is_system:
        raise HTTPException(403, "Οι καρτέλες του συστήματος δεν μετονομάζονται και δεν διαγράφονται")
    return t


@router.post("/tabs")
def mat_tab_create(data: TabName, db: Session = Depends(get_db), user: User = Depends(require_permission("master.edit"))):
    ensure_material_tabs(db)
    name = _clean_tab_name(db, data.name)
    last = max([t.sort_order or 0 for t in db.scalars(select(models.MaterialTab)).all()] or [0])
    t = models.MaterialTab(code="TAB_" + _uuid.uuid4().hex[:8].upper(), name=name, sort_order=max(last, 90) + 10, is_system=False, active=True)
    db.add(t)
    db.flush()
    write_audit(db, user, "material_tab", t.id, "CREATE", new={"code": t.code, "name": name})
    db.commit()
    return {"code": t.code, "name": t.name}


@router.put("/tabs/{code}")
def mat_tab_rename(code: str, data: TabName, db: Session = Depends(get_db), user: User = Depends(require_permission("master.edit"))):
    t = _custom_tab(db, code)
    name = _clean_tab_name(db, data.name, exclude_code=code)
    old = t.name
    t.name = name           # ο εσωτερικός κωδικός μένει ίδιος
    write_audit(db, user, "material_tab", t.id, "UPDATE", old={"name": old}, new={"name": name})
    db.commit()
    return {"code": t.code, "name": t.name}


@router.delete("/tabs/{code}")
def mat_tab_delete(code: str, db: Session = Depends(get_db), user: User = Depends(require_permission("master.edit"))):
    """Απενεργοποιεί την καρτέλα. ΟΛΑ τα υλικά της πάνε αυτόματα στα Αξιοποιήσιμα, στο τέλος τους, με την ίδια μεταξύ τους σειρά. Δεν σβήνεται υλικό ούτε κίνηση."""
    t = _custom_tab(db, code)
    st = _tab_cards_state(db)
    ov, labels_of = st["ov"], st["labels_of"]
    moving = sorted([r for r in st["rows"] if r["tab"] == code], key=lambda r: (r["ord"], _fold_key(r["labels"][0] if r["labels"] else r["name"]), r["erp"]))
    base = max([r["ord"] for r in st["rows"] if r["tab"] == DEFAULT_TAB] or [0])
    n_labels = 0
    for i, r in enumerate(moving):
        for lb, x, g in labels_of.get(r["id"], []):
            if x.sheet == code:
                x.sheet = DEFAULT_TAB
            o = ov.get(lb)
            if o:
                o.category_group = DEFAULT_TAB
            else:
                ov[lb] = models.MaterialGroupOverride(material_label=lb, category_group=DEFAULT_TAB, sort_order=0)
                db.add(ov[lb])
            n_labels += 1
        key = r["key"]
        if key:
            o = ov.get(key)
            if o:
                o.category_group = DEFAULT_TAB
                o.sort_order = base + 1 + i
            else:
                ov[key] = models.MaterialGroupOverride(material_label=key, category_group=DEFAULT_TAB, sort_order=base + 1 + i)
                db.add(ov[key])
    # υπόλοιπες αντικαταστάσεις/αντιστοιχίσεις που δείχνουν στην καρτέλα (π.χ. ετικέτες χωρίς υλικό): επίσης στα Αξιοποιήσιμα
    for o in db.scalars(select(models.MaterialGroupOverride).where(models.MaterialGroupOverride.category_group == code)).all():
        o.category_group = DEFAULT_TAB
    for x in db.scalars(select(MaterialLabelMap).where(MaterialLabelMap.sheet == code)).all():
        x.sheet = DEFAULT_TAB
    t.active = False
    write_audit(db, user, "material_tab", t.id, "DELETE", old={"code": t.code, "name": t.name}, new={"materials_moved": len(moving), "to": DEFAULT_TAB}, reason="Διαγραφή καρτέλας: τα υλικά πήγαν στα Αξιοποιήσιμα")
    db.commit()
    return {"ok": True, "moved": len(moving)}
