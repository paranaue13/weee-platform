"""Καρτέλες Υλικών ανά μήνα (διάταξη/ομαδοποίηση). Ο τρέχων μήνας = ζωντανοί πίνακες· παλιότεροι μήνες = αποθηκευμένο στιγμιότυπο.

Πρώτη αλλαγή σε παλιό μήνα: δημιουργούνται στιγμιότυπα για ΟΛΟΥΣ τους παλιούς μήνες (αντίγραφο της τρέχουσας διάταξης), ώστε η αλλαγή ενός μήνα να μην επηρεάζει τους άλλους.
Ανάγνωση/εγγραφή παλιού μήνα: το στιγμιότυπο εφαρμόζεται προσωρινά σε ιδιωτική σύνδεση που ΠΑΝΤΑ ακυρώνεται (rollback)· ό,τι άλλαξε αποθηκεύεται ξανά ως στιγμιότυπο.
Δεν αγγίζονται ποτέ απόθεμα, κινήσεις, κιλά ή ιστορικό υλικών."""
import json
from datetime import datetime
from sqlalchemy import select
from sqlalchemy.orm import Session
from .db import engine
from . import models

FIRST_MONTH = "2026-01"


def month_now() -> str:
    return datetime.now().strftime("%Y-%m")


def is_past(month) -> bool:
    return bool(month) and len(str(month)) == 7 and str(month) < month_now()


def capture(db: Session) -> dict:
    ov = [{"label": o.material_label, "group": o.category_group, "ord": o.sort_order} for o in db.scalars(select(models.MaterialGroupOverride)).all()]
    mats = {m.id: [m.label_group, m.label_group_order or 0] for m in db.scalars(select(models.Material)).all() if (m.label_group or "").strip()}
    maps = [{"id": x.id, "source": x.source, "label": x.label, "key": x.label_key, "kind": x.kind, "mid": x.material_id, "wc": x.weee_category_id, "grp": x.group_name,
             "active": bool(x.active), "ord": x.sort_order, "sheet": x.sheet} for x in db.scalars(select(models.MaterialLabelMap).where(models.MaterialLabelMap.source == "EXCEL")).all()]
    return {"ov": ov, "mats": mats, "maps": maps}


def apply(db: Session, snap: dict):
    # αντικαταστάσεις ομάδας
    cur = {o.material_label: o for o in db.scalars(select(models.MaterialGroupOverride)).all()}
    want = {o["label"]: o for o in snap["ov"]}
    for k, o in cur.items():
        if k not in want:
            db.delete(o)
    for k, w in want.items():
        o = cur.get(k)
        if o:
            o.category_group = w["group"]; o.sort_order = w["ord"]
        else:
            db.add(models.MaterialGroupOverride(material_label=k, category_group=w["group"], sort_order=w["ord"]))
    # μέλη ετικετών (ομάδες ετικετών υλικών)
    for m in db.scalars(select(models.Material)).all():
        w = snap["mats"].get(m.id)
        lg, od = (w[0], w[1]) if w else (None, 0)
        if (m.label_group or None) != (lg or None) or (m.label_group_order or 0) != od:
            m.label_group = lg; m.label_group_order = od
    # αντιστοιχίσεις ετικετών Excel (καρτέλα/σειρά + στήλες που δημιουργήθηκαν όταν υλικό μπήκε σε καρτέλα)
    curm = {x.id: x for x in db.scalars(select(models.MaterialLabelMap).where(models.MaterialLabelMap.source == "EXCEL")).all()}
    wantm = {x["id"]: x for x in snap["maps"]}
    for i, x in curm.items():
        if i not in wantm:
            db.delete(x)
    for i, w in wantm.items():
        x = curm.get(i)
        if x:
            x.sheet = w["sheet"]; x.sort_order = w["ord"]; x.active = w["active"]; x.kind = w["kind"]; x.material_id = w["mid"]; x.group_name = w["grp"]
        else:
            db.add(models.MaterialLabelMap(id=i, source="EXCEL", label=w["label"], label_key=w["key"], kind=w["kind"], material_id=w["mid"], weee_category_id=w["wc"], group_name=w["grp"], active=w["active"], sort_order=w["ord"], sheet=w["sheet"]))
    db.flush()


def _months_before_now():
    y, m = map(int, FIRST_MONTH.split("-")); out = []
    cur = month_now()
    while f"{y:04d}-{m:02d}" < cur:
        out.append(f"{y:04d}-{m:02d}"); m += 1
        if m > 12: y += 1; m = 1
    return out


def materialize(db: Session):
    have = {s.month for s in db.scalars(select(models.MaterialLayoutSnapshot)).all()}
    todo = [m for m in _months_before_now() if m not in have]
    if not todo:
        return
    payload = json.dumps(capture(db), ensure_ascii=False)
    for m in todo:
        db.add(models.MaterialLayoutSnapshot(month=m, payload=payload))
    db.commit()


def snapshot_of(db: Session, month: str) -> dict:
    s = db.get(models.MaterialLayoutSnapshot, month)
    return json.loads(s.payload) if s else capture(db)


def _private(snap):
    """Ιδιωτική σύνδεση με ΠΡΑΓΜΑΤΙΚΟ BEGIN (το pysqlite δεν το στέλνει μόνο του)· το τέλος γίνεται ΠΑΝΤΑ με rollback, άρα ό,τι εφαρμόζεται εδώ δεν φτάνει ποτέ στη βάση."""
    conn = engine.connect()
    conn.exec_driver_sql("BEGIN")
    sess = Session(bind=conn, join_transaction_mode="create_savepoint", autoflush=False, expire_on_commit=False)
    apply(sess, snap)
    return conn, sess


def _discard(conn, sess):
    try:
        sess.close()
    finally:
        try:
            conn.rollback()
        finally:
            conn.close()


def read_month(db: Session, month, fn):
    """fn(session) πάνω στη διάταξη του (παλιού) μήνα· τίποτα δεν αποθηκεύεται."""
    if not is_past(month):
        return fn(db)
    snap = snapshot_of(db, month); db.rollback()
    conn, sess = _private(snap)
    try:
        return fn(sess)
    finally:
        _discard(conn, sess)


def write_month(db: Session, month, fn):
    """fn(session) εκτελείται πάνω στη διάταξη του παλιού μήνα· το αποτέλεσμα αποθηκεύεται ως νέο στιγμιότυπο του μήνα, οι ζωντανοί πίνακες μένουν ανέγγιχτοι."""
    if not is_past(month):
        return fn(db)
    materialize(db)
    snap = snapshot_of(db, month); db.rollback()
    conn, sess = _private(snap)
    try:
        res = fn(sess)
        new = capture(sess)
    finally:
        _discard(conn, sess)
    row = db.get(models.MaterialLayoutSnapshot, month)
    payload = json.dumps(new, ensure_ascii=False)
    if row: row.payload = payload
    else: db.add(models.MaterialLayoutSnapshot(month=month, payload=payload))
    db.commit()
    return res
