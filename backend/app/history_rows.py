"""Αναίρεση ΓΕΝΙΚΩΝ αλλαγών (μητρώα, εγγραφές παραγωγής, ταξινόμηση Windows) με «ιστορικό γραμμών».

Πώς δουλεύει (απλά): σε κάθε αίτημα που ΕΠΙΤΡΕΠΕΤΑΙ (λίστα ROUTES) καταγράφονται, μέσα στην ΙΔΙΑ συναλλαγή με την αλλαγή, οι γραμμές της βάσης που
άλλαξαν: πριν / μετά. Η αναίρεση γυρίζει ΟΛΕΣ αυτές τις γραμμές πίσω ΜΟΝΟ αν η βάση είναι ακριβώς όπως την άφησε η αλλαγή (αλλιώς σημαίνει ότι
κάτι άλλαξε στο μεταξύ → μπλοκάρει με μήνυμα και δεν αλλάζει τίποτα). Η επανάληψη είναι το αντίστροφο.
Ασφάλεια: αν το αίτημα άγγιξε οποιονδήποτε πίνακα εκτός της λίστας TRACKED (ή έγραψε «ωμά» σε πίνακα που δεν παρακολουθείται), δεν καταγράφεται καθόλου
(δεν υπάρχει μισή αναίρεση). Αιτήματα από Android ΔΕΝ καταγράφονται ποτέ."""
import re, json
from contextvars import ContextVar
from datetime import datetime, date
from decimal import Decimal
from sqlalchemy import event, select, insert, update as sa_update, delete as sa_delete, inspect as sa_inspect
from sqlalchemy.orm import Session
from sqlalchemy.orm.attributes import get_history
from . import models
from .models import ActionHistory, AuditEvent, User
from .db import Base

req_ctx: ContextVar = ContextVar("hist_req", default=None)

TRACKED = {c for c in (
    models.OrganizationalUnit, models.Employee, models.ProductionWorkEntry, models.Organization, models.OrganizationRegistryDetail,
    models.CarrierDriver, models.CarrierVehicle, models.WEEECategory, models.Material, models.StorageGroup, models.CollectionMediumType,
    models.CollectionMedium, models.ContainerAsset, models.WEEEStockLot, models.SortingEntry, getattr(models, "MaterialTab", None), getattr(models, "StockMovement", None), getattr(models, "OrgUnitPosition", None), getattr(models, "Person", None),
) if c is not None}
IGNORE_TABLES = {"audit_events", "action_history"}
# πίνακες συσχετίσεων που γράφονται «ωμά»: (πίνακας) → (στήλη ιδιοκτήτη, στήλη τιμής, πίνακας ιδιοκτήτη)
SET_TABLES = {"organization_roles": ("organization_id", "role", "organizations"), "employee_org_units": ("employee_id", "org_unit_id", "employees")}

# (μέθοδοι, regex διαδρομής) που επιτρέπεται να καταγράφονται
_REG = r"(org-units|organizations|weee-categories|materials|medium-types|media|containers|employees|storage-groups)"
ROUTES = [
    (("POST", "PUT", "DELETE"), re.compile(r"^/master/" + _REG + r"(/[^/]+)?(/(activate|name|tare|usage|storage-group))?$")),
    (("POST", "PUT", "DELETE"), re.compile(r"^/master/carriers/[^/]+/(drivers|vehicles)(/[^/]+)?$")),
    (("PUT",), re.compile(r"^/master/carrier-drivers/[^/]+$")),
    (("POST", "PUT", "DELETE"), re.compile(r"^/production/work-entries(/[^/]+)?$")),
    (("POST",), re.compile(r"^/sorting/[^/]+/entries$")),
    (("PUT", "DELETE"), re.compile(r"^/sorting/entries/[^/]+$")),
    (("POST", "PUT"), re.compile(r"^/mat/tabs(-order|/[^/]+)?$")),
]
NEVER = re.compile(r"/(merge|purge|permanent|bulk-[a-z]+|move)$")

