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
