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
    models.ShipmentHistoryEntry, models.LoadingOrder, models.MaterialShipmentEntry, models.ReadyMaterialLot, models.ReadyMaterialMovement,
    models.OrganizationalUnit, models.Employee, models.ProductionWorkEntry, models.Organization, models.OrganizationRegistryDetail,
    models.CarrierDriver, models.CarrierVehicle, models.WEEECategory, models.Material, models.StorageGroup, models.CollectionMediumType,
    models.CollectionMedium, models.CodeCounter, models.ContainerAsset, models.ProductionTransfer, models.ProductionTransferItem, models.ProductionInputBalance, models.MaterialInventoryEntry, models.WEEEStockLot, models.SortingEntry, getattr(models, "MaterialTab", None), getattr(models, "StockMovement", None), getattr(models, "OrgUnitPosition", None), getattr(models, "Person", None), getattr(models, "InventoryYearCorrection", None), getattr(models, "MaterialOpeningStock", None), getattr(models, "PressOpeningStock", None), getattr(models, "ProductionPlacementInterval", None),
) if c is not None}
IGNORE_TABLES = {"audit_events", "action_history", "idempotency_keys"}
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
    (("PUT",), re.compile(r"^/loading/da/\d+/[^/]+$")),
    (("POST",), re.compile(r"^/loading/da/\d+/[^/]+/cancel$")),
    (("POST",), re.compile(r"^/production/transfers$")),                       # μεταφορά στην παραγωγή
    (("POST",), re.compile(r"^/production/transfers/[^/]+/(cancel|replace)$")),
    (("PUT",), re.compile(r"^/production/transfers/[^/]+/weight$")),
    (("POST",), re.compile(r"^/mat/export$")),                                  # εξαγωγή υλικού
    (("PUT", "DELETE"), re.compile(r"^/mat/exports/[^/]+$")),
    (("PUT",), re.compile(r"^/inventory/year-corrections$")),
]
NEVER = re.compile(r"/(merge|purge|permanent|bulk-[a-z]+|move)$")

TABLE_LABEL = {"inventory_year_corrections": "διορθωμένου αποθέματος", "material_opening_stocks": "αρχικού αποθέματος υλικού", "press_opening_stocks": "αρχικού αποθέματος πρέσας", "organization_roles": "ρόλων οργανισμού", "organizations": "οργανισμού", "organization_registry_details": "στοιχείων οργανισμού", "organizational_units": "τμήματος", "employees": "εργαζομένου", "production_placement_intervals": "ιστορικού τοποθέτησης εργαζομένου",
               "production_work_entries": "εγγραφής παραγωγής", "carrier_drivers": "οδηγού", "carrier_vehicles": "οχήματος", "weee_categories": "κατηγορίας ΑΗΗΕ",
               "materials": "υλικού", "storage_groups": "ομάδας αποθήκευσης", "collection_medium_types": "τύπου μέσου", "collection_media": "μέσου συλλογής",
               "containers": "εμπορευματοκιβωτίου", "sorting_entries": "καταχώρησης ταξινόμησης", "weee_stock_lots": "παρτίδας αποθέματος", "stock_movements": "κίνησης αποθέματος", "org_unit_positions": "θέσης τμήματος", "people": "προσώπου", "employee_org_units": "τμημάτων εργαζομένου", "material_tabs": "καρτέλας υλικών"}