TABLE_LABEL = {"organization_roles": "ρόλων οργανισμού", "organizations": "οργανισμού", "organization_registry_details": "στοιχείων οργανισμού", "organizational_units": "τμήματος", "employees": "εργαζομένου",
               "production_work_entries": "εγγραφής παραγωγής", "carrier_drivers": "οδηγού", "carrier_vehicles": "οχήματος", "weee_categories": "κατηγορίας ΑΗΗΕ",
               "materials": "υλικού", "storage_groups": "ομάδας αποθήκευσης", "collection_medium_types": "τύπου μέσου", "collection_media": "μέσου συλλογής",
               "containers": "εμπορευματοκιβωτίου", "sorting_entries": "καταχώρησης ταξινόμησης", "weee_stock_lots": "παρτίδας αποθέματος", "stock_movements": "κίνησης αποθέματος", "org_unit_positions": "θέσης τμήματος", "people": "προσώπου", "employee_org_units": "τμημάτων εργαζομένου", "material_tabs": "καρτέλας υλικών"}
PRIMARY_ORDER = ["sorting_entries", "production_work_entries", "organizations", "materials", "weee_categories", "organizational_units", "employees", "collection_media",
                 "collection_medium_types", "containers", "carrier_drivers", "carrier_vehicles", "storage_groups", "material_tabs", "organization_roles", "organization_registry_details", "weee_stock_lots", "stock_movements", "org_unit_positions", "employee_org_units", "people"]
NAME_ATTRS = ("trade_name", "legal_name", "internal_name", "name_el", "display_name", "full_name", "name", "official_description", "code", "container_number", "plate")
VERB = {"create": "Προσθήκη", "update": "Αλλαγή", "delete": "Διαγραφή"}


class HistCtx:
    """Pure ASGI: κρατά (μέθοδο, διαδρομή, αν είναι Android) για τον έλεγχο καταγραφής."""
    def __init__(self, inner): self.inner = inner

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http" or scope.get("method") not in ("POST", "PUT", "PATCH", "DELETE"):
            return await self.inner(scope, receive, send)
        ua = ""
        for k, v in scope.get("headers") or []:
            if k == b"user-agent":
                ua = v.decode("latin-1")
        path = scope.get("path") or ""
        ok = any(scope["method"] in m and r.match(path) for m, r in ROUTES) and not NEVER.search(path)
        tok = req_ctx.set({"m": scope["method"], "p": path, "android": ("android" in ua.lower() or "dalvik" in ua.lower() or "okhttp" in ua.lower()), "ok": ok, "bad": set()})
        try:
            await self.inner(scope, receive, send)
        finally:
            req_ctx.reset(tok)


# ---------- (de)serialization ----------
def _ser(v):
    if v is None or isinstance(v, (bool, int, float, str)):
        return v
    if isinstance(v, Decimal):
        return str(v)
    if isinstance(v, (datetime, date)):
        return v.isoformat()
    return str(v)


def _de(col, v):
    if v is None:
        return None
    try:
        pt = col.type.python_type
    except NotImplementedError:
        return v
    if pt is Decimal:
        return Decimal(v)
    if pt is datetime:
        d = datetime.fromisoformat(v)
        return d.replace(tzinfo=None)      # η SQLite αποθηκεύει την ώρα χωρίς ζώνη (ίδια «ώρα ρολογιού»)
    if pt is date:
        return date.fromisoformat(v)
    return v


def _obj_snap(obj, old=False):
    m = sa_inspect(type(obj))
    out = {}
    for prop in m.column_attrs:
        col = prop.columns[0]
        v = getattr(obj, prop.key)
        if old:
            h = get_history(obj, prop.key)
            if h.has_changes():
                v = h.deleted[0] if h.deleted else None
        out[col.name] = _ser(v)
    return out


def _pk(obj):
    m = sa_inspect(type(obj))
    return str(getattr(obj, m.get_property_by_column(m.primary_key[0]).key))


def install(engine):
    @event.listens_for(Session, "before_flush")
    def _before_flush(session, fctx, instances):
        ctx = req_ctx.get()
        if ctx is None or not ctx["ok"]:
            return
        info = session.info.setdefault("hist", {"rows": {}, "order": []})
        for obj in list(session.new) + list(session.dirty) + list(session.deleted):
            cls = type(obj)
            tn = getattr(cls, "__tablename__", None)
            if tn in IGNORE_TABLES:
                continue
            if cls not in TRACKED:
                ctx["bad"].add(tn or cls.__name__)
                continue
            isnew, isdel = obj in session.new, obj in session.deleted
            if not isnew and not isdel and not session.is_modified(obj):
                continue
            key = (tn, id(obj))        # ταυτότητα αντικειμένου (το id της γραμμής δίνεται μόνο στο flush)
            r = info["rows"].get(key)
            if r is None:
                r = {"obj": obj, "table": tn, "before": (None if isnew else _obj_snap(obj, old=True)), "was_new": isnew}
                info["rows"][key] = r
                info["order"].append(key)
            r["deleted"] = isdel

    @event.listens_for(engine, "before_cursor_execute")
    def _guard(conn, cursor, statement, params, context, executemany):
        ctx = req_ctx.get()
        if ctx is None or not ctx["ok"]:
            return
        m = re.match(r"\s*(INSERT\s+(?:OR\s+\w+\s+)?INTO|UPDATE|DELETE\s+FROM)\s+[\"`]?(\w+)", statement, re.I)
        if m:
            t = m.group(2)
            if t in SET_TABLES:
                # συσχετίσεις (ρόλοι οργανισμού, τμήματα εργαζομένου): γράφονται «ωμά»· κρατάμε την κατάσταση ΠΡΙΝ την πρώτη εγγραφή
                from sqlalchemy import text as _t
                oc, vc, ot = SET_TABLES[t]
                flat = []
                for x in (params if isinstance(params, (list, tuple)) else [params]):
                    flat.extend(x.values() if isinstance(x, dict) else (x if isinstance(x, (list, tuple)) else [x]))
                sets = ctx.setdefault("sets", {})
                for v in flat:
                    if isinstance(v, str) and (t, v) not in sets and conn.execute(_t("select 1 from %s where id=:i" % ot), {"i": v}).first():
                        sets[(t, v)] = sorted(r[0] for r in conn.execute(_t("select %s from %s where %s=:i" % (vc, t, oc)), {"i": v}))
            elif t not in IGNORE_TABLES and t not in {c.__tablename__ for c in TRACKED}:
                ctx["bad"].add(t)

    @event.listens_for(Session, "before_commit")
    def _before_commit(session):
        try:
            _before_commit_inner(session)
        except Exception:
            import logging
            logging.getLogger("uvicorn.error").exception("Αναίρεση: η καταγραφή απέτυχε (η ενέργεια του χρήστη ΔΕΝ επηρεάστηκε)")

    def _before_commit_inner(session):
        ctx = req_ctx.get()
        if ctx is None or not ctx["ok"] or ctx["android"]:
            session.info.pop("hist", None)
            return
        if not session._is_clean():
            session.flush()          # το flush γίνεται ΠΡΙΝ για να καταγραφούν οι αλλαγές (before_commit τρέχει πριν το αυτόματο flush του commit)
        info = session.info.pop("hist", None) or {"rows": {}, "order": []}
        if ctx["bad"]:
            _DEBUG_BAD.append((ctx["m"], ctx["p"], sorted(ctx["bad"])))
            import logging
            logging.getLogger("uvicorn.error").warning("Αναίρεση: δεν καταγράφηκε %s %s (άγγιξε πίνακες εκτός λίστας: %s)", ctx["m"], ctx["p"], ", ".join(sorted(ctx["bad"])))
            return
        if not info["order"] and not ctx.get("sets"):
            return
        uid = session.info.get("hist_user")
        if not uid or ctx["bad"]:
            if ctx["bad"]:
                _DEBUG_BAD.append((ctx["m"], ctx["p"], sorted(ctx["bad"])))
                del _DEBUG_BAD[:-50]
                import logging
                logging.getLogger("uvicorn.error").warning("Αναίρεση: δεν καταγράφηκε %s %s (άγγιξε πίνακες εκτός λίστας: %s)", ctx["m"], ctx["p"], ", ".join(sorted(ctx["bad"])))
            return
        rows = []
        for key in info["order"]:
            r = info["rows"][key]
            obj, before = r["obj"], r["before"]
            deleted = r.get("deleted")
            if r["was_new"] and deleted:
                continue
            after = None if deleted else _obj_snap(obj)
            if before is None and after is None:
                continue
            if before is not None and after is not None and _norm(r["table"], before) == _norm(r["table"], after):
                continue
            if getattr(obj, "source", None) == "ANDROID":       # καταχώρηση Android: ποτέ στο ιστορικό
                return
            op = "create" if before is None else ("delete" if after is None else "update")
            rows.append({"t": r["table"], "pk": _pk(obj), "before": before, "after": after, "op": op, "obj": obj})
        for (tn_, oid), before_v in (ctx.get("sets") or {}).items():
            now_v = _set_now(session, tn_, oid)
            if now_v != before_v:
                rows.append({"t": tn_, "pk": oid, "before": {"roles": before_v}, "after": {"roles": now_v}, "op": "update"})
        if not rows:
            return
        # Σύνδεση ταξινόμησης με φορτίο/κατάσταση συνεδρίας (ασφάλεια: αναίρεση μόνο όσο δεν έχει κλείσει)
        subjects, extra = [], {}
        for rw in rows:
            subjects.append("row:%s:%s" % ((SET_TABLES[rw["t"]][2] if rw["t"] in SET_TABLES else rw["t"]), rw["pk"]))
            if rw["t"] == "sorting_entries":
                ses = session.get(models.SortingSession, (rw["after"] or rw["before"])["session_id"])
                if ses is not None:
                    extra["ses_id"] = ses.id
                    extra["ses_status"] = ses.status
                    subjects.append("load:%s" % ses.inbound_load_id)
                    if ses.status in ("CLOSED", "MANAGEMENT_REVIEW"):
                        return
        main = sorted(rows, key=lambda x: PRIMARY_ORDER.index(x["t"]) if x["t"] in PRIMARY_ORDER else 99)[0]
        snap = main["after"] or main["before"] or {}
        name = next((str(snap[a]) for a in NAME_ATTRS if snap.get(a)), "")
        label = "%s %s%s" % (VERB[main["op"]], TABLE_LABEL.get(main["t"], main["t"]), (" «%s»" % name[:60]) if name else "")
        if len(rows) > 1:
            label += " (+%d σχετικές εγγραφές)" % (len(rows) - 1)
        for rw in rows:
            rw.pop("obj", None)
        from .history import record
        user = session.get(User, uid)
        record(session, user, "rows", label, subjects, {"rows": rows, **extra})