PRIMARY_ORDER = ["sorting_entries", "production_work_entries", "organizations", "materials", "weee_categories", "organizational_units", "employees", "production_placement_intervals", "collection_media",
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
    return "|".join(str(getattr(obj, m.get_property_by_column(col).key)) for col in m.primary_key)      # σύνθετο κλειδί: τιμές χωρισμένες με |


def _pkexpr(tbl, pk):
    cols = list(tbl.primary_key.columns)
    if len(cols) == 1:
        return cols[0] == pk
    from sqlalchemy import and_
    out = []
    for col, v in zip(cols, str(pk).split("|")):
        try:
            v = col.type.python_type(v)
        except Exception:
            pass
        out.append(col == v)
    return and_(*out)


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
            elif t == "code_counters":
                # μετρητής αριθμών μέσων: γράφεται «ωμά» (UPDATE ... last_no+1)· κρατάμε την τιμή ΠΡΙΝ την πρώτη αλλαγή, ώστε η αναίρεση να ελευθερώνει τον αριθμό
                cc = ctx.setdefault("counters", {})
                try:
                    from sqlalchemy import text as _t
                    flat = list(params.values()) if isinstance(params, dict) else list(params[0] if params and isinstance(params[0], (list, tuple)) else params)
                    key = (int(flat[0]), str(flat[1]))
                    if key not in cc:
                        r0 = conn.execute(_t("select last_no from code_counters where year=:y and code=:c"), {"y": key[0], "c": key[1]}).first()
                        cc[key] = None if r0 is None else int(r0[0])
                except Exception:
                    ctx["bad"].add("code_counters")
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
        if ctx is None or not ctx["ok"]:
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
            op = "create" if before is None else ("delete" if after is None else "update")
            rows.append({"t": r["table"], "pk": _pk(obj), "before": before, "after": after, "op": op, "obj": obj})
        for (tn_, oid), before_v in (ctx.get("sets") or {}).items():
            now_v = _set_now(session, tn_, oid)
            if now_v != before_v:
                rows.append({"t": tn_, "pk": oid, "before": {"roles": before_v}, "after": {"roles": now_v}, "op": "update"})
        for (y_, c_), b_ in (ctx.get("counters") or {}).items():
            from sqlalchemy import text as _t
            r1 = session.execute(_t("select last_no from code_counters where year=:y and code=:c"), {"y": y_, "c": c_}).first()
            n_ = None if r1 is None else int(r1[0])
            if n_ != b_:
                rows.append({"t": "code_counters", "pk": "%s|%s" % (y_, c_), "before": (None if b_ is None else {"year": y_, "code": c_, "last_no": b_}),
                             "after": (None if n_ is None else {"year": y_, "code": c_, "last_no": n_}), "op": ("create" if b_ is None else "update")})
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
        if ctx.get("android"):
            try:
                label = _android_label(session, rows, main) or label
            except Exception:
                pass
        label = session.info.pop("hist_label", None) or label
        for rw in rows:
            rw.pop("obj", None)
        from .history import record
        user = session.get(User, uid)
        record(session, user, "rows", label, subjects, {"rows": rows, **extra})


_DEBUG_BAD: list = []


def _android_label(session, rows, main):
    """Περιγραφή κίνησης για το Android (απλά ελληνικά, μόνο ονόματα από τα μητρώα): «Τίτλος · λεπτομέρειες»."""
    snap = main["after"] or main["before"] or {}
    op = main["op"]
    n0 = lambda v: int(round(float(v or 0)))
    items = [r for r in rows if r["t"] == "production_transfer_items"]
    if items or any(r["t"] == "production_transfers" for r in rows):      # μεταφορά στην παραγωγή
        trow = next((r for r in rows if r["t"] == "production_transfers"), None)
        tid = (trow["after"] or trow["before"])["id"] if trow else (items[0]["after"] or items[0]["before"])["transfer_id"]
        tr = session.get(models.ProductionTransfer, tid)
        unit = session.get(models.OrganizationalUnit, tr.destination_org_unit_id) if tr else None
        parts = [unit.name_el if unit else "Τμήμα"]
        names = []
        for it in items[:2]:
            sn = it["after"] or it["before"] or {}
            lot = session.get(models.WEEEStockLot, sn.get("stock_lot_id"))
            cat = session.get(models.WEEECategory, lot.weee_category_id) if lot else None
            med = session.get(models.CollectionMedium, lot.collection_medium_id) if lot and lot.collection_medium_id else None
            names.append(((cat.her_description or cat.description_el) if cat else "Υλικό") + ((" · " + str(med.code)) if med else " · Χύμα"))
        if names:
            parts.append(", ".join(names) + ((" (+%d)" % (len(items) - 2)) if len(items) > 2 else ""))
        if trow and trow["op"] == "create":
            parts.append("%d kg" % sum(n0((r["after"] or {}).get("weight")) for r in items))
            return "Μεταφορά στην παραγωγή · " + " · ".join(parts)
        if trow and (trow["after"] or {}).get("status") != (trow["before"] or {}).get("status") and "CANCEL" in str((trow["after"] or {}).get("status") or "").upper():
            k_ = sum(n0((r["before"] or {}).get("weight")) for r in items)
            if k_:
                parts.append("%d kg" % k_)
            return "Ακύρωση μεταφοράς στην παραγωγή · " + " · ".join(parts)
        b_ = sum(n0((r["before"] or {}).get("weight")) for r in items)
        a_ = sum(n0((r["after"] or {}).get("weight")) for r in items)
        parts.append("%d → %d kg" % (b_, a_))
        return "Αλλαγή μεταφοράς στην παραγωγή · " + " · ".join(parts)
    if main["t"] == "ready_material_lots" or any(r["t"] == "ready_material_lots" for r in rows):      # εξαγωγή υλικού
        rl = next(r for r in rows if r["t"] == "ready_material_lots")
        sn, b_, a_ = (rl["after"] or rl["before"] or {}), (rl["before"] or {}), (rl["after"] or {})
        mat = session.get(models.Material, sn.get("material_id"))
        med = session.get(models.CollectionMedium, sn.get("collection_medium_id")) if sn.get("collection_medium_id") else None
        parts = [(mat.internal_name if mat else "Υλικό"), (str(med.code) if med else "Χύμα")]
        if rl["op"] == "create":
            return "Εξαγωγή υλικού · " + " · ".join(parts + ["%d kg" % n0(sn.get("net_weight"))])
        if a_.get("status") == "CANCELLED" and b_.get("status") != "CANCELLED":
            return "Διαγραφή εξαγωγής υλικού · " + " · ".join(parts + ["%d kg" % n0(sn.get("net_weight"))])
        return "Αλλαγή εξαγωγής υλικού · " + " · ".join(parts + ["%d → %d kg" % (n0(b_.get("net_weight")), n0(a_.get("net_weight")))])
    if main["t"] == "sorting_entries":
        cat = session.get(models.WEEECategory, snap.get("weee_category_id"))
        cname = ((cat.her_description or cat.description_el) if cat and not cat.is_internal_subcategory else (cat.description_el if cat else "")) or "Υλικό"
        mid = snap.get("collection_medium_id")
        med = session.get(models.CollectionMedium, mid) if mid else None
        mt = session.get(models.CollectionMediumType, med.type_id) if med else None
        parts = [cname, (((mt.name_el if mt else "Μέσο") + " · " + str(med.code)) if med else "Χύμα")]
        kg = lambda d: (None if not d or d.get("raw_weight") is None else int(round(float(d["raw_weight"]))))
        if op == "update":
            title = "Αλλαγή καταχώρησης"
            b, a = main["before"] or {}, main["after"] or {}
            ch = []
            if kg(b) != kg(a):
                ch.append("%s → %s kg" % (kg(b), kg(a)))
            if b.get("collection_medium_id") != a.get("collection_medium_id"):
                ch.append("Άλλο μέσο")
            if b.get("weee_category_id") != a.get("weee_category_id"):
                ch.append("Άλλο υλικό")
            for rw in rows:
                if rw["t"] == "collection_media" and rw["before"] and rw["after"] and rw["before"].get("is_closed") != rw["after"].get("is_closed"):
                    ch.append("Με χώρο → Γεμάτο" if rw["after"].get("is_closed") else "Γεμάτο → Με χώρο")
            parts += ch or ["%s kg" % kg(a)]
        else:
            title = "Νέα καταχώρηση" if op == "create" else "Διαγραφή καταχώρησης"
            parts.append("%s kg" % kg(snap))
        return title + " · " + " · ".join(parts)
    if main["t"] == "collection_media":
        mt = session.get(models.CollectionMediumType, snap.get("type_id"))
        ch = ""
        b, a_ = main["before"] or {}, main["after"] or {}
        if b and a_ and b.get("is_closed") != a_.get("is_closed"):
            ch = " · " + ("Με χώρο → Γεμάτο" if a_.get("is_closed") else "Γεμάτο → Με χώρο")
        return "Αλλαγή μέσου συλλογής · %s · %s%s" % ((mt.name_el if mt else "Μέσο"), snap.get("code"), ch)
    if main["t"] == "production_work_entries":
        unit = session.get(models.OrganizationalUnit, snap.get("org_unit_id"))
        cat = session.get(models.WEEECategory, snap.get("weee_category_id"))
        title = {"create": "Νέα εγγραφή παραγωγής", "update": "Αλλαγή εγγραφής παραγωγής", "delete": "Διαγραφή εγγραφής παραγωγής"}[op]
        parts = [(unit.name_el if unit and getattr(unit, "name_el", None) else (getattr(unit, "name", None) or "Τμήμα")),
                 ((cat.her_description or cat.description_el) if cat else "Υλικό"), "%s kg" % int(round(float(snap.get("weight_kg") or 0)))]
        return title + " · " + " · ".join(str(x) for x in parts if x)
    return None


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
    r = db.execute(select(tbl).where(_pkexpr(tbl, pk))).mappings().first()
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
            if r["t"] in ("code_counters", "medium_code_counters"):
                return "Στο μεταξύ δόθηκε νεότερος αριθμός μέσου (παλέτα / σάκος / κουτί / καλάθι) και ο αριθμός δεν μπορεί να ελευθερωθεί ή να ξαναδοθεί."
            return "Η εγγραφή έχει αλλάξει στο μεταξύ (από άλλον χρήστη ή από άλλη ενέργεια)."
        if target is None and cur is not None and _fk_refs(db, r["t"], r["pk"], ig):
            return "Η εγγραφή χρησιμοποιείται πλέον αλλού και δεν μπορεί να αναιρεθεί."
        if target is not None and cur is None and not _parents_ok(db, r["t"], target, {(x["t"], x["pk"]) for x in rows if (x["after"] if redo else x["before"]) is not None}):
            return "Κάποια εγγραφή από την οποία εξαρτάται έχει διαγραφεί στο μεταξύ."
    return None


def redo_ok(db, payload):
    """Η Αναίρεση επιτρέπεται μόνο αν, αμέσως μετά από αυτήν, θα μπορούσε να γίνει Επανάληψη. Επιστρέφει None αν ναι, αλλιώς το μήνυμα (ελληνικά)."""
    rows = payload["rows"]
    ig = {(r["t"], r["pk"]) for r in rows}
    # γραμμές που θα υπάρχουν όταν γίνει η Επανάληψη (και άρα μπορούν να είναι γονείς η μία της άλλης)
    will = {(x["t"], x["pk"]) for x in rows if x["after"] is not None}
    for r in rows:
        if r["before"] is None and r["after"] is not None:      # η αναίρεση σβήνει τη γραμμή· η επανάληψη πρέπει να τη ξαναφτιάξει
            if not _parents_ok(db, r["t"], r["after"], will):
                return "Η επανάληψη δεν θα μπορούσε να γίνει αμέσως μετά: κάποια εγγραφή από την οποία εξαρτάται έχει διαγραφεί στο μεταξύ."
    return None


def apply(db, payload, redo):
    rows = payload["rows"]
    seq = rows if redo else list(reversed(rows))
    # σειρά: πρώτα διαγραφές παιδιών, μετά εισαγωγές γονέων (αντίστροφη σειρά καταγραφής για αναίρεση)
    for r in seq:
        tbl = None if r["t"] in SET_TABLES else _table(r["t"])
        target = r["after"] if redo else r["before"]
        if r["t"] in SET_TABLES:
            from sqlalchemy import text as _t
            oc, vc, ot = SET_TABLES[r["t"]]
            db.execute(_t("delete from %s where %s=:i" % (r["t"], oc)), {"i": r["pk"]})
            for v in target["roles"]:
                db.execute(_t("insert into %s(%s, %s) values(:i, :v)" % (r["t"], oc, vc)), {"i": r["pk"], "v": v})
            continue
        if target is None:
            db.execute(sa_delete(tbl).where(_pkexpr(tbl, r["pk"])))
        else:
            vals = {c.name: _de(c, target.get(c.name)) for c in tbl.columns}
            if _row(db, r["t"], r["pk"]) is None:
                db.execute(insert(tbl).values(**vals))
            else:
                db.execute(sa_update(tbl).where(_pkexpr(tbl, r["pk"])).values(**vals))
    db.flush()