_DEBUG_BAD: list = []


def _cmp(d):
    return {k: v for k, v in d.items() if k not in ("updated_at", "created_at")}


def _norm(t, d):
    """Σύγκριση με τους πραγματικούς τύπους (Decimal 123.0 = 123.000, ώρες χωρίς ζώνη), όχι με κείμενο."""
    if d is None or t in SET_TABLES:
        return d
    tbl = _table(t)
    return {c.name: _de(c, d.get(c.name)) for c in tbl.columns if c.name not in ("updated_at", "created_at")}


# ---------- εφαρμογή αναίρεσης / επανάληψης ----------
def _set_now(db, tn, oid):
    from sqlalchemy import text as _t
    oc, vc, ot = SET_TABLES[tn]
    return sorted(r[0] for r in db.execute(_t("select %s from %s where %s=:i" % (vc, tn, oc)), {"i": oid}))


def _table(name):
    return Base.metadata.tables[name]


def _row(db, t, pk):
    if t in SET_TABLES:
        return {"roles": _set_now(db, t, pk)}
    tbl = _table(t)
    pkc = list(tbl.primary_key.columns)[0]
    r = db.execute(select(tbl).where(pkc == pk)).mappings().first()
    return None if r is None else {c.name: _ser(r[c.name]) for c in tbl.columns}


def _fk_refs(db, t, pk, ignore):
    """Πόσες άλλες γραμμές (εκτός όσων αλλάζουν στην ίδια αναίρεση) δείχνουν σε αυτή τη γραμμή."""
    n = 0
    for tbl in Base.metadata.tables.values():
        for fk in tbl.foreign_keys:
            if fk.column.table.name == t:
                pkc = list(tbl.primary_key.columns)[0]
                for r in db.execute(select(pkc).where(fk.parent == pk)).all():
                    if (tbl.name, str(r[0])) not in ignore:
                        n += 1
    return n


def _parents_ok(db, t, vals, restoring):
    for fk in _table(t).foreign_keys:
        v = vals.get(fk.parent.name)
        if v is None:
            continue
        if (fk.column.table.name, str(v)) in restoring:
            continue
        if db.execute(select(fk.column).where(fk.column == v)).first() is None:
            return False
    return True


def check(db, payload, redo):
    """Επιστρέφει None αν η αναίρεση/επανάληψη είναι ασφαλής, αλλιώς το μήνυμα (ελληνικά) για το τι άλλαξε."""
    rows = payload["rows"]
    ig = {(r["t"], r["pk"]) for r in rows}
    ses_id = payload.get("ses_id")
    if ses_id:
        ses = db.get(models.SortingSession, ses_id)
        if ses is None or ses.status != payload.get("ses_status") or ses.status in ("CLOSED", "MANAGEMENT_REVIEW"):
            return "Η ταξινόμηση έχει κλείσει ή αλλάξει κατάσταση στο μεταξύ."
    for r in rows:
        want = r["before"] if redo else r["after"]          # η κατάσταση που πρέπει να έχει τώρα η βάση
        target = r["after"] if redo else r["before"]        # η κατάσταση που θα αποκατασταθεί
        cur = _row(db, r["t"], r["pk"])
        if (cur is None) != (want is None) or (cur is not None and _norm(r["t"], cur) != _norm(r["t"], want)):
            return "Η εγγραφή έχει αλλάξει στο μεταξύ (από άλλον χρήστη ή από άλλη ενέργεια)."
        if target is None and cur is not None and _fk_refs(db, r["t"], r["pk"], ig):
            return "Η εγγραφή χρησιμοποιείται πλέον αλλού και δεν μπορεί να αναιρεθεί."
        if target is not None and cur is None and not _parents_ok(db, r["t"], target, {(x["t"], x["pk"]) for x in rows if (x["after"] if redo else x["before"]) is not None}):
            return "Κάποια εγγραφή από την οποία εξαρτάται έχει διαγραφεί στο μεταξύ."
    return None


def apply(db, payload, redo):
    rows = payload["rows"]
    seq = rows if redo else list(reversed(rows))
    # σειρά: πρώτα διαγραφές παιδιών, μετά εισαγωγές γονέων (αντίστροφη σειρά καταγραφής για αναίρεση)
    for r in seq:
        tbl = None if r["t"] in SET_TABLES else _table(r["t"])
        pkc = None if tbl is None else list(tbl.primary_key.columns)[0]
        target = r["after"] if redo else r["before"]
        if r["t"] in SET_TABLES:
            from sqlalchemy import text as _t
            oc, vc, ot = SET_TABLES[r["t"]]
            db.execute(_t("delete from %s where %s=:i" % (r["t"], oc)), {"i": r["pk"]})
            for v in target["roles"]:
                db.execute(_t("insert into %s(%s, %s) values(:i, :v)" % (r["t"], oc, vc)), {"i": r["pk"], "v": v})
            continue
        if target is None:
            db.execute(sa_delete(tbl).where(pkc == r["pk"]))
        else:
            vals = {c.name: _de(c, target.get(c.name)) for c in tbl.columns}
            if _row(db, r["t"], r["pk"]) is None:
                db.execute(insert(tbl).values(**vals))
            else:
                db.execute(sa_update(tbl).where(pkc == r["pk"]).values(**vals))
    db.flush()
