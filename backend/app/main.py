import os
import re
import asyncio, logging, json
from contextlib import asynccontextmanager
from datetime import datetime, timezone, timedelta
from fastapi import FastAPI, Depends, HTTPException, Query, Request
from sqlalchemy import select, inspect, text, update, func
from sqlalchemy.orm import Session, aliased
from .db import Base, engine, get_db, SessionLocal
from . import models, schemas
from .models import User, OrganizationalUnit, Organization, WEEECategory, Material, CollectionMediumType, CollectionMedium, AppSetting, Employee, Person, ProductionWorkEntry, ProductionAttendance, ProductionPlacementInterval, ProductionAttendanceEvent, MaterialOutputEntry, OrgUnitPosition, employee_org_units, EquipmentItem, ConsumableType, ConsumableLot, MaterialOpeningStock, ElectrocycleOrder, ElectrocycleSyncStatus
from .security import verify_password, make_token, current_user, require_permission
from .seed import seed
from .import_real_2026 import ensure_real_2026_import
from .import_production_2026 import ensure_real_production_2026_import
from .import_material_output_2026 import ensure_material_output_2026_import
from .import_material_opening_stock_2025 import ensure_material_opening_stock_2025_import
from .audit import write_audit
from .migrations import run_alembic_migrations
from .config import settings
from .electrocycle_sync import sync_electrocycle_orders
from .export_settings import get_export_settings, archive_export_copy, EXPORT_DIR_KEY

_log = logging.getLogger("electrocycle")

def _setup_file_log():
    """Εγγραφή σφαλμάτων (με traceback) σε αρχείο `server.log` στον φάκελο δεδομένων, ώστε να φαίνονται τα σφάλματα 500."""
    try:
        from logging.handlers import RotatingFileHandler
        from pathlib import Path
        from .config import settings as _st
        url=_st.database_url
        if url.startswith("sqlite:///"): base=Path(url[len("sqlite:///"):]).resolve().parent
        else: base=Path(os.environ.get("LOCALAPPDATA") or Path.home())/"WEEE Platform"/"data"
        base.mkdir(parents=True,exist_ok=True)
        h=RotatingFileHandler(str(base/"server.log"),maxBytes=2_000_000,backupCount=5,encoding="utf-8")
        h.setLevel(logging.WARNING)
        h.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
        for name in ("","uvicorn.error","uvicorn.access","electrocycle","sqlalchemy.engine.Engine"):
            lg=logging.getLogger(name)
            if not any(isinstance(x,RotatingFileHandler) and getattr(x,"baseFilename","").endswith("server.log") for x in lg.handlers): lg.addHandler(h)
        logging.getLogger("uvicorn.error").setLevel(logging.INFO)
        # Το alembic (fileConfig) απενεργοποιεί τους υπάρχοντες loggers -- τους ξαναενεργοποιούμε ώστε να μην χάνονται τα σφάλματα 500
        for nm,lg in list(logging.root.manager.loggerDict.items()):
            if isinstance(lg,logging.Logger) and (nm.startswith("uvicorn") or nm.startswith("electrocycle") or nm.startswith("app")): lg.disabled=False
    except Exception as e:
        print("server.log setup failed:",e)
_setup_file_log()

async def _electrocycle_loop():
    # First run soon after startup, then every electrocycle_sync_minutes -- or sooner (every
    # 60s, up to 5 tries) right after a failed attempt, so a transient network blip (e.g. the
    # machine switching Wi-Fi networks mid-sync) clears itself without needing the manual
    # "Ανανέωση" button. A hard timeout guards against a genuinely stuck Playwright run
    # (a hung browser/profile lock) wedging this loop forever.
    await asyncio.sleep(15)
    fail_streak = 0
    while True:
        ok = False
        try:
            with SessionLocal() as db:
                result = await asyncio.wait_for(asyncio.to_thread(sync_electrocycle_orders, db), timeout=90)
                ok = bool(result and result.get("ok"))
        except Exception:
            _log.exception("electrocycle sync loop iteration failed")
        fail_streak = 0 if ok else fail_streak + 1
        delay = 60 if 0 < fail_streak <= 5 else max(60, settings.electrocycle_sync_minutes * 60)
        await asyncio.sleep(delay)

@asynccontextmanager
async def lifespan(app: FastAPI):
    Base.metadata.create_all(bind=engine)
    try: _purge_idem()
    except Exception: pass
    # Small forward-compatible migration for existing 1.x SQLite/PostgreSQL databases.
    inspector=inspect(engine)
    cols={c["name"] for c in inspector.get_columns("collection_media")} if "collection_media" in inspector.get_table_names() else set()
    if "linked_loading_order_id" not in cols:
        with engine.begin() as conn:
            conn.execute(text("ALTER TABLE collection_media ADD COLUMN linked_loading_order_id VARCHAR(36)"))
    if "collection_media" in inspector.get_table_names() and "is_closed" not in cols:
        with engine.begin() as conn:
            conn.execute(text("ALTER TABLE collection_media ADD COLUMN is_closed BOOLEAN NOT NULL DEFAULT 0"))
    tables=set(inspector.get_table_names())
    with engine.begin() as conn:
        if "inbound_loads" in tables:
            load_cols={c["name"] for c in inspect(engine).get_columns("inbound_loads")}
            if "dpp_number" not in load_cols:
                conn.execute(text("ALTER TABLE inbound_loads ADD COLUMN dpp_number INTEGER"))
            if "outgoing_container_tare" not in load_cols:
                conn.execute(text("ALTER TABLE inbound_loads ADD COLUMN outgoing_container_tare NUMERIC(14,3)"))
            for col,sqltype in [("weighbridge_number","VARCHAR(100)"),("dispatch_note_number","VARCHAR(100)"),("seal_number","VARCHAR(100)")]:
                if col not in load_cols: conn.execute(text(f"ALTER TABLE inbound_loads ADD COLUMN {col} {sqltype}"))
        if "sorting_entries" in tables:
            se_cols={c["name"] for c in inspect(engine).get_columns("sorting_entries")}
            if "source" not in se_cols:
                conn.execute(text("ALTER TABLE sorting_entries ADD COLUMN source VARCHAR(10)"))
        if "sorting_sessions" in tables:
            sort_cols={c["name"] for c in inspect(engine).get_columns("sorting_sessions")}
            for col,sqltype in [("foreign_materials","VARCHAR(200)"),("foreign_weight","NUMERIC(14,3)"),("special_waste","VARCHAR(200)"),("special_waste_weight","NUMERIC(14,3)"),("load_pure","BOOLEAN DEFAULT 0"),("check_special","BOOLEAN DEFAULT 0"),("check_kday","BOOLEAN DEFAULT 0"),("check_non_integer","BOOLEAN DEFAULT 0")]:
                if col not in sort_cols:
                    conn.execute(text(f"ALTER TABLE sorting_sessions ADD COLUMN {col} {sqltype}"))
        if "inbound_trips" in tables:
            trip_cols={c["name"] for c in inspect(engine).get_columns("inbound_trips")}
            if "deleted_at" not in trip_cols: conn.execute(text("ALTER TABLE inbound_trips ADD COLUMN deleted_at DATETIME"))
            if "aggregate_weighbridge_number" not in trip_cols: conn.execute(text("ALTER TABLE inbound_trips ADD COLUMN aggregate_weighbridge_number VARCHAR(100)"))
        if "organizations" in tables:
            orgs_cols={c["name"] for c in inspect(engine).get_columns("organizations")}
            if "supplier_kind" not in orgs_cols: conn.execute(text("ALTER TABLE organizations ADD COLUMN supplier_kind VARCHAR(20)"))
            if "supplier_source" not in orgs_cols:
                conn.execute(text("ALTER TABLE organizations ADD COLUMN supplier_source VARCHAR(20)"))
                for nm in ("ELECTRONET AE","MEGA ELECTRICS ΑΕΒΕ","ΑΚΤΙΒ ΚΟΜΠΙΟΥΤΕΡ ΣΥΣΤΕΜΣ%"):
                    conn.execute(text("UPDATE organizations SET supplier_source='PICKUP_POINT' WHERE legal_name LIKE :n"),{"n":nm})
        if "collection_media" in tables:
            # ο κωδικός μέσου ήταν μοναδικός σε ΟΛΑ τα μέσα· γίνεται μοναδικός ανά τύπο (ίδιος κωδικός σε άλλον τύπο επιτρέπεται)
            for ix in inspect(engine).get_indexes("collection_media"):
                if ix.get("name")=="ix_collection_media_code" and ix.get("unique"):
                    conn.execute(text("DROP INDEX ix_collection_media_code"))
                    conn.execute(text("CREATE INDEX IF NOT EXISTS ix_collection_media_code ON collection_media (code)"))
            conn.execute(text("CREATE UNIQUE INDEX IF NOT EXISTS uq_collection_media_type_code ON collection_media (type_id, code)"))
            # κωδικοί της νέας μορφής ΕΕ-ΤΤΤ-ΝΝΝΝ είναι μοναδικοί σε ΟΛΑ τα μέσα (οι παλιοί κωδικοί δεν επηρεάζονται)
            conn.execute(text("CREATE UNIQUE INDEX IF NOT EXISTS uq_collection_media_newcode ON collection_media (code) WHERE code GLOB '[0-9][0-9]-[A-Z0-9][A-Z0-9][A-Z0-9]-[0-9]*'"))
        if "code_counters" in tables and "medium_code_counters" in tables:
            # οι παλιοί μετρητές ανά τύπο περνούν στον κοινό πίνακα (έτος, κωδικός)
            conn.execute(text("""INSERT INTO code_counters (year, code, last_no)
                SELECT c.year, t.short_code, MAX(c.last_no) FROM medium_code_counters c JOIN collection_medium_types t ON t.id=c.type_id
                WHERE t.short_code IS NOT NULL
                  AND NOT EXISTS (SELECT 1 FROM code_counters x WHERE x.year=c.year AND x.code=t.short_code)
                GROUP BY c.year, t.short_code"""))
        if "collection_medium_types" in tables:
            mt_cols={c["name"] for c in inspect(engine).get_columns("collection_medium_types")}
            if "single_use" not in mt_cols:
                conn.execute(text("ALTER TABLE collection_medium_types ADD COLUMN single_use BOOLEAN DEFAULT 0 NOT NULL"))
                conn.execute(text("UPDATE collection_medium_types SET single_use=1 WHERE code IN ('SACK_1KG','SACK_2KG_UN','BIG_BAG','MATERIAL_PALLET','MATERIAL_SACK')"))
                conn.execute(text("UPDATE collection_medium_types SET single_use=1 WHERE name_el LIKE 'Σάκος 1.5%'"))
            if "short_code" not in mt_cols:
                conn.execute(text("ALTER TABLE collection_medium_types ADD COLUMN short_code VARCHAR(3)"))
                for _c,_sc in {"INFOCYCLE_1":"NF1","INFOCYCLE_2":"NF2","BASKET_LARGE":"KLM","BASKET_SMALL":"KLK","METAL_BASKET":"KMT","PALLET":"PAL","BOX":"BOX",
                               "SACK_1KG":"AK1","SACK_2KG_UN":"AK2","MATERIAL_PALLET":"PMT","MATERIAL_SACK":"AKM","BIG_BAG":"MGA"}.items():
                    conn.execute(text("UPDATE collection_medium_types SET short_code=:s WHERE code=:c AND short_code IS NULL"),{"s":_sc,"c":_c})
            conn.execute(text("CREATE UNIQUE INDEX IF NOT EXISTS uq_medium_type_short_code ON collection_medium_types (short_code) WHERE short_code IS NOT NULL"))
            if "tare_fixed" not in mt_cols:
                conn.execute(text("ALTER TABLE collection_medium_types ADD COLUMN tare_fixed BOOLEAN DEFAULT 0 NOT NULL"))
                # οι σάκοι 1kg/2kg είχαν ήδη στάνταρ αποβαρό: γίνονται «σταθερό αποβαρό»
                conn.execute(text("UPDATE collection_medium_types SET tare_fixed=1 WHERE code IN ('SACK_1KG','SACK_2KG_UN') AND default_tare_weight IS NOT NULL"))
            if "usage" not in mt_cols:
                conn.execute(text("ALTER TABLE collection_medium_types ADD COLUMN usage VARCHAR(10) DEFAULT 'BOTH'"))
                conn.execute(text("UPDATE collection_medium_types SET usage='BOTH'"))
                # τιμές εκκίνησης: εισερχόμενα = καλάθια, εξερχόμενα = σάκοι/παλέτα/κουτί/χύμα, τα υπόλοιπα «και τα δύο»
                conn.execute(text("UPDATE collection_medium_types SET usage='IN' WHERE code IN ('BASKET_SMALL','BASKET_LARGE','INFOCYCLE_1','INFOCYCLE_2','METAL_BASKET')"))
                conn.execute(text("UPDATE collection_medium_types SET usage='OUT' WHERE code IN ('SACK_1KG','SACK_2KG_UN','PALLET','BOX','BULK')"))
        if "organizations" in tables:
            o_cols={c["name"] for c in inspect(engine).get_columns("organizations")}
            for col in ("permit_number","permit_ada"):
                if col not in o_cols: conn.execute(text(f"ALTER TABLE organizations ADD COLUMN {col} VARCHAR(100)"))
        if "loading_orders" in tables:
            lo_cols={c["name"] for c in inspect(engine).get_columns("loading_orders")}
            for col,typ in [("driver_name","VARCHAR(200)"),("eka_code","VARCHAR(60)"),("reptool_code","VARCHAR(80)"),("delivery_date","VARCHAR(10)"),("prep_mode","VARCHAR(10)")]:
                if col not in lo_cols: conn.execute(text(f"ALTER TABLE loading_orders ADD COLUMN {col} {typ}"))
        for tbl in ("shipment_history_entries","loading_orders"):
            if tbl in tables:
                t_cols={c["name"] for c in inspect(engine).get_columns(tbl)}
                for col in ("first_recipient","mgmt_operation","tracking_document","destination_country","container_number","gr_notification_no","bill_of_lading"):
                    if col not in t_cols: conn.execute(text(f"ALTER TABLE {tbl} ADD COLUMN {col} VARCHAR(200)"))
        if "production_transfer_items" in tables:
            pti_cols={c["name"] for c in inspect(engine).get_columns("production_transfer_items")}
            for col,typ in (("tare_weight","NUMERIC(14,3)"),("sent_weight","NUMERIC(14,3)"),("remainder_net","NUMERIC(14,3)"),("remainder_gross","NUMERIC(14,3)"),("remainder_mode","VARCHAR(10)"),("remainder_at","DATETIME"),("emptied","BOOLEAN DEFAULT 0")):
                if col not in pti_cols: conn.execute(text(f"ALTER TABLE production_transfer_items ADD COLUMN {col} {typ}"))
        if "materials" in tables:
            mt_cols={c["name"] for c in inspect(engine).get_columns("materials")}
            if "short_description" not in mt_cols: conn.execute(text("ALTER TABLE materials ADD COLUMN short_description VARCHAR(300)"))
            if "can_bale" not in mt_cols: conn.execute(text("ALTER TABLE materials ADD COLUMN can_bale BOOLEAN DEFAULT 0"))
            if "press_label" not in mt_cols: conn.execute(text("ALTER TABLE materials ADD COLUMN press_label VARCHAR(100)"))
        if "production_transfers" in tables:
            pt_cols={c["name"] for c in inspect(engine).get_columns("production_transfers")}
            if "present_json" not in pt_cols: conn.execute(text("ALTER TABLE production_transfers ADD COLUMN present_json TEXT"))
        if "production_transfer_items" in tables:
            pti2={c["name"] for c in inspect(engine).get_columns("production_transfer_items")}
            if "remainder_present" not in pti2: conn.execute(text("ALTER TABLE production_transfer_items ADD COLUMN remainder_present TEXT"))
        if "production_work_entries" in tables:
            pwe_cols={c["name"] for c in inspect(engine).get_columns("production_work_entries")}
            if "transfer_id" not in pwe_cols: conn.execute(text("ALTER TABLE production_work_entries ADD COLUMN transfer_id VARCHAR(36)"))
        if "sorting_sessions" in tables:
            ss_cols={c["name"] for c in inspect(engine).get_columns("sorting_sessions")}
            if "correction" not in ss_cols: conn.execute(text("ALTER TABLE sorting_sessions ADD COLUMN correction BOOLEAN DEFAULT 0"))
        if "production_attendance" in tables:
            pa_cols={c["name"] for c in inspect(engine).get_columns("production_attendance")}
            if "arrived_at" not in pa_cols: conn.execute(text("ALTER TABLE production_attendance ADD COLUMN arrived_at DATETIME"))
            if "late" not in pa_cols: conn.execute(text("ALTER TABLE production_attendance ADD COLUMN late BOOLEAN DEFAULT 0"))
            if "short_leaves" not in pa_cols: conn.execute(text("ALTER TABLE production_attendance ADD COLUMN short_leaves TEXT"))
        if "production_attendance_events" in tables:
            pe_cols={c["name"] for c in inspect(engine).get_columns("production_attendance_events")}
            if "late" not in pe_cols: conn.execute(text("ALTER TABLE production_attendance_events ADD COLUMN late BOOLEAN DEFAULT 0"))
            if "prev_late" not in pe_cols: conn.execute(text("ALTER TABLE production_attendance_events ADD COLUMN prev_late BOOLEAN DEFAULT 0"))
            if "prev_arrived_at" not in pe_cols: conn.execute(text("ALTER TABLE production_attendance_events ADD COLUMN prev_arrived_at DATETIME"))
        if "organizational_units" in tables:
            org_cols={c["name"] for c in inspect(engine).get_columns("organizational_units")}
            if "position" not in org_cols: conn.execute(text("ALTER TABLE organizational_units ADD COLUMN position VARCHAR(150)"))
            if "profile" not in org_cols: conn.execute(text("ALTER TABLE organizational_units ADD COLUMN profile VARCHAR(20)"))
        if "production_attendance_events" in tables:
            pe2 = {c["name"] for c in inspect(engine).get_columns("production_attendance_events")}
            if "unit_ids" not in pe2: conn.execute(text("ALTER TABLE production_attendance_events ADD COLUMN unit_ids TEXT"))
            if "prev_unit_ids" not in pe2: conn.execute(text("ALTER TABLE production_attendance_events ADD COLUMN prev_unit_ids TEXT"))
        if "production_placement_intervals" in tables:
            pi_cols = {c["name"] for c in inspect(engine).get_columns("production_placement_intervals")}
            if "org_unit_ids" not in pi_cols: conn.execute(text("ALTER TABLE production_placement_intervals ADD COLUMN org_unit_ids TEXT"))
        if "materials" in tables:
            mat2={c["name"] for c in inspect(engine).get_columns("materials")}
            if "storage_group_id" not in mat2: conn.execute(text("ALTER TABLE materials ADD COLUMN storage_group_id VARCHAR(36)"))
        if "ready_material_lots" in tables:
            rl={c["name"] for c in inspect(engine).get_columns("ready_material_lots")}
            for col,typ in [("entry_type","VARCHAR(20) DEFAULT 'EXPORT'"),("period_year","INTEGER"),("period_quarter","INTEGER"),("period_month","INTEGER"),("counted_kg","NUMERIC(14,3)"),("storage_group_id","VARCHAR(36)"),("source_inventory_id","VARCHAR(36)"),("is_demo","BOOLEAN DEFAULT 0"),("is_bale","BOOLEAN DEFAULT 0")]:
                if col not in rl: conn.execute(text(f"ALTER TABLE ready_material_lots ADD COLUMN {col} {typ}"))
        if "weee_categories" in tables:
            wcols={c["name"] for c in inspect(engine).get_columns("weee_categories")}
            if "her_description" not in wcols: conn.execute(text("ALTER TABLE weee_categories ADD COLUMN her_description VARCHAR(300)"))
            if "eka_code" not in wcols: conn.execute(text("ALTER TABLE weee_categories ADD COLUMN eka_code VARCHAR(50)"))
            if "processable" not in wcols: conn.execute(text("ALTER TABLE weee_categories ADD COLUMN processable BOOLEAN DEFAULT 1"))
        if "materials" in tables:
            mcols={c["name"] for c in inspect(engine).get_columns("materials")}
            for col,sqltype in [("genre","VARCHAR(120)"),("official_description","VARCHAR(300)"),("her_description","VARCHAR(300)"),("reptool_description","VARCHAR(500)"),("export_step_kg","NUMERIC(14,3) DEFAULT 0.500")]:
                if col not in mcols: conn.execute(text(f"ALTER TABLE materials ADD COLUMN {col} {sqltype}"))
    # Build 2.5.36+: new schema changes are Alembic migrations instead of another
    # ALTER TABLE block above. This only stamps/upgrades -- it never re-runs the
    # baseline DDL against a database that already has it (see app/migrations.py).
    run_alembic_migrations(engine)
    _setup_file_log()   # ξανά μετά το alembic (που απενεργοποιεί τους loggers)
    with SessionLocal() as db:
        # Backfill legacy employee default department into the new many-to-many mapping.
        for emp in db.scalars(select(Employee).where(Employee.default_org_unit_id.is_not(None))).all():
            exists=db.execute(select(employee_org_units).where(employee_org_units.c.employee_id==emp.id, employee_org_units.c.org_unit_id==emp.default_org_unit_id)).first()
            if not exists:
                db.execute(employee_org_units.insert().values(employee_id=emp.id,org_unit_id=emp.default_org_unit_id))
        # Preserve any legacy single "position" as the first item of the new department positions list.
        for unit in db.scalars(select(OrganizationalUnit).where(OrganizationalUnit.position.is_not(None))).all():
            name=(unit.position or '').strip()
            if name and not db.scalar(select(OrgUnitPosition).where(OrgUnitPosition.org_unit_id==unit.id,OrgUnitPosition.name==name)):
                db.add(OrgUnitPosition(org_unit_id=unit.id,name=name,sort_order=0,active=True))
        db.commit()
        _reconcile_unit_sets(db)
        _flatten_storage_groups(db)
        seed(db)
        ensure_real_2026_import(db)
        ensure_real_production_2026_import(db)
        ensure_material_output_2026_import(db)
        ensure_material_opening_stock_2025_import(db)
        _backfill_dpp_numbers(db)
    ec_task = asyncio.create_task(_electrocycle_loop())
    yield
    ec_task.cancel()

app = FastAPI(title="WEEE Operations Platform API", version="2.5.35", lifespan=lifespan)

# ---- Άμεση ειδοποίηση αλλαγών (Server-Sent Events) -------------------------------------------------
# Κάθε επιτυχής εγγραφή (POST/PUT/PATCH/DELETE) ειδοποιεί όλες τις συνδεδεμένες οθόνες (Windows/Android) με τα «θέματα» που άλλαξαν·
# οι οθόνες ξαναφορτώνουν μόνο αυτά. Η ανανέωση ανά 15″ στις οθόνες μένει ως εφεδρική.
_event_subs:set=set()

def _topics_for_path(path:str)->set:
    p=path.lower(); t=set()
    if p.startswith("/production/attendance") or p.startswith("/production/placement"): t|={"attendance"}
    if p.startswith("/production/") and not p.startswith("/production/attendance") and not p.startswith("/production/placement"): t|={"production","inventory"}
    if p.startswith("/master/employees") or p.startswith("/master/org-units"): t|={"masters","attendance"}
    elif p.startswith("/master/"): t|={"masters"}
    if p.startswith("/sorting") or p.startswith("/inventory") or p.startswith("/receipts"): t|={"inventory","sorting"}
    if p.startswith("/settings"): t|={"settings","attendance"}
    return t or {"misc"}

def _publish_change(path:str):
    topics=_topics_for_path(path)
    for q in list(_event_subs):
        for tp in topics:
            try: q.put_nowait(tp)
            except Exception: pass

class _ChangeNotifier:
    """Καθαρό ASGI middleware: μετά από επιτυχή εγγραφή (η απάντηση ξεκινά ΜΕΤΑ το commit) ειδοποιεί τους συνδρομητές."""
    def __init__(self, inner): self.inner=inner
    async def __call__(self, scope, receive, send):
        if scope["type"]!="http" or scope.get("method") not in ("POST","PUT","PATCH","DELETE") or scope["path"].startswith("/events"):
            return await self.inner(scope,receive,send)
        path=scope["path"]
        async def snd(m):
            if m["type"]=="http.response.start" and m["status"]<400: _publish_change(path)
            await send(m)
        await self.inner(scope,receive,snd)

app.add_middleware(_ChangeNotifier)

# ---- Μοναδικός κωδικός αιτήματος (X-Request-Id): το ίδιο αίτημα που ξαναέρχεται ΔΕΝ γράφεται ξανά ----------
_idem_locks:dict={}

def _idem_get(rid:str):
    db=SessionLocal()
    try:
        r=db.get(models.IdempotencyKey,rid)
        return (r.status,r.body or "") if r else None
    finally: db.close()

IDEM_KEEP_DAYS=30
_idem_last_purge=[0.0]

def _purge_idem(days:int=IDEM_KEEP_DAYS)->int:
    """Σβήνει τους κωδικούς αιτημάτων παλιότερους από `days` ημέρες· επιστρέφει πόσους έσβησε."""
    db=SessionLocal()
    try:
        r=db.execute(models.IdempotencyKey.__table__.delete().where(models.IdempotencyKey.created_at<datetime.utcnow()-timedelta(days=days)))
        db.commit(); return r.rowcount or 0
    except Exception:
        db.rollback(); return 0
    finally: db.close()

def _idem_put(rid:str,method:str,path:str,status:int,body:str):
    import time as _t
    if _t.time()-_idem_last_purge[0]>86400: _idem_last_purge[0]=_t.time(); _purge_idem()
    db=SessionLocal()
    try:
        if not db.get(models.IdempotencyKey,rid):
            db.add(models.IdempotencyKey(id=rid,method=method,path=path[:300],status=status,body=body)); db.commit()
    except Exception: db.rollback()
    finally: db.close()

class _Idempotency:
    """Pure ASGI: αίτημα εγγραφής με header X-Request-Id. Πρώτη φορά εκτελείται και αποθηκεύεται η (επιτυχής) απάντηση·
    αν ξαναέρθει ο ίδιος κωδικός, επιστρέφεται η αρχική απάντηση (header X-Idempotent-Replay) χωρίς νέα εγγραφή."""
    def __init__(self, inner): self.inner=inner
    async def __call__(self, scope, receive, send):
        if scope["type"]!="http" or scope.get("method") not in ("POST","PUT","PATCH","DELETE") or scope["path"].startswith("/events") or scope["path"].startswith("/auth/"):
            return await self.inner(scope,receive,send)
        rid=None
        for k,v in scope.get("headers") or []:
            if k==b"x-request-id": rid=v.decode("latin-1").strip()[:64]
        if not rid: return await self.inner(scope,receive,send)
        from starlette.concurrency import run_in_threadpool
        lock=_idem_locks.setdefault(rid,asyncio.Lock())
        try:
            async with lock:
                rec=await run_in_threadpool(_idem_get,rid)
                if rec:
                    st,body=rec; raw=body.encode("utf-8")
                    await send({"type":"http.response.start","status":st,"headers":[(b"content-type",b"application/json"),(b"content-length",str(len(raw)).encode()),(b"x-idempotent-replay",b"true")]})
                    await send({"type":"http.response.body","body":raw})
                    return
                cap={"status":None,"body":b""}
                async def snd(m):
                    if m["type"]=="http.response.start": cap["status"]=m["status"]
                    elif m["type"]=="http.response.body": cap["body"]+=m.get("body",b"")
                    await send(m)
                await self.inner(scope,receive,snd)
                if cap["status"] and 200<=cap["status"]<300:
                    await run_in_threadpool(_idem_put,rid,scope["method"],scope["path"],cap["status"],cap["body"].decode("utf-8","replace"))
        finally:
            if not lock.locked(): _idem_locks.pop(rid,None)

app.add_middleware(_Idempotency)

# ---- Ώρα που έγινε η ενέργεια στην οθόνη του χρήστη (X-Occurred-At, ISO UTC) ----------------------------------
# Η ουρά των οθονών στέλνει την ώρα του κλικ· ο server γράφει ΑΥΤΗ την ώρα (παρουσίες, αποστολές, Υπόλοιπο, μεταφορές εργαζομένων),
# όχι την ώρα που έφτασε το αίτημα. Έλεγχος: όχι στο μέλλον (ανοχή ρολογιού 5′) και όχι πάνω από 3 ημέρες πίσω.
import contextvars as _cv
_occurred=_cv.ContextVar("occurred_at",default=None)
OCCURRED_MAX_AGE=timedelta(days=3); OCCURRED_FUTURE_SLACK=timedelta(minutes=5)

def _event_now()->datetime:
    """Ώρα της ενέργειας (naive UTC): της οθόνης αν στάλθηκε, αλλιώς η τωρινή."""
    return _occurred.get() or datetime.utcnow()

def _event_now_aware()->datetime:
    return _event_now().replace(tzinfo=timezone.utc)

def _event_now_local()->datetime:
    v=_occurred.get()
    return v.replace(tzinfo=timezone.utc).astimezone().replace(tzinfo=None) if v else datetime.now()

def _parse_occurred(v:str):
    d=datetime.fromisoformat(v.strip().replace("Z","+00:00"))
    return d.astimezone(timezone.utc).replace(tzinfo=None) if d.tzinfo else d

class _ClientTime:
    """Pure ASGI: διαβάζει το X-Occurred-At και το κάνει διαθέσιμο στον κώδικα που γράφει ώρες."""
    def __init__(self, inner): self.inner=inner
    async def __call__(self, scope, receive, send):
        if scope["type"]!="http" or scope.get("method") not in ("POST","PUT","PATCH","DELETE"):
            return await self.inner(scope,receive,send)
        hv=None
        for k,v in scope.get("headers") or []:
            if k==b"x-occurred-at": hv=v.decode("latin-1")
        if not hv: return await self.inner(scope,receive,send)
        msg=None; occ=None
        try:
            occ=_parse_occurred(hv); now=datetime.utcnow()
            if occ>now+OCCURRED_FUTURE_SLACK: msg="Η ώρα της συσκευής δεν είναι σωστή (είναι στο μέλλον). Έλεγξε την ώρα του κινητού/υπολογιστή."
            elif occ<now-OCCURRED_MAX_AGE: msg="Η ενέργεια έγινε πάνω από 3 ημέρες πριν και δεν γράφτηκε."
            elif occ>now: occ=now
        except Exception: msg="Μη έγκυρη ώρα ενέργειας."
        if msg:
            raw=json.dumps({"detail":msg},ensure_ascii=False).encode("utf-8")
            await send({"type":"http.response.start","status":422,"headers":[(b"content-type",b"application/json; charset=utf-8"),(b"content-length",str(len(raw)).encode())]})
            await send({"type":"http.response.body","body":raw}); return
        tok=_occurred.set(occ)
        try: await self.inner(scope,receive,send)
        finally: _occurred.reset(tok)

app.add_middleware(_ClientTime)
from .mat_warehouse import router as _mat_router
app.include_router(_mat_router)

@app.get("/health")
def health(): return {"status":"ok","version":"2.5.35"}

@app.post("/auth/token", response_model=schemas.Token)
def login(req: schemas.LoginRequest, db: Session=Depends(get_db)):
    user=db.scalar(select(User).where(User.username==req.username))
    if not user or not user.active or not verify_password(req.password,user.password_hash):
        raise HTTPException(401,"Λάθος στοιχεία σύνδεσης")
    user.last_login=datetime.now(timezone.utc); db.commit()
    return schemas.Token(access_token=make_token(user))

@app.post("/auth/refresh", response_model=schemas.Token)
def refresh_token(user: User=Depends(current_user)):
    """Νέο token με νέα διάρκεια (για το κανάλι /events και για μακρές βάρδιες)."""
    return schemas.Token(access_token=make_token(user))

@app.get("/me")
def me(db: Session=Depends(get_db), user: User=Depends(current_user)):
    person=db.get(Person,user.person_id) if user.person_id else None
    return {"id":user.id,"username":user.username,"email":(person.email if person else None),"roles":[r.code for r in user.roles],"permissions":sorted({p.code for r in user.roles for p in r.permissions})}

@app.get("/account/role-levels")
def account_role_levels(db:Session=Depends(get_db), user:User=Depends(current_user)):
    roles=db.scalars(select(models.Role).order_by(models.Role.name_el)).all()
    return [{"code":r.code,"name":r.name_el,"permissions":sorted(p.code for p in r.permissions)} for r in roles]

@app.get("/master/org-units", response_model=list[schemas.OrgUnitOut])
def list_org_units(include_inactive:bool=Query(default=False), db:Session=Depends(get_db), user=Depends(require_permission("master.view"))):
    stmt=select(OrganizationalUnit)
    if not include_inactive: stmt=stmt.where(OrganizationalUnit.active==True)
    units=db.scalars(stmt.order_by(OrganizationalUnit.sort_order,OrganizationalUnit.name_el)).all()
    out=[]
    for u in units:
        poss=db.scalars(select(OrgUnitPosition).where(OrgUnitPosition.org_unit_id==u.id,OrgUnitPosition.active==True).order_by(OrgUnitPosition.sort_order,OrgUnitPosition.name)).all()
        out.append({"id":u.id,"code":u.code,"name_el":u.name_el,"name_en":u.name_en,"parent_id":u.parent_id,"sort_order":u.sort_order,"position":u.position,"positions":[x.name for x in poss],"active":u.active,"profile":u.profile})
    return out

def _replace_org_positions(db:Session, unit_id:str, positions:list[str]):
    clean=[]
    for x in positions or []:
        v=(x or '').strip()
        if v and v.casefold() not in {y.casefold() for y in clean}: clean.append(v)
    existing=db.scalars(select(OrgUnitPosition).where(OrgUnitPosition.org_unit_id==unit_id)).all()
    by_name={x.name.casefold():x for x in existing}
    keep=set()
    for i,name in enumerate(clean):
        key=name.casefold(); keep.add(key)
        row=by_name.get(key)
        if row:
            row.name=name; row.sort_order=i; row.active=True
        else:
            db.add(OrgUnitPosition(org_unit_id=unit_id,name=name,sort_order=i,active=True))
    for row in existing:
        if row.name.casefold() not in keep: row.active=False

@app.post("/master/org-units", response_model=schemas.OrgUnitOut)
def create_org_unit(data:schemas.OrgUnitCreate, db:Session=Depends(get_db), user:User=Depends(require_permission("master.edit"))):
    if db.scalar(select(OrganizationalUnit).where(OrganizationalUnit.code==data.code)): raise HTTPException(409,"Ο κωδικός υπάρχει ήδη")
    if data.profile not in (None,"PRODUCTION","SUPPORT","MANAGEMENT"): raise HTTPException(422,"Άγνωστο προφίλ τμήματος")
    payload=data.model_dump(exclude={"positions"}); obj=OrganizationalUnit(**payload); db.add(obj); db.flush(); _replace_org_positions(db,obj.id,data.positions)
    write_audit(db,user,"organizational_unit",obj.id,"CREATE",new=data.model_dump()); db.commit();
    rows=list_org_units(True,db,user); return next(x for x in rows if x["id"]==obj.id)

@app.put("/master/org-units/{unit_id}", response_model=schemas.OrgUnitOut)
def update_org_unit(unit_id:str, data:schemas.OrgUnitCreate, db:Session=Depends(get_db), user:User=Depends(require_permission("master.edit"))):
    obj=db.get(OrganizationalUnit,unit_id)
    if not obj: raise HTTPException(404,"Το τμήμα δεν βρέθηκε")
    old={"code":obj.code,"name_el":obj.name_el,"name_en":obj.name_en,"parent_id":obj.parent_id,"sort_order":obj.sort_order,"position":obj.position,"profile":obj.profile}
    if data.profile not in (None,"PRODUCTION","SUPPORT","MANAGEMENT"): raise HTTPException(422,"Άγνωστο προφίλ τμήματος")
    for k,v in data.model_dump(exclude={"positions"}).items():
        if k=="profile" and "profile" not in data.model_fields_set: continue  # παλιοί πελάτες δεν σβήνουν το προφίλ
        setattr(obj,k,v)
    if "positions" in data.model_fields_set: _replace_org_positions(db,obj.id,data.positions)
    write_audit(db,user,"organizational_unit",obj.id,"UPDATE",old=old,new=data.model_dump(exclude={"positions"}))
    db.commit()
    rows=list_org_units(True,db,user); return next(x for x in rows if x["id"]==obj.id)

@app.delete("/master/org-units/{unit_id}")
def delete_org_unit(unit_id:str, db:Session=Depends(get_db), user:User=Depends(require_permission("master.edit"))):
    obj=db.get(OrganizationalUnit,unit_id)
    if not obj: raise HTTPException(404,"Το τμήμα δεν βρέθηκε")
    obj.active=False; write_audit(db,user,"organizational_unit",obj.id,"DEACTIVATE",old={"active":True},new={"active":False}); db.commit(); return {"ok":True}

def _org_unit_usage(db:Session,unit_id:str)->dict:
    """Πόσες εγγραφές ιστορικού/χρήσης αναφέρονται στο τμήμα (κιλά, παρουσίες, εργαζόμενοι, ιστορικό)."""
    counts={"kg":0,"attendance":0,"employees":0,"history":0,"other":0}
    for t in Base.metadata.tables.values():
        if t.name in ("org_unit_positions","employee_org_units","organizational_units"): continue
        for col in t.columns:
            if col.name in ("org_unit_id","destination_org_unit_id","source_org_unit_id","prev_org_unit_id","default_org_unit_id"):
                n=db.scalar(select(func.count()).select_from(t).where(col==unit_id)) or 0
                if not n: continue
                if t.name in ("production_work_entries","production_transfers"): counts["kg"]+=n
                elif t.name=="production_attendance": counts["attendance"]+=n
                elif t.name=="employees": counts["employees"]+=n
                elif t.name in ("production_attendance_events","production_placement_intervals"): counts["history"]+=n
                else: counts["other"]+=n
    counts["employees"]+=db.scalar(select(func.count()).select_from(employee_org_units).where(employee_org_units.c.org_unit_id==unit_id)) or 0
    counts["other"]+=db.scalar(select(func.count()).select_from(OrganizationalUnit).where(OrganizationalUnit.parent_id==unit_id)) or 0
    counts["total"]=sum(counts.values())
    return counts

@app.get("/master/org-units/{unit_id}/usage")
def org_unit_usage(unit_id:str, db:Session=Depends(get_db), user=Depends(require_permission("master.view"))):
    if not db.get(OrganizationalUnit,unit_id): raise HTTPException(404,"Το τμήμα δεν βρέθηκε")
    return _org_unit_usage(db,unit_id)

@app.delete("/master/org-units/{unit_id}/permanent")
def delete_org_unit_permanent(unit_id:str, db:Session=Depends(get_db), user:User=Depends(require_permission("master.edit"))):
    """Οριστική διαγραφή -- ΜΟΝΟ αν το τμήμα δεν έχει καμία χρήση. Αλλιώς 409 (κρατιούνται τα στατιστικά· χρησιμοποίησε «Μη ενεργό»)."""
    obj=db.get(OrganizationalUnit,unit_id)
    if not obj: raise HTTPException(404,"Το τμήμα δεν βρέθηκε")
    u=_org_unit_usage(db,unit_id)
    if u["total"]: raise HTTPException(409,"Το τμήμα έχει ιστορικό (κιλά, παρουσίες, εργαζόμενοι) και δεν μπορεί να διαγραφεί")
    old={"code":obj.code,"name_el":obj.name_el,"profile":obj.profile}
    db.execute(OrgUnitPosition.__table__.delete().where(OrgUnitPosition.org_unit_id==unit_id))
    write_audit(db,user,"organizational_unit",obj.id,"DELETE",old=old,new=None)
    db.delete(obj); db.commit(); return {"ok":True}

@app.get("/master/organizations", response_model=list[schemas.OrganizationOut])
def list_organizations(role:str|None=Query(default=None), include_inactive:bool=Query(default=False), db:Session=Depends(get_db), user=Depends(require_permission("master.view"))):
    stmt=select(Organization)
    if not include_inactive: stmt=stmt.where(Organization.active==True)
    if role:
        stmt=stmt.join(models.organization_roles, models.organization_roles.c.organization_id==Organization.id).where(models.organization_roles.c.role==role)
    return db.scalars(stmt.order_by(Organization.legal_name)).all()

@app.post("/master/organizations", response_model=schemas.OrganizationOut)
def create_organization(data:schemas.OrganizationCreate, db:Session=Depends(get_db), user:User=Depends(require_permission("master.edit"))):
    if data.supplier_kind not in (None,"COMPANY","SCRAP_DEALER"): raise HTTPException(422,"Μη έγκυρη κατηγορία προμηθευτή")
    if data.supplier_source not in (None,"SENDER","PICKUP_POINT"): raise HTTPException(422,"Μη έγκυρη πηγή προμηθευτή")
    payload=data.model_dump(exclude={"roles"}); obj=Organization(**payload); db.add(obj); db.flush()
    if data.roles:
        from sqlalchemy import insert
        for role in sorted(set(data.roles)):
            db.execute(models.organization_roles.insert().values(organization_id=obj.id,role=role))
    write_audit(db,user,"organization",obj.id,"CREATE",new=data.model_dump()); db.commit(); db.refresh(obj); return obj

@app.put("/master/organizations/{organization_id}", response_model=schemas.OrganizationOut)
def update_organization(organization_id:str, data:schemas.OrganizationUpdate, db:Session=Depends(get_db), user:User=Depends(require_permission("master.edit"))):
    obj=db.get(Organization,organization_id)
    if not obj: raise HTTPException(404,"Η εταιρεία δεν βρέθηκε")
    if data.supplier_kind not in (None,"COMPANY","SCRAP_DEALER"): raise HTTPException(422,"Μη έγκυρη κατηγορία προμηθευτή")
    if data.supplier_source not in (None,"SENDER","PICKUP_POINT"): raise HTTPException(422,"Μη έγκυρη πηγή προμηθευτή")
    old={"legal_name":obj.legal_name,"trade_name":obj.trade_name,"tax_id":obj.tax_id,"email":obj.email,"phone":obj.phone,"supplier_kind":obj.supplier_kind,"supplier_source":obj.supplier_source}
    for k,v in data.model_dump(exclude={"roles"}).items():
        if k in ("supplier_kind","supplier_source","permit_number","permit_ada") and k not in data.model_fields_set: continue
        setattr(obj,k,v)
    db.execute(models.organization_roles.delete().where(models.organization_roles.c.organization_id==organization_id))
    for role in sorted(set(data.roles)):
        db.execute(models.organization_roles.insert().values(organization_id=organization_id,role=role))
    write_audit(db,user,"organization",obj.id,"UPDATE",old=old,new=data.model_dump()); db.commit(); db.refresh(obj); return obj

@app.delete("/master/organizations/{organization_id}")
def deactivate_organization(organization_id:str, db:Session=Depends(get_db), user:User=Depends(require_permission("master.edit"))):
    obj=db.get(Organization,organization_id)
    if not obj: raise HTTPException(404,"Η εταιρεία δεν βρέθηκε")
    obj.active=False
    write_audit(db,user,"organization",obj.id,"DEACTIVATE",old={"active":True},new={"active":False}); db.commit()
    return {"id":obj.id,"active":False}

@app.delete("/master/organizations/{organization_id}/purge")
def purge_organization(organization_id:str, db:Session=Depends(get_db), user:User=Depends(require_permission("master.edit"))):
    obj=db.get(Organization,organization_id)
    if not obj: raise HTTPException(404,"Η εταιρεία δεν βρέθηκε")
    n_trips=db.scalar(select(func.count()).select_from(InboundTrip).where(InboundTrip.carrier_id==organization_id)) or 0
    n_loads=db.scalar(select(func.count()).select_from(InboundLoad).where(InboundLoad.supplier_id==organization_id)) or 0
    if n_trips:
        raise HTTPException(409,f"Ο μεταφορέας «{obj.legal_name}» έχει {n_trips} παραλαβές και δεν μπορεί να διαγραφεί οριστικά, για να μη χαθεί το ιστορικό τους. Χρησιμοποίησε «Μη ενεργό» (φεύγει από τις λίστες επιλογής αλλά κρατιέται το ιστορικό) ή «Συγχώνευση» με άλλον μεταφορέα.")
    if n_loads:
        raise HTTPException(409,f"Η εγγραφή «{obj.legal_name}» έχει {n_loads} παραλαβές ως προμηθευτής και δεν μπορεί να διαγραφεί οριστικά. Χρησιμοποίησε «Μη ενεργό» ή «Συγχώνευση».")
    db.execute(models.organization_roles.delete().where(models.organization_roles.c.organization_id==organization_id)); db.delete(obj); db.commit(); return {"deleted":True,"id":organization_id}

@app.post("/master/organizations/{organization_id}/activate")
def activate_organization(organization_id:str, db:Session=Depends(get_db), user:User=Depends(require_permission("master.edit"))):
    obj=db.get(Organization,organization_id)
    if not obj: raise HTTPException(404,"Η εταιρεία δεν βρέθηκε")
    obj.active=True; write_audit(db,user,"organization",obj.id,"ACTIVATE",old={"active":False},new={"active":True}); db.commit()
    return {"id":obj.id,"active":True}

@app.post("/master/organizations/merge")
def merge_organizations(data:schemas.OrganizationMergeRequest, db:Session=Depends(get_db), user:User=Depends(require_permission("master.edit"))):
    target=db.get(Organization,data.target_id)
    if not target: raise HTTPException(404,"Η εγγραφή-στόχος δεν βρέθηκε")
    source_ids=[s for s in dict.fromkeys(data.source_ids) if s!=data.target_id]
    if not source_ids: raise HTTPException(422,"Δεν επιλέχθηκαν εγγραφές για συγχώνευση")
    # Ίδιος κωδικός container στον μεταφορέα που συγχωνεύεται και στον στόχο: δεν γράφεται δεύτερος· διακόπτεται η συγχώνευση (χωρίς καμία αλλαγή)
    def _ctr_codes(oid):
        return {_container_public(x).container_number for x in db.scalars(select(ContainerAsset).where(ContainerAsset.owner_organization_id==oid)).all()}
    tgt_codes=_ctr_codes(data.target_id); dups=[]
    for sid in source_ids:
        dups+=sorted(_ctr_codes(sid)&tgt_codes)
    if dups: raise HTTPException(409,"Η συγχώνευση διακόπηκε: οι κωδικοί containers "+", ".join(dups[:15])+(" …" if len(dups)>15 else "")+" υπάρχουν και στους δύο μεταφορείς. Δεν έγινε καμία αλλαγή.")
    merged=[]
    for sid in source_ids:
        src=db.get(Organization,sid)
        if not src: continue
        src_roles=set(db.execute(select(models.organization_roles.c.role).where(models.organization_roles.c.organization_id==sid)).scalars().all())
        tgt_roles=set(db.execute(select(models.organization_roles.c.role).where(models.organization_roles.c.organization_id==data.target_id)).scalars().all())
        for role in src_roles-tgt_roles:
            db.execute(models.organization_roles.insert().values(organization_id=data.target_id,role=role))
        db.execute(models.organization_roles.delete().where(models.organization_roles.c.organization_id==sid))
        tgt_detail=db.scalar(select(models.OrganizationRegistryDetail).where(models.OrganizationRegistryDetail.organization_id==data.target_id))
        src_detail=db.scalar(select(models.OrganizationRegistryDetail).where(models.OrganizationRegistryDetail.organization_id==sid))
        if src_detail:
            if tgt_detail: db.delete(src_detail)
            else: src_detail.organization_id=data.target_id
        for b in db.scalars(select(models.SupplierBranch).where(models.SupplierBranch.supplier_id==sid)).all():
            clash=db.scalar(select(models.SupplierBranch).where(models.SupplierBranch.supplier_id==data.target_id,models.SupplierBranch.name==b.name))
            if clash: db.delete(b)
            else: b.supplier_id=data.target_id
        db.execute(update(models.CarrierDriver).where(models.CarrierDriver.carrier_id==sid).values(carrier_id=data.target_id))
        for v in db.scalars(select(models.CarrierVehicle).where(models.CarrierVehicle.carrier_id==sid)).all():
            clash=db.scalar(select(models.CarrierVehicle).where(models.CarrierVehicle.carrier_id==data.target_id,models.CarrierVehicle.plate_number==v.plate_number))
            if clash: db.delete(v)
            else: v.carrier_id=data.target_id
        db.execute(update(models.ContainerAsset).where(models.ContainerAsset.owner_organization_id==sid).values(owner_organization_id=data.target_id))
        db.execute(update(models.InboundTrip).where(models.InboundTrip.carrier_id==sid).values(carrier_id=data.target_id))
        db.execute(update(models.InboundLoad).where(models.InboundLoad.supplier_id==sid).values(supplier_id=data.target_id))
        db.execute(update(models.LoadingOrder).where(models.LoadingOrder.customer_id==sid).values(customer_id=data.target_id))
        db.execute(update(models.LoadingOrder).where(models.LoadingOrder.carrier_id==sid).values(carrier_id=data.target_id))
        write_audit(db,user,"organization",data.target_id,"MERGE",old={"merged_from_id":sid,"merged_from_name":src.legal_name},new={"merged_into_id":data.target_id,"merged_into_name":target.legal_name})
        db.delete(src)
        merged.append(sid)
    db.commit(); db.refresh(target)
    return {"target_id":target.id,"merged_ids":merged}

@app.get("/master/suppliers/{supplier_id}/branches", response_model=list[schemas.SupplierBranchOut])
def supplier_branches(supplier_id:str, include_inactive:bool=Query(default=False), db:Session=Depends(get_db), user=Depends(require_permission("master.view"))):
    stmt=select(models.SupplierBranch).where(models.SupplierBranch.supplier_id==supplier_id)
    if not include_inactive: stmt=stmt.where(models.SupplierBranch.active==True)
    return db.scalars(stmt.order_by(models.SupplierBranch.name)).all()

@app.get("/master/organizations-search", response_model=list[schemas.OrganizationSearchOut])
def organizations_search(q:str=Query(default=""), role:str|None=Query(default=None), limit:int=Query(default=20, ge=1, le=100), db:Session=Depends(get_db), user=Depends(require_permission("master.view"))):
    from sqlalchemy import or_
    stmt=select(Organization).where(Organization.active==True)
    if role:
        stmt=stmt.join(models.organization_roles, models.organization_roles.c.organization_id==Organization.id).where(models.organization_roles.c.role==role)
    rows=db.scalars(stmt).all()
    qn=(q or '').strip().casefold()
    out=[]
    for o in rows:
        d=db.scalar(select(models.OrganizationRegistryDetail).where(models.OrganizationRegistryDetail.organization_id==o.id))
        hay=' | '.join(filter(None,[o.legal_name,o.trade_name,o.tax_id,o.phone, getattr(d,'external_code',None),getattr(d,'transaction_code',None),getattr(d,'municipality',None),getattr(d,'prefecture',None),getattr(d,'profession',None)])).casefold()
        if qn and qn not in hay: continue
        name=(o.trade_name or o.legal_name or '')
        score=0 if not qn else (100 if name.casefold().startswith(qn) else 80 if (o.tax_id or '').casefold().startswith(qn) else 60 if qn in name.casefold() else 30)
        extra=' · '.join(filter(None,[o.tax_id,getattr(d,'municipality',None),getattr(d,'profession',None)]))
        out.append((score,name.casefold(),schemas.OrganizationSearchOut(id=o.id,legal_name=o.legal_name,trade_name=o.trade_name,tax_id=o.tax_id,phone=o.phone,extra=extra or None)))
    out.sort(key=lambda x:(-x[0],x[1]))
    return [x[2] for x in out[:limit]]

@app.get("/master/carriers/{carrier_id}/drivers", response_model=list[schemas.CarrierDriverOut])
def carrier_drivers(carrier_id:str, include_inactive:bool=Query(default=False), db:Session=Depends(get_db), user=Depends(require_permission("master.view"))):
    stmt=select(models.CarrierDriver).where(models.CarrierDriver.carrier_id==carrier_id)
    if not include_inactive: stmt=stmt.where(models.CarrierDriver.active==True)
    return db.scalars(stmt.order_by(models.CarrierDriver.full_name)).all()

@app.post("/master/carriers/{carrier_id}/drivers", response_model=schemas.CarrierDriverOut)
def add_carrier_driver(carrier_id:str, data:schemas.CarrierDriverCreate, db:Session=Depends(get_db), user:User=Depends(require_permission("master.edit"))):
    if not db.get(Organization,carrier_id): raise HTTPException(404,"Ο μεταφορέας δεν βρέθηκε")
    obj=models.CarrierDriver(carrier_id=carrier_id,full_name=data.full_name.strip(),phone=data.phone,active=data.active); db.add(obj); db.commit(); db.refresh(obj); return obj

@app.put("/master/carrier-drivers/{driver_id}", response_model=schemas.CarrierDriverOut)
def update_carrier_driver(driver_id:str, data:schemas.CarrierDriverCreate, db:Session=Depends(get_db), user:User=Depends(require_permission("master.edit"))):
    obj=db.get(models.CarrierDriver,driver_id)
    if not obj: raise HTTPException(404,"Ο οδηγός δεν βρέθηκε")
    obj.full_name=data.full_name.strip(); obj.phone=data.phone; obj.active=data.active; db.commit(); db.refresh(obj); return obj

@app.get("/master/carriers/{carrier_id}/vehicles", response_model=list[schemas.CarrierVehicleOut])
def carrier_vehicles(carrier_id:str, include_inactive:bool=Query(default=False), db:Session=Depends(get_db), user=Depends(require_permission("master.view"))):
    stmt=select(models.CarrierVehicle).where(models.CarrierVehicle.carrier_id==carrier_id)
    if not include_inactive: stmt=stmt.where(models.CarrierVehicle.active==True)
    return db.scalars(stmt.order_by(models.CarrierVehicle.plate_number)).all()

@app.post("/master/carriers/{carrier_id}/vehicles", response_model=schemas.CarrierVehicleOut)
def add_carrier_vehicle(carrier_id:str, data:schemas.CarrierVehicleCreate, db:Session=Depends(get_db), user:User=Depends(require_permission("master.edit"))):
    if not db.get(Organization,carrier_id): raise HTTPException(404,"Ο μεταφορέας δεν βρέθηκε")
    plate=data.plate_number.strip().upper()
    if not plate: raise HTTPException(422,"Συμπλήρωσε πινακίδα")
    existing=db.scalar(select(models.CarrierVehicle).where(models.CarrierVehicle.carrier_id==carrier_id,models.CarrierVehicle.plate_number==plate))
    if existing:
        if not existing.active: existing.active=True; db.commit(); db.refresh(existing)
        return existing
    obj=models.CarrierVehicle(carrier_id=carrier_id,plate_number=plate,active=True); db.add(obj); db.commit(); db.refresh(obj); return obj

@app.get("/visitor-log", response_model=list[schemas.VisitorLogOut])
def visitor_log(db:Session=Depends(get_db), user=Depends(require_permission("receipt.view"))):
    return db.scalars(select(models.VisitorLog).order_by(models.VisitorLog.visit_date.desc(),models.VisitorLog.arrival_at.desc())).all()

@app.post("/visitor-log", response_model=schemas.VisitorLogOut)
def add_visitor_log(data:schemas.VisitorLogCreate, db:Session=Depends(get_db), user:User=Depends(require_permission("receipt.edit"))):
    obj=models.VisitorLog(**data.model_dump(),source_type="MANUAL",created_by=user.id); db.add(obj); db.commit(); db.refresh(obj); return obj

def _sync_receipt_visitor(db:Session, trip:models.InboundTrip, user:User):
    if not (trip.driver_name or '').strip(): return
    loads=db.scalars(select(models.InboundLoad).where(models.InboundLoad.trip_id==trip.id)).all()
    has_first=any(l.gross_weight is not None for l in loads); has_second=bool(loads) and all(l.tare_weight is not None for l in loads)
    now=datetime.now(timezone.utc)
    v=db.scalar(select(models.VisitorLog).where(models.VisitorLog.source_type=="RECEIPT",models.VisitorLog.source_id==trip.id))
    if not v:
        v=models.VisitorLog(visit_date=trip.receipt_date,full_name=trip.driver_name.strip(),reason="Παραλαβή",source_type="RECEIPT",source_id=trip.id,created_by=user.id); db.add(v)
    v.full_name=trip.driver_name.strip(); v.visit_date=trip.receipt_date
    if has_first and not v.arrival_at: v.arrival_at=now
    if has_second and not v.departure_at: v.departure_at=now

@app.get("/master/organizations/{organization_id}/roles")
def organization_role_list(organization_id:str, db:Session=Depends(get_db), user=Depends(require_permission("master.view"))):
    if not db.get(Organization,organization_id): raise HTTPException(404,"Η εταιρεία δεν βρέθηκε")
    rows=db.execute(select(models.organization_roles.c.role).where(models.organization_roles.c.organization_id==organization_id)).scalars().all()
    return {"organization_id":organization_id,"roles":sorted(rows)}

@app.get("/master/weee-categories", response_model=list[schemas.WEEECategoryOut])
def list_weee(db:Session=Depends(get_db), user=Depends(require_permission("master.view"))):
    return db.scalars(select(WEEECategory).order_by(WEEECategory.code)).all()

@app.post("/master/weee-categories", response_model=schemas.WEEECategoryOut)
def create_weee(data:schemas.WEEECategoryCreate, db:Session=Depends(get_db), user:User=Depends(require_permission("master.edit"))):
    if db.scalar(select(WEEECategory).where(WEEECategory.code==data.code)): raise HTTPException(409,"Ο κωδικός υπάρχει ήδη")
    obj=WEEECategory(**data.model_dump()); db.add(obj); db.flush(); write_audit(db,user,"weee_category",obj.id,"CREATE",new=data.model_dump()); db.commit(); db.refresh(obj); return obj

@app.put("/master/weee-categories/{category_id}", response_model=schemas.WEEECategoryOut)
def update_weee_category(category_id:str, data:schemas.WEEECategoryCreate, db:Session=Depends(get_db), user:User=Depends(require_permission("master.edit"))):
    obj=db.get(WEEECategory,category_id)
    if not obj: raise HTTPException(404,"Η κατηγορία ΑΗΗΕ δεν βρέθηκε")
    if data.code!=obj.code and db.scalar(select(WEEECategory).where(WEEECategory.code==data.code)): raise HTTPException(409,"Ο κωδικός υπάρχει ήδη")
    old={"code":obj.code,"description_el":obj.description_el,"her_description":obj.her_description,"eka_code":obj.eka_code,"processable":obj.processable,"average_weight":obj.average_weight}
    for k,v in data.model_dump().items(): setattr(obj,k,v)
    write_audit(db,user,"weee_category",obj.id,"UPDATE",old=old,new=data.model_dump())
    db.commit(); db.refresh(obj); return obj

@app.get("/master/weee-categories/{category_id}/history")
def weee_category_history(category_id:str, db:Session=Depends(get_db), user=Depends(require_permission("master.view"))):
    events=db.scalars(select(models.AuditEvent).where(models.AuditEvent.entity_type=="weee_category",models.AuditEvent.entity_id==category_id).order_by(models.AuditEvent.created_at.desc())).all()
    uids={e.user_id for e in events if e.user_id}
    users={u.id:u.username for u in db.scalars(select(User).where(User.id.in_(uids))).all()} if uids else {}
    return [{"action":e.action,"old_values":json.loads(e.old_values) if e.old_values else None,"new_values":json.loads(e.new_values) if e.new_values else None,"reason":e.reason,"user":users.get(e.user_id),"created_at":e.created_at.isoformat()} for e in events]

def _weee_display_setting(db:Session, category_id:str):
    row=db.scalar(select(AppSetting).where(AppSetting.key==f"weee.display.{category_id}"))
    if not row: return {}
    import json
    try: return json.loads(row.value)
    except Exception: return {}

@app.get("/master/weee-display")
def list_weee_display(include_inactive:bool=Query(default=False), db:Session=Depends(get_db), user=Depends(require_permission("master.view"))):
    stmt=select(WEEECategory)
    if not include_inactive: stmt=stmt.where(WEEECategory.active==True)
    rows=db.scalars(stmt.order_by(WEEECategory.code)).all(); out=[]
    internal_order={
      "4Δ0000":["INT-4D-AUDIO","INT-4D-PROJ"],
      "4Ι0000":["INT-4I-UPS","INT-4I-MON","INT-4I-CASH"],
      "4Λ0000":["INT-4L-PCSERVER","INT-4L-PRINT","INT-4L-SCAN","INT-4L-COPY","INT-4L-KEYB"],
      "5Δ0000":["INT-5D-AV","INT-5D-SPEAK","INT-5D-PROJ"],
      "5Ι2000":["INT-5I2-UPS","INT-5I2-MON","INT-5I2-CASH"],
      "6Α0000":["INT-6A-PCSERVER","INT-6A-PRINT","INT-6A-MODEM","INT-6A-KEYB","INT-6A-TELCO"]}
    def _disp_sort(c):
        if c.is_internal_subcategory and c.parent_code in internal_order:
            try: return (c.parent_code,1,internal_order[c.parent_code].index(c.code))
            except ValueError: return (c.parent_code,1,999)
        return (c.code,0,0)
    rows=sorted(rows,key=_disp_sort)
    for c in rows:
        cfg=_weee_display_setting(db,c.id); parent=db.scalar(select(WEEECategory).where(WEEECategory.code==c.parent_code)) if c.parent_code else None
        official=parent if c.is_internal_subcategory and parent else c
        out.append({"id":c.id,"code":c.code,"official_code":official.code,"official_description":official.description_el,"her_description":official.her_description,"eka_code":official.eka_code,"processable":bool(official.processable),"display_name":cfg.get("display_name") or c.description_el,"display_group":cfg.get("display_group"),"parent_code":c.parent_code,"is_internal_subcategory":c.is_internal_subcategory,"average_weight":float(c.average_weight) if c.average_weight is not None else None,"group_no":(official.code[:1] if official.code[:1] in "123456" else None),"active":bool(c.active)})
    return out

@app.put("/master/weee-display/{category_id}")
def update_weee_display(category_id:str,data:schemas.WEEEDisplayUpdate,db:Session=Depends(get_db),user:User=Depends(require_permission("master.edit"))):
    c=db.get(WEEECategory,category_id)
    if not c: raise HTTPException(404,"Η κατηγορία δεν βρέθηκε")
    import json
    key=f"weee.display.{category_id}"; row=db.scalar(select(AppSetting).where(AppSetting.key==key)); payload={"display_name":data.display_name,"display_group":data.display_group}
    if row: row.value=json.dumps(payload,ensure_ascii=False)
    else: db.add(AppSetting(key=key,value=json.dumps(payload,ensure_ascii=False)))
    write_audit(db,user,"weee_display",category_id,"UPDATE",new=payload); db.commit(); return {"ok":True,**payload}

@app.post("/master/weee-internal-subcategories")
def create_weee_internal(data:schemas.WEEEInternalSubcategoryCreate,db:Session=Depends(get_db),user:User=Depends(require_permission("master.edit"))):
    parent=db.get(WEEECategory,data.parent_category_id)
    if not parent or parent.is_internal_subcategory: raise HTTPException(422,"Επίλεξε επίσημη κατηγορία ΣΕΔ")
    count=len(db.scalars(select(WEEECategory).where(WEEECategory.is_internal_subcategory==True)).all())+1
    code=f"INT-{count:06d}"
    obj=WEEECategory(code=code,description_el=data.display_name,parent_code=parent.code,is_internal_subcategory=True,average_weight=parent.average_weight,active=True); db.add(obj); db.flush()
    write_audit(db,user,"weee_category",obj.id,"CREATE_INTERNAL",new={"display_name":data.display_name,"official_parent":parent.code}); db.commit(); db.refresh(obj)
    return {"id":obj.id,"code":obj.code,"display_name":obj.description_el,"official_code":parent.code}

@app.get("/master/materials", response_model=list[schemas.MaterialOut])
def list_materials(include_inactive:bool=Query(default=False), db:Session=Depends(get_db), user=Depends(require_permission("master.view"))):
    stmt=select(Material)
    if not include_inactive: stmt=stmt.where(Material.active==True)
    return db.scalars(stmt.order_by(Material.internal_name)).all()

def _material_precious(her_description:str|None, official_description:str|None=None):
    t=((her_description or '')+' '+(official_description or '')).casefold().replace('²','2').replace(' ','')
    return ('τυπ/νωνκυκλωμάτων>10cm2' in t) or ('πλακετ' in t) or ('motherboard' in t) or ('μνημεσram' in t) or ('επεξεργαστ' in t)

def _apply_material_rules(obj:Material):
    obj.galaxy_code=(obj.galaxy_code or '').strip() or None
    obj.active=bool(obj.galaxy_code)
    obj.is_precious=_material_precious(obj.her_description,obj.official_description or obj.galaxy_description)
    obj.export_step_kg=0.05 if obj.is_precious else 0.5

@app.post("/master/materials", response_model=schemas.MaterialOut)
def create_material(data:schemas.MaterialCreate, db:Session=Depends(get_db), user:User=Depends(require_permission("master.edit"))):
    if db.scalar(select(Material).where(Material.internal_code==data.internal_code)): raise HTTPException(409,"Ο κωδικός υπάρχει ήδη")
    obj=Material(**data.model_dump()); _apply_material_rules(obj); db.add(obj); db.flush(); write_audit(db,user,"material",obj.id,"CREATE",new=data.model_dump()); db.commit(); db.refresh(obj); return obj

@app.get("/master/medium-types", response_model=list[schemas.MediumTypeOut])
def list_medium_types(include_inactive:bool=Query(default=False), db:Session=Depends(get_db), user=Depends(require_permission("master.view"))):
    stmt=select(CollectionMediumType)
    if not include_inactive: stmt=stmt.where(CollectionMediumType.active==True)
    return db.scalars(stmt.order_by(CollectionMediumType.name_el)).all()

def _media_in_use_ids(db:Session)->set:
    """Μέσα «σε χρήση»: κατάσταση άλλη από AVAILABLE, ή κρατούν διαθέσιμο απόθεμα ΑΗΗΕ / μη εξαγόμενα υλικά."""
    used=set(db.scalars(select(CollectionMedium.id).where(CollectionMedium.status!='AVAILABLE')).all())
    used|=set(x for x in db.scalars(select(WEEEStockLot.collection_medium_id).where(WEEEStockLot.available_weight>0,WEEEStockLot.collection_medium_id.is_not(None))).all() if x)
    used|=set(x for x in db.scalars(select(ReadyMaterialLot.collection_medium_id).where(ReadyMaterialLot.status.in_(['AVAILABLE','RESERVED','LOADING']),ReadyMaterialLot.collection_medium_id.is_not(None))).all() if x)
    return used

def _medium_referenced(db:Session,mid:str)->bool:
    return bool(db.scalar(select(models.SortingEntry.id).where(models.SortingEntry.collection_medium_id==mid).limit(1))
        or db.scalar(select(models.WEEEStockLot.id).where(models.WEEEStockLot.collection_medium_id==mid).limit(1))
        or db.scalar(select(models.ReadyMaterialLot.id).where(models.ReadyMaterialLot.collection_medium_id==mid).limit(1)))

def _medium_remove(db:Session,user,m)->str:
    """Διαγραφή μέσου: αν δεν έχει ιστορικό σβήνεται, αλλιώς γίνεται ανενεργό (μένει το ιστορικό). Καταγράφεται στο ιστορικό αλλαγών."""
    if _medium_referenced(db,m.id):
        m.active=False; write_audit(db,user,"collection_medium",m.id,"DEACTIVATE",old={"active":True},new={"active":False},reason="Διαγραφή μέσου (έχει ιστορικό: κρατιέται ανενεργό)")
        return "deactivated"
    write_audit(db,user,"collection_medium",m.id,"PURGE",old={"code":m.code,"type_id":m.type_id,"tare_weight":m.tare_weight},reason="Διαγραφή μέσου")
    db.delete(m); return "deleted"

@app.get("/master/media", response_model=list[schemas.MediumOut])
def list_media(include_inactive:bool=Query(default=False), db:Session=Depends(get_db), user=Depends(require_permission("master.view"))):
    stmt=select(CollectionMedium)
    if not include_inactive: stmt=stmt.where(CollectionMedium.active==True)
    rows=db.scalars(stmt.order_by(CollectionMedium.code)).all()
    used=_media_in_use_ids(db)
    for r in rows: r.in_use=r.id in used
    return rows

_CODE_LETTERS="ACDEFGHJKLMNPRTUVWXY"      # γράμματα χωρίς B I O S Z Q (μπερδεύονται με 8, 1, 0, 5, 2)
_GR2LAT={"Α":"A","Β":"V","Γ":"G","Δ":"D","Ε":"E","Ζ":"Z","Η":"I","Θ":"T","Ι":"I","Κ":"K","Λ":"L","Μ":"M","Ν":"N","Ξ":"X","Ο":"O","Π":"P","Ρ":"R","Σ":"S","Τ":"T","Υ":"Y","Φ":"F","Χ":"C","Ψ":"P","Ω":"O"}
_NEWCODE_RE=re.compile(r"^(\d{2})-([A-Z0-9]{3})-(\d{4,})$")

def _suggest_short_code(db:Session,name:str)->str:
    import unicodedata
    base=unicodedata.normalize("NFD",(name or "").upper()).encode("utf-8").decode("utf-8")
    base="".join(ch for ch in base if not unicodedata.combining(ch))
    letters=[ _GR2LAT.get(ch,ch) for ch in base ]
    cand=[ch for ch in "".join(letters) if ch in _CODE_LETTERS]
    taken={c for c in db.scalars(select(CollectionMediumType.short_code).where(CollectionMediumType.short_code.is_not(None))).all()}
    taken|={c for c in db.scalars(select(models.ContentCode.code)).all()}
    code="".join(cand[:3])
    for ch in "KLMNPRTCDEFGHJAUVWXY":
        if len(code)>=3: break
        code+=ch
    code=code[:3]
    i=0
    while code in taken and i<400:
        # αλλαγή του τελευταίου γράμματος, μετά του μεσαίου
        a,b,c=code
        L=_CODE_LETTERS; j=(L.index(c) if c in L else 0)+1
        code=a+b+L[j%len(L)]
        if j>=len(L): code=a+L[(L.index(b)+1)%len(L) if b in L else 0]+L[0]
        i+=1
    return code

def _valid_short_code(code:str)->bool:
    return bool(re.fullmatch(r"[A-Z0-9]{3}",code or ""))

def _next_medium_code(db:Session,mt)->str:
    """Αυτόματος κωδικός ΕΕ-ΤΤΤ-ΝΝΝΝ: έτος δημιουργίας, σύντομος κωδικός τύπου, αύξων αριθμός ανά έτος και τύπο (δεν μειώνεται ποτέ)."""
    if not mt.short_code:
        mt.short_code=_suggest_short_code(db,mt.name_el); db.flush()
    year=datetime.now().year
    return _next_code_for(db,mt.short_code,year)

def _next_code_for(db:Session,code3:str,year:int|None=None)->str:
    """ΕΝΑΣ μετρητής ανά (έτος, κωδικός) για όλες τις πηγές· δεν μειώνεται ποτέ. Μοναδικότητα από τη βάση."""
    from . import codes as _codes
    return _codes.next_code_for(db,code3,year)

def _content_code_for_category(db:Session,cat)->str:
    """Κωδικός περιεχομένου (3 γράμματα) μιας κατηγορίας ΑΗΗΕ· οι δικές μας υποκατηγορίες παίρνουν τον κωδικό του parent."""
    m=db.get(models.ContentCodeMap,("WEEE",cat.code))
    if not m and getattr(cat,"parent_code",None): m=db.get(models.ContentCodeMap,("WEEE",cat.parent_code))
    return m.code if m else "NCT"

def _assign_single_use_code(db:Session,user,medium_id:str|None,cat)->str|None:
    """Μέσο μίας χρήσης: ο κωδικός ΕΕ-ΤΤΤ-ΝΝΝΝ δίνεται στην πρώτη αποθήκευση (κωδικός περιεχομένου της πρώτης κατηγορίας) και ΜΕΤΑ δεν αλλάζει.
    Αν μπει δεύτερη κατηγορία στο ίδιο μέσο επιστρέφεται προειδοποίηση και μένει ο πρώτος κωδικός."""
    if not medium_id: return None
    m=db.get(CollectionMedium,medium_id)
    if not m: return None
    t=db.get(CollectionMediumType,m.type_id)
    if not t or not t.single_use: return None
    if str(m.code or "").startswith("~"):
        code=_next_code_for(db,_content_code_for_category(db,cat))
        write_audit(db,user,"collection_medium",m.id,"ASSIGN_CODE",old={"code":m.code},new={"code":code},reason="Κωδικός μέσου μίας χρήσης στην πρώτη χρήση")
        m.code=code
        return None
    other=db.scalar(select(models.SortingEntry.id).where(models.SortingEntry.collection_medium_id==m.id,models.SortingEntry.weee_category_id!=cat.id).limit(1))
    if other: return "Το μέσο "+m.code+" περιέχει ήδη άλλη κατηγορία. Ο κωδικός του μένει ως έχει."
    return None

def _short_code_conflict(db:Session,sc:str,exclude_type_id:str|None=None)->str|None:
    """Κωδικός τύπου ≠ κωδικός περιεχομένου και μοναδικός ανάμεσα στους τύπους. Επιστρέφει μήνυμα σφάλματος ή None."""
    if db.scalar(select(models.ContentCode.code).where(models.ContentCode.code==sc)):
        return "Ο κωδικός «"+sc+"» χρησιμοποιείται ήδη ως κωδικός περιεχομένου"
    if db.scalar(select(CollectionMediumType.id).where(CollectionMediumType.short_code==sc,CollectionMediumType.id!=exclude_type_id)):
        return "Ο κωδικός τύπου «"+sc+"» χρησιμοποιείται ήδη"
    return None

def _check_new_format(db:Session,code:str,type_id:str):
    """Κωδικός που μοιάζει με τη νέα μορφή (ΕΕ-…) πρέπει να είναι έγκυρος και να ταιριάζει με τον κωδικό του τύπου."""
    if not re.match(r"^\d{2}-",code or ""): return
    m=_NEWCODE_RE.match(code)
    t=db.get(CollectionMediumType,type_id)
    if not m or (t and t.short_code and m.group(2)!=t.short_code):
        raise HTTPException(422,"Μη έγκυρος κωδικός. Η μορφή είναι ΕΕ-"+((t.short_code if t and t.short_code else "ΤΤΤ"))+"-ΝΝΝΝ (π.χ. 26-"+((t.short_code if t and t.short_code else "PAL"))+"-0001).")

def _type_name_taken(db:Session,name:str,exclude_id:str|None=None)->bool:
    n=name.strip().lower()
    return any(t.id!=exclude_id and (t.name_el or "").strip().lower()==n for t in db.scalars(select(CollectionMediumType)).all())

def _set_setting(db:Session,key:str,value:str):
    row=db.scalar(select(AppSetting).where(AppSetting.key==key))
    if row: row.value=value
    else: db.add(AppSetting(key=key,value=value))

@app.get("/master/medium-types/suggest-code")
def suggest_medium_type_code(name:str="", db:Session=Depends(get_db), user=Depends(require_permission("master.view"))):
    return {"short_code":_suggest_short_code(db,name)}

@app.post("/master/medium-types", response_model=schemas.MediumTypeOut)
def create_medium_type(data:schemas.MediumTypeNew, db:Session=Depends(get_db), user:User=Depends(require_permission("master.edit"))):
    name=(data.name_el or "").strip()
    if not name: raise HTTPException(422,"Γράψε όνομα τύπου")
    if data.usage not in ("IN","OUT","BOTH"): raise HTTPException(422,"Μη έγκυρη χρήση")
    if _type_name_taken(db,name): raise HTTPException(409,"Υπάρχει ήδη τύπος με αυτό το όνομα")
    if data.tare_fixed and (data.default_tare_weight is None or data.default_tare_weight<0): raise HTTPException(422,"Γράψε το σταθερό αποβαρό του τύπου")
    import uuid as _uuid
    sc=(data.short_code or "").strip().upper() or _suggest_short_code(db,name)
    if not _valid_short_code(sc): raise HTTPException(422,"Ο κωδικός τύπου είναι 3 χαρακτήρες (κεφαλαία λατινικά ή ψηφία)")
    msg=_short_code_conflict(db,sc)
    if msg: raise HTTPException(409,msg)
    t=CollectionMediumType(code="CUSTOM_"+_uuid.uuid4().hex[:8].upper(),name_el=name,usage=data.usage,tare_fixed=bool(data.tare_fixed),short_code=sc,single_use=bool(data.single_use),
        default_tare_weight=data.default_tare_weight if data.tare_fixed else None,requires_unique_number=True,never_reuse_number=False,active=True)
    db.add(t); db.flush()
    write_audit(db,user,"collection_medium_type",t.id,"CREATE",new={"name_el":name,"usage":t.usage,"tare_fixed":t.tare_fixed,"default_tare_weight":t.default_tare_weight})
    db.commit(); db.refresh(t); return t

@app.put("/master/medium-types/{type_id}/name", response_model=schemas.MediumTypeOut)
def rename_medium_type(type_id:str, data:schemas.MediumTypeRename, db:Session=Depends(get_db), user:User=Depends(require_permission("master.edit"))):
    t=db.get(CollectionMediumType,type_id)
    if not t: raise HTTPException(404,"Άγνωστος τύπος μέσου")
    if t.code=="BULK": raise HTTPException(409,"Το Χύμα δεν μετονομάζεται")
    name=(data.name_el or "").strip()
    if not name: raise HTTPException(422,"Γράψε το νέο όνομα")
    if _type_name_taken(db,name,t.id): raise HTTPException(409,"Υπάρχει ήδη τύπος με αυτό το όνομα")
    old=t.name_el; t.name_el=name
    _set_setting(db,"medium_type.name."+t.code,name)      # ώστε να μη γυρίσει στο αρχικό όνομα μετά από επανεκκίνηση
    write_audit(db,user,"collection_medium_type",t.id,"RENAME",old={"name_el":old},new={"name_el":name})
    db.commit(); db.refresh(t); return t

@app.put("/master/medium-types/{type_id}", response_model=schemas.MediumTypeOut)
def edit_medium_type(type_id:str, data:schemas.MediumTypeEdit, db:Session=Depends(get_db), user:User=Depends(require_permission("master.edit"))):
    t=db.get(CollectionMediumType,type_id)
    if not t: raise HTTPException(404,"Άγνωστος τύπος μέσου")
    if t.code=="BULK": raise HTTPException(409,"Το Χύμα δεν επεξεργάζεται")
    name=(data.name_el or "").strip()
    if not name: raise HTTPException(422,"Γράψε όνομα τύπου")
    if data.usage not in ("IN","OUT","BOTH"): raise HTTPException(422,"Μη έγκυρη χρήση")
    if _type_name_taken(db,name,t.id): raise HTTPException(409,"Υπάρχει ήδη τύπος με αυτό το όνομα")
    sc=(data.short_code if data.short_code is not None else t.short_code or "").strip().upper()
    if sc:
        if not _valid_short_code(sc): raise HTTPException(422,"Ο κωδικός τύπου είναι 3 χαρακτήρες (κεφαλαία λατινικά ή ψηφία)")
        msg=_short_code_conflict(db,sc,t.id)
        if msg: raise HTTPException(409,msg)
    fixed=bool(data.tare_fixed)
    if fixed and (data.default_tare_weight is None or data.default_tare_weight<0): raise HTTPException(422,"Γράψε το σταθερό αποβαρό του τύπου")
    old={"name_el":t.name_el,"short_code":t.short_code,"usage":t.usage,"tare_fixed":bool(t.tare_fixed),"default_tare_weight":t.default_tare_weight,"single_use":bool(t.single_use)}
    t.name_el=name; t.usage=data.usage; t.short_code=sc or None; t.single_use=bool(data.single_use)
    if name!=old["name_el"]: _set_setting(db,"medium_type.name."+t.code,name)
    n=0
    if fixed:
        t.tare_fixed=True; t.default_tare_weight=data.default_tare_weight
        for m in db.scalars(select(CollectionMedium).where(CollectionMedium.type_id==t.id)).all():
            if m.tare_weight!=data.default_tare_weight:
                write_audit(db,user,"collection_medium",m.id,"UPDATE",old={"tare_weight":m.tare_weight},new={"tare_weight":data.default_tare_weight},reason="Σταθερό αποβαρό τύπου")
                m.tare_weight=data.default_tare_weight; n+=1
    else:
        t.tare_fixed=False      # τα μέσα κρατούν το αποβαρό που έχουν· από εδώ και πέρα ορίζεται ανά μέσο
    write_audit(db,user,"collection_medium_type",t.id,"UPDATE",old=old,new={"name_el":t.name_el,"short_code":t.short_code,"usage":t.usage,"tare_fixed":bool(t.tare_fixed),"default_tare_weight":t.default_tare_weight,"single_use":bool(t.single_use),"media_updated":n})
    db.commit(); db.refresh(t); return t

@app.put("/master/medium-types/{type_id}/tare", response_model=schemas.MediumTypeOut)
def set_medium_type_tare(type_id:str, data:schemas.MediumTypeTare, db:Session=Depends(get_db), user:User=Depends(require_permission("master.edit"))):
    t=db.get(CollectionMediumType,type_id)
    if not t: raise HTTPException(404,"Άγνωστος τύπος μέσου")
    if not t.tare_fixed: raise HTTPException(409,"Ο τύπος δεν έχει σταθερό αποβαρό: το αποβαρό ορίζεται ανά μέσο")
    if data.default_tare_weight is None or data.default_tare_weight<0: raise HTTPException(422,"Μη έγκυρο αποβαρό")
    old=t.default_tare_weight; t.default_tare_weight=data.default_tare_weight
    n=0
    for m in db.scalars(select(CollectionMedium).where(CollectionMedium.type_id==t.id)).all():
        if m.tare_weight!=data.default_tare_weight:
            write_audit(db,user,"collection_medium",m.id,"UPDATE",old={"tare_weight":m.tare_weight},new={"tare_weight":data.default_tare_weight},reason="Αλλαγή σταθερού αποβάρου τύπου")
            m.tare_weight=data.default_tare_weight; n+=1
    write_audit(db,user,"collection_medium_type",t.id,"UPDATE_TARE",old={"default_tare_weight":old},new={"default_tare_weight":data.default_tare_weight,"media_updated":n})
    db.commit(); db.refresh(t); return t

@app.post("/master/media/move")
def move_media(data:schemas.MediumMove, db:Session=Depends(get_db), user:User=Depends(require_permission("master.edit"))):
    tgt=db.get(CollectionMediumType,data.target_type_id)
    if not tgt or not tgt.active: raise HTTPException(404,"Άγνωστος τύπος προορισμού")
    if tgt.code=="BULK": raise HTTPException(409,"Το Χύμα δεν είναι προορισμός")
    ids=list(dict.fromkeys(data.ids))
    ms=db.scalars(select(CollectionMedium).where(CollectionMedium.id.in_(ids))).all()
    if not ms: raise HTTPException(404,"Δεν βρέθηκαν μέσα")
    ms=[m for m in ms if m.type_id!=tgt.id]
    if not ms: raise HTTPException(409,"Τα μέσα ανήκουν ήδη σε αυτόν τον τύπο")
    src_types={t.id:t for t in db.scalars(select(CollectionMediumType).where(CollectionMediumType.id.in_({m.type_id for m in ms}))).all()}
    if any((src_types.get(m.type_id) and src_types[m.type_id].code=="BULK") for m in ms): raise HTTPException(409,"Τα μέσα Χύμα δεν μετακινούνται")
    existing={c for c in db.scalars(select(CollectionMedium.code).where(CollectionMedium.type_id==tgt.id)).all()}
    clash=[m.code for m in ms if m.code in existing]
    if clash: raise HTTPException(409,"Στον τύπο προορισμού υπάρχει ήδη μέσο με τον ίδιο κωδικό ("+", ".join(clash[:8])+"). Άλλαξε πρώτα τον κωδικό.")
    dup=[c for c in {m.code for m in ms} if sum(1 for m in ms if m.code==c)>1]
    if dup: raise HTTPException(409,"Μέσα με τον ίδιο κωδικό ("+", ".join(dup[:8])+") δεν μπορούν να πάνε μαζί στον ίδιο τύπο. Άλλαξε πρώτα τον κωδικό.")
    for m in ms:
        old={"type_id":m.type_id,"tare_weight":m.tare_weight}
        m.type_id=tgt.id
        if tgt.tare_fixed: m.tare_weight=tgt.default_tare_weight
        write_audit(db,user,"collection_medium",m.id,"UPDATE",old=old,new={"type_id":tgt.id,"tare_weight":m.tare_weight},reason="Μετακίνηση σε άλλον τύπο")
    db.commit(); return {"moved":len(ms),"target":tgt.name_el}

@app.post("/master/media/bulk-tare")
def media_bulk_tare(data:schemas.MediumBulkTare, db:Session=Depends(get_db), user:User=Depends(require_permission("master.edit"))):
    if data.tare_weight is None or data.tare_weight<0: raise HTTPException(422,"Το αποβαρό πρέπει να είναι μηδέν ή θετικό")
    ids=list(dict.fromkeys(data.ids))
    ms=db.scalars(select(CollectionMedium).where(CollectionMedium.id.in_(ids))).all()
    if not ms: raise HTTPException(404,"Δεν βρέθηκαν μέσα")
    fixed=[t.name_el for t in db.scalars(select(CollectionMediumType).where(CollectionMediumType.id.in_({m.type_id for m in ms}),CollectionMediumType.tare_fixed==True)).all()]
    if fixed: raise HTTPException(409,"Ο τύπος «"+", ".join(fixed)+"» έχει σταθερό αποβαρό: αλλάζει από τον τύπο, όχι ανά μέσο")
    for m in ms:
        old=m.tare_weight; m.tare_weight=data.tare_weight
        write_audit(db,user,"collection_medium",m.id,"UPDATE",old={"tare_weight":old},new={"tare_weight":data.tare_weight},reason="Μαζική αλλαγή αποβάρου")
    db.commit(); return {"updated":len(ms)}

@app.post("/master/media/bulk-delete")
def media_bulk_delete(data:schemas.MediumBulkIds, db:Session=Depends(get_db), user:User=Depends(require_permission("master.edit"))):
    ids=list(dict.fromkeys(data.ids))
    ms=db.scalars(select(CollectionMedium).where(CollectionMedium.id.in_(ids))).all()
    if not ms: raise HTTPException(404,"Δεν βρέθηκαν μέσα")
    used=_media_in_use_ids(db)
    busy=[m.code for m in ms if m.id in used]
    if busy: raise HTTPException(409,"Περιλαμβάνονται μέσα σε χρήση: δεν διαγράφονται ("+", ".join(busy[:8])+(" …" if len(busy)>8 else "")+")")
    res={"deleted":0,"deactivated":0}
    for m in ms: res[_medium_remove(db,user,m)]+=1
    db.commit(); return res

@app.delete("/master/medium-types/{type_id}")
def delete_medium_type(type_id:str, db:Session=Depends(get_db), user:User=Depends(require_permission("master.edit"))):
    t=db.get(CollectionMediumType,type_id)
    if not t: raise HTTPException(404,"Άγνωστο είδος μέσου")
    if t.code=="BULK": raise HTTPException(409,"Το Χύμα δεν διαγράφεται")
    ms=db.scalars(select(CollectionMedium).where(CollectionMedium.type_id==type_id)).all()
    used=_media_in_use_ids(db)
    busy=[m.code for m in ms if m.id in used and m.active]
    if busy: raise HTTPException(409,"Το είδος έχει μέσα σε χρήση: δεν διαγράφεται ("+", ".join(busy[:8])+(" …" if len(busy)>8 else "")+")")
    n=0
    for m in ms:
        if m.active or _medium_referenced(db,m.id) is False:
            _medium_remove(db,user,m); n+=1
    t.active=False
    key="medium_type.deleted."+t.code
    if not db.scalar(select(AppSetting).where(AppSetting.key==key)): db.add(AppSetting(key=key,value="1"))
    write_audit(db,user,"collection_medium_type",t.id,"DELETE",old={"code":t.code,"name_el":t.name_el,"active":True},new={"active":False,"media_removed":n},reason="Διαγραφή είδους μέσου")
    db.commit(); return {"ok":True,"media_removed":n}

@app.put("/master/medium-types/{type_id}/usage", response_model=schemas.MediumTypeOut)
def set_medium_type_usage(type_id:str, data:schemas.MediumTypeUsageIn, db:Session=Depends(get_db), user:User=Depends(require_permission("master.edit"))):
    if data.usage not in ("IN","OUT","BOTH"): raise HTTPException(422,"Μη έγκυρη χρήση (Εισερχόμενο / Εξερχόμενο / Και τα δύο)")
    mt=db.get(CollectionMediumType,type_id)
    if not mt: raise HTTPException(404,"Άγνωστος τύπος μέσου")
    old=mt.usage; mt.usage=data.usage
    write_audit(db,user,"collection_medium_type",mt.id,"UPDATE_USAGE",old={"usage":old},new={"usage":mt.usage})
    db.commit(); db.refresh(mt); return mt

@app.get("/master/media/next-code")
def media_next_code(type_id:str, code:str|None=Query(default=None), db:Session=Depends(get_db), user=Depends(require_permission("sorting.perform"))):
    """Μόνο ανάγνωση: προτεινόμενος επόμενος ελεύθερος αριθμός για ένα είδος μέσου. Λαμβάνει υπόψη ΟΛΑ τα μέσα (ενεργά, ανενεργά, DEMO)
    και κάθε κωδικό που υπήρξε ποτέ στο ιστορικό ενεργειών (π.χ. μέσα που έχουν διαγραφεί), ώστε να μην ξαναχρησιμοποιείται αριθμός."""
    import json as _json
    mt=db.get(CollectionMediumType,type_id)
    if not mt: raise HTTPException(404,"Άγνωστος τύπος μέσου")
    media=db.scalars(select(CollectionMedium)).all()
    taken={m.code for m in media}
    mine=[m.code for m in media if m.type_id==type_id]
    for ev in db.scalars(select(models.AuditEvent).where(models.AuditEvent.entity_type=="collection_medium")).all():
        try: nv=_json.loads(ev.new_values or "{}")
        except Exception: nv={}
        c=nv.get("code") if isinstance(nv,dict) else None
        if c:
            taken.add(c)
            if nv.get("type")==mt.code: mine.append(c)
    best=None;mx=0;pref={}
    for c in mine:
        r=re.match(r"^(\D*)(\d+)$",str(c))
        if not r: continue
        n=int(r.group(2)); mx=max(mx,n)
        if not str(c).upper().startswith("DEMO"):
            pref[(r.group(1),len(r.group(2)))]=pref.get((r.group(1),len(r.group(2))),0)+1
    if pref: pre,ln=max(pref.items(),key=lambda x:x[1])[0]
    else: pre,ln="",1
    n=mx+1
    cand=f"{pre}{str(n).zfill(ln)}"
    while cand in taken:
        n+=1; cand=f"{pre}{str(n).zfill(ln)}"
    return {"code":cand,"taken":(code in taken) if code else False,"never_reuse":bool(mt.never_reuse_number)}

@app.post("/master/media", response_model=schemas.MediumOut)
def create_medium(data:schemas.MediumCreate, db:Session=Depends(get_db), user:User=Depends(require_permission("master.edit"))):
    mt=db.get(CollectionMediumType,data.type_id)
    if not mt: raise HTTPException(404,"Άγνωστος τύπος μέσου")
    code=data.code
    if mt.code=="BIG_BAG" and not code:
        prefix=db.scalar(select(AppSetting.value).where(AppSetting.key=="big_bag.number_prefix")) or "BB"
        seq_setting=db.scalar(select(AppSetting).where(AppSetting.key=="big_bag.next_sequence").with_for_update())
        if not seq_setting:
            seq_setting=AppSetting(key="big_bag.next_sequence",value="1"); db.add(seq_setting); db.flush()
        seq=int(seq_setting.value); seq_setting.value=str(seq+1)
        year=datetime.now().year
        code=f"{prefix}-{year}-{seq:06d}"
    if mt.code=="BULK" and not code:
        seq=len(db.scalars(select(CollectionMedium).where(CollectionMedium.code.like("BULK-%"))).all())+1
        code=f"BULK-{datetime.now().year}-{seq:06d}"
    if mt.code in ("MATERIAL_SACK","MATERIAL_PALLET") and not code:
        prefix="MS" if mt.code=="MATERIAL_SACK" else "MP"
        seq=len(db.scalars(select(CollectionMedium).where(CollectionMedium.code.like(f"{prefix}-%"))).all())+1
        code=f"{prefix}-{datetime.now().year}-{seq:06d}"
    if mt.code=="BULK": raise HTTPException(422,"Το Χύμα δεν έχει αριθμό: δεν δημιουργούνται μέσα Χύμα")
    if mt.usage=="IN":
        # καλάθια (εισερχόμενα, επαναχρησιμοποιούμενα): ο κωδικός γράφεται από τον χρήστη (π.χ. όνομα κατασκευαστή)
        code=(data.code or "").strip()
        if not code: raise HTTPException(422,"Γράψε αριθμό / κωδικό για το μέσο")
        _check_new_format(db,code,data.type_id)
    elif mt.single_use:
        import uuid as _u2
        code="~"+_u2.uuid4().hex[:8]        # μέσο μίας χρήσης: ο κωδικός δίνεται στην πρώτη χρήση (δεν δημιουργείται εδώ)
    else:
        code=_next_medium_code(db,mt)       # αυτόματος κωδικός στη δημιουργία νέου μέσου
    if db.scalar(select(CollectionMedium).where(CollectionMedium.code==code,CollectionMedium.type_id==data.type_id)): raise HTTPException(409,"Ο κωδικός υπάρχει ήδη στον τύπο. Σε άλλον τύπο επιτρέπεται.")
    if data.linked_loading_order_id and not db.get(models.LoadingOrder,data.linked_loading_order_id): raise HTTPException(422,"Άγνωστο δελτίο φόρτωσης")
    tare=mt.default_tare_weight if getattr(mt,"tare_fixed",False) else (data.tare_weight if data.tare_weight is not None else mt.default_tare_weight)
    obj=CollectionMedium(type_id=data.type_id,code=code,tare_weight=tare,linked_loading_order_id=data.linked_loading_order_id); db.add(obj); db.flush(); write_audit(db,user,"collection_medium",obj.id,"CREATE",new={"code":code,"type":mt.code,"tare":str(tare) if tare is not None else None,"loading_order_id":data.linked_loading_order_id}); db.commit(); db.refresh(obj); return obj


# ---- Build 2.5.4: complete editable Master Data ----
@app.put("/master/containers/{item_id}", response_model=schemas.ContainerOut)
def update_container(item_id:str,data:schemas.ContainerCreate,db:Session=Depends(get_db),user:User=Depends(require_permission("master.edit"))):
    x=db.get(ContainerAsset,item_id)
    if not x: raise HTTPException(404,"Ο κάδος δεν βρέθηκε")
    old={"container_number":x.container_number,"owner_organization_id":x.owner_organization_id,"tare_weight":x.tare_weight,"notes":x.notes}
    x.container_number=data.container_number; x.owner_organization_id=data.owner_organization_id; x.tare_weight=data.tare_weight; x.notes=data.notes
    write_audit(db,user,"container",x.id,"UPDATE",old=old,new=data.model_dump())
    db.commit(); db.refresh(x); return _container_public(x)
class _ContainerTransfer(schemas.BaseModel):
    owner_organization_id: str

@app.post("/master/containers/{item_id}/transfer", response_model=schemas.ContainerOut)
def transfer_container(item_id:str, data:_ContainerTransfer, db:Session=Depends(get_db), user:User=Depends(require_permission("master.edit"))):
    """Μεταφορά ενός container σε άλλον μεταφορέα (αλλάζει ΜΟΝΟ ο ιδιοκτήτης· ο αριθμός και το απόβαρο μένουν)."""
    x=db.get(ContainerAsset,item_id)
    if not x: raise HTTPException(404,"Ο κάδος δεν βρέθηκε")
    org=db.get(models.Organization,data.owner_organization_id)
    if not org: raise HTTPException(404,"Ο μεταφορέας δεν βρέθηκε")
    old=x.owner_organization_id
    if old!=org.id:
        x.owner_organization_id=org.id
        write_audit(db,user,"container",x.id,"TRANSFER",old={"owner_organization_id":old},new={"owner_organization_id":org.id},reason="Μεταφορά container σε άλλον μεταφορέα (Νέα Παραλαβή)")
        db.commit(); db.refresh(x)
    return _container_public(x)

@app.delete("/master/containers/{item_id}")
def delete_container_master(item_id:str,db:Session=Depends(get_db),user:User=Depends(require_permission("master.edit"))):
    x=db.get(ContainerAsset,item_id)
    if not x: raise HTTPException(404,"Ο κάδος δεν βρέθηκε")
    x.active=False; write_audit(db,user,"container",x.id,"DEACTIVATE",old={"active":True},new={"active":False}); db.commit(); return {"ok":True}
@app.delete("/master/containers/{item_id}/purge")
def purge_container_master(item_id:str,db:Session=Depends(get_db),user:User=Depends(require_permission("master.edit"))):
    x=db.get(ContainerAsset,item_id)
    if not x: raise HTTPException(404,"Ο κάδος δεν βρέθηκε")
    used=db.scalar(select(models.InboundLoad.id).where(models.InboundLoad.outgoing_container_id==item_id).limit(1))
    if used: raise HTTPException(409,"Ο κάδος έχει χρησιμοποιηθεί σε παραλαβή. Χρησιμοποίησε «Μη ενεργό» για να διατηρηθεί το ιστορικό.")
    db.delete(x); db.commit(); return {"deleted":True,"id":item_id}
@app.put("/master/media/{item_id}", response_model=schemas.MediumOut)
def update_medium_master(item_id:str,data:schemas.MediumCreate,db:Session=Depends(get_db),user:User=Depends(require_permission("master.edit"))):
    x=db.get(CollectionMedium,item_id)
    if not x: raise HTTPException(404,"Το μέσο δεν βρέθηκε")
    old={"type_id":x.type_id,"code":x.code,"tare_weight":x.tare_weight,"linked_loading_order_id":x.linked_loading_order_id}
    new_code=(data.code or x.code or "").strip()
    if not new_code: raise HTTPException(422,"Ο αριθμός / κωδικός δεν μπορεί να είναι κενός")
    if data.type_id!=x.type_id:
        tgt=db.get(CollectionMediumType,data.type_id)
        if not tgt or not tgt.active: raise HTTPException(404,"Άγνωστος τύπος προορισμού")
        if tgt.code=="BULK": raise HTTPException(409,"Το Χύμα δεν είναι προορισμός")
    if new_code!=x.code or data.type_id!=x.type_id: _check_new_format(db,new_code,data.type_id)
    if db.scalar(select(CollectionMedium.id).where(CollectionMedium.code==new_code,CollectionMedium.type_id==data.type_id,CollectionMedium.id!=x.id)):
        raise HTTPException(409,"Ο κωδικός υπάρχει ήδη στον τύπο. Σε άλλον τύπο επιτρέπεται.")
    tmt=db.get(CollectionMediumType,data.type_id)
    if tmt and getattr(tmt,"tare_fixed",False): data.tare_weight=tmt.default_tare_weight      # σταθερό αποβαρό: το παίρνει από τον τύπο
    x.type_id=data.type_id; x.code=new_code; x.tare_weight=data.tare_weight; x.linked_loading_order_id=data.linked_loading_order_id
    write_audit(db,user,"collection_medium",x.id,"UPDATE",old=old,new=data.model_dump())
    db.commit(); db.refresh(x); return x
@app.delete("/master/media/{item_id}")
def delete_medium_master(item_id:str,db:Session=Depends(get_db),user:User=Depends(require_permission("master.edit"))):
    x=db.get(CollectionMedium,item_id)
    if not x: raise HTTPException(404,"Το μέσο δεν βρέθηκε")
    x.active=False; write_audit(db,user,"collection_medium",x.id,"DEACTIVATE",old={"active":True},new={"active":False}); db.commit(); return {"ok":True}
@app.delete("/master/media/{item_id}/purge")
def purge_medium_master(item_id:str,db:Session=Depends(get_db),user:User=Depends(require_permission("master.edit"))):
    x=db.get(CollectionMedium,item_id)
    if not x: raise HTTPException(404,"Το μέσο δεν βρέθηκε")
    used=(db.scalar(select(models.SortingEntry.id).where(models.SortingEntry.collection_medium_id==item_id).limit(1))
          or db.scalar(select(models.WEEEStockLot.id).where(models.WEEEStockLot.collection_medium_id==item_id).limit(1))
          or db.scalar(select(models.ReadyMaterialLot.id).where(models.ReadyMaterialLot.collection_medium_id==item_id).limit(1)))
    if used: raise HTTPException(409,"Το μέσο έχει χρησιμοποιηθεί σε ταξινόμηση/απόθεμα. Χρησιμοποίησε «Μη ενεργό» για να διατηρηθεί το ιστορικό.")
    db.delete(x); db.commit(); return {"deleted":True,"id":item_id}
@app.put("/master/materials/{item_id}", response_model=schemas.MaterialOut)
def update_material_master(item_id:str,data:schemas.MaterialCreate,db:Session=Depends(get_db),user:User=Depends(require_permission("master.edit"))):
    x=db.get(Material,item_id)
    if not x: raise HTTPException(404,"Το υλικό δεν βρέθηκε")
    old={"internal_name":x.internal_name,"galaxy_code":x.galaxy_code,"galaxy_description":x.galaxy_description,"genre":x.genre,"official_description":x.official_description,"her_description":x.her_description,"eka_code":x.eka_code,"reptool_code":x.reptool_code,"reptool_description":x.reptool_description}
    old["storage_group_id"]=x.storage_group_id; old["short_description"]=x.short_description; old["can_bale"]=x.can_bale; old["press_label"]=x.press_label
    if "storage_group_id" in data.model_fields_set and data.storage_group_id and not _storage_group_ok(db,data.storage_group_id,allow_inactive_id=x.storage_group_id): raise HTTPException(422,"Μη έγκυρη κατηγορία αποθήκης")
    for k,v in data.model_dump().items():
        if k=="storage_group_id" and "storage_group_id" not in data.model_fields_set: continue   # παλιοί πελάτες δεν σβήνουν την ομάδα
        if k=="short_description" and "short_description" not in data.model_fields_set: continue  # αιτήματα χωρίς το πεδίο (π.χ. επαναφορά/μαζική επεξεργασία) δεν σβήνουν τη σύντομη περιγραφή
        if k in ("can_bale","press_label") and k not in data.model_fields_set: continue   # παλιοί πελάτες/μαζική επεξεργασία δεν αλλάζουν τη ρύθμιση μπάλας
        if k=="short_description": v=(v or "").strip() or None
        if k=="press_label": v=(v or "").strip() or None
        setattr(x,k,v)
    _apply_material_rules(x)
    write_audit(db,user,"material",x.id,"UPDATE",old=old,new=data.model_dump(exclude={f for f in ("storage_group_id","short_description","can_bale","press_label") if f not in data.model_fields_set}))
    db.commit(); db.refresh(x); return x

def _storage_group_ok(db:Session,gid:str,allow_inactive_id:str|None=None)->bool:
    """Στο υλικό μπαίνει μόνο ΕΝΕΡΓΗ κατηγορία αποθήκης· μια ήδη ανατεθειμένη μη ενεργή κατηγορία διατηρείται."""
    g=db.get(models.StorageGroup,gid)
    if not g: return False
    return bool(g.active) or gid==allow_inactive_id

@app.get("/master/storage-groups")
def list_storage_groups(include_inactive:bool=Query(default=True), db:Session=Depends(get_db), user=Depends(require_permission("master.view"))):
    """Κατηγορίες αποθήκης (ένα επίπεδο) με πλήθος υλικών."""
    rows=db.scalars(select(models.StorageGroup).order_by(models.StorageGroup.sort_order,models.StorageGroup.name)).all()
    if not include_inactive: rows=[r for r in rows if r.active]
    counts=dict(db.execute(select(Material.storage_group_id,func.count()).where(Material.storage_group_id.is_not(None)).group_by(Material.storage_group_id)).all())
    return [{"id":r.id,"name":r.name,"active":r.active,"sort_order":r.sort_order,"material_count":int(counts.get(r.id,0))} for r in rows]

def _storage_group_check(db:Session,data:schemas.StorageGroupIn,self_id:str|None=None):
    name=(data.name or '').strip()
    if not name: raise HTTPException(422,"Συμπλήρωσε όνομα")
    for sib in db.scalars(select(models.StorageGroup)).all():   # σύγκριση στην Python (το lower() της SQLite δεν χειρίζεται ελληνικά)
        if sib.id!=self_id and (sib.name or '').strip().casefold()==name.casefold(): raise HTTPException(409,"Υπάρχει ήδη κατηγορία με αυτό το όνομα")
    return name

@app.post("/master/storage-groups")
def create_storage_group(data:schemas.StorageGroupIn, db:Session=Depends(get_db), user:User=Depends(require_permission("master.edit"))):
    name=_storage_group_check(db,data)
    g=models.StorageGroup(name=name,parent_id=None,active=True); db.add(g); db.flush()
    write_audit(db,user,"storage_group",g.id,"CREATE",new={"name":name}); db.commit()
    return {"id":g.id,"name":g.name,"active":g.active}

@app.put("/master/storage-groups/{gid}")
def update_storage_group(gid:str, data:schemas.StorageGroupIn, db:Session=Depends(get_db), user:User=Depends(require_permission("master.edit"))):
    g=db.get(models.StorageGroup,gid)
    if not g: raise HTTPException(404,"Δεν βρέθηκε")
    name=_storage_group_check(db,data,self_id=gid)
    old={"name":g.name,"active":g.active}
    g.name=name; g.active=bool(data.active)
    write_audit(db,user,"storage_group",g.id,"UPDATE",old=old,new={"name":name,"active":g.active}); db.commit()
    return {"id":g.id,"name":g.name,"active":g.active}

@app.delete("/master/storage-groups/{gid}")
def delete_storage_group(gid:str, db:Session=Depends(get_db), user:User=Depends(require_permission("master.edit"))):
    g=db.get(models.StorageGroup,gid)
    if not g: raise HTTPException(404,"Δεν βρέθηκε")
    if db.scalar(select(func.count()).select_from(Material).where(Material.storage_group_id==gid)): raise HTTPException(409,"Έχει υλικά -- ορίστε την «Μη ενεργή»")
    write_audit(db,user,"storage_group",g.id,"DELETE",old={"name":g.name}); db.delete(g); db.commit()
    return {"ok":True}

def _flatten_storage_groups(db:Session):
    """Μία φορά: το δεύτερο επίπεδο (ομάδες μέσα σε κατηγορίες) καταργείται. Τα υλικά που είχαν ομάδα περνούν στην κατηγορία της·
    οι κατηγορίες (και οι αντιστοιχίσεις σε αυτές) μένουν ως έχουν."""
    key="migr.storage_groups_flat_v1"
    if db.scalar(select(AppSetting).where(AppSetting.key==key)): return
    rows=db.scalars(select(models.StorageGroup)).all()
    for g in rows:
        if g.parent_id:
            db.execute(update(Material).where(Material.storage_group_id==g.id).values(storage_group_id=g.parent_id))
    db.flush()
    for g in rows:
        if g.parent_id: db.delete(g)
        else: g.parent_id=None
    db.add(AppSetting(key=key,value="1")); db.commit()

@app.post("/master/materials/storage-group")
def assign_storage_group(data:schemas.StorageGroupAssignIn, db:Session=Depends(get_db), user:User=Depends(require_permission("master.edit"))):
    """Μαζική ανάθεση «Ομάδας αποθήκης» σε επιλεγμένα υλικά (None = Χωρίς ομάδα)."""
    if data.storage_group_id and not _storage_group_ok(db,data.storage_group_id): raise HTTPException(422,"Μη έγκυρη κατηγορία αποθήκης")
    n=0
    for mid in data.material_ids:
        x=db.get(Material,mid)
        if not x or x.storage_group_id==data.storage_group_id: continue
        write_audit(db,user,"material",x.id,"UPDATE",old={"storage_group_id":x.storage_group_id},new={"storage_group_id":data.storage_group_id})
        x.storage_group_id=data.storage_group_id; n+=1
    db.commit(); return {"ok":True,"updated":n}

@app.get("/master/materials/{item_id}/history")
def material_history(item_id:str, db:Session=Depends(get_db), user=Depends(require_permission("master.view"))):
    events=db.scalars(select(models.AuditEvent).where(models.AuditEvent.entity_type=="material",models.AuditEvent.entity_id==item_id).order_by(models.AuditEvent.created_at.desc())).all()
    uids={e.user_id for e in events if e.user_id}
    users={u.id:u.username for u in db.scalars(select(User).where(User.id.in_(uids))).all()} if uids else {}
    return [{"action":e.action,"old_values":json.loads(e.old_values) if e.old_values else None,"new_values":json.loads(e.new_values) if e.new_values else None,"reason":e.reason,"user":users.get(e.user_id),"created_at":e.created_at.isoformat()} for e in events]

MASTER_HISTORY_ENTITY_TYPES={"container","collection_medium","material","weee_category","organizational_unit","employee","storage_group"}
@app.get("/master/history/{entity_type}")
def master_tab_history(entity_type:str, limit:int=Query(default=300,le=1000), db:Session=Depends(get_db), user=Depends(require_permission("master.view"))):
    if entity_type not in MASTER_HISTORY_ENTITY_TYPES: raise HTTPException(404,"Άγνωστος τύπος ιστορικού")
    events=db.scalars(select(models.AuditEvent).where(models.AuditEvent.entity_type==entity_type).order_by(models.AuditEvent.created_at.desc()).limit(limit)).all()
    uids={e.user_id for e in events if e.user_id}
    users={u.id:u.username for u in db.scalars(select(User).where(User.id.in_(uids))).all()} if uids else {}
    return [{"id":e.id,"entity_id":e.entity_id,"action":e.action,"old_values":json.loads(e.old_values) if e.old_values else None,"new_values":json.loads(e.new_values) if e.new_values else None,"reason":e.reason,"user":users.get(e.user_id),"user_id":e.user_id,"created_at":e.created_at.isoformat()} for e in events]
@app.delete("/master/materials/{item_id}")
def delete_material_master(item_id:str,db:Session=Depends(get_db),user:User=Depends(require_permission("master.edit"))):
    x=db.get(Material,item_id)
    if not x: raise HTTPException(404,"Το υλικό δεν βρέθηκε")
    x.active=False; write_audit(db,user,"material",x.id,"DEACTIVATE",old={"active":True},new={"active":False}); db.commit(); return {"ok":True}
@app.delete("/master/materials/{item_id}/purge")
def purge_material_master(item_id:str,db:Session=Depends(get_db),user:User=Depends(require_permission("master.edit"))):
    x=db.get(Material,item_id)
    if not x: raise HTTPException(404,"Το υλικό δεν βρέθηκε")
    used=(db.scalar(select(models.ReadyMaterialLot.id).where(models.ReadyMaterialLot.material_id==item_id).limit(1))
          or db.scalar(select(models.DirectProcessingMapping.id).where(models.DirectProcessingMapping.output_material_id==item_id).limit(1)))
    if used: raise HTTPException(409,"Το υλικό έχει χρησιμοποιηθεί σε παρτίδα/αντιστοίχιση. Χρησιμοποίησε «Μη ενεργό» για να διατηρηθεί το ιστορικό.")
    db.delete(x); db.commit(); return {"deleted":True,"id":item_id}
@app.delete("/master/weee-categories/{item_id}")
def delete_weee_master(item_id:str,db:Session=Depends(get_db),user:User=Depends(require_permission("master.edit"))):
    x=db.get(WEEECategory,item_id)
    if not x: raise HTTPException(404,"Η κατηγορία δεν βρέθηκε")
    x.active=False; write_audit(db,user,"weee_category",x.id,"DEACTIVATE",old={"active":True},new={"active":False}); db.commit(); return {"ok":True}


@app.post("/master/org-units/{unit_id}/activate")
def activate_org_unit(unit_id:str, db:Session=Depends(get_db), user:User=Depends(require_permission("master.edit"))):
    obj=db.get(OrganizationalUnit,unit_id)
    if not obj: raise HTTPException(404,"Το τμήμα δεν βρέθηκε")
    obj.active=True; write_audit(db,user,"organizational_unit",obj.id,"ACTIVATE",old={"active":False},new={"active":True}); db.commit(); return {"ok":True}

@app.post("/master/containers/{item_id}/activate")
def activate_container_master(item_id:str,db:Session=Depends(get_db),user:User=Depends(require_permission("master.edit"))):
    x=db.get(ContainerAsset,item_id)
    if not x: raise HTTPException(404,"Ο κάδος δεν βρέθηκε")
    x.active=True; write_audit(db,user,"container",x.id,"ACTIVATE",old={"active":False},new={"active":True}); db.commit(); return {"ok":True}

@app.post("/master/media/{item_id}/activate")
def activate_medium_master(item_id:str,db:Session=Depends(get_db),user:User=Depends(require_permission("master.edit"))):
    x=db.get(CollectionMedium,item_id)
    if not x: raise HTTPException(404,"Το μέσο δεν βρέθηκε")
    x.active=True; write_audit(db,user,"collection_medium",x.id,"ACTIVATE",old={"active":False},new={"active":True}); db.commit(); return {"ok":True}

@app.post("/master/materials/{item_id}/activate")
def activate_material_master(item_id:str,db:Session=Depends(get_db),user:User=Depends(require_permission("master.edit"))):
    x=db.get(Material,item_id)
    if not x: raise HTTPException(404,"Το υλικό δεν βρέθηκε")
    if not (x.galaxy_code or '').strip(): raise HTTPException(409,"Υλικό χωρίς Κωδικό ERP δεν μπορεί να είναι ενεργό")
    x.active=True; write_audit(db,user,"material",x.id,"ACTIVATE",old={"active":False},new={"active":True}); db.commit(); return {"ok":True}

@app.post("/master/weee-categories/{item_id}/activate")
def activate_weee_master(item_id:str,db:Session=Depends(get_db),user:User=Depends(require_permission("master.edit"))):
    x=db.get(WEEECategory,item_id)
    if not x: raise HTTPException(404,"Η κατηγορία δεν βρέθηκε")
    x.active=True; write_audit(db,user,"weee_category",x.id,"ACTIVATE",old={"active":False},new={"active":True}); db.commit(); return {"ok":True}


import json as _json

def _emp_unit_ids(db:Session,emp:Employee)->list[str]:
    """Τα τμήματα του εργαζομένου (κοινό σύνολο Μητρώων + Δελτίου). Πρώτο το κύριο (default)."""
    ids=[r[0] for r in db.execute(select(employee_org_units.c.org_unit_id).where(employee_org_units.c.employee_id==emp.id)).all()]
    if not ids: return []
    order={u.id:(u.sort_order,u.name_el) for u in db.scalars(select(OrganizationalUnit).where(OrganizationalUnit.id.in_(ids))).all()}
    ids=sorted([i for i in ids if i in order],key=lambda i:order[i])
    if emp.default_org_unit_id in ids: ids=[emp.default_org_unit_id]+[i for i in ids if i!=emp.default_org_unit_id]
    return ids

def _apply_unit_set(db:Session,emp:Employee,ids:list[str]):
    clean=[]
    for i in ids or []:
        if i and i not in clean: clean.append(i)
    db.execute(employee_org_units.delete().where(employee_org_units.c.employee_id==emp.id))
    for i in clean: db.execute(employee_org_units.insert().values(employee_id=emp.id,org_unit_id=i))
    emp.default_org_unit_id=clean[0] if clean else None

def _reconcile_unit_sets(db:Session):
    """Μία φορά: το κοινό σύνολο τμημάτων ακολουθεί την πραγματική τελευταία θέση του Δελτίου (παλιά η θέση του Δελτίου
    δεν άλλαζε το μητρώο). Δεν χάνεται κανένα τμήμα εκτός από το αρχικό (κύριο) που αντικαθίσταται από τη θέση."""
    key="migr.unit_sets_v1"
    if db.scalar(select(AppSetting).where(AppSetting.key==key)): return
    for emp in db.scalars(select(Employee)).all():
        last=db.scalar(select(ProductionAttendance.org_unit_id).where(ProductionAttendance.employee_id==emp.id,ProductionAttendance.org_unit_id.isnot(None)).order_by(ProductionAttendance.work_date.desc()).limit(1))
        if not last: continue
        ids=_emp_unit_ids(db,emp)
        if last in ids and ids and ids[0]==last: continue
        _apply_unit_set(db,emp,[last]+[i for i in ids if i!=emp.default_org_unit_id and i!=last])
    db.add(AppSetting(key=key,value="1")); db.commit()

def _employee_public(db:Session,e:Employee,p:Person):
    ids=[r[0] for r in db.execute(select(employee_org_units.c.org_unit_id).where(employee_org_units.c.employee_id==e.id)).all()]
    units=db.scalars(select(OrganizationalUnit).where(OrganizationalUnit.id.in_(ids))).all() if ids else []
    names=[u.name_el for u in sorted(units,key=lambda u:u.name_el)]
    return {"id":e.id,"employee_code":e.employee_code,"full_name":((p.first_name+" "+p.last_name).strip()),"phone":p.phone,"default_org_unit_id":e.default_org_unit_id,"org_unit_ids":ids,"org_unit_names":names,"active":bool(e.active and p.active)}

def _log_placement_interval(db:Session,employee_id:str,new_org_unit_id:str|None,at:datetime|None=None,unit_ids:list[str]|None=None):
    """Closes any open placement interval for this employee today and opens a new one for
    new_org_unit_id. No-op if the department isn't actually changing. Pure addition -- never read by
    ProductionWorkEntry/ProductionAttendance or the reports built on them."""
    now=at or _event_now_aware()
    day=datetime(now.year,now.month,now.day,tzinfo=timezone.utc)
    open_row=db.scalar(select(ProductionPlacementInterval).where(ProductionPlacementInterval.employee_id==employee_id,ProductionPlacementInterval.work_date==day,ProductionPlacementInterval.ended_at.is_(None)))
    ids_json=_json.dumps(unit_ids if unit_ids is not None else ([new_org_unit_id] if new_org_unit_id else []))
    if open_row:
        old_set=set(_json.loads(open_row.org_unit_ids)) if open_row.org_unit_ids else ({open_row.org_unit_id} if open_row.org_unit_id else set())
        new_set=set(unit_ids) if unit_ids is not None else ({new_org_unit_id} if new_org_unit_id else set())
        if open_row.org_unit_id==new_org_unit_id and (old_set==new_set or unit_ids is None): return (None,None)
        open_row.ended_at=now
    new_row=ProductionPlacementInterval(employee_id=employee_id,work_date=day,org_unit_id=new_org_unit_id,started_at=now,org_unit_ids=ids_json)
    db.add(new_row); db.flush()
    return (open_row.id if open_row else None, new_row.id)

def _replace_employee_units(db:Session,emp:Employee,ids:list[str]):
    clean=[]
    for unit_id in ids or []:
        if unit_id and unit_id not in clean:
            if not db.get(OrganizationalUnit,unit_id): raise HTTPException(422,"Άγνωστο τμήμα")
            clean.append(unit_id)
    db.execute(employee_org_units.delete().where(employee_org_units.c.employee_id==emp.id))
    for unit_id in clean: db.execute(employee_org_units.insert().values(employee_id=emp.id,org_unit_id=unit_id))
    new_default=clean[0] if clean else None
    if new_default!=emp.default_org_unit_id or True: _log_placement_interval(db,emp.id,new_default,unit_ids=clean)
    emp.default_org_unit_id=new_default

@app.get("/master/employees", response_model=list[schemas.EmployeeOut])
def list_employees(include_inactive:bool=Query(default=False), db:Session=Depends(get_db), user=Depends(require_permission("master.view"))):
    stmt=select(Employee,Person).join(Person,Person.id==Employee.person_id)
    if not include_inactive: stmt=stmt.where(Employee.active==True,Person.active==True)
    rows=db.execute(stmt.order_by(Person.last_name,Person.first_name)).all()
    return [_employee_public(db,e,p) for e,p in rows]

@app.post("/master/employees", response_model=schemas.EmployeeOut)
def create_employee(data:schemas.EmployeeCreate, db:Session=Depends(get_db), user:User=Depends(require_permission("master.edit"))):
    full=data.full_name.strip(); parts=full.split(None,1); first=parts[0] if parts else full; last=parts[1] if len(parts)>1 else ""
    person=Person(first_name=first,last_name=last,phone=data.phone); db.add(person); db.flush()
    next_no=(db.scalar(select(text('count(*)')).select_from(Employee)) or 0)+1; code=f"EMP-{next_no:04d}"
    while db.scalar(select(Employee).where(Employee.employee_code==code)): next_no+=1; code=f"EMP-{next_no:04d}"
    emp=Employee(person_id=person.id,employee_code=code); db.add(emp); db.flush()
    ids=data.org_unit_ids or ([data.default_org_unit_id] if data.default_org_unit_id else []); _replace_employee_units(db,emp,ids)
    write_audit(db,user,"employee",emp.id,"CREATE",new=data.model_dump())
    db.commit(); db.refresh(emp)
    return _employee_public(db,emp,person)

@app.put("/master/employees/{employee_id}", response_model=schemas.EmployeeOut)
def update_employee(employee_id:str,data:schemas.EmployeeCreate,db:Session=Depends(get_db),user:User=Depends(require_permission("master.edit"))):
    emp=db.get(Employee,employee_id)
    if not emp: raise HTTPException(404,"Ο εργαζόμενος δεν βρέθηκε")
    person=db.get(Person,emp.person_id)
    old={"full_name":(person.first_name+" "+person.last_name).strip(),"phone":person.phone,"default_org_unit_id":emp.default_org_unit_id,"org_unit_ids":[r[0] for r in db.execute(select(employee_org_units.c.org_unit_id).where(employee_org_units.c.employee_id==emp.id)).all()]}
    full=data.full_name.strip(); parts=full.split(None,1); person.first_name=parts[0] if parts else full; person.last_name=parts[1] if len(parts)>1 else ""; person.phone=data.phone
    ids=data.org_unit_ids or ([data.default_org_unit_id] if data.default_org_unit_id else []); _replace_employee_units(db,emp,ids)
    write_audit(db,user,"employee",emp.id,"UPDATE",old=old,new=data.model_dump())
    db.commit(); db.refresh(emp)
    return _employee_public(db,emp,person)

@app.delete("/master/employees/{employee_id}/permanent")
def delete_employee_permanent(employee_id:str,db:Session=Depends(get_db),user:User=Depends(require_permission("master.edit"))):
    """Οριστική διαγραφή -- ΜΟΝΟ αν ο εργαζόμενος δεν έχει καμία εγγραφή ιστορικού (παρουσίες, παραγωγή, διαστήματα κ.λπ.).
    Αλλιώς 409: το ιστορικό και οι αναφορές μένουν ανέγγιχτα και ο χρήστης χρησιμοποιεί «Μη ενεργό»."""
    emp=db.get(Employee,employee_id)
    if not emp: raise HTTPException(404,"Ο εργαζόμενος δεν βρέθηκε")
    refs=[]
    for t in Base.metadata.tables.values():
        if t.name in ("employees","employee_org_units"): continue
        for fk in t.foreign_keys:
            if fk.column.table.name=="employees":
                n=db.scalar(select(func.count()).select_from(t).where(fk.parent==emp.id)) or 0
                if n: refs.append(f"{t.name} ({n})")
    if refs: raise HTTPException(409,"Ο εργαζόμενος έχει ιστορικό ("+", ".join(refs)+") και δεν μπορεί να διαγραφεί οριστικά -- χρησιμοποίησε «Μη ενεργό».")
    person_id=emp.person_id; name=emp.full_name if hasattr(emp,"full_name") else employee_id
    db.execute(employee_org_units.delete().where(employee_org_units.c.employee_id==emp.id))
    write_audit(db,user,"employee",emp.id,"DELETE",old={"person_id":person_id},new=None)
    db.delete(emp); db.flush()
    person=db.get(Person,person_id)
    if person:
        used=any(db.scalar(select(func.count()).select_from(t).where(fk.parent==person_id)) for t in Base.metadata.tables.values() if t.name!="persons" for fk in t.foreign_keys if fk.column.table.name=="persons")
        if not used: db.delete(person)
    db.commit(); return {"ok":True}

@app.delete("/master/employees/{employee_id}")
def delete_employee(employee_id:str,db:Session=Depends(get_db),user:User=Depends(require_permission("master.edit"))):
    emp=db.get(Employee,employee_id)
    if not emp: raise HTTPException(404,"Ο εργαζόμενος δεν βρέθηκε")
    emp.active=False; p=db.get(Person,emp.person_id); p.active=False; write_audit(db,user,"employee",emp.id,"DEACTIVATE",old={"active":True},new={"active":False}); db.commit(); return {"ok":True}

@app.post("/master/employees/{employee_id}/activate")
def activate_employee(employee_id:str,db:Session=Depends(get_db),user:User=Depends(require_permission("master.edit"))):
    emp=db.get(Employee,employee_id)
    if not emp: raise HTTPException(404,"Ο εργαζόμενος δεν βρέθηκε")
    emp.active=True; p=db.get(Person,emp.person_id); p.active=True; write_audit(db,user,"employee",emp.id,"ACTIVATE",old={"active":False},new={"active":True}); db.commit(); return {"ok":True}

@app.get("/production/work-entries", response_model=list[schemas.ProductionWorkEntryOut])
def production_work_entries(start:str|None=Query(default=None), end:str|None=Query(default=None), db:Session=Depends(get_db), user=Depends(require_permission("production.view"))):
    stmt=select(ProductionWorkEntry).where(ProductionWorkEntry.active==True)
    if start: stmt=stmt.where(ProductionWorkEntry.work_date>=datetime.fromisoformat(start))
    if end: stmt=stmt.where(ProductionWorkEntry.work_date<datetime.fromisoformat(end)+timedelta(days=1))
    return db.scalars(stmt.order_by(ProductionWorkEntry.work_date,ProductionWorkEntry.created_at)).all()

@app.post("/production/work-entries", response_model=schemas.ProductionWorkEntryOut)
def create_production_work_entry(data:schemas.ProductionWorkEntryCreate,db:Session=Depends(get_db),user:User=Depends(require_permission("production.move"))):
    if not db.get(OrganizationalUnit,data.org_unit_id): raise HTTPException(404,"Το τμήμα δεν βρέθηκε")
    if data.employee_id and not db.get(Employee,data.employee_id): raise HTTPException(404,"Ο εργαζόμενος δεν βρέθηκε")
    if not db.get(WEEECategory,data.weee_category_id): raise HTTPException(404,"Η κατηγορία ΑΗΗΕ δεν βρέθηκε")
    obj=ProductionWorkEntry(**data.model_dump(),created_by_user_id=user.id,created_at=_event_now()); db.add(obj); db.commit(); db.refresh(obj); return obj

def _production_entry_snapshot(obj:ProductionWorkEntry)->dict:
    return {"work_date":obj.work_date.isoformat(),"org_unit_id":obj.org_unit_id,"employee_id":obj.employee_id,"weee_category_id":obj.weee_category_id,"weight_kg":str(obj.weight_kg),"supplier_group":obj.supplier_group,"notes":obj.notes}

@app.put("/production/work-entries/{entry_id}", response_model=schemas.ProductionWorkEntryOut)
def update_production_work_entry(entry_id:str, data:schemas.ProductionWorkEntryUpdate, db:Session=Depends(get_db), user:User=Depends(require_permission("production.edit"))):
    obj=db.get(ProductionWorkEntry,entry_id)
    if not obj or not obj.active: raise HTTPException(404,"Η καταχώριση δεν βρέθηκε")
    fields=data.model_dump(exclude={"reason"},exclude_unset=True)
    if not fields: raise HTTPException(400,"Δεν στάλθηκαν αλλαγές")
    if "org_unit_id" in fields and not db.get(OrganizationalUnit,fields["org_unit_id"]): raise HTTPException(404,"Το τμήμα δεν βρέθηκε")
    if fields.get("employee_id") and not db.get(Employee,fields["employee_id"]): raise HTTPException(404,"Ο εργαζόμενος δεν βρέθηκε")
    if "weee_category_id" in fields and not db.get(WEEECategory,fields["weee_category_id"]): raise HTTPException(404,"Η κατηγορία ΑΗΗΕ δεν βρέθηκε")
    old=_production_entry_snapshot(obj)
    for k,v in fields.items(): setattr(obj,k,v)
    write_audit(db,user,"production_work_entry",obj.id,"CORRECTION",old=old,new=_production_entry_snapshot(obj),reason=data.reason)
    db.commit(); db.refresh(obj); return obj

@app.delete("/production/work-entries/{entry_id}")
def delete_production_work_entry(entry_id:str, reason:str|None=Query(default=None), db:Session=Depends(get_db), user:User=Depends(require_permission("production.edit"))):
    obj=db.get(ProductionWorkEntry,entry_id)
    if not obj or not obj.active: raise HTTPException(404,"Η καταχώριση δεν βρέθηκε")
    old=_production_entry_snapshot(obj)
    obj.active=False
    write_audit(db,user,"production_work_entry",obj.id,"DELETE",old=old,new={"active":False},reason=reason)
    db.commit(); return {"ok":True}

@app.get("/production/work-entries/{entry_id}/history")
def production_work_entry_history(entry_id:str, db:Session=Depends(get_db), user=Depends(require_permission("production.view"))):
    events=db.scalars(select(models.AuditEvent).where(models.AuditEvent.entity_type=="production_work_entry",models.AuditEvent.entity_id==entry_id).order_by(models.AuditEvent.created_at.desc())).all()
    uids={e.user_id for e in events if e.user_id}
    users={u.id:u.username for u in db.scalars(select(User).where(User.id.in_(uids))).all()} if uids else {}
    return [{"action":e.action,"old_values":json.loads(e.old_values) if e.old_values else None,"new_values":json.loads(e.new_values) if e.new_values else None,"reason":e.reason,"user":users.get(e.user_id),"created_at":e.created_at.isoformat()} for e in events]

def _short_leaves_list(raw)->list:
    """Ολιγόωρες απουσίες από το JSON της βάσης -> λίστα {"from","to"} (πάντα λίστα)."""
    if not raw: return []
    try: v=_json.loads(raw)
    except Exception: return []
    return [{"from":x.get("from"),"to":x.get("to")} for x in v if isinstance(x,dict) and x.get("from")]

def _validate_short_leaves(items):
    """Έλεγχος: μορφή ΩΩ:ΛΛ, «Επέστρεψε» μετά το «Έφυγε», καμία επικάλυψη (ανοιχτή = μέχρι το τέλος της ημέρας). Επιστρέφει JSON ή None αν δεν υπάρχουν."""
    import re as _re
    def tm(v):
        m=_re.fullmatch(r"(\d\d):(\d\d)",v or "")
        if not m or int(m.group(1))>23 or int(m.group(2))>59: return None
        return int(m.group(1))*60+int(m.group(2))
    spans=[]
    for it in items or []:
        a=tm(it.from_); b=tm(it.to) if it.to else None
        if a is None or (it.to and b is None): raise HTTPException(422,"Η ώρα της ολιγόωρης πρέπει να είναι της μορφής ΩΩ:ΛΛ")
        if b is not None and b<=a: raise HTTPException(422,"Η ώρα «Επέστρεψε» πρέπει να είναι μετά την ώρα «Έφυγε»")
        spans.append((a,b if b is not None else 1440))
    spans.sort()
    for i in range(1,len(spans)):
        if spans[i][0]<spans[i-1][1]: raise HTTPException(422,"Οι ολιγόωρες απουσίες δεν επιτρέπεται να επικαλύπτονται")
    if not items: return None
    return _json.dumps([{"from":it.from_,"to":it.to or None} for it in sorted(items,key=lambda x:x.from_)],ensure_ascii=False)

def _hm(v):
    try:
        h,m=[int(x) for x in str(v or "").split(":")]
        return h*60+m if 0<=h<24 and 0<=m<60 else None
    except Exception: return None

def _net_ctx(db:Session)->dict:
    """Ωράριο (ενεργό: θερινό/χειμερινό/έκτακτο), αντιστοίχιση Τμήμα -> ομάδα διαλειμμάτων Α/Β και τμήματα εργαζομένων.
    Ωράριο και διαλείμματα ορίζονται ΜΟΝΟ στα Windows (Ρυθμίσεις)· Windows και Android τα διαβάζουν."""
    row=db.scalar(select(AppSetting).where(AppSetting.key==SCHEDULE_KEY))
    try: sc=_sched_norm(json.loads(row.value)) if row else _sched_norm(DEFAULT_SCHEDULE)
    except Exception: sc=_sched_norm(DEFAULT_SCHEDULE)
    d=sc.get(sc.get("active") or "winter") or sc.get("summer") or {}
    def brk(x):
        out=[]
        for k in ("b1","b2"):
            b=(x or {}).get(k) or {}
            a,e=_hm(b.get("start")),_hm(b.get("end"))
            if a is not None and e is not None: out.append((a,e))
        return out
    g=db.scalar(select(AppSetting).where(AppSetting.key==BREAK_GROUPS_KEY))
    try: groups=json.loads(g.value) if g else {}
    except Exception: groups={}
    emp_units={}
    for eid,uid_ in db.execute(select(employee_org_units.c.employee_id,employee_org_units.c.org_unit_id)).all(): emp_units.setdefault(eid,[]).append(uid_)
    return {"s":_hm(d.get("start")),"e":_hm(d.get("end")),"A":brk(d),"B":brk(d.get("B")),"groups":groups,"emp_units":emp_units}

def _local_min(dt):
    if dt is None: return None
    l=dt.replace(tzinfo=timezone.utc).astimezone() if dt.tzinfo is None else dt.astimezone()
    return l.hour*60+l.minute

def _net_minutes_core(sch,breaks,status,late,arrived,since,shorts,live_to=None):
    """ΜΙΑ συνάρτηση καθαρών ωρών (λεπτά) για Windows και Android.
    καθαρές = (τώρα | λήξη βάρδιας | ώρα ΕΦΥΓΕ) − (έναρξη βάρδιας | ώρα άφιξης, ό,τι είναι μεταγενέστερο) − διαλείμματα του τμήματος μέσα στο διάστημα − ολιγόωρες (μόνο ο εργάσιμος χρόνος τους).
    live_to: λεπτά της ώρας «τώρα» (μόνο για τη σημερινή ημέρα)· None = όλη η ημέρα (παλαιότερες ημέρες).
    Αποτέλεσμα None = ακόμα χωρίς ώρα (αργοπορία/έφυγε χωρίς ώρα) ή ανοιχτή ολιγόωρη."""
    if sch["s"] is None or sch["e"] is None: return None
    if status=="ABSENT": return 0
    a,b=sch["s"],sch["e"]
    if late:
        if arrived is None: return None
        a=max(a,arrived)
    if status=="LEFT":
        if since is None: return None
        b=min(since,b)
    elif live_to is not None:
        b=min(b,live_to)
    if b<=a: return 0
    t=b-a
    for x,y in breaks:
        o=min(b,y)-max(a,x)
        if o>0: t-=o
    sh=[x for x in (shorts or []) if x[0] is not None]
    if any(x[1] is None for x in sh): return None
    for x,y in sh:
        s0,e0=max(x,a),min(y,b)
        if e0<=s0: continue
        w=e0-s0
        for bx,by in breaks:
            o=min(e0,by)-max(s0,bx)
            if o>0: w-=o
        t-=w
    return max(0,t)

def _row_net(ctx,emp,status,late,arrived_at,since_at,short_leaves,org_unit_id,day,now=None):
    """Καθαρές ώρες μιας γραμμής παρουσίας: ζωντανά για τη σημερινή ημέρα, ολόκληρη η ημέρα για τις παλαιότερες, μελλοντική = 0."""
    now=now or datetime.now()
    today=datetime(now.year,now.month,now.day); d=datetime(day.year,day.month,day.day)
    if d>today: return 0
    unit=org_unit_id or (emp.default_org_unit_id if emp else None)
    if not unit and emp is not None: unit=(ctx["emp_units"].get(emp.id) or [None])[0]
    grp="B" if ctx["groups"].get(unit)=="B" else "A"
    shorts=[(_hm(x.get("from")),_hm(x.get("to")) if x.get("to") else None) for x in (short_leaves or [])]
    return _net_minutes_core(ctx,ctx[grp],status or "PRESENT",bool(late),_local_min(arrived_at),_local_min(since_at),shorts,live_to=(now.hour*60+now.minute) if d==today else None)

def _with_net(db:Session,out:list)->list:
    """Προσθέτει «net_minutes» (ζωντανές καθαρές ώρες, ΙΔΙΑ συνάρτηση για Windows και Android) σε κάθε γραμμή παρουσίας."""
    ctx=_net_ctx(db); emps={e.id:e for e in db.scalars(select(Employee)).all()}; now=datetime.now()
    for x in out:
        x["net_minutes"]=_row_net(ctx,emps.get(x["employee_id"]),x.get("status"),x.get("late"),x.get("arrived_at"),x.get("since_at"),x.get("short_leaves"),x.get("org_unit_id"),x["work_date"],now)
    return out

@app.get("/production/attendance", response_model=list[schemas.ProductionAttendanceOut])
def production_attendance_for_date(date:str=Query(...), db:Session=Depends(get_db), user=Depends(require_permission("production.view"))):
    day=datetime.fromisoformat(date)
    rows=db.scalars(select(ProductionAttendance).where(ProductionAttendance.work_date>=day,ProductionAttendance.work_date<day+timedelta(days=1))).all()
    ctx=_net_ctx(db); emps={e.id:e for e in db.scalars(select(Employee)).all()}
    return [{"id":r.id,"work_date":r.work_date,"employee_id":r.employee_id,"status":r.status,"org_unit_id":r.org_unit_id,"position_text":r.position_text,"since_at":r.since_at,"late":bool(r.late),"arrived_at":r.arrived_at,
             "short_leaves":_short_leaves_list(r.short_leaves),"net_minutes":_row_net(ctx,emps.get(r.employee_id),r.status,r.late,r.arrived_at,r.since_at,_short_leaves_list(r.short_leaves),r.org_unit_id,r.work_date)} for r in rows]

def _shift_start(db:Session)->str:
    v=db.scalar(select(AppSetting.value).where(AppSetting.key=="production.shift_start"))
    try:
        h,m=[int(x) for x in (v or "").split(":")]
        if 0<=h<24 and 0<=m<60: return f"{h:02d}:{m:02d}"
    except Exception: pass
    return "07:00"

def _after_shift_start(db:Session, when_utc:datetime)->bool:
    h,m=[int(x) for x in _shift_start(db).split(":")]
    local=when_utc.replace(tzinfo=timezone.utc).astimezone()  # ώρα του υπολογιστή-server (Ελλάδα)
    return (local.hour,local.minute)>(h,m)

def _last_known_unit(db:Session, employee_id:str, day:datetime):
    """Τελευταία γνωστή θέση: η πιο πρόσφατη τοποθέτηση σε προηγούμενη ημέρα, αλλιώς η μόνιμη (ΕΡΓΑΤΕΣ)."""
    r=db.scalar(select(ProductionAttendance.org_unit_id).where(ProductionAttendance.employee_id==employee_id,ProductionAttendance.work_date<day,ProductionAttendance.org_unit_id.isnot(None)).order_by(ProductionAttendance.work_date.desc()).limit(1))
    if r: return r
    emp=db.get(Employee,employee_id); return emp.default_org_unit_id if emp else None

def _shift_end(db:Session)->str:
    v=db.scalar(select(AppSetting.value).where(AppSetting.key=="production.shift_end"))
    try:
        h,m=[int(x) for x in (v or "").split(":")]
        if 0<=h<24 and 0<=m<60: return f"{h:02d}:{m:02d}"
    except Exception: pass
    return "15:00"

@app.get("/production/shift-start")
def get_shift_start(db:Session=Depends(get_db), user=Depends(require_permission("production.view"))):
    return {"shift_start":_shift_start(db),"shift_end":_shift_end(db)}

@app.put("/production/shift-start")
def set_shift_start(data:schemas.ShiftStartIn, db:Session=Depends(get_db), user:User=Depends(require_permission("production.move"))):
    for key,raw in (("production.shift_start",data.shift_start),("production.shift_end",data.shift_end)):
        if raw is None: continue
        try:
            h,m=[int(x) for x in raw.split(":")]; assert 0<=h<24 and 0<=m<60
        except Exception: raise HTTPException(422,"Η ώρα πρέπει να είναι της μορφής ΩΩ:ΛΛ")
        val=f"{h:02d}:{m:02d}"; row=db.scalar(select(AppSetting).where(AppSetting.key==key))
        if row: row.value=val
        else: db.add(AppSetting(key=key,value=val))
        write_audit(db,user,"app_setting",key,"UPDATE",new={"value":val})
    db.commit(); return {"shift_start":_shift_start(db),"shift_end":_shift_end(db)}

@app.get("/production/attendance/effective")
def production_attendance_effective(date:str=Query(...), db:Session=Depends(get_db), user=Depends(require_permission("production.view"))):
    """Η ΠΡΑΓΜΑΤΙΚΗ κατάσταση της ημέρας για ΚΑΘΕ ενεργό εργαζόμενο. Όποιος δεν έχει εγγραφή ξεκινά ΠΑΡΩΝ (εγκαίρως)
    στην τελευταία γνωστή θέση του. ΑΠΩΝ/ΕΦΥΓΕ δεν αλλάζουν τη θέση· όταν γυρίσει παρών ξεκινά από εκεί."""
    day=datetime.fromisoformat(date); day=datetime(day.year,day.month,day.day)
    rows={r.employee_id:r for r in db.scalars(select(ProductionAttendance).where(ProductionAttendance.work_date==day)).all()}
    last={}
    for emp_id,org in db.execute(select(ProductionAttendance.employee_id,ProductionAttendance.org_unit_id).where(ProductionAttendance.work_date<day,ProductionAttendance.org_unit_id.isnot(None)).order_by(ProductionAttendance.work_date.desc())).all():
        last.setdefault(emp_id,org)
    out=[]
    for e in db.scalars(select(Employee).where(Employee.active==True)).all():
        r=rows.get(e.id)
        if r:
            out.append({"id":r.id,"work_date":r.work_date,"employee_id":e.id,"status":r.status or "PRESENT","org_unit_id":r.org_unit_id,"position_text":r.position_text,"short_leaves":_short_leaves_list(r.short_leaves),"since_at":r.since_at,"late":bool(r.late),"arrived_at":r.arrived_at,"explicit":True})
        else:
            out.append({"id":None,"work_date":day,"employee_id":e.id,"status":"PRESENT","org_unit_id":last.get(e.id) or e.default_org_unit_id,"position_text":None,"short_leaves":[],"since_at":None,"late":False,"arrived_at":None,"explicit":False})
    return _with_net(db,out)

@app.get("/production/attendance/range")
def production_attendance_range(start:str=Query(...), end:str=Query(...), db:Session=Depends(get_db), user=Depends(require_permission("production.view"))):
    """Μόνο ανάγνωση: οι ΚΑΤΑΓΕΓΡΑΜΜΕΝΕΣ παρουσίες (ρητές εγγραφές) ενός διαστήματος -- για την καρτέλα «Παραγωγή ανά Τμήμα / Άτομο» σε περίοδο μεγαλύτερη της ημέρας."""
    d0=datetime.fromisoformat(start); d1=datetime.fromisoformat(end)+timedelta(days=1)
    rows=db.scalars(select(ProductionAttendance).where(ProductionAttendance.work_date>=d0,ProductionAttendance.work_date<d1).order_by(ProductionAttendance.work_date)).all()
    return _with_net(db,[{"id":r.id,"work_date":r.work_date,"employee_id":r.employee_id,"status":r.status or "PRESENT","org_unit_id":r.org_unit_id,"position_text":r.position_text,"short_leaves":_short_leaves_list(r.short_leaves),"since_at":r.since_at,"late":bool(r.late),"arrived_at":r.arrived_at,"explicit":True} for r in rows])

@app.get("/production/attendance/effective-range")
def production_attendance_effective_range(start:str=Query(...), end:str=Query(...), db:Session=Depends(get_db), user=Depends(require_permission("production.view"))):
    """Μόνο ανάγνωση: η ΠΡΑΓΜΑΤΙΚΗ παρουσία ΚΑΘΕ ημέρας ενός διαστήματος με τον ίδιο κανόνα του /production/attendance/effective
    (όποιος δεν έχει εγγραφή είναι ΠΑΡΩΝ στην τελευταία γνωστή θέση του). Ημέρες που λογίζονται: μέχρι σήμερα, Δευτέρα–Παρασκευή,
    και κάθε ημέρα (και Σαβ/Κυρ) που έχει παραγωγή ή ρητή παρουσία."""
    d0=datetime.fromisoformat(start); d1=datetime.fromisoformat(end)
    d0=datetime(d0.year,d0.month,d0.day); d1=datetime(d1.year,d1.month,d1.day)
    today=datetime.now(); today=datetime(today.year,today.month,today.day)
    if d1>today: d1=today
    if d1<d0: return []
    explicit={}
    for r in db.scalars(select(ProductionAttendance).where(ProductionAttendance.work_date>=d0,ProductionAttendance.work_date<=d1)).all():
        explicit[(datetime(r.work_date.year,r.work_date.month,r.work_date.day),r.employee_id)]=r
    prod_days={datetime(x.year,x.month,x.day) for (x,) in db.execute(select(ProductionWorkEntry.work_date).where(ProductionWorkEntry.active==True,ProductionWorkEntry.work_date>=d0,ProductionWorkEntry.work_date<d1+timedelta(days=1))).all()}
    att_days={k[0] for k in explicit}
    last={}
    for emp_id,org in db.execute(select(ProductionAttendance.employee_id,ProductionAttendance.org_unit_id).where(ProductionAttendance.work_date<d0,ProductionAttendance.org_unit_id.isnot(None)).order_by(ProductionAttendance.work_date.desc())).all():
        last.setdefault(emp_id,org)
    emps=db.scalars(select(Employee).where(Employee.active==True)).all()
    out=[]; day=d0
    while day<=d1:
        if day.weekday()<5 or day in prod_days or day in att_days:
            for e in emps:
                r=explicit.get((day,e.id))
                if r:
                    if r.org_unit_id: last[e.id]=r.org_unit_id
                    out.append({"id":r.id,"work_date":day,"employee_id":e.id,"status":r.status or "PRESENT","org_unit_id":r.org_unit_id,"position_text":r.position_text,"short_leaves":_short_leaves_list(r.short_leaves),"since_at":r.since_at,"late":bool(r.late),"arrived_at":r.arrived_at,"explicit":True})
                else:
                    out.append({"id":None,"work_date":day,"employee_id":e.id,"status":"PRESENT","org_unit_id":last.get(e.id) or e.default_org_unit_id,"position_text":None,"short_leaves":[],"since_at":None,"late":False,"arrived_at":None,"explicit":False})
        day+=timedelta(days=1)
    return _with_net(db,out)

@app.put("/production/attendance", response_model=schemas.ProductionAttendanceOut)
def upsert_production_attendance(data:schemas.ProductionAttendanceUpsert, db:Session=Depends(get_db), user:User=Depends(require_permission("production.move"))):
    if not db.get(Employee,data.employee_id): raise HTTPException(404,"Ο εργαζόμενος δεν βρέθηκε")
    if data.org_unit_id and not db.get(OrganizationalUnit,data.org_unit_id): raise HTTPException(404,"Το τμήμα δεν βρέθηκε")
    day=datetime(data.work_date.year,data.work_date.month,data.work_date.day)
    obj=db.scalar(select(ProductionAttendance).where(ProductionAttendance.work_date==day,ProductionAttendance.employee_id==data.employee_id))
    # Προηγούμενη ΠΡΑΓΜΑΤΙΚΗ κατάσταση (όποιος δεν έχει εγγραφή είναι παρών στην τελευταία γνωστή θέση)
    if obj: p_exists,p_status,p_org,p_late,p_arr,p_since=True,(obj.status or "PRESENT"),obj.org_unit_id,bool(obj.late),obj.arrived_at,obj.since_at
    else: p_exists,p_status,p_org,p_late,p_arr,p_since=False,"PRESENT",_last_known_unit(db,data.employee_id,day),False,None,None
    status=data.status or "PRESENT"
    # Η θέση ΔΕΝ αλλάζει με ΑΠΩΝ/ΕΦΥΓΕ -- όταν γυρίσει παρών ξεκινά από την τελευταία γνωστή.
    new_org=data.org_unit_id
    if new_org is None and (status in ("ABSENT","LEFT") or p_status in ("ABSENT","LEFT")): new_org=p_org  # επιστροφή = από την τελευταία γνωστή θέση
    now=_event_now()
    if status=="PRESENT":
        if p_status=="ABSENT":   # ήρθε (ή ξαναήρθε) τώρα -- αργοπορία αν είναι μετά την έναρξη βάρδιας
            arrived=now; late=True if data.late else (False if data.late is False else _after_shift_start(db,now))
        elif p_status=="LEFT": arrived,late=p_arr,p_late  # επιστροφή από ΕΦΥΓΕ δεν αλλάζει την καθυστέρηση
        elif data.late is True: late,arrived=True,(p_arr or now)
        elif data.late is False: late,arrived=False,None
        else: late,arrived=p_late,p_arr
        if "arrived_at" in data.model_fields_set:  # χειροκίνητη διόρθωση ώρας άφιξης από το Παρουσιολόγιο
            arrived=data.arrived_at.replace(tzinfo=None) if data.arrived_at and data.arrived_at.tzinfo is None else (data.arrived_at.astimezone(timezone.utc).replace(tzinfo=None) if data.arrived_at else None)
            late=bool(arrived) if data.late is None else data.late
    elif status=="ABSENT": arrived,late=None,False  # απών = δεν ξεκίνησε ποτέ την ημέρα
    else:  # LEFT: κρατά την αργοπορία· μπορεί να οριστεί/αλλάξει και αργοπορία ταυτόχρονα (Αργοπορία + Έφυγε)
        arrived,late=p_arr,p_late
        if data.late is True: late,arrived=True,(p_arr or now)
        elif data.late is False: late,arrived=False,None
        if "arrived_at" in data.model_fields_set:
            arrived=data.arrived_at.replace(tzinfo=None) if data.arrived_at and data.arrived_at.tzinfo is None else (data.arrived_at.astimezone(timezone.utc).replace(tzinfo=None) if data.arrived_at else None)
            late=bool(arrived) if data.late is None else data.late
    sl_json=_validate_short_leaves(data.short_leaves) if "short_leaves" in data.model_fields_set else None
    old=None
    if obj:
        old={"status":obj.status,"org_unit_id":obj.org_unit_id,"position_text":obj.position_text,"since_at":obj.since_at.isoformat() if obj.since_at else None,"late":bool(obj.late)}
        obj.status=status; obj.org_unit_id=new_org; obj.position_text=data.position_text; obj.since_at=data.since_at; obj.late=late; obj.arrived_at=arrived
        if "short_leaves" in data.model_fields_set: obj.short_leaves=sl_json     # χωρίς το πεδίο στο αίτημα (π.χ. Android) οι ολιγόωρες μένουν όπως είναι
    else:
        obj=ProductionAttendance(work_date=day,employee_id=data.employee_id,status=status,org_unit_id=new_org,position_text=data.position_text,since_at=data.since_at,late=late,arrived_at=arrived,created_by_user_id=user.id,short_leaves=sl_json)
        db.add(obj)
    closed_id=opened_id=None
    emp_row=db.get(Employee,data.employee_id); prev_ids=_emp_unit_ids(db,emp_row); new_ids=prev_ids
    if new_org and new_org!=p_org:   # ΜΕΤΑΚΙΝΗΣΗ: φεύγει από το τρέχον τμήμα και μπαίνει στο νέο (τα υπόλοιπα τμήματά του μένουν)
        new_ids=[new_org]+[i for i in prev_ids if i!=p_org and i!=new_org]
        _apply_unit_set(db,emp_row,new_ids)
    if new_org!=p_org: closed_id,opened_id=_log_placement_interval(db,data.employee_id,new_org,at=data.since_at,unit_ids=new_ids)
    db.flush()
    event_id=None
    if (not p_exists) and (status!="PRESENT" or new_org!=p_org or late) or (p_exists and (p_status!=status or p_org!=new_org or p_late!=late)):
        ev=ProductionAttendanceEvent(created_at=_event_now(),work_date=day,employee_id=data.employee_id,user_id=user.id,status=status,org_unit_id=new_org,since_at=data.since_at,late=late,
            prev_exists=p_exists,prev_status=p_status,prev_org_unit_id=p_org,prev_since_at=p_since,prev_late=p_late,prev_arrived_at=p_arr,closed_interval_id=closed_id,opened_interval_id=opened_id,
            unit_ids=_json.dumps(new_ids),prev_unit_ids=_json.dumps(prev_ids))
        db.add(ev); db.flush(); event_id=ev.id
    new={"status":obj.status,"org_unit_id":obj.org_unit_id,"position_text":obj.position_text,"since_at":obj.since_at.isoformat() if obj.since_at else None,"late":bool(obj.late)}
    write_audit(db,user,"production_attendance",obj.id,"UPSERT",old=old,new=new)
    db.commit(); db.refresh(obj)
    return {"id":obj.id,"work_date":obj.work_date,"employee_id":obj.employee_id,"status":obj.status,"org_unit_id":obj.org_unit_id,"position_text":obj.position_text,"since_at":obj.since_at,"late":bool(obj.late),"arrived_at":obj.arrived_at,"short_leaves":_short_leaves_list(obj.short_leaves),"net_minutes":_row_net(_net_ctx(db),emp_row,obj.status,obj.late,obj.arrived_at,obj.since_at,_short_leaves_list(obj.short_leaves),obj.org_unit_id,obj.work_date),"event_id":event_id}

def _short_name(person)->str:
    if not person: return ""
    last=(person.last_name or "").strip()
    return f"{person.first_name} {last[0]}." if last else (person.first_name or "")

@app.post("/production/attendance/units")
def change_attendance_units(data:schemas.AttendanceUnitsIn, db:Session=Depends(get_db), user:User=Depends(require_permission("production.move"))):
    """«Προσθήκη και σε άλλο τμήμα» / «Αφαίρεση από τμήμα»: αλλάζει το κοινό σύνολο τμημάτων του εργαζομένου (Μητρώα + Δελτίο).
    Η παρουσία (ΠΑΡΩΝ/ΑΠΩΝ/ΕΦΥΓΕ) μένει μία ανά εργαζόμενο -- δεν αλλάζει. Καταγράφεται στο Ιστορικό με ΑΚΥΡΩΣΗ."""
    emp=db.get(Employee,data.employee_id)
    if not emp: raise HTTPException(404,"Ο εργαζόμενος δεν βρέθηκε")
    if data.action not in ("add","remove","move"): raise HTTPException(422,"Άγνωστη ενέργεια")
    if not db.get(OrganizationalUnit,data.unit_id): raise HTTPException(404,"Το τμήμα δεν βρέθηκε")
    day=datetime(data.work_date.year,data.work_date.month,data.work_date.day)
    prev_ids=_emp_unit_ids(db,emp)
    if data.action=="move":
        # «Μεταφορά»: ΕΝΑ αίτημα -- φεύγει από τα from_unit_ids και πηγαίνει στο unit_id (γίνεται το κύριο τμήμα)
        frm=[x for x in (data.from_unit_ids or []) if x]
        if data.unit_id in prev_ids: raise HTTPException(409,"Ο εργαζόμενος ανήκει ήδη σε αυτό το τμήμα")
        if not frm or any(x not in prev_ids for x in frm): raise HTTPException(409,"Ο εργαζόμενος δεν ανήκει στο τμήμα από το οποίο φεύγει")
        new_ids=[data.unit_id]+[i for i in prev_ids if i not in frm]
    elif data.action=="add":
        if data.unit_id in prev_ids: raise HTTPException(409,"Ο εργαζόμενος ανήκει ήδη σε αυτό το τμήμα")
        new_ids=prev_ids+[data.unit_id]
    else:
        if data.unit_id not in prev_ids: raise HTTPException(409,"Ο εργαζόμενος δεν ανήκει σε αυτό το τμήμα")
        if len(prev_ids)<2: raise HTTPException(409,"Η αφαίρεση επιτρέπεται μόνο αν ο εργαζόμενος ανήκει σε 2 ή περισσότερα τμήματα (χρησιμοποίησε «Μετακίνηση»)")
        new_ids=[i for i in prev_ids if i!=data.unit_id]
    obj=db.scalar(select(ProductionAttendance).where(ProductionAttendance.work_date==day,ProductionAttendance.employee_id==emp.id))
    if obj: p_exists,p_status,p_org,p_late,p_arr,p_since=True,(obj.status or "PRESENT"),obj.org_unit_id,bool(obj.late),obj.arrived_at,obj.since_at
    else: p_exists,p_status,p_org,p_late,p_arr,p_since=False,"PRESENT",_last_known_unit(db,emp.id,day),False,None,None
    new_org=new_ids[0] if new_ids else None
    _apply_unit_set(db,emp,new_ids)
    if obj: obj.org_unit_id=new_org
    else:
        obj=ProductionAttendance(work_date=day,employee_id=emp.id,status="PRESENT",org_unit_id=new_org,late=False,created_by_user_id=user.id); db.add(obj)
    closed_id,opened_id=_log_placement_interval(db,emp.id,new_org,unit_ids=new_ids)
    db.flush()
    ev=ProductionAttendanceEvent(created_at=_event_now(),work_date=day,employee_id=emp.id,user_id=user.id,status=obj.status,org_unit_id=new_org,since_at=obj.since_at,late=bool(obj.late),
        prev_exists=p_exists,prev_status=p_status,prev_org_unit_id=p_org,prev_since_at=p_since,prev_late=p_late,prev_arrived_at=p_arr,closed_interval_id=closed_id,opened_interval_id=opened_id,
        unit_ids=_json.dumps(new_ids),prev_unit_ids=_json.dumps(prev_ids))
    db.add(ev); db.flush()
    write_audit(db,user,"production_attendance",obj.id,"UNITS_"+data.action.upper(),old={"unit_ids":prev_ids},new={"unit_ids":new_ids})
    db.commit()
    return {"ok":True,"event_id":ev.id,"org_unit_ids":new_ids}

@app.get("/production/attendance/events")
def production_attendance_events(date:str=Query(...), db:Session=Depends(get_db), user=Depends(require_permission("production.view"))):
    """Ιστορικό της ημέρας (η πιο πρόσφατη αλλαγή πρώτη). can_undo = δεν υπάρχει νεότερη αλλαγή του ίδιου εργαζομένου."""
    day=datetime.fromisoformat(date); day=datetime(day.year,day.month,day.day)
    evs=db.scalars(select(ProductionAttendanceEvent).where(ProductionAttendanceEvent.work_date==day).order_by(ProductionAttendanceEvent.created_at.desc(),ProductionAttendanceEvent.id.desc())).all()
    emps={e.id:e for e in db.scalars(select(Employee)).all()}; people={p.id:p for p in db.scalars(select(Person)).all()}
    units={u.id:u.name_el for u in db.scalars(select(OrganizationalUnit)).all()}; users={u.id:u.username for u in db.scalars(select(User)).all()}
    seen=set(); out=[]
    for ev in evs:
        emp=emps.get(ev.employee_id); person=people.get(emp.person_id) if emp else None
        nm=_short_name(person); new_u=units.get(ev.org_unit_id) if ev.org_unit_id else None; old_u=units.get(ev.prev_org_unit_id) if ev.prev_org_unit_id else None
        if ev.status=="LEFT": tx="έφυγε"
        elif ev.status=="ABSENT": tx="απών"
        elif ev.prev_status in ("ABSENT","LEFT"):
            tx=("επέστρεψε" if ev.prev_status=="LEFT" else ("άργησε" if ev.late else "παρών"))+(f" στο {new_u}" if new_u else "")
        elif ev.unit_ids is not None and ev.prev_unit_ids is not None and set(_json.loads(ev.unit_ids))!=set(_json.loads(ev.prev_unit_ids)):
            _n,_p=_json.loads(ev.unit_ids),_json.loads(ev.prev_unit_ids)
            add_=[units.get(i,"") for i in _n if i not in _p]; rem_=[units.get(i,"") for i in _p if i not in _n]
            tx=(f"{', '.join(rem_)} → {', '.join(add_)}" if add_ and rem_ else (f"προσθήκη στο {', '.join(add_)}" if add_ else f"αφαίρεση από το {', '.join(rem_)}"))
        elif new_u and old_u and new_u!=old_u: tx=f"{old_u} → {new_u}"
        elif new_u and new_u!=old_u: tx=f"τοποθετήθηκε στο {new_u}"
        elif ev.late and not ev.prev_late: tx="αργοπορία"
        else: tx="παρών"
        out.append({"id":ev.id,"time":ev.created_at.isoformat(),"employee_id":ev.employee_id,"employee_name":(f"{person.first_name} {person.last_name}".strip() if person else ""),
            "text":f"{nm}: {tx}","user":users.get(ev.user_id),"status":ev.status,"org_unit_id":ev.org_unit_id,"can_undo":ev.employee_id not in seen})
        seen.add(ev.employee_id)
    return out

@app.post("/production/attendance/events/{event_id}/undo")
def undo_production_attendance_event(event_id:str, db:Session=Depends(get_db), user:User=Depends(require_permission("production.move"))):
    """ΑΚΥΡΩΣΗ: μόνο αν δεν υπάρχει νεότερη αλλαγή του ΙΔΙΟΥ εργαζομένου. Επαναφέρει την προηγούμενη κατάσταση,
    ΔΙΑΓΡΑΦΕΙ την εγγραφή ιστορικού και διορθώνει τα χρονικά διαστήματα τμήματος (σημείο 2)."""
    ev=db.get(ProductionAttendanceEvent,event_id)
    if not ev: raise HTTPException(404,"Η εγγραφή δεν βρέθηκε")
    newer=db.scalar(select(ProductionAttendanceEvent).where(ProductionAttendanceEvent.employee_id==ev.employee_id,ProductionAttendanceEvent.work_date==ev.work_date,
        (ProductionAttendanceEvent.created_at>ev.created_at)|((ProductionAttendanceEvent.created_at==ev.created_at)&(ProductionAttendanceEvent.id>ev.id))))
    if newer: raise HTTPException(409,"Υπάρχει νεότερη αλλαγή του ίδιου εργαζομένου")
    obj=db.scalar(select(ProductionAttendance).where(ProductionAttendance.work_date==ev.work_date,ProductionAttendance.employee_id==ev.employee_id))
    if obj:
        if ev.prev_exists: obj.status=ev.prev_status; obj.org_unit_id=ev.prev_org_unit_id; obj.since_at=ev.prev_since_at; obj.late=bool(ev.prev_late); obj.arrived_at=ev.prev_arrived_at
        else: db.delete(obj)
    if ev.prev_unit_ids is not None:
        emp_row=db.get(Employee,ev.employee_id)
        if emp_row: _apply_unit_set(db,emp_row,[i for i in _json.loads(ev.prev_unit_ids) if db.get(OrganizationalUnit,i)])
    if ev.opened_interval_id:
        iv=db.get(ProductionPlacementInterval,ev.opened_interval_id)
        if iv: db.delete(iv)
    if ev.closed_interval_id:
        iv=db.get(ProductionPlacementInterval,ev.closed_interval_id)
        if iv: iv.ended_at=None
    write_audit(db,user,"production_attendance",ev.employee_id,"UNDO",old={"status":ev.status,"org_unit_id":ev.org_unit_id},new={"status":ev.prev_status,"org_unit_id":ev.prev_org_unit_id})
    db.delete(ev); db.commit(); return {"ok":True}

@app.get("/production/placement-intervals")
def production_placement_intervals(date:str=Query(...), db:Session=Depends(get_db), user=Depends(require_permission("production.view"))):
    day=datetime.fromisoformat(date)
    rows=db.scalars(select(ProductionPlacementInterval).where(ProductionPlacementInterval.work_date==datetime(day.year,day.month,day.day)).order_by(ProductionPlacementInterval.employee_id,ProductionPlacementInterval.started_at)).all()
    emps={e.id:e for e in db.scalars(select(Employee)).all()}
    people={p.id:p for p in db.scalars(select(Person)).all()}
    units={u.id:u for u in db.scalars(select(OrganizationalUnit)).all()}
    out=[]
    for r in rows:
        emp=emps.get(r.employee_id); person=people.get(emp.person_id) if emp else None
        unit=units.get(r.org_unit_id) if r.org_unit_id else None
        # SQLite returns DateTime(timezone=True) values naive regardless of how they were stored, so
        # the "still ongoing" fallback must be naive too or the subtraction below throws.
        ended=r.ended_at or datetime.utcnow()
        out.append({"id":r.id,"employee_id":r.employee_id,"employee_name":(f"{person.first_name} {person.last_name}".strip() if person else ""),
            "org_unit_id":r.org_unit_id,"org_unit_name":unit.name_el if unit else None,
            "org_unit_ids":(_json.loads(r.org_unit_ids) if r.org_unit_ids else ([r.org_unit_id] if r.org_unit_id else [])),
            "org_unit_names":[units[i].name_el for i in (_json.loads(r.org_unit_ids) if r.org_unit_ids else ([r.org_unit_id] if r.org_unit_id else [])) if i in units],
            "started_at":r.started_at.isoformat(),"ended_at":r.ended_at.isoformat() if r.ended_at else None,
            "ongoing":r.ended_at is None,"minutes":round((ended-r.started_at).total_seconds()/60),"kg":0.0,"entries":0})
    # Κιλά ανά διάστημα: κάθε καταχώρηση παραγωγής του εργαζομένου (ίδια ημέρα) ανήκει στο διάστημα όπου
    # βρισκόταν ΤΗΝ ΩΡΑ που καταχωρήθηκε (created_at). Καταχωρήσεις πριν από το πρώτο διάστημα πάνε στο πρώτο.
    # ΜΟΝΟ ανάγνωση -- δεν αλλάζει καμία καταχώρηση ούτε οι υπάρχουσες αναφορές.
    day0=datetime(day.year,day.month,day.day)
    ents=db.scalars(select(ProductionWorkEntry).where(ProductionWorkEntry.active==True,ProductionWorkEntry.employee_id.isnot(None),
        ProductionWorkEntry.work_date>=day0,ProductionWorkEntry.work_date<day0+timedelta(days=1)).order_by(ProductionWorkEntry.created_at)).all()
    by_emp={}
    for r,o in zip(rows,out): by_emp.setdefault(r.employee_id,[]).append((r,o))
    # Αρχικό «άρρητο» διάστημα: όποιος είναι στη θέση του από την αρχή της βάρδιας (δεν μετακινήθηκε ή μετακινήθηκε αργότερα)
    # έχει διάστημα από την έναρξη βάρδιας μέχρι την πρώτη του μετακίνηση (ή όλη τη μέρα). Μόνο ανάγνωση -- δεν αποθηκεύεται τίποτα.
    class _Iv:
        def __init__(self,emp_id,started,ended): self.employee_id=emp_id; self.started_at=started; self.ended_at=ended
    sh,sm=[int(x) for x in _shift_start(db).split(":")]
    start_utc=datetime(day0.year,day0.month,day0.day,sh,sm).astimezone(timezone.utc).replace(tzinfo=None)
    att_rows={a.employee_id:a for a in db.scalars(select(ProductionAttendance).where(ProductionAttendance.work_date==day0)).all()}
    first_ev={}
    for ev in db.scalars(select(ProductionAttendanceEvent).where(ProductionAttendanceEvent.work_date==day0).order_by(ProductionAttendanceEvent.created_at)).all(): first_ev.setdefault(ev.employee_id,ev)
    for emp in emps.values():
        if emp.active is False: continue
        a=att_rows.get(emp.id)
        if a and a.status=="ABSENT": continue
        mine=by_emp.get(emp.id)
        if mine:
            if mine[0][0].started_at<=start_utc: continue
            ev=first_ev.get(emp.id); org=ev.prev_org_unit_id if ev else None; end=mine[0][0].started_at
        else:
            org=a.org_unit_id if a else _last_known_unit(db,emp.id,day0); end=(a.since_at if a and a.status=="LEFT" else None)
        if not org: continue
        person=people.get(emp.person_id); unit=units.get(org); iv=_Iv(emp.id,start_utc,end)
        o={"id":"implicit-"+emp.id,"employee_id":emp.id,"employee_name":(f"{person.first_name} {person.last_name}".strip() if person else ""),
            "org_unit_id":org,"org_unit_name":unit.name_el if unit else None,
            "org_unit_ids":(_emp_unit_ids(db,emp) or [org]),"org_unit_names":[units[i].name_el for i in (_emp_unit_ids(db,emp) or [org]) if i in units],"started_at":start_utc.isoformat(),"ended_at":end.isoformat() if end else None,
            "ongoing":end is None,"minutes":max(0,round(((end or datetime.utcnow())-start_utc).total_seconds()/60)),"kg":0.0,"entries":0,"implicit":True}
        out.append(o); by_emp.setdefault(emp.id,[]).insert(0,(iv,o))
    for e in ents:
        mine=by_emp.get(e.employee_id)
        if not mine: continue
        target=mine[0][1]
        for r,o in mine:
            if r.started_at<=e.created_at and (r.ended_at is None or e.created_at<r.ended_at): target=o
        target["kg"]=round(target["kg"]+float(e.weight_kg or 0),3); target["entries"]+=1
    out.sort(key=lambda o:(o["employee_id"],o["started_at"]))
    return out

@app.post("/production/day-material", response_model=schemas.ProductionWorkEntryOut)
def upsert_production_day_material(data:schemas.ProductionDayMaterialIn, db:Session=Depends(get_db), user:User=Depends(require_permission("production.move"))):
    unit=db.get(OrganizationalUnit,data.org_unit_id)
    if not unit: raise HTTPException(404,"Το τμήμα δεν βρέθηκε")
    if data.employee_id and not db.get(Employee,data.employee_id): raise HTTPException(404,"Ο εργαζόμενος δεν βρέθηκε")
    if not db.get(WEEECategory,data.weee_category_id): raise HTTPException(404,"Η κατηγορία ΑΗΗΕ δεν βρέθηκε")
    day=datetime(data.work_date.year,data.work_date.month,data.work_date.day)
    obj=db.scalar(select(ProductionWorkEntry).where(ProductionWorkEntry.work_date==day,ProductionWorkEntry.org_unit_id==data.org_unit_id,
        ProductionWorkEntry.employee_id==data.employee_id,ProductionWorkEntry.weee_category_id==data.weee_category_id,ProductionWorkEntry.active==True))
    prev=obj.weight_kg if obj else 0
    delta=data.weight_kg-prev
    # Δελτίο Παραγωγής: a plain material+kg table cell, not a physical lot pick like Android's
    # forklift flow -- auto-consume the INCREASE from whatever ΑΗΗΕ stock sorting has produced for
    # this category (oldest lots first), same real stock as /production/transfers. A decrease only
    # corrects the reported number, same no-reversal convention as the existing Windows "Διόρθωση
    # παραγωγής" editor for production_work_entries.
    if delta>0: _consume_weee_stock_for_category(db,unit,data.weee_category_id,delta,user,notes="Δελτίο Παραγωγής")
    if obj:
        obj.weight_kg=data.weight_kg
    else:
        obj=ProductionWorkEntry(work_date=day,org_unit_id=data.org_unit_id,employee_id=data.employee_id,weee_category_id=data.weee_category_id,
            weight_kg=data.weight_kg,source=data.source,created_by_user_id=user.id)
        db.add(obj)
    db.commit(); db.refresh(obj); return obj

@app.get("/production/material-output")
def material_output_entries(start:str|None=Query(default=None), end:str|None=Query(default=None), db:Session=Depends(get_db), user=Depends(require_permission("production.view"))):
    stmt=select(MaterialOutputEntry).where(MaterialOutputEntry.active==True)
    if start: stmt=stmt.where(MaterialOutputEntry.work_date>=datetime.fromisoformat(start))
    if end: stmt=stmt.where(MaterialOutputEntry.work_date<datetime.fromisoformat(end)+timedelta(days=1))
    rows=db.scalars(stmt.order_by(MaterialOutputEntry.work_date,MaterialOutputEntry.created_at)).all()
    return [{"id":r.id,"work_date":r.work_date.isoformat(),"category_group":r.category_group,"material_label":r.material_label,"weight_kg":float(r.weight_kg or 0),"notes":r.notes,"active":r.active} for r in rows]

@app.get("/production/material-shipments")
def material_shipment_entries(start:str|None=Query(default=None), end:str|None=Query(default=None), db:Session=Depends(get_db), user=Depends(require_permission("production.view"))):
    stmt=select(models.MaterialShipmentEntry).where(models.MaterialShipmentEntry.active==True)
    if start: stmt=stmt.where(models.MaterialShipmentEntry.work_date>=datetime.fromisoformat(start))
    if end: stmt=stmt.where(models.MaterialShipmentEntry.work_date<datetime.fromisoformat(end)+timedelta(days=1))
    rows=db.scalars(stmt.order_by(models.MaterialShipmentEntry.work_date,models.MaterialShipmentEntry.created_at)).all()
    return [{"id":r.id,"work_date":r.work_date.isoformat(),"category_group":r.category_group,"material_label":r.material_label,"weight_kg":float(r.weight_kg or 0),"notes":r.notes,"active":r.active} for r in rows]

# ---- Build 2.5.36: Απογραφή (τρέχον έτος) -- quarterly stock-reconciliation report ----
_HER_LOOKALIKE_TABLE=str.maketrans({"Α":"A","Β":"B","Ε":"E","Ζ":"Z","Η":"H","Ι":"I","Κ":"K","Μ":"M","Ν":"N","Ο":"O","Ρ":"P","Τ":"T","Υ":"Y","Χ":"X"})
def _norm_material_label(s:str|None)->str:
    """Normalise a material label for matching live production/shipment data against the Ylika.xlsx
    HER-group mapping -- the two disagree here and there on Greek-vs-Latin lookalike letters (e.g.
    Greek 'ΙΝΟΧ' vs Latin 'INOX') or stray whitespace."""
    if not s: return ""
    return s.strip().upper().translate(_HER_LOOKALIKE_TABLE)

def _quarter_label_totals(entries, quarter_of):
    """Bucket entries into {normalised_label: [q1_total, q2_total, q3_total, q4_total]} in one O(n)
    pass -- the per-report-row loop below only ever needs a label's total for a given quarter, so
    precomputing this once avoids rescanning the full entries list for every (row x quarter) combo
    (with ~150 rows x 4 quarters x thousands of entries, that rescan used to cost over a second)."""
    totals:dict[str,list[float]]={}
    for e in entries:
        bucket=totals.setdefault(_norm_material_label(e.material_label),[0.0,0.0,0.0,0.0])
        bucket[quarter_of(e)-1]+=float(e.weight_kg or 0)
    return totals

@app.get("/reports/inventory-count")
def inventory_count_report(year:int=Query(...), db:Session=Depends(get_db), user=Depends(require_permission("production.view"))):
    rows=db.scalars(select(models.InventoryReportRow).order_by(models.InventoryReportRow.sort_order)).all()
    her_map=db.scalars(select(models.MaterialHerGroup)).all()
    labels_by_her:dict[str,set[str]]={}
    for m in her_map: labels_by_her.setdefault(m.her_group,set()).add(_norm_material_label(m.material_label))
    year_start=datetime(year,1,1); year_end=datetime(year+1,1,1)
    out_rows=db.scalars(select(models.MaterialOutputEntry).where(models.MaterialOutputEntry.active==True,models.MaterialOutputEntry.work_date>=year_start,models.MaterialOutputEntry.work_date<year_end)).all()
    ship_rows=db.scalars(select(models.MaterialShipmentEntry).where(models.MaterialShipmentEntry.active==True,models.MaterialShipmentEntry.work_date>=year_start,models.MaterialShipmentEntry.work_date<year_end)).all()
    count_rows=db.scalars(select(models.InventoryCountEntry).where(models.InventoryCountEntry.year==year)).all()
    quarter_of_date=lambda e:(e.work_date.month-1)//3+1
    proc_totals=_quarter_label_totals(out_rows,quarter_of_date)
    sales_totals=_quarter_label_totals(ship_rows,quarter_of_date)
    counted_totals=_quarter_label_totals(count_rows,lambda e:e.quarter)
    zero4=[0.0,0.0,0.0,0.0]

    # ΠΡΑΓΜΑΤΙΚΟ is fully computed now, not typed in by hand: the same "Τρέχον απόθεμα" figure Υλικά
    # shows (all-time produced minus all-time shipped per material, NOT scoped to `year` -- stock on
    # hand doesn't reset each year, see loadReadyBalance()'s comment in desktop_v11.html) plus that
    # quarter's own Ποσότητα απογραφής. Opening-stock (2025) figures are deliberately excluded here
    # too, same as Υλικά, per prior explicit user direction that it must not feed "ready to load".
    all_out=db.scalars(select(models.MaterialOutputEntry).where(models.MaterialOutputEntry.active==True)).all()
    all_ship=db.scalars(select(models.MaterialShipmentEntry).where(models.MaterialShipmentEntry.active==True)).all()
    current_balance:dict[str,float]={}
    for e in all_out:
        lbl=_norm_material_label(e.material_label)
        current_balance[lbl]=current_balance.get(lbl,0.0)+float(e.weight_kg or 0)
    for e in all_ship:
        lbl=_norm_material_label(e.material_label)
        current_balance[lbl]=current_balance.get(lbl,0.0)-float(e.weight_kg or 0)

    result=[]
    for r in rows:
        active=r.her_group is not None
        matched=labels_by_her.get(r.her_group,set()) if active else set()
        row_current_stock=sum(current_balance.get(lbl,0.0) for lbl in matched) if active else 0.0
        quarters=[]
        cum_proc=cum_sales=0.0
        for q in (1,2,3,4):
            if active:
                proc_q=sum(proc_totals.get(lbl,zero4)[q-1] for lbl in matched)
                sales_q=sum(sales_totals.get(lbl,zero4)[q-1] for lbl in matched)
                cum_proc+=proc_q; cum_sales+=sales_q
                counted=sum(counted_totals.get(lbl,zero4)[q-1] for lbl in matched)
                stock=float(r.baseline_stock_2025 or 0)+cum_proc-cum_sales+counted
                actual=row_current_stock+counted
                diff=stock-actual
            else:
                proc_q=sales_q=stock=0.0; actual=diff=None
            quarters.append({
                "processing":round(cum_proc,3) if active else 0.0,
                "sales":round(cum_sales,3) if active else 0.0,
                "processing_interval":round(proc_q,3) if active else 0.0,
                "sales_interval":round(sales_q,3) if active else 0.0,
                "stock":round(stock,3),
                "actual_stock":round(actual,3) if actual is not None else None,
                "diff":round(diff,3) if diff is not None else None,
            })
        result.append({"id":r.id,"group_name":r.group_name,"subcategory":r.subcategory,"her_group":r.her_group,"eka_code":r.eka_code,"reptool_code":r.reptool_code,"baseline_stock_2025":float(r.baseline_stock_2025 or 0),"active":active,"frozen_hidden":r.frozen_hidden,"quarters":quarters})
    return {"year":year,"rows":result}

@app.get("/inventory/count-entries")
def list_inventory_count_entries(year:int=Query(...), quarter:int=Query(...), db:Session=Depends(get_db), user=Depends(require_permission("production.view"))):
    rows=db.scalars(select(models.InventoryCountEntry).where(models.InventoryCountEntry.year==year,models.InventoryCountEntry.quarter==quarter)).all()
    return {r.material_label:float(r.weight_kg or 0) for r in rows}

@app.put("/inventory/count-entries")
def save_inventory_count_entry(data:schemas.InventoryCountEntryIn, db:Session=Depends(get_db), user:User=Depends(require_permission("production.move"))):
    if data.quarter not in (1,2,3,4): raise HTTPException(422,"Μη έγκυρο τρίμηνο")
    existing=db.scalar(select(models.InventoryCountEntry).where(models.InventoryCountEntry.year==data.year,models.InventoryCountEntry.quarter==data.quarter,models.InventoryCountEntry.material_label==data.material_label))
    if existing: existing.weight_kg=data.weight_kg; existing.updated_by_user_id=user.id
    else: db.add(models.InventoryCountEntry(year=data.year,quarter=data.quarter,material_label=data.material_label,weight_kg=data.weight_kg,updated_by_user_id=user.id))
    db.commit()
    return {"ok":True}

@app.put("/inventory/report-rows/{row_id}/her-group")
def set_inventory_row_her_group(row_id:str, data:schemas.InventoryRowHerGroupIn, db:Session=Depends(get_db), user:User=Depends(require_permission("production.move"))):
    row=db.get(models.InventoryReportRow,row_id)
    if not row: raise HTTPException(404,"Δεν βρέθηκε γραμμή")
    val=(data.her_group or "").strip() or None
    old=row.her_group
    row.her_group=val
    write_audit(db,user,'inventory_report_row',row.id,'EDIT',old={'her_group':old},new={'her_group':val})
    db.commit()
    return {"ok":True,"her_group":val}

@app.get("/inventory/material-corrections")
def list_material_corrections(year:int=Query(...), month:int=Query(...), db:Session=Depends(get_db), user=Depends(require_permission("production.view"))):
    start=datetime(year,month,1); end=datetime(year+1,1,1) if month==12 else datetime(year,month+1,1)
    rows=db.scalars(select(models.MaterialCorrectionEntry).where(models.MaterialCorrectionEntry.work_date>=start,models.MaterialCorrectionEntry.work_date<end).order_by(models.MaterialCorrectionEntry.work_date,models.MaterialCorrectionEntry.created_at)).all()
    uids={r.created_by_user_id for r in rows if r.created_by_user_id}
    users={u.id:u.username for u in db.scalars(select(User).where(User.id.in_(uids))).all()} if uids else {}
    return [schemas.MaterialCorrectionOut(id=r.id,work_date=r.work_date.date().isoformat(),material_label=r.material_label,weight_kg_delta=r.weight_kg_delta,piece_delta=r.piece_delta,reason=r.reason,created_by=users.get(r.created_by_user_id),created_at=r.created_at.isoformat() if r.created_at else None) for r in rows]

@app.get("/inventory/material-corrections/totals")
def material_corrections_totals(db:Session=Depends(get_db), user=Depends(require_permission("production.view"))):
    """Σύνολο ΟΛΩΝ των διορθώσεων (χειροκίνητες κινήσεις +/-) ανά υλικό -- μετράνε στο Τρέχον απόθεμα (κιλά και τεμάχια)."""
    rows=db.execute(select(models.MaterialCorrectionEntry.material_label,func.sum(models.MaterialCorrectionEntry.weight_kg_delta),func.sum(models.MaterialCorrectionEntry.piece_delta)).group_by(models.MaterialCorrectionEntry.material_label)).all()
    return [{"material_label":l,"weight_kg":float(w or 0),"pieces":int(p or 0)} for l,w,p in rows]

@app.post("/inventory/material-corrections", response_model=schemas.MaterialCorrectionOut)
def create_material_correction(data:schemas.MaterialCorrectionIn, db:Session=Depends(get_db), user:User=Depends(require_permission("production.move"))):
    wd=datetime.fromisoformat(data.work_date)
    obj=models.MaterialCorrectionEntry(work_date=wd,material_label=data.material_label,weight_kg_delta=data.weight_kg_delta,piece_delta=data.piece_delta,reason=data.reason,created_by_user_id=user.id)
    db.add(obj); db.flush()
    write_audit(db,user,'material_correction',obj.id,'CREATE',new={'material':data.material_label,'kg':str(data.weight_kg_delta),'pieces':data.piece_delta,'reason':data.reason})
    db.commit(); db.refresh(obj)
    return schemas.MaterialCorrectionOut(id=obj.id,work_date=obj.work_date.date().isoformat(),material_label=obj.material_label,weight_kg_delta=obj.weight_kg_delta,piece_delta=obj.piece_delta,reason=obj.reason,created_by=user.username,created_at=obj.created_at.isoformat() if obj.created_at else None)

@app.delete("/inventory/material-corrections/{entry_id}")
def delete_material_correction(entry_id:str, db:Session=Depends(get_db), user:User=Depends(require_permission("production.move"))):
    """Διαγραφή κίνησης διόρθωσης από το παράθυρο κινήσεων / Αναίρεση. Η «οριστική διαγραφή από το ιστορικό» είναι ξεχωριστή και μόνο για τη Διοίκηση (/permanent)."""
    obj=db.get(models.MaterialCorrectionEntry,entry_id)
    if not obj: raise HTTPException(404,"Δεν βρέθηκε")
    write_audit(db,user,'material_correction',obj.id,'DELETE',old={'material':obj.material_label,'kg':str(obj.weight_kg_delta),'pieces':obj.piece_delta})
    db.delete(obj); db.commit()
    return {"ok":True}

@app.delete("/inventory/material-corrections/{entry_id}/permanent")
def delete_material_correction_permanent(entry_id:str, db:Session=Depends(get_db), user:User=Depends(current_user)):
    """Οριστική διαγραφή κίνησης από το ιστορικό διορθώσεων -- ΜΟΝΟ Διοίκηση."""
    if not any(r.code=="MANAGEMENT" for r in user.roles): raise HTTPException(403,"Μόνο η Διοίκηση μπορεί να διαγράψει ιστορικό")
    obj=db.get(models.MaterialCorrectionEntry,entry_id)
    if not obj: raise HTTPException(404,"Δεν βρέθηκε")
    write_audit(db,user,'material_correction',obj.id,'DELETE_PERMANENT',old={'material':obj.material_label,'kg':str(obj.weight_kg_delta),'pieces':obj.piece_delta,'reason':obj.reason})
    db.delete(obj); db.commit()
    return {"ok":True}

def _yield_row_label(r)->str:
    return r.her_group or r.description_en or r.subcategory or r.group_name or r.reptool_code or "—"

@app.get("/reports/device-yields")
def device_yields(db:Session=Depends(get_db), user=Depends(require_permission("production.view"))):
    cats=db.scalars(select(WEEECategory).where(WEEECategory.is_internal_subcategory==False,WEEECategory.active==True,WEEECategory.processable!=False).order_by(WEEECategory.code)).all()
    rows=db.scalars(select(models.InventoryReportRow).order_by(models.InventoryReportRow.sort_order)).all()
    cells=db.scalars(select(models.DeviceMaterialYield)).all()
    batches=db.scalars(select(models.DeviceYieldBatch).order_by(models.DeviceYieldBatch.created_at)).all()
    batches_by_cat={}
    for b in batches: batches_by_cat.setdefault(b.weee_category_id,[]).append({"id":b.id,"label":b.label,"sample_size":b.sample_size})
    active_batch_by_cat={}
    for x in cells:
        if x.source_batch_id: active_batch_by_cat[x.weee_category_id]=x.source_batch_id
    return {
        "categories":[{"id":c.id,"code":c.code,"description_el":c.description_el,"her_description":c.her_description,"batches":batches_by_cat.get(c.id,[]),"active_batch_id":active_batch_by_cat.get(c.id)} for c in cats],
        "materials":[{"id":r.id,"name":_yield_row_label(r),"system_description":r.description_en,"active":r.her_group is not None} for r in rows],
        "cells":[{"weee_category_id":x.weee_category_id,"report_row_id":x.report_row_id,"percentage":x.percentage} for x in cells],
    }

@app.post("/reports/device-yields/apply-batch")
def apply_device_yield_batch(data:schemas.DeviceYieldApplyBatchIn, db:Session=Depends(get_db), user:User=Depends(require_permission("reports.manage"))):
    cat=db.get(WEEECategory,data.weee_category_id)
    if not cat: raise HTTPException(404,"Άγνωστη κατηγορία ΑΗΗΕ")
    all_batches=db.scalars(select(models.DeviceYieldBatch).where(models.DeviceYieldBatch.weee_category_id==data.weee_category_id)).all()
    if not all_batches: raise HTTPException(422,"Δεν υπάρχει κανένα batch για αυτή την κατηγορία")
    if data.batch_id:
        batch=next((b for b in all_batches if b.id==data.batch_id),None)
        if not batch: raise HTTPException(404,"Το batch δεν βρέθηκε για αυτή την κατηγορία")
        target_cells={c.report_row_id:c.percentage for c in db.scalars(select(models.DeviceYieldBatchCell).where(models.DeviceYieldBatchCell.batch_id==batch.id)).all()}
        applied_batch_id=batch.id
    else:
        # Weighted average across every batch for this category, weighted by sample_size (falls back
        # to an unweighted average -- weight 1 each -- for batches with no recorded sample_size).
        all_cells=db.scalars(select(models.DeviceYieldBatchCell).where(models.DeviceYieldBatchCell.batch_id.in_([b.id for b in all_batches]))).all()
        weight_by_batch={b.id:(b.sample_size or 1) for b in all_batches}
        num={}; den={}
        for c in all_cells:
            w=weight_by_batch.get(c.batch_id,1)
            num[c.report_row_id]=num.get(c.report_row_id,0)+float(c.percentage)*w
            den[c.report_row_id]=den.get(c.report_row_id,0)+w
        target_cells={rid:Decimal(str(num[rid]/den[rid])) for rid in num}
        applied_batch_id=None
    existing_by_row={x.report_row_id:x for x in db.scalars(select(models.DeviceMaterialYield).where(models.DeviceMaterialYield.weee_category_id==data.weee_category_id)).all()}
    for row_id, pct in target_cells.items():
        if row_id in existing_by_row:
            existing_by_row[row_id].percentage=pct; existing_by_row[row_id].updated_by_user_id=user.id; existing_by_row[row_id].source_batch_id=applied_batch_id
        else:
            db.add(models.DeviceMaterialYield(weee_category_id=data.weee_category_id,report_row_id=row_id,percentage=pct,updated_by_user_id=user.id,source_batch_id=applied_batch_id))
    # Materials that had a value from a previously-applied batch but aren't in the newly-selected one
    # go back to zero/blank rather than silently keeping a stale figure from the old source.
    for row_id, existing in existing_by_row.items():
        if row_id not in target_cells and existing.source_batch_id is not None:
            db.delete(existing)
    db.commit()
    return {"ok":True,"applied_batch_id":applied_batch_id,"cells":len(target_cells)}

@app.put("/reports/device-yields/cell")
def set_device_yield_cell(data:schemas.DeviceYieldCellIn, db:Session=Depends(get_db), user:User=Depends(require_permission("reports.manage"))):
    row=db.scalar(select(models.DeviceMaterialYield).where(models.DeviceMaterialYield.weee_category_id==data.weee_category_id,models.DeviceMaterialYield.report_row_id==data.report_row_id))
    if data.percentage is None or data.percentage==0:
        if row: db.delete(row); db.commit()
        return {"ok":True}
    if row:
        row.percentage=data.percentage; row.updated_by_user_id=user.id
    else:
        db.add(models.DeviceMaterialYield(weee_category_id=data.weee_category_id,report_row_id=data.report_row_id,percentage=data.percentage,updated_by_user_id=user.id))
    db.commit()
    return {"ok":True}

from fastapi import UploadFile, File
@app.post("/reports/device-yields/import")
async def import_device_yields(file:UploadFile=File(...), db:Session=Depends(get_db), user:User=Depends(require_permission("reports.manage"))):
    from openpyxl import load_workbook
    import io
    content=await file.read()
    try:
        wb=load_workbook(io.BytesIO(content),data_only=True)
    except Exception:
        raise HTTPException(422,"Δεν ήταν δυνατή η ανάγνωση του αρχείου Excel")
    ws=wb[wb.sheetnames[0]]
    cats={c.code:c for c in db.scalars(select(WEEECategory).where(WEEECategory.is_internal_subcategory==False)).all()}
    report_rows=db.scalars(select(models.InventoryReportRow)).all()
    rows_by_key={}
    for r in report_rows:
        rows_by_key[_yield_row_label(r).strip().lower()]=r
        if r.reptool_code: rows_by_key[r.reptool_code.strip().lower()]=r
    header=[c.value for c in next(ws.iter_rows(min_row=1,max_row=1))]
    col_map={}
    for idx,val in enumerate(header):
        if val is None: continue
        code=str(val).strip()
        if code in cats: col_map[idx]=cats[code]
    if not col_map:
        raise HTTPException(422,"Δεν βρέθηκε καμία στήλη με αναγνωρίσιμο κωδικό ΑΗΗΕ στην πρώτη γραμμή")
    updated=0; unmatched_materials=[]
    for row in ws.iter_rows(min_row=2):
        if not row: continue
        name_cell=row[0].value
        if name_cell is None or str(name_cell).strip()=="": continue
        rrow=rows_by_key.get(str(name_cell).strip().lower())
        if not rrow:
            unmatched_materials.append(str(name_cell)); continue
        for idx,cat in col_map.items():
            if idx>=len(row): continue
            val=row[idx].value
            if val is None or val=="": continue
            try: pct=Decimal(str(val))
            except Exception: continue
            existing=db.scalar(select(models.DeviceMaterialYield).where(models.DeviceMaterialYield.weee_category_id==cat.id,models.DeviceMaterialYield.report_row_id==rrow.id))
            if existing: existing.percentage=pct; existing.updated_by_user_id=user.id
            else: db.add(models.DeviceMaterialYield(weee_category_id=cat.id,report_row_id=rrow.id,percentage=pct,updated_by_user_id=user.id))
            updated+=1
    db.commit()
    write_audit(db,user,'device_material_yield','import','IMPORT',new={'updated':updated,'unmatched_materials':len(unmatched_materials)})
    return {"updated":updated,"unmatched_materials":unmatched_materials[:30]}

@app.get("/production/press-bales")
def press_bale_entries(start:str|None=Query(default=None), end:str|None=Query(default=None), db:Session=Depends(get_db), user=Depends(require_permission("production.view"))):
    """Per-bale packaging detail from the ΠΡΕΣΑ (baling press) sheets, purely informational --
    these materials are already counted in /production/material-output, never re-summed here."""
    stmt=select(models.BaleEntry).where(models.BaleEntry.active==True)
    if start: stmt=stmt.where(models.BaleEntry.period>=datetime.fromisoformat(start))
    if end: stmt=stmt.where(models.BaleEntry.period<datetime.fromisoformat(end)+timedelta(days=1))
    rows=db.scalars(stmt.order_by(models.BaleEntry.material_group,models.BaleEntry.bale_seq)).all()
    return [{"id":r.id,"period":r.period.isoformat(),"material_group":r.material_group,"bale_seq":r.bale_seq,"weight_kg":float(r.weight_kg or 0),"is_bulk":r.is_bulk,"bale_count":r.bale_count,"notes":r.notes} for r in rows]

@app.get("/inventory/material-opening-stock")
def material_opening_stock(db:Session=Depends(get_db),user=Depends(require_permission("production.view"))):
    rows=db.scalars(select(MaterialOpeningStock).where(MaterialOpeningStock.active==True).order_by(MaterialOpeningStock.category_group,MaterialOpeningStock.material_label)).all()
    return [{"id":r.id,"as_of_date":r.as_of_date.isoformat(),"category_group":r.category_group,"material_label":r.material_label,"kg":float(r.kg),"reptool_code":r.reptool_code,"her_description":r.her_description,"notes":r.notes} for r in rows]

@app.get("/reports/material-reptool-export")
def material_reptool_export(db:Session=Depends(get_db),user=Depends(require_permission("production.view"))):
    rows=db.scalars(select(MaterialOpeningStock).where(MaterialOpeningStock.active==True)).all()
    grouped={};unmatched=[];as_of=None
    for r in rows:
        as_of=r.as_of_date
        if r.reptool_code:
            g=grouped.setdefault(r.reptool_code,{"reptool_code":r.reptool_code,"her_description":r.her_description,"kg":0.0,"source_labels":[]})
            g["kg"]+=float(r.kg);g["source_labels"].append(r.material_label)
        else:
            unmatched.append({"material_label":r.material_label,"category_group":r.category_group,"kg":float(r.kg)})
    matched_out=sorted(grouped.values(),key=lambda x:x["reptool_code"])
    unmatched.sort(key=lambda x:-x["kg"])
    return {"as_of_date":as_of.isoformat() if as_of else None,"matched":matched_out,"unmatched":unmatched,
            "matched_total_kg":sum(x["kg"] for x in matched_out),"unmatched_total_kg":sum(x["kg"] for x in unmatched)}

@app.get("/materials/group-overrides")
def material_group_overrides(db:Session=Depends(get_db),user=Depends(require_permission("production.view"))):
    rows=db.scalars(select(models.MaterialGroupOverride)).all()
    return {r.material_label:{"category_group":r.category_group,"sort_order":r.sort_order} for r in rows}

@app.put("/materials/group-overrides/{material_label:path}")
def material_group_override_set(material_label:str,data:schemas.MaterialGroupOverrideSet,db:Session=Depends(get_db),user=Depends(require_permission("production.edit"))):
    if data.category_group not in {"AXIOPOIISIMA","EIDIKIS_DIACHEIRISIS","APORRIPSI"}: raise HTTPException(422,"Άγνωστη ομάδα υλικού")
    row=db.scalar(select(models.MaterialGroupOverride).where(models.MaterialGroupOverride.material_label==material_label))
    if row: row.category_group=data.category_group; row.sort_order=data.sort_order
    else: db.add(models.MaterialGroupOverride(material_label=material_label,category_group=data.category_group,sort_order=data.sort_order))
    db.commit(); return {"ok":True}

@app.get("/integrations/electrocycle/orders")
def electrocycle_orders(date:str|None=Query(default=None,pattern=r'^\d{4}-\d{2}-\d{2}$'),db:Session=Depends(get_db),user=Depends(require_permission("receipt.view"))):
    # date lets the Παραλαβές calendar look up a past day's synced orders (source_date is kept
    # indefinitely -- only today's rows get replaced on each sync); defaults to today.
    target_date=date or datetime.now().date().isoformat()
    # An order used to create a receipt (InboundLoad.order_number) disappears from the live feed --
    # re-appears if that receipt is later deleted (soft-deleted trips are excluded from the "used" set).
    used_order_nos={r for (r,) in db.execute(
        select(models.InboundLoad.order_number).join(models.InboundTrip, models.InboundLoad.trip_id==models.InboundTrip.id)
        .where(models.InboundTrip.deleted_at.is_(None), models.InboundLoad.order_number.is_not(None))
    ).all()}
    rows=[r for r in db.scalars(select(ElectrocycleOrder).where(ElectrocycleOrder.source_date==target_date).order_by(ElectrocycleOrder.order_no)).all() if r.order_no not in used_order_nos]
    status=db.scalar(select(ElectrocycleSyncStatus))
    return {"orders":[{"id":r.id,"order_no":r.order_no,"execution_route":r.execution_route,"delivery_route":r.delivery_route,
             "sender":r.sender,"pickup_point":r.pickup_point,"address":r.address,"city":r.city,"postal_code":r.postal_code,
             "carrier":r.carrier,"collection_medium":r.collection_medium,"source_date":r.source_date,"synced_at":r.synced_at.isoformat()} for r in rows],
            "status":{"ok":status.ok,"message":status.message,
                      "last_attempt_at":status.last_attempt_at.isoformat() if status and status.last_attempt_at else None,
                      "last_success_at":status.last_success_at.isoformat() if status and status.last_success_at else None,
                      "sync_minutes":settings.electrocycle_sync_minutes} if status else None,
            "server_now":datetime.now().isoformat()}

@app.post("/integrations/electrocycle/sync")
async def electrocycle_manual_sync(date:str|None=Query(default=None,pattern=r'^\d{4}-\d{2}-\d{2}$'),db:Session=Depends(get_db),user=Depends(require_permission("receipt.edit"))):
    target=datetime.fromisoformat(date).date() if date else None
    result=await asyncio.to_thread(sync_electrocycle_orders,db,target)
    return result

# ---- Build 0.2: Windows Receipts ----
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from decimal import Decimal
from pathlib import Path
from sqlalchemy.orm import selectinload
from .models import ContainerAsset, InboundTrip, InboundLoad

RECEIPT_TYPES = {"CONTAINER", "CURTAIN_TRAILER", "SMALL_POINTS"}


def _receipt_number(db: Session, when: datetime) -> str:
    year = when.year
    rows = db.scalars(select(InboundTrip).where(InboundTrip.receipt_number.like(f"REC-{year}-%"))).all()
    return f"REC-{year}-{len(rows)+1:06d}"


def _compute_net(receipt_type: str, load: schemas.ReceiptLoadCreate, outgoing: ContainerAsset|None) -> Decimal|None:
    if load.gross_weight is None or load.tare_weight is None:
        return None
    if receipt_type == "CONTAINER":
        out_tare = Decimal(outgoing.tare_weight) if outgoing is not None else (Decimal(load.outgoing_container_tare) if load.outgoing_container_tare is not None else None)
        if load.incoming_container_tare is None or out_tare is None:
            return None
        # 1st scale = truck + incoming container + load
        # 2nd scale = truck + selected/custom outgoing empty container
        return load.gross_weight - load.tare_weight - load.incoming_container_tare + out_tare
    return load.gross_weight - load.tare_weight

def _nonneg(value, label: str):
    """Κανένα βάρος/τεμάχια δεν μπορεί να είναι αρνητικό -- σε καμία καταχώρηση."""
    if value is not None and Decimal(value) < 0:
        raise HTTPException(422, f"{label}: δεν επιτρέπεται αρνητική τιμή. Έλεγξε το πεδίο.")

def _check_load_weights(ld: schemas.ReceiptLoadCreate, net, row: int):
    for v, name in ((ld.gross_weight, "1η ζύγιση"), (ld.tare_weight, "2η ζύγιση"), (ld.incoming_container_tare, "Απόβαρο κάδου εισόδου"), (ld.outgoing_container_tare, "Απόβαρο κάδου εξόδου")):
        _nonneg(v, f"Γραμμή {row} - {name}")
    if net is not None and net < 0:
        raise HTTPException(422, f"Γραμμή {row}: τα κιλά παραλαβής βγαίνουν αρνητικά ({net:f} kg). Έλεγξε την 1η και 2η ζύγιση.")

def _compute_aggregate_weighbridge(data: schemas.ReceiptCreate) -> str|None:
    # Container / Καρότσα / μοναδικό μικρό σημείο: το συγκεντρωτικό ζυγολόγιο είναι από προεπιλογή ο
    # αριθμός ζυγολογίου του ίδιου του φορτίου, κρίσιμο για τη μελλοντική διασύνδεση με το ERP
    # (Galaxy). Αν ο χρήστης έχει δώσει δικό του αριθμό (και σε μοναδικό σημείο), ισχύει αυτός. Σε
    # πολλαπλά μικρά σημεία (ένα φορτηγό, πολλές εντολές) είναι πάντα χειροκίνητο.
    manual = (data.aggregate_weighbridge_number or '').strip() or None
    if len(data.loads) == 1:
        return manual or data.loads[0].weighbridge_number
    return manual


def _receipt_out(db: Session, trip: InboundTrip, loads=None):
    if loads is None:
        loads = db.scalars(select(models.InboundLoad).where(models.InboundLoad.trip_id==trip.id).order_by(InboundLoad.load_sequence)).all()
    return schemas.ReceiptOut(
        id=trip.id, receipt_number=trip.receipt_number, receipt_type=trip.receipt_type,
        receipt_date=trip.receipt_date, carrier_id=trip.carrier_id, driver_name=trip.driver_name,
        vehicle_registration=trip.vehicle_registration, status=trip.status, notes=trip.notes,
        aggregate_weighbridge_number=trip.aggregate_weighbridge_number, deleted_at=trip.deleted_at,
        loads=[schemas.ReceiptLoadOut.model_validate(x) for x in loads]
    )

def _receipts_out_bulk(db: Session, trips: list[InboundTrip]):
    """Same shape as calling _receipt_out() per trip, but fetches every trip's loads in one query
    instead of one SELECT per trip -- list_receipts()/receipt_archive() used to pay N+1 round-trips
    (one per historical receipt, growing forever as more get recorded), which was the single biggest
    contributor to Παραλαβές's load time."""
    trip_ids = [t.id for t in trips]
    loads_by_trip: dict[str, list] = {}
    if trip_ids:
        all_loads = db.scalars(select(models.InboundLoad).where(models.InboundLoad.trip_id.in_(trip_ids)).order_by(InboundLoad.trip_id, InboundLoad.load_sequence)).all()
        for ld in all_loads:
            loads_by_trip.setdefault(ld.trip_id, []).append(ld)
    return [_receipt_out(db, t, loads_by_trip.get(t.id, [])) for t in trips]

def _container_public(x: ContainerAsset):
    display=x.container_number
    if x.notes and "REGISTRY_CODE=" in x.notes:
        display=x.notes.split("REGISTRY_CODE=",1)[1].split("\n",1)[0].strip()
    return schemas.ContainerOut(id=x.id,container_number=display,owner_organization_id=x.owner_organization_id, tare_weight=x.tare_weight,notes=x.notes,status=x.status,active=x.active)



def _ensure_container_registry(db: Session):
    """Ensure every row from the supplied carrier/container register exists as real Master Data."""
    import json
    from pathlib import Path
    data_path=Path(__file__).resolve().parent / "data" / "container_registry.json"
    if not data_path.exists():
        return []
    rows=json.loads(data_path.read_text(encoding="utf-8"))
    # This used to re-run ~600 SELECT/UPSERT round-trips on every single GET call (3+
    # seconds, and it queued every other request behind it). Re-run the full upsert loop
    # only once per revision; otherwise just read back what's already there.
    revision=f"container_registry_v1_{len(rows)}"
    marker=db.scalar(select(models.AppSetting).where(models.AppSetting.key=='data.container_registry.import_revision'))
    if marker and marker.value==revision:
        existing=db.execute(
            select(models.ContainerAsset,models.Organization)
            .join(models.Organization,models.Organization.id==models.ContainerAsset.owner_organization_id)
            .where(models.ContainerAsset.notes.like('REGISTRY_CODE=%'))
            .order_by(models.ContainerAsset.container_number)
        ).all()
        return [{"id":asset.id,"carrier_id":org.id,"carrier":org.legal_name,"code":(asset.notes or '').split('REGISTRY_CODE=',1)[-1],"tare_weight":float(asset.tare_weight or 0)} for asset,org in existing]
    out=[]
    for row in rows:
        carrier=str(row.get("carrier","")).strip(); code=str(row.get("code","")).strip()
        if not carrier or not code: continue
        org=db.scalar(select(models.Organization).where(models.Organization.legal_name==carrier))
        if not org:
            org=models.Organization(legal_name=carrier,trade_name=carrier,active=True); db.add(org); db.flush()
        role_exists=db.execute(select(models.organization_roles.c.organization_id).where(models.organization_roles.c.organization_id==org.id,models.organization_roles.c.role=="CARRIER")).first()
        if not role_exists:
            db.execute(models.organization_roles.insert().values(organization_id=org.id,role="CARRIER"))
        stored=f"{org.id[:8]}::{code}"
        asset=db.scalar(select(models.ContainerAsset).where(models.ContainerAsset.container_number==stored))
        if not asset:
            asset=models.ContainerAsset(container_number=stored,owner_organization_id=org.id,tare_weight=row.get("tare_kg") or 0,status="AVAILABLE",active=True,notes=f"REGISTRY_CODE={code}")
            db.add(asset); db.flush()
        else:
            asset.owner_organization_id=org.id; asset.tare_weight=row.get("tare_kg") or 0; asset.active=True; asset.notes=f"REGISTRY_CODE={code}"
        out.append({"id":asset.id,"carrier_id":org.id,"carrier":carrier,"code":code,"tare_weight":float(asset.tare_weight or 0)})
    if marker: marker.value=revision
    else: db.add(models.AppSetting(key='data.container_registry.import_revision',value=revision))
    db.commit()
    return out

@app.get("/master/container-registry")
def container_registry(carrier_id:str|None=Query(default=None), db:Session=Depends(get_db), user=Depends(require_permission("master.view"))):
    rows=_ensure_container_registry(db)
    if carrier_id:
        rows=[r for r in rows if r["carrier_id"]==carrier_id]
    return rows

@app.get("/master/containers", response_model=list[schemas.ContainerOut])
def list_containers(include_inactive:bool=Query(default=False), db:Session=Depends(get_db), user=Depends(require_permission("master.view"))):
    stmt=select(ContainerAsset)
    if not include_inactive: stmt=stmt.where(ContainerAsset.active==True)
    rows=db.scalars(stmt.order_by(ContainerAsset.owner_organization_id,ContainerAsset.container_number)).all()
    return [_container_public(x) for x in rows]

@app.post("/master/containers", response_model=schemas.ContainerOut)
def create_container(data:schemas.ContainerCreate, db:Session=Depends(get_db), user:User=Depends(require_permission("master.edit"))):
    if db.scalar(select(ContainerAsset).where(ContainerAsset.container_number==data.container_number)):
        raise HTTPException(409,"Ο αριθμός container υπάρχει ήδη")
    obj=ContainerAsset(**data.model_dump()); db.add(obj); db.flush()
    write_audit(db,user,"container",obj.id,"CREATE",new=data.model_dump())
    db.commit(); db.refresh(obj); return obj

@app.get("/receipts", response_model=list[schemas.ReceiptOut])
def list_receipts(db:Session=Depends(get_db), user=Depends(require_permission("receipt.view"))):
    trips=db.scalars(select(InboundTrip).where(InboundTrip.deleted_at.is_(None)).order_by(InboundTrip.receipt_date.desc())).all()
    return _receipts_out_bulk(db,trips)

@app.get("/receipts/{receipt_id}", response_model=schemas.ReceiptOut)
def get_receipt(receipt_id:str, db:Session=Depends(get_db), user=Depends(require_permission("receipt.view"))):
    trip=db.get(InboundTrip,receipt_id)
    if not trip: raise HTTPException(404,"Η παραλαβή δεν βρέθηκε")
    return _receipt_out(db,trip)

def _notes_dpp(notes:str|None):
    import re, json
    txt=str(notes or '')
    m=re.search(r'(?:DPP|ΔΠΠ)\s*[=:]\s*(\d+)',txt,re.I)
    if m: return int(m.group(1))
    if txt.startswith('__EXTRA__'):
        try:
            first=txt.split('\n',1)[0].replace('__EXTRA__','',1)
            return int(json.loads(first).get('dppNo') or 0) or None
        except Exception:
            pass
    return None

def _next_dpp_numbers(db:Session, year:int, count:int=1, exclude_load_ids:set[str]|None=None):
    exclude_load_ids=exclude_load_ids or set()
    rows=db.execute(select(models.InboundLoad.dpp_number,models.InboundLoad.id,models.InboundTrip.receipt_date).join(models.InboundTrip,models.InboundTrip.id==models.InboundLoad.trip_id).where(models.InboundLoad.dpp_number.is_not(None),models.InboundTrip.deleted_at.is_(None))).all()
    vals=[int(n) for n,lid,dt in rows if lid not in exclude_load_ids and dt and dt.year==year and n is not None]
    start=max(vals)+1 if vals else 1
    return list(range(start,start+count))

def _backfill_dpp_numbers(db:Session):
    changed=False
    trips=db.scalars(select(models.InboundTrip)).all()
    for t in trips:
        loads=db.scalars(select(models.InboundLoad).where(models.InboundLoad.trip_id==t.id).order_by(models.InboundLoad.load_sequence)).all()
        if len(loads)==1 and loads[0].dpp_number is None:
            n=_notes_dpp(t.notes)
            if n:
                loads[0].dpp_number=n; changed=True
    if changed: db.commit()

@app.get('/receipts/dpp/next')
def next_dpp_preview(report_year:int=Query(...,ge=2000,le=2200),count:int=Query(default=1,ge=1,le=100),db:Session=Depends(get_db),user=Depends(require_permission('receipt.view'))):
    return {'year':report_year,'numbers':_next_dpp_numbers(db,report_year,count)}

@app.post("/receipts", response_model=schemas.ReceiptOut)
def create_receipt(data:schemas.ReceiptCreate, db:Session=Depends(get_db), user:User=Depends(require_permission("receipt.create"))):
    if data.receipt_type not in RECEIPT_TYPES: raise HTTPException(422,"Μη έγκυρος τύπος παραλαβής")
    for load in data.loads:
        for w in (load.gross_weight, load.tare_weight):
            if w is not None and Decimal(w) != Decimal(w).to_integral_value():
                raise HTTPException(422,"Η 1η και 2η ζύγιση καταχωρούνται σε ακέραια κιλά")
    if not data.loads: raise HTTPException(422,"Η παραλαβή πρέπει να περιέχει τουλάχιστον ένα φορτίο")
    if data.receipt_type != "SMALL_POINTS" and len(data.loads)!=1:
        raise HTTPException(422,"Container και κουρτίνα έχουν ένα φορτίο ανά παραλαβή")
    trip=InboundTrip(receipt_number=_receipt_number(db,data.receipt_date),receipt_type=data.receipt_type,
        receipt_date=data.receipt_date,carrier_id=data.carrier_id,driver_name=data.driver_name,
        vehicle_registration=data.vehicle_registration,status="DRAFT",created_by=user.id,notes=data.notes,
        aggregate_weighbridge_number=_compute_aggregate_weighbridge(data))
    db.add(trip); db.flush()
    auto_dpps=_next_dpp_numbers(db,data.receipt_date.year,len(data.loads))
    for i,ld in enumerate(data.loads,1):
        if not db.get(Organization,ld.supplier_id): raise HTTPException(422,f"Άγνωστος προμηθευτής στη γραμμή {i}")
        outgoing=db.get(ContainerAsset,ld.outgoing_container_id) if ld.outgoing_container_id else None
        if data.receipt_type=="CONTAINER":
            if not ld.incoming_container_number: raise HTTPException(422,"Απαιτείται αριθμός εισερχόμενου container")
            if ld.incoming_container_tare is None: raise HTTPException(422,"Απαιτείται απόβαρο εισερχόμενου container")
            if not outgoing and ld.outgoing_container_tare is None: raise HTTPException(422,"Απαιτείται κάδος εξόδου ή Προσαρμοσμένο απόβαρο")
        net=_compute_net(data.receipt_type,ld,outgoing)
        _check_load_weights(ld,net,i)
        obj=InboundLoad(trip_id=trip.id,load_sequence=i,supplier_id=ld.supplier_id,order_number=ld.order_number,
            incoming_container_number=ld.incoming_container_number,incoming_container_tare=ld.incoming_container_tare,
            outgoing_container_id=ld.outgoing_container_id,outgoing_container_tare=(outgoing.tare_weight if outgoing else ld.outgoing_container_tare),gross_weight=ld.gross_weight,tare_weight=ld.tare_weight,
            net_weight=net,status="DRAFT",notes=ld.notes,dpp_number=(ld.dpp_number or auto_dpps[i-1]),
            weighbridge_number=ld.weighbridge_number,dispatch_note_number=ld.dispatch_note_number,seal_number=ld.seal_number)
        db.add(obj)
    db.flush()
    created_loads=db.scalars(select(models.InboundLoad).where(models.InboundLoad.trip_id==trip.id)).all()
    complete=bool(created_loads) and all(l.net_weight is not None and l.net_weight>0 and (data.receipt_type!='SMALL_POINTS' or bool(l.order_number)) for l in created_loads)
    if complete:
        now=datetime.now(timezone.utc); trip.status='READY_FOR_SORTING'
        for l in created_loads: l.status='READY_FOR_SORTING'; l.ready_for_sorting_at=now
    write_audit(db,user,"receipt",trip.id,"CREATE",new={"receipt_number":trip.receipt_number,"type":trip.receipt_type,"loads":len(data.loads),"sorting_available":complete})
    _sync_receipt_visitor(db,trip,user)
    db.commit(); db.refresh(trip); return _receipt_out(db,trip)

@app.put("/receipts/{receipt_id}", response_model=schemas.ReceiptOut)
def update_receipt(receipt_id:str, data:schemas.ReceiptCreate, db:Session=Depends(get_db), user:User=Depends(require_permission("receipt.edit"))):
    trip=db.get(InboundTrip,receipt_id)
    if not trip: raise HTTPException(404,"Η παραλαβή δεν βρέθηκε")
    sessions=db.scalars(select(models.SortingSession).join(InboundLoad,models.SortingSession.inbound_load_id==InboundLoad.id).where(InboundLoad.trip_id==receipt_id)).all()
    if any(x.status not in ("NOT_STARTED",) for x in sessions):
        raise HTTPException(409,"Η ταξινόμηση έχει ξεκινήσει. Η παραλαβή δεν μπορεί πλέον να τροποποιηθεί από αυτή την καρτέλα.")
    if data.receipt_type not in RECEIPT_TYPES: raise HTTPException(422,"Μη έγκυρος τύπος παραλαβής")
    for load in data.loads:
        for w in (load.gross_weight, load.tare_weight):
            if w is not None and Decimal(w) != Decimal(w).to_integral_value():
                raise HTTPException(422,"Η 1η και 2η ζύγιση καταχωρούνται σε ακέραια κιλά")
    if not data.loads: raise HTTPException(422,"Η παραλαβή πρέπει να περιέχει τουλάχιστον ένα φορτίο")
    if data.receipt_type != "SMALL_POINTS" and len(data.loads)!=1: raise HTTPException(422,"Container και κουρτίνα έχουν ένα φορτίο ανά παραλαβή")
    old={"receipt_type":trip.receipt_type,"receipt_date":trip.receipt_date.isoformat(),"carrier_id":trip.carrier_id,"driver_name":trip.driver_name,"vehicle_registration":trip.vehicle_registration,"notes":trip.notes}
    trip.receipt_type=data.receipt_type; trip.receipt_date=data.receipt_date; trip.carrier_id=data.carrier_id; trip.driver_name=data.driver_name; trip.vehicle_registration=data.vehicle_registration; trip.notes=data.notes
    trip.aggregate_weighbridge_number=_compute_aggregate_weighbridge(data)
    existing=db.scalars(select(InboundLoad).where(InboundLoad.trip_id==receipt_id).order_by(InboundLoad.load_sequence)).all()
    old_dpp_by_order={x.order_number:x.dpp_number for x in existing if x.order_number and x.dpp_number}
    old_dpp_by_seq={x.load_sequence:x.dpp_number for x in existing if x.dpp_number}
    old_ids={x.id for x in existing}
    for x in existing: db.delete(x)
    db.flush()
    auto_pool=_next_dpp_numbers(db,data.receipt_date.year,len(data.loads),exclude_load_ids=old_ids)
    auto_i=0
    for i,ld in enumerate(data.loads,1):
        if not db.get(Organization,ld.supplier_id): raise HTTPException(422,f"Άγνωστος προμηθευτής στη γραμμή {i}")
        outgoing=db.get(ContainerAsset,ld.outgoing_container_id) if ld.outgoing_container_id else None
        if data.receipt_type=="CONTAINER":
            if not ld.incoming_container_number: raise HTTPException(422,"Απαιτείται αριθμός εισερχόμενου container")
            if ld.incoming_container_tare is None: raise HTTPException(422,"Απαιτείται απόβαρο εισερχόμενου container")
            if not outgoing and ld.outgoing_container_tare is None: raise HTTPException(422,"Απαιτείται κάδος εξόδου ή Προσαρμοσμένο απόβαρο")
        net=_compute_net(data.receipt_type,ld,outgoing)
        _check_load_weights(ld,net,i)
        keep_dpp=ld.dpp_number or old_dpp_by_order.get(ld.order_number) or old_dpp_by_seq.get(i)
        if not keep_dpp:
            keep_dpp=auto_pool[auto_i]; auto_i+=1
        db.add(InboundLoad(trip_id=trip.id,load_sequence=i,supplier_id=ld.supplier_id,order_number=ld.order_number,incoming_container_number=ld.incoming_container_number,incoming_container_tare=ld.incoming_container_tare,outgoing_container_id=ld.outgoing_container_id,outgoing_container_tare=(outgoing.tare_weight if outgoing else ld.outgoing_container_tare),gross_weight=ld.gross_weight,tare_weight=ld.tare_weight,net_weight=net,status="READY_FOR_SORTING" if trip.status=="READY_FOR_SORTING" else "DRAFT",ready_for_sorting_at=datetime.now(timezone.utc) if trip.status=="READY_FOR_SORTING" else None,notes=ld.notes,dpp_number=keep_dpp,weighbridge_number=ld.weighbridge_number,dispatch_note_number=ld.dispatch_note_number,seal_number=ld.seal_number))
    write_audit(db,user,"receipt",trip.id,"UPDATE",old=old,new={"type":data.receipt_type,"loads":len(data.loads)}); _sync_receipt_visitor(db,trip,user); db.commit(); db.refresh(trip); return _receipt_out(db,trip)


@app.delete("/receipts/{receipt_id}")
def delete_receipt(receipt_id:str, db:Session=Depends(get_db), user:User=Depends(require_permission("receipt.edit"))):
    trip=db.get(InboundTrip,receipt_id)
    if not trip: raise HTTPException(404,"Η παραλαβή δεν βρέθηκε")
    trip.deleted_at=datetime.now(timezone.utc)
    # Το απόθεμα της διαγραμμένης παραλαβής δεν υπολογίζεται πουθενά (ό,τι έχει ήδη καταναλωθεί στην παραγωγή μένει ως έχει)
    for lot in db.scalars(select(WEEEStockLot).join(InboundLoad,InboundLoad.id==WEEEStockLot.inbound_load_id).where(InboundLoad.trip_id==receipt_id)).all(): _retire_lot(db,lot)
    write_audit(db,user,"receipt",receipt_id,"SOFT_DELETE",old={"receipt_number":trip.receipt_number},new={"deleted":True})
    db.commit(); return {"status":"archived","id":receipt_id}

@app.get("/receipts-archive", response_model=list[schemas.ReceiptOut])
def receipt_archive(db:Session=Depends(get_db), user=Depends(require_permission("receipt.view"))):
    trips=db.scalars(select(InboundTrip).where(InboundTrip.deleted_at.is_not(None)).order_by(InboundTrip.receipt_date.desc())).all()
    return _receipts_out_bulk(db,trips)

@app.post("/receipts/{receipt_id}/restore")
def restore_receipt(receipt_id:str, db:Session=Depends(get_db), user:User=Depends(require_permission("receipt.edit"))):
    trip=db.get(InboundTrip,receipt_id)
    if not trip: raise HTTPException(404,"Η παραλαβή δεν βρέθηκε")
    # Οι διαγραμμένες παραλαβές δεν δεσμεύουν αριθμούς ΔΠΠ -- αν κάποιος αριθμός της έχει δοθεί στο μεταξύ
    # σε άλλη παραλαβή, παίρνει νέο (επόμενο) αριθμό ώστε να μην υπάρχουν διπλοί.
    trip.deleted_at=None; db.flush()
    loads=db.scalars(select(InboundLoad).where(InboundLoad.trip_id==receipt_id).order_by(InboundLoad.load_sequence)).all()
    for l in loads:
        if l.dpp_number is None: continue
        year=trip.receipt_date.year
        clash=db.scalar(select(InboundLoad.id).join(InboundTrip,InboundTrip.id==InboundLoad.trip_id).where(InboundLoad.dpp_number==l.dpp_number,InboundLoad.trip_id!=receipt_id,InboundTrip.deleted_at.is_(None),InboundTrip.receipt_date>=datetime(year,1,1),InboundTrip.receipt_date<datetime(year+1,1,1)).limit(1))
        if clash: l.dpp_number=_next_dpp_numbers(db,year,1,exclude_load_ids={l.id})[0]; db.flush()
    trip.deleted_at=None
    for e in db.scalars(select(SortingEntry).join(SortingSession,SortingSession.id==SortingEntry.session_id).join(InboundLoad,InboundLoad.id==SortingSession.inbound_load_id).where(InboundLoad.trip_id==receipt_id)).all(): _sync_entry_stock(db,e,user)
    write_audit(db,user,"receipt",receipt_id,"RESTORE",new={"deleted":False}); db.commit()
    return {"status":"restored","id":receipt_id}

@app.post("/receipts/{receipt_id}/ready-for-sorting", response_model=schemas.ReceiptStatusOut)
def ready_for_sorting(receipt_id:str, db:Session=Depends(get_db), user:User=Depends(require_permission("receipt.edit"))):
    trip=db.get(InboundTrip,receipt_id)
    if not trip: raise HTTPException(404,"Η παραλαβή δεν βρέθηκε")
    loads=db.scalars(select(InboundLoad).where(InboundLoad.trip_id==receipt_id)).all()
    problems=[]
    for l in loads:
        if l.net_weight is None: problems.append(f"Φορτίο {l.load_sequence}: λείπει ολοκληρωμένη ζύγιση")
        if l.net_weight is not None and l.net_weight <= 0: problems.append(f"Φορτίο {l.load_sequence}: μη έγκυρο καθαρό βάρος")
        if trip.receipt_type=="SMALL_POINTS" and not l.order_number: problems.append(f"Φορτίο {l.load_sequence}: λείπει αριθμός εντολής")
    if problems: raise HTTPException(422,detail=problems)
    now=datetime.now(timezone.utc)
    for l in loads: l.status="READY_FOR_SORTING"; l.ready_for_sorting_at=now
    trip.status="READY_FOR_SORTING"
    write_audit(db,user,"receipt",trip.id,"READY_FOR_SORTING",new={"loads":len(loads),"at":now.isoformat()})
    db.commit()
    return schemas.ReceiptStatusOut(id=trip.id,receipt_number=trip.receipt_number,status=trip.status,loads_ready=len(loads),loads_total=len(loads))

# Lightweight Windows workspace for Build 0.2. The production desktop client can later consume the same API.
static_dir = Path(__file__).parent / "static"
@app.get("/")
def windows_workspace():
    return FileResponse(static_dir / "desktop_v11.html", headers={"Cache-Control":"no-store, no-cache, must-revalidate, max-age=0","Pragma":"no-cache","Expires":"0","X-WEEE-Build":"2.5.35"})

@app.get("/desktop")
def desktop_workspace():
    return FileResponse(static_dir / "desktop_v11.html", headers={"Cache-Control":"no-store, no-cache, must-revalidate, max-age=0","Pragma":"no-cache","Expires":"0","X-WEEE-Build":"2.5.35"})

# ---- Builds 0.3-0.5: Android Sorting + Logistics Review + MVP workflow ----
from fastapi import UploadFile, File, Form
from fastapi.responses import FileResponse as _FileResponse
from fastapi.responses import StreamingResponse as _StreamingResponse

@app.get("/events")
async def change_events(request:Request, token:str=Query(...)):
    """Ροή αλλαγών (EventSource δεν στέλνει headers -> το token στο query). Μήνυμα: JSON λίστα θεμάτων που άλλαξαν."""
    import jwt as _jwt
    try: _claims=_jwt.decode(token, settings.jwt_secret, algorithms=["HS256"])
    except Exception: raise HTTPException(401,"Μη έγκυρη σύνδεση")
    _exp=float(_claims.get("exp") or 0)
    async def gen():
        q=asyncio.Queue(); _event_subs.add(q)
        try:
            yield "retry: 2000\n\n: ok\n\n"
            while True:
                if _exp and datetime.now(timezone.utc).timestamp()>=_exp-30:
                    yield "event: expired\ndata: {}\n\n"; break     # η οθόνη παίρνει νέο token (/auth/refresh) και ξανασυνδέεται
                try: first=await asyncio.wait_for(q.get(),timeout=15)
                except asyncio.TimeoutError:
                    if await request.is_disconnected(): break
                    yield ": ka\n\n"; continue
                await asyncio.sleep(0.15)                       # συγκέντρωση πολλών αλλαγών μαζί
                topics={first}
                while not q.empty(): topics.add(q.get_nowait())
                yield "data: "+json.dumps(sorted(topics))+"\n\n"
        finally: _event_subs.discard(q)
    return _StreamingResponse(gen(), media_type="text/event-stream", headers={"Cache-Control":"no-cache","X-Accel-Buffering":"no"})
from datetime import date, timedelta
from uuid import uuid4
import shutil
from .models import SortingSession, SortingEntry, SortingAdjustment, FileAttachment

UPLOAD_DIR = Path(__file__).parent.parent / "uploads"
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)


def _session_for_load(db: Session, load_id: str, create: bool=False, user: User|None=None):
    load=db.get(InboundLoad,load_id)
    if not load: raise HTTPException(404,"Το φορτίο δεν βρέθηκε")
    ses=db.scalar(select(SortingSession).where(SortingSession.inbound_load_id==load_id))
    if not ses and create:
        if load.status!="READY_FOR_SORTING": raise HTTPException(409,"Το φορτίο δεν είναι έτοιμο για ταξινόμηση")
        ses=SortingSession(inbound_load_id=load_id,status="IN_PROGRESS",started_at=datetime.now(timezone.utc),started_by=user.id if user else None)
        db.add(ses); db.flush(); load.status="SORTING_IN_PROGRESS"
    return load,ses


def _sorting_payload(db: Session, load: InboundLoad, ses: SortingSession):
    entries=db.scalars(select(SortingEntry).where(SortingEntry.session_id==ses.id).order_by(SortingEntry.created_at.desc())).all()
    total=sum((e.approved_weight if e.approved_weight is not None else e.raw_weight or Decimal('0')) for e in entries)
    diff=(total-load.net_weight) if load.net_weight is not None else None
    return schemas.SortingSessionOut(id=ses.id,inbound_load_id=load.id,status=ses.status,net_weight=load.net_weight,
        sorting_weight=total,difference=diff,requires_management_approval=ses.requires_management_approval,
        entries=[schemas.SortingEntryOut.model_validate(e) for e in entries])

@app.get('/inventory/weee/media-content')
def weee_media_content(db:Session=Depends(get_db), user=Depends(require_permission('sorting.review'))):
    """Μόνο ανάγνωση: ανά κατηγορία ΑΗΗΕ, ποια μέσα συλλογής περιέχουν ήδη υλικό και πόσα kg (διαθέσιμο υπόλοιπο στα lots)."""
    rows=db.execute(select(WEEEStockLot.weee_category_id,WEEEStockLot.collection_medium_id,func.sum(WEEEStockLot.available_weight))
        .where(WEEEStockLot.available_weight>0,WEEEStockLot.collection_medium_id.is_not(None)).group_by(WEEEStockLot.weee_category_id,WEEEStockLot.collection_medium_id)).all()
    out={}
    for cat,med,kg in rows:
        out.setdefault(cat,[]).append({'medium_id':med,'kg':float(kg or 0)})
    for v in out.values(): v.sort(key=lambda x:-x['kg'])
    return out

@app.get('/sorting/available')
def sorting_available(db:Session=Depends(get_db), user=Depends(require_permission('sorting.perform'))):
    rows=db.scalars(select(InboundLoad).where(InboundLoad.status.in_(['READY_FOR_SORTING','SORTING_IN_PROGRESS'])).order_by(InboundLoad.ready_for_sorting_at)).all()
    out=[]
    for l in rows:
        # Session state is authoritative for operator visibility. Once submitted,
        # the load must disappear even if a stale InboundLoad status remains.
        ses=db.scalar(select(SortingSession).where(SortingSession.inbound_load_id==l.id))
        if ses is not None and ses.status != 'IN_PROGRESS':
            continue
        trip=db.get(InboundTrip,l.trip_id); sup=db.get(Organization,l.supplier_id)
        if trip.deleted_at is not None: continue  # deleted receipts must not be offered for sorting
        out.append({'load_id':l.id,'receipt_id':trip.id,'receipt_number':trip.receipt_number,'receipt_type':trip.receipt_type,
          'receipt_date':trip.receipt_date.isoformat(),'supplier':sup.trade_name or sup.legal_name,'carrier_id':trip.carrier_id,'carrier':((lambda c:(c.trade_name or c.legal_name) if c else '')(db.get(Organization,trip.carrier_id) if trip.carrier_id else None)),
          'order_number':l.order_number,'dpp_number':l.dpp_number,'container_number':l.incoming_container_number,'net_weight':float(l.net_weight or 0),'status':l.status})
    return out

@app.post('/sorting/{load_id}/start', response_model=schemas.SortingStartOut)
def sorting_start(load_id:str, db:Session=Depends(get_db), user:User=Depends(require_permission('sorting.perform'))):
    load,ses=_session_for_load(db,load_id,True,user)
    write_audit(db,user,'sorting_session',ses.id,'START',new={'load_id':load_id}); db.commit()
    return schemas.SortingStartOut(id=ses.id,inbound_load_id=load.id,status=ses.status)

@app.get('/sorting/review-queue')
def sorting_review_queue(db:Session=Depends(get_db), user=Depends(require_permission('sorting.review'))):
    # Windows history/review must show every real inbound load, not only submitted sessions.
    # This keeps legacy/older orders visible regardless of their current workflow stage.
    # One joined query instead of ~4 db.get() calls per load: at real data scale (1000+
    # loads) the old N+1 version took several seconds and made the Sorting tab look empty
    # while it was still loading. See weee_dashboard() above for the same pattern.
    CarrierOrg=aliased(Organization)
    rows=db.execute(
        select(InboundLoad,InboundTrip,SortingSession,Organization,CarrierOrg)
        .join(InboundTrip,InboundLoad.trip_id==InboundTrip.id)
        .outerjoin(SortingSession,SortingSession.inbound_load_id==InboundLoad.id)
        .outerjoin(Organization,Organization.id==InboundLoad.supplier_id)
        .outerjoin(CarrierOrg,CarrierOrg.id==InboundTrip.carrier_id)
        .where(InboundTrip.deleted_at.is_(None))
        .order_by(InboundLoad.created_at.desc())
    ).all()
    entry_counts={}
    for sid in db.scalars(select(SortingEntry.session_id)).all(): entry_counts[sid]=entry_counts.get(sid,0)+1
    out=[]
    for load,trip,ses,sup,carrier in rows:
        effective_status=(ses.status if ses else load.status) or trip.status or 'DRAFT'
        if effective_status=='IN_PROGRESS': effective_status='SORTING_IN_PROGRESS'
        # Opening a load starts its session, but it only counts as "in sorting" once at least one entry exists.
        if effective_status=='SORTING_IN_PROGRESS' and not (ses and entry_counts.get(ses.id)): effective_status='READY_FOR_SORTING'
        # «Προς Διόρθωση»: προσωρινή κατάσταση όσο γίνονται διορθώσεις στον έλεγχο (Windows), μέχρι την Ολοκλήρωση
        if ses and ses.correction and effective_status in ('LOGISTICS_REVIEW','MANAGEMENT_REVIEW','SORTING_CONFIRMED'): effective_status='CORRECTION'
        out.append({'load_id':load.id,'session_id':ses.id if ses else None,'status':effective_status,'receipt_id':trip.id,'receipt_number':trip.receipt_number,
          'receipt_type':trip.receipt_type,'receipt_date':trip.receipt_date.isoformat(),'supplier':(sup.trade_name or sup.legal_name) if sup else '', 'carrier':((carrier.trade_name or carrier.legal_name) if carrier else ''),
          'order_number':load.order_number,'dpp_number':load.dpp_number,'container_number':load.incoming_container_number,'net_weight':float(load.net_weight or 0),
          'time_known':('\"sourceTimeKnown\":false' not in (trip.notes or '').replace(' ','')),
          'sorting_confirmed_at':ses.sorting_confirmed_at.isoformat() if ses and ses.sorting_confirmed_at else None})
    return out

@app.get('/sorting/month-report')
def sorting_month_report(month:str=Query(pattern=r'^\d{4}-\d{2}$'), db:Session=Depends(get_db), user=Depends(require_permission('sorting.review'))):
    y,m=map(int,month.split('-')); start=datetime(y,m,1); end=datetime(y+1,1,1) if m==12 else datetime(y,m+1,1)
    q=(select(InboundTrip,InboundLoad,SortingSession,SortingEntry,WEEECategory,Organization)
       .join(InboundLoad,InboundLoad.trip_id==InboundTrip.id)
       .join(SortingSession,SortingSession.inbound_load_id==InboundLoad.id)
       .join(SortingEntry,SortingEntry.session_id==SortingSession.id)
       .join(WEEECategory,WEEECategory.id==SortingEntry.weee_category_id)
       .join(Organization,Organization.id==InboundLoad.supplier_id)
       .where(InboundTrip.receipt_date>=start,InboundTrip.receipt_date<end,InboundTrip.deleted_at.is_(None))
       .order_by(InboundTrip.receipt_date,InboundLoad.order_number,WEEECategory.code))
    days={}
    for trip,load,ses,e,cat,sup in db.execute(q).all():
        day=trip.receipt_date.date().isoformat(); d=days.setdefault(day,{'date':day,'loads':{}})
        lk=load.id; l=d['loads'].setdefault(lk,{'load_id':lk,'order_number':load.order_number or trip.receipt_number,'supplier':sup.trade_name or sup.legal_name,'net_weight':float(load.net_weight or 0),'codes':{}})
        code=cat.parent_code if cat.is_internal_subcategory and cat.parent_code else cat.code
        w=float(e.approved_weight if e.approved_weight is not None else (e.raw_weight or 0)); l['codes'][code]=l['codes'].get(code,0)+w
    out=[]; month_totals={}
    for day in sorted(days):
        loads=list(days[day]['loads'].values()); dt={}
        for l in loads:
            for c,w in l['codes'].items(): dt[c]=dt.get(c,0)+w; month_totals[c]=month_totals.get(c,0)+w
        out.append({'date':day,'loads':loads,'totals':dt})
    return {'month':month,'days':out,'totals':month_totals}

# ---- Μέσα συλλογής στην Ταξινόμηση: ΕΝΑ κοινό φίλτρο (Windows + Android) ----
# Στην Ταξινόμηση ο εργαζόμενος επιλέγει μέσο για υλικό που ΕΙΣΕΡΧΕΤΑΙ: μόνο είδη με Χρήση «Εισερχόμενο» ή «Και τα δύο» (ΟΧΙ «Εξερχόμενο»),
# και μόνο μέσα διαθέσιμα: κατάσταση AVAILABLE (άδειο) ή WEEE_STORAGE (κρατά απόθεμα που μπορεί να συνεχιστεί). IN_PRODUCTION / READY_STORAGE / κάθε άλλη
# κατάσταση (σε παραγωγή, έτοιμο υλικό, δεσμευμένο…) δεν εμφανίζεται. Από το παράθυρο ταξινόμησης δημιουργούνται μόνο Παλέτα / Σάκος 1kg (+Χύμα ως επιλογή).
SORTING_MEDIUM_STATUSES=('AVAILABLE','WEEE_STORAGE')
SORTING_CREATABLE_TYPES=('PALLET','MATERIAL_PALLET','SACK_1KG','SACK_2KG_UN')
def _sorting_medium_types(db:Session)->list:
    return [t for t in db.scalars(select(CollectionMediumType).where(CollectionMediumType.active==True).order_by(CollectionMediumType.name_el)).all() if (t.usage or 'BOTH') in ('IN','BOTH')]
def _sorting_media(db:Session,type_ids)->list:
    ids=list(type_ids)
    if not ids: return []
    return db.scalars(select(CollectionMedium).where(CollectionMedium.active==True,CollectionMedium.type_id.in_(ids),CollectionMedium.is_closed==False,CollectionMedium.status.in_(SORTING_MEDIUM_STATUSES)).order_by(CollectionMedium.code)).all()

@app.get('/sorting/medium-options')
def sorting_medium_options(db:Session=Depends(get_db), user=Depends(require_permission('sorting.perform'))):
    """Τα είδη και τα μέσα που προσφέρονται στην Ταξινόμηση (κοινό φίλτρο για Windows και Android)."""
    types=_sorting_medium_types(db)
    media=_sorting_media(db,[t.id for t in types])
    # τρέχοντα κιλά ανά μέσο (και ανά κατηγορία ΑΗΗΕ) από τα διαθέσιμα lots· μέσο χωρίς εγγραφή = άδειο
    mkg={}; mcat={}
    for med,cat,k in db.execute(select(WEEEStockLot.collection_medium_id,WEEEStockLot.weee_category_id,func.sum(WEEEStockLot.available_weight)).where(WEEEStockLot.available_weight>0,WEEEStockLot.collection_medium_id.is_not(None)).group_by(WEEEStockLot.collection_medium_id,WEEEStockLot.weee_category_id)).all():
        mkg[med]=mkg.get(med,0.0)+float(k or 0); mcat.setdefault(med,{})[cat]=float(k or 0)
    # μέσα των ίδιων ειδών που ΔΕΝ προσφέρονται (σε χρήση / σε παραγωγή / αποθηκευμένο έτοιμο υλικό…): μόνο για την ένδειξη «σε χρήση (φόρτωση <ημερομηνία>)» όταν γραφτεί ο αριθμός τους
    tids=[t.id for t in types]; since={}
    if tids:
        for med,d in db.execute(select(WEEEStockLot.collection_medium_id,func.max(WEEEStockLot.created_at)).where(WEEEStockLot.collection_medium_id.is_not(None)).group_by(WEEEStockLot.collection_medium_id)).all(): since[med]=d
    busy_rows=db.scalars(select(CollectionMedium).where(CollectionMedium.active==True,CollectionMedium.type_id.in_(tids),CollectionMedium.is_closed==False,CollectionMedium.status.not_in(SORTING_MEDIUM_STATUSES))).all() if tids else []
    busy=[{'type_id':m.type_id,'code':m.code,'status':m.status,'since':((since.get(m.id) or m.updated_at).date().isoformat() if (since.get(m.id) or m.updated_at) else None)} for m in busy_rows]
    return {'busy':busy,'types':[{'id':t.id,'code':t.code,'name_el':t.name_el,'usage':t.usage or 'BOTH','active':bool(t.active),'default_tare_weight':float(t.default_tare_weight) if t.default_tare_weight is not None else None,'tare_fixed':bool(t.tare_fixed),'creatable':t.code in SORTING_CREATABLE_TYPES} for t in types],
            'media':[{'id':m.id,'type_id':m.type_id,'code':m.code,'tare_weight':float(m.tare_weight) if m.tare_weight is not None else None,'status':m.status,'active':bool(m.active),'kg':round(mkg.get(m.id,0.0),3),'cats':mcat.get(m.id,{})} for m in media]}

@app.get('/sorting/overview')
def sorting_overview(start:str=Query(pattern=r'^\d{4}-\d{2}-\d{2}$'), end:str=Query(pattern=r'^\d{4}-\d{2}-\d{2}$'), db:Session=Depends(get_db), user=Depends(require_permission('sorting.review'))):
    """Μόνο ανάγνωση: κιλά ανά επίσημο κωδικό ΑΗΗΕ για κάθε φορτίο με ταξινόμηση στο διάστημα (για την καρτέλα Συγκεντρωτικά)."""
    try:
        d0=datetime.fromisoformat(start); d1=datetime.fromisoformat(end)+timedelta(days=1)
    except ValueError:
        raise HTTPException(422,'Μη έγκυρο διάστημα')
    q=(select(InboundLoad.id,SortingEntry,WEEECategory)
       .join(InboundTrip,InboundLoad.trip_id==InboundTrip.id)
       .join(SortingSession,SortingSession.inbound_load_id==InboundLoad.id)
       .join(SortingEntry,SortingEntry.session_id==SortingSession.id)
       .join(WEEECategory,WEEECategory.id==SortingEntry.weee_category_id)
       .where(InboundTrip.receipt_date>=d0,InboundTrip.receipt_date<d1,InboundTrip.deleted_at.is_(None)))
    out={}
    for lid,e,cat in db.execute(q).all():
        code=cat.parent_code if cat.is_internal_subcategory and cat.parent_code else cat.code
        w=float(e.approved_weight if e.approved_weight is not None else (e.raw_weight or 0))
        d=out.setdefault(lid,{}); d[code]=d.get(code,0)+w
    return {'loads':out}

@app.get('/sorting/{load_id}/detail')
def sorting_detail(load_id:str, db:Session=Depends(get_db), user=Depends(require_permission('sorting.review'))):
    load,ses=_session_for_load(db,load_id,False)
    trip=db.get(InboundTrip,load.trip_id); sup=db.get(Organization,load.supplier_id); carrier=db.get(Organization,trip.carrier_id) if trip.carrier_id else None
    entries=db.scalars(select(SortingEntry).where(SortingEntry.session_id==ses.id).order_by(SortingEntry.created_at.desc())).all() if ses else []
    rows=[]
    for e in entries:
        cat=db.get(WEEECategory,e.weee_category_id); parent=db.scalar(select(WEEECategory).where(WEEECategory.code==cat.parent_code)) if cat and cat.parent_code else None
        med=db.get(CollectionMedium,e.collection_medium_id) if e.collection_medium_id else None
        mt=db.get(CollectionMediumType,med.type_id) if med else None
        rows.append({'id':e.id,'weee_category_id':e.weee_category_id,'collection_medium_id':e.collection_medium_id,'display_name':cat.description_el if cat else '', 'official_code':(parent.code if parent else cat.code) if cat else '',
          'official_description':(parent.description_el if parent else cat.description_el) if cat else '', 'her_description':(parent.her_description if parent else cat.her_description) if cat else '', 'is_internal_subcategory':bool(cat.is_internal_subcategory) if cat else False,
          'medium_type':mt.name_el if mt else None,'medium_code':(str(med.code).replace('I2-','') if med else None),'tare_weight':float(med.tare_weight) if med and med.tare_weight is not None else None,
          'entry_type':e.entry_type,'raw_weight':float(e.raw_weight or 0),'approved_weight':float(e.approved_weight) if e.approved_weight is not None else None,
          'piece_count':e.piece_count,'notes':e.notes,'created_at':e.created_at.isoformat(),'source':e.source})
    photos=db.scalars(select(FileAttachment).where(FileAttachment.entity_type=='INBOUND_LOAD',FileAttachment.entity_id==load.id).order_by(FileAttachment.created_at)).all()
    audits=db.scalars(select(models.AuditEvent).where(models.AuditEvent.entity_type.in_(['sorting_session','sorting_entry'])).order_by(models.AuditEvent.created_at.desc()).limit(100)).all()
    return {'load_id':load.id,'receipt_id':trip.id,'status':(ses.status if ses else load.status),'correction':bool(ses.correction) if ses else False,'receipt_number':trip.receipt_number,'receipt_type':trip.receipt_type,'receipt_date':trip.receipt_date.isoformat(),
      'supplier':(sup.trade_name or sup.legal_name) if sup else '', 'carrier':((carrier.trade_name or carrier.legal_name) if carrier else ''), 'order_number':load.order_number,'net_weight':float(load.net_weight or 0),
      'sorting_weight':sum((r['approved_weight'] if r['approved_weight'] is not None else r['raw_weight']) for r in rows),'entries':rows,
      'dpp_number':load.dpp_number,'foreign_materials':(ses.foreign_materials if ses else None),'foreign_weight':(float(ses.foreign_weight) if ses and ses.foreign_weight is not None else 0),
      'special_waste':(ses.special_waste if ses else None),'special_waste_weight':(float(ses.special_waste_weight) if ses and ses.special_waste_weight is not None else 0),'load_pure':bool(ses.load_pure) if ses else False,'check_special':bool(ses.check_special) if ses else False,'check_kday':bool(ses.check_kday) if ses else False,'check_non_integer':bool(ses.check_non_integer) if ses else False,
      'photos':[{'id':p.id,'filename':p.filename,'category':p.category,'created_at':p.created_at.isoformat()} for p in photos],
      'history':[{'action':a.action,'reason':a.reason,'created_at':a.created_at.isoformat()} for a in audits if a.entity_id in ({ses.id} if ses else set()) | {e.id for e in entries}]}

@app.get('/sorting/daily-export')
def sorting_daily_export(day:str=Query(...,pattern=r'^\d{4}-\d{2}-\d{2}$'), db:Session=Depends(get_db), user=Depends(require_permission('sorting.review'))):
    """Daily workbook: one sorting per worksheet plus final 'Σύνολο Μέρας', matching the imported daily workbook structure."""
    d=datetime.fromisoformat(day); start=datetime(d.year,d.month,d.day)
    return _received_workbook_response(db,start,start+timedelta(days=1),'Σύνολο Μέρας',d.strftime('%d.%m.%Y')+'.xlsx')

def _copy_print_setup(src,dst):
    """copy_worksheet δεν μεταφέρει περιοχή εκτύπωσης, κλίμακα, προβολή σελίδας και διακοπές σελίδας της φόρμας."""
    from copy import copy
    area=src.print_area
    if area: dst.print_area=area.split('!')[-1].replace('$','')
    dst.page_setup=copy(src.page_setup); dst.page_margins=copy(src.page_margins); dst.print_options=copy(src.print_options)
    if src.sheet_properties.pageSetUpPr is not None: dst.sheet_properties.pageSetUpPr=copy(src.sheet_properties.pageSetUpPr)
    dst.sheet_view.view=src.sheet_view.view; dst.sheet_view.zoomScale=src.sheet_view.zoomScale; dst.sheet_view.zoomScaleNormal=src.sheet_view.zoomScaleNormal; dst.sheet_view.zoomScalePageLayoutView=src.sheet_view.zoomScalePageLayoutView
    dst.row_breaks=copy(src.row_breaks); dst.col_breaks=copy(src.col_breaks)

def _received_workbook_response(db:Session, start:datetime, end:datetime, summary_title:str, filename:str):
    from openpyxl import load_workbook
    from copy import copy
    from tempfile import NamedTemporaryFile
    import os
    from starlette.background import BackgroundTask
    loads=db.scalars(select(InboundLoad).join(InboundTrip,InboundLoad.trip_id==InboundTrip.id).where(InboundTrip.receipt_date>=start,InboundTrip.receipt_date<end,InboundTrip.deleted_at.is_(None)).order_by(InboundLoad.dpp_number.is_(None),InboundLoad.dpp_number,InboundTrip.receipt_date,InboundLoad.created_at)).all()
    template=Path(__file__).parent/'templates'/'daily_sorting_report_template.xlsx'
    wb=load_workbook(template)
    # Keep a pristine detail sheet and summary sheet from the imported template.
    detail_src=wb[wb.sheetnames[0]]; summary_src=wb['Σύνολο Μέρας'] if 'Σύνολο Μέρας' in wb.sheetnames else wb[wb.sheetnames[-1]]
    for ws in list(wb.worksheets):
        if ws not in (detail_src,summary_src): wb.remove(ws)
    detail_src.title='__DETAIL_TEMPLATE__'; summary_src.title=summary_title
    def fill(ws,data):
        l,t,ses=data['load'],data['trip'],data['session']; ex=data['extras']; org=lambda o:(o.trade_name or o.legal_name) if o else ''
        ws['B2']=org(data['supplier']);ws['D2']=l.order_number or '';ws['B3']=org(data['carrier']);ws['D3']=l.seal_number or ex.get('sealNo','') or '-';ws['B4']=ex.get('recycler') or 'ΚΕΝΤΡΟ ΕΛΛΗΝΙΚΗΣ ΠΕΡΙΒΑΛΛΟΝΤΙΚΗΣ ΑΝΑΚΥΚΛΩΣΗΣ Α.Β.Ε.Τ.Ε.';ws['B5']=l.incoming_container_number or '-';ws['D5']='ΝΑΙ' if ses and float(ses.foreign_weight or 0)>0 else 'ΌΧΙ';ws['B6']=l.weighbridge_number or ex.get('weighbridgeNo','');ws['D6']=int(round(float(ses.foreign_weight or 0))) if ses else 0;ws['B7']=(t.receipt_date or start).strftime('%d.%m.%Y');ws['D7']='ΝΑΙ' if ses and float(ses.special_waste_weight or 0)>0 else 'ΌΧΙ';ws['B8']=l.dispatch_note_number or ex.get('dispatchNo','');ws['D8']=int(round(float(ses.special_waste_weight or 0))) if ses else 0;ws['B9']=l.dpp_number or '';ws['D9']=t.vehicle_registration or ''
        # Only user-authored observations; never workflow/import status text.
        plain=(ex.get('plainNotes','') or (ses.notes if ses else '') or '')
        import re as _re; plain=_re.sub(r'^Ιστορική εισαγωγή από .*?\.xlsx\s*','',plain,flags=_re.I)
        ws['A10']='Παρατηρήσεις - Σχόλια ανακυκλωτή'+('\n'+plain if plain.strip() else '')
        feed=db.scalar(select(models.ElectrocycleOrder).where(models.ElectrocycleOrder.order_no==(l.order_number or '')).order_by(models.ElectrocycleOrder.source_date.desc()))
        ws['A12']='ΥΠ/ΜΑ: '+((feed.address or '') if feed else '')+'\nΠΟΛΗ: '+((feed.city or '') if feed else '')
        ws['G12']='ΝΑΙ' if ses and ses.check_special else 'ΌΧΙ';ws['I12']='ΝΑΙ' if ses and ses.check_kday else 'ΌΧΙ';ws['L12']='ΝΑΙ' if ses and ses.check_non_integer else 'ΌΧΙ';ws['O12']='ΝΑΙ' if ses and ses.load_pure else 'ΌΧΙ';ws['R12']='ΝΑΙ' if ses and float(ses.foreign_weight or 0)>0 else 'ΌΧΙ'
        for row in range(15,83):
            c=str(ws.cell(row=row,column=4).value or '').strip()
            if c: ws.cell(row=row,column=15).value=int(round(float(data['weights'].get(c,0)))) or None; ws.cell(row=row,column=16).value=int(data['pieces'].get(c,0)) or None
    made=[]
    for i,l in enumerate(loads,1):
        ws=wb.copy_worksheet(detail_src); _copy_print_setup(detail_src,ws); data=_sorting_export_data(db,l.id); fill(ws,data); name=str(l.dpp_number or l.order_number or i)[:31];
        while name in wb.sheetnames: name=(name[:27]+'_'+str(i))[:31]
        ws.title=name; made.append(ws)
    wb.remove(detail_src)
    if (end-start)<=timedelta(days=1): summary_src['B7']=start.strftime('%d.%m.%Y')
    # Rebuild cross-sheet totals from exactly the generated daily sorting sheets.
    detail_names=[ws.title for ws in made]
    def sum_tabs(cell):
        return '=' + '+'.join("'%s'!%s"%(n.replace("'","''"),cell) for n in detail_names) if detail_names else '=0'
    summary_src['D6']=sum_tabs('D6'); summary_src['D8']=sum_tabs('D8')
    for rr in range(15,83):
        summary_src.cell(rr,15).value=sum_tabs(f'O{rr}')
        summary_src.cell(rr,16).value=sum_tabs(f'P{rr}')
    # Summary is always the final tab, like the imported daily workbooks.
    wb._sheets=[ws for ws in wb._sheets if ws is not summary_src]+[summary_src]
    # Excel recalculates on open, including the legacy 6->old-category mappings already present in the template.
    try: wb.calculation.fullCalcOnLoad=True;wb.calculation.forceFullCalc=True;wb.calculation.calcMode='auto'
    except Exception: pass
    tmp=NamedTemporaryFile(delete=False,suffix='.xlsx');tmp.close();wb.save(tmp.name)
    archive_export_copy(db,tmp.name,filename,start.date())
    return FileResponse(tmp.name,media_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',filename=filename,background=BackgroundTask(os.unlink,tmp.name))

@app.get('/sorting/{load_id}', response_model=schemas.SortingSessionOut)
def sorting_get(load_id:str, db:Session=Depends(get_db), user=Depends(require_permission('receipt.view'))):
    load,ses=_session_for_load(db,load_id,False)
    if not ses: raise HTTPException(404,'Η ταξινόμηση δεν έχει ξεκινήσει')
    return _sorting_payload(db,load,ses)

@app.get('/master/media', response_model=list[schemas.MediumOut])
def list_media(db:Session=Depends(get_db), user=Depends(require_permission('master.view'))):
    return db.scalars(select(CollectionMedium).where(CollectionMedium.active==True).order_by(CollectionMedium.code)).all()

@app.post('/sorting/{load_id}/entries', response_model=schemas.SortingEntryOut)
def sorting_add_entry(load_id:str, data:schemas.SortingEntryCreate, db:Session=Depends(get_db), user:User=Depends(require_permission('sorting.perform'))):
    _nonneg(data.raw_weight,'Βάρος'); _nonneg(data.piece_count,'Τεμάχια')
    load,ses=_session_for_load(db,load_id,True,user)
    if ses.status not in ('IN_PROGRESS','LOGISTICS_REVIEW','MANAGEMENT_REVIEW'): raise HTTPException(409,'Η ταξινόμηση δεν είναι σε επεξεργασία')
    cat=db.get(WEEECategory,data.weee_category_id)
    if not cat: raise HTTPException(422,'Άγνωστη κατηγορία ΑΗΗΕ')
    if data.collection_medium_id and not db.get(CollectionMedium,data.collection_medium_id): raise HTTPException(422,'Άγνωστο μέσο συλλογής')
    if data.collection_medium_id and db.get(CollectionMedium,data.collection_medium_id).is_closed: raise HTTPException(409,'Το μέσο είναι κλειστό και δεν δέχεται άλλα κιλά')
    if data.raw_weight is None and data.piece_count is None: raise HTTPException(422,'Απαιτείται βάρος ή τεμάχια')
    raw=data.raw_weight
    if data.entry_type=='SCALE_GROSS':
        if not data.collection_medium_id or data.raw_weight is None: raise HTTPException(422,'Απαιτείται μέσο συλλογής και ένδειξη ζυγαριάς')
        med=db.get(CollectionMedium,data.collection_medium_id)
        if med.tare_weight is None: raise HTTPException(422,'Δεν υπάρχει απόβαρο στο μητρώο για αυτό το μέσο')
        # Current known content of the medium inside this open sorting session.
        existing=db.scalars(select(SortingEntry).where(SortingEntry.session_id==ses.id,SortingEntry.collection_medium_id==med.id)).all()
        existing_net=sum((x.approved_weight if x.approved_weight is not None else x.raw_weight or Decimal('0')) for x in existing)
        raw=Decimal(data.raw_weight)-Decimal(med.tare_weight)-existing_net
        if raw<=0: raise HTTPException(422,f'Η ένδειξη ζυγαριάς δεν δίνει θετική νέα ποσότητα (υπάρχον καθαρό {existing_net} kg, απόβαρο {med.tare_weight} kg)')
    if data.entry_type=='BULK' and data.piece_count is not None:
        if cat.code not in {'4Α2110','4Α2120','4Α2200','4Α1000','1Α1100','1Α1200','1Α2100','1Α2200','1Α3000'}: raise HTTPException(422,'Το υλικό δεν είναι ενεργοποιημένο για χύμα')
        if cat.average_weight is None: raise HTTPException(422,'Δεν υπάρχει μέσο βάρος για το χύμα υλικό')
        raw=Decimal(data.piece_count)*cat.average_weight
    raw=_round_kg(raw)      # ΑΚΕΡΑΙΑ kg ανά καταχώρηση (και τεμάχια × μέσο βάρος, και μεικτό − απόβαρο)
    obj=SortingEntry(session_id=ses.id,weee_category_id=data.weee_category_id,collection_medium_id=data.collection_medium_id,
      entry_type=data.entry_type,raw_weight=raw,piece_count=data.piece_count,created_by=user.id,notes=data.notes,
      source=(data.source.upper() if data.source and data.source.upper() in ('PC','ANDROID') else None))
    db.add(obj); db.flush()
    warn=_assign_single_use_code(db,user,data.collection_medium_id,cat)
    _sync_entry_stock(db,obj,user); write_audit(db,user,'sorting_entry',obj.id,'CREATE',new={'load_id':load_id,'category':cat.code,'weight':str(raw),'pieces':data.piece_count,'close_medium':bool(data.close_medium)})
    if data.close_medium and data.collection_medium_id and data.entry_type!='BULK':
        mm=db.get(CollectionMedium,data.collection_medium_id)
        if mm: mm.is_closed=True; write_audit(db,user,'collection_medium',mm.id,'CLOSE',new={'code':mm.code})
    db.commit(); db.refresh(obj); obj.warning=warn; return obj

@app.put('/sorting/entries/{entry_id}', response_model=schemas.SortingEntryOut)
def sorting_edit_entry(entry_id:str, data:schemas.SortingEntryCreate, db:Session=Depends(get_db), user:User=Depends(require_permission('sorting.perform'))):
    _nonneg(data.raw_weight,'Βάρος'); _nonneg(data.piece_count,'Τεμάχια')
    e=db.get(SortingEntry,entry_id)
    if not e: raise HTTPException(404,'Η εγγραφή δεν βρέθηκε')
    ses=db.get(SortingSession,e.session_id)
    if not ses or ses.status not in ('IN_PROGRESS','LOGISTICS_REVIEW','MANAGEMENT_REVIEW'): raise HTTPException(409,'Η ταξινόμηση έχει ήδη ολοκληρωθεί')
    cat=db.get(WEEECategory,data.weee_category_id)
    if not cat: raise HTTPException(422,'Άγνωστη κατηγορία ΑΗΗΕ')
    if data.collection_medium_id and data.collection_medium_id!=e.collection_medium_id:
        tm=db.get(CollectionMedium,data.collection_medium_id)
        if tm and tm.is_closed: raise HTTPException(409,'Το μέσο είναι κλειστό και δεν δέχεται άλλα κιλά')
    old={'category_id':e.weee_category_id,'medium_id':e.collection_medium_id,'weight':str(e.raw_weight),'pieces':e.piece_count}
    e.weee_category_id=data.weee_category_id; e.collection_medium_id=data.collection_medium_id; e.entry_type=data.entry_type
    e.raw_weight=data.raw_weight; e.piece_count=data.piece_count; e.notes=data.notes
    if data.entry_type=='BULK' and data.piece_count is not None:
        if cat.average_weight is None: raise HTTPException(422,'Δεν υπάρχει μέσο βάρος για το χύμα υλικό')
        e.raw_weight=Decimal(data.piece_count)*cat.average_weight
    e.raw_weight=_round_kg(e.raw_weight)
    db.flush()
    warn=_assign_single_use_code(db,user,e.collection_medium_id,cat) if e.collection_medium_id and e.collection_medium_id!=old['medium_id'] else None
    _sync_entry_stock(db,e,user)
    write_audit(db,user,'sorting_entry',e.id,'EDIT_DRAFT',old=old,new={'category_id':e.weee_category_id,'medium_id':e.collection_medium_id,'weight':str(e.raw_weight),'pieces':e.piece_count})
    db.commit(); db.refresh(e); e.warning=warn; return e

@app.get('/sorting/{load_id}/medium-type-suggestions')
def sorting_medium_type_suggestions(load_id:str, weee_category_id:str, db:Session=Depends(get_db), user:User=Depends(require_permission('sorting.perform'))):
    from sqlalchemy import func
    rows=db.execute(select(CollectionMedium.type_id, func.count(models.SortingEntry.id).label('n')).join(models.SortingEntry, models.SortingEntry.collection_medium_id==CollectionMedium.id).where(models.SortingEntry.weee_category_id==weee_category_id, CollectionMedium.active==True).group_by(CollectionMedium.type_id).order_by(func.count(models.SortingEntry.id).desc())).all()
    types={x.id:x for x in _sorting_medium_types(db)}
    ranked=[]; seen=set()
    for tid,n in rows:
        if tid in types: ranked.append({'id':tid,'code':types[tid].code,'name_el':types[tid].name_el,'usage_count':n}); seen.add(tid)
    for t in sorted(types.values(), key=lambda x:x.name_el):
        if t.id not in seen: ranked.append({'id':t.id,'code':t.code,'name_el':t.name_el,'usage_count':0})
    return ranked

@app.post('/sorting/{load_id}/media', response_model=schemas.MediumOut)
def sorting_create_medium(load_id:str, data:schemas.MediumCreate, db:Session=Depends(get_db), user:User=Depends(require_permission('sorting.perform'))):
    # Operators may create a missing medium in-place without leaving sorting.
    _session_for_load(db,load_id,True,user)
    mt=db.get(CollectionMediumType,data.type_id)
    if not mt or not mt.active: raise HTTPException(404,'Άγνωστος τύπος μέσου')
    if (mt.usage or 'BOTH') not in ('IN','BOTH'): raise HTTPException(422,'Το είδος «'+mt.name_el+'» είναι εξερχόμενο και δεν χρησιμοποιείται στην Ταξινόμηση')
    code=(data.code or '').strip()
    if mt.code=='BULK': raise HTTPException(422,'Το Χύμα δεν έχει αριθμό: καταχώρησέ το χωρίς μέσο συλλογής')
    if not code: raise HTTPException(422,'Γράψε αριθμό / κωδικό μέσου')
    existing=db.scalar(select(CollectionMedium).where(CollectionMedium.code==code,CollectionMedium.type_id==data.type_id,CollectionMedium.active==True))
    if existing: return existing
    if db.scalar(select(CollectionMedium.id).where(CollectionMedium.code==code,CollectionMedium.type_id==data.type_id)):
        raise HTTPException(409,'Ο κωδικός υπάρχει ήδη στον τύπο (ανενεργός). Σε άλλον τύπο επιτρέπεται.')
    tare=mt.default_tare_weight if getattr(mt,'tare_fixed',False) else (data.tare_weight if data.tare_weight is not None else mt.default_tare_weight)
    obj=CollectionMedium(type_id=data.type_id,code=code,tare_weight=tare,linked_loading_order_id=data.linked_loading_order_id)
    db.add(obj); db.flush(); write_audit(db,user,'collection_medium',obj.id,'CREATE_FROM_SORTING',new={'code':code,'type':mt.code,'tare':str(tare) if tare is not None else None}); db.commit(); db.refresh(obj); return obj

@app.get('/sorting/{load_id}/medium-suggestions')
def sorting_medium_suggestions(load_id:str, weee_category_id:str, db:Session=Depends(get_db), user:User=Depends(require_permission('sorting.perform'))):
    load,ses=_session_for_load(db,load_id,False)
    if not ses: return []
    entries=db.scalars(select(SortingEntry).where(SortingEntry.weee_category_id==weee_category_id,SortingEntry.collection_medium_id.is_not(None)).order_by(SortingEntry.created_at.desc())).all()
    allowed_types={t.id for t in _sorting_medium_types(db)}
    seen=set(); out=[]
    for e in entries:
        if e.collection_medium_id in seen: continue
        med=db.get(CollectionMedium,e.collection_medium_id)
        if not med or not med.active or med.is_closed or med.status not in SORTING_MEDIUM_STATUSES or med.type_id not in allowed_types: continue
        seen.add(med.id)
        out.append({'id':med.id,'type_id':med.type_id,'code':med.code,'tare_weight':float(med.tare_weight) if med.tare_weight is not None else None,'used_by_me':e.created_by==user.id,'last_used_at':e.created_at.isoformat()})
    out.sort(key=lambda x:(not x['used_by_me'], x['last_used_at']), reverse=False)
    return out

@app.delete('/sorting/entries/{entry_id}')
def sorting_delete_entry(entry_id:str, db:Session=Depends(get_db), user:User=Depends(require_permission('sorting.perform'))):
    e=db.get(SortingEntry,entry_id)
    if not e: raise HTTPException(404,'Η εγγραφή δεν βρέθηκε')
    ses=db.get(SortingSession,e.session_id)
    if ses.status not in ('IN_PROGRESS','LOGISTICS_REVIEW','MANAGEMENT_REVIEW'): raise HTTPException(409,'Η ταξινόμηση έχει ήδη ολοκληρωθεί')
    lot=db.scalar(select(WEEEStockLot).where(WEEEStockLot.source_sorting_entry_id==e.id))
    if lot: _retire_lot(db,lot,strict=True)
    write_audit(db,user,'sorting_entry',e.id,'DELETE_DRAFT',old={'weight':str(e.raw_weight),'category_id':e.weee_category_id}); db.delete(e); db.flush()
    # Deleting the only/last entry leaves an empty IN_PROGRESS session with the load stuck showing
    # "Σε ταξινόμηση" even though nothing is left to sort -- reset back to the pre-start state so the
    # load reappears as ready and a later /start creates a clean new session.
    remaining=db.scalars(select(SortingEntry).where(SortingEntry.session_id==ses.id)).all()
    if not remaining:
        load=db.get(InboundLoad,ses.inbound_load_id)
        if load: load.status='READY_FOR_SORTING'
        db.delete(ses)
    db.commit(); return {'ok':True}

@app.get('/sorting/{load_id}/metadata')
def sorting_metadata_get(load_id:str, db:Session=Depends(get_db), user:User=Depends(require_permission('sorting.perform'))):
    load,ses=_session_for_load(db,load_id,False)
    if not ses: return {'foreign_materials':None,'foreign_weight':0,'special_waste':None,'special_waste_weight':0,'load_pure':False,'check_special':False,'check_kday':False,'check_non_integer':False}
    return {'foreign_materials':ses.foreign_materials,'foreign_weight':float(ses.foreign_weight or 0),'special_waste':ses.special_waste,'special_waste_weight':float(ses.special_waste_weight or 0),'load_pure':bool(ses.load_pure),'check_special':bool(ses.check_special),'check_kday':bool(ses.check_kday),'check_non_integer':bool(ses.check_non_integer)}

@app.put('/sorting/{load_id}/metadata')
def sorting_metadata(load_id:str, data:schemas.SortingMetaUpdate, db:Session=Depends(get_db), user:User=Depends(require_permission('sorting.perform'))):
    load,ses=_session_for_load(db,load_id,True,user)
    if not ses: raise HTTPException(404,'Η ταξινόμηση δεν βρέθηκε')
    for field in ('foreign_weight','special_waste_weight'):
        v=getattr(data,field)
        _nonneg(v,'Καθαρό βάρος ξένων υλικών' if field=='foreign_weight' else 'Καθαρό βάρος αποβλήτων ειδικής διαχείρισης')
        if v is not None and Decimal(v)!=Decimal(v).to_integral_value():
            raise HTTPException(422,'Τα βάρη καταχωρούνται σε ακέραια kg')
    ses.foreign_materials=(data.foreign_materials or '').strip() or None
    ses.foreign_weight=data.foreign_weight or 0
    ses.special_waste=(data.special_waste or '').strip() or None
    ses.special_waste_weight=data.special_waste_weight or 0
    ses.load_pure=bool(data.load_pure); ses.check_special=bool(data.check_special); ses.check_kday=bool(data.check_kday); ses.check_non_integer=bool(data.check_non_integer)
    write_audit(db,user,'sorting_session',ses.id,'UPDATE_METADATA',new=data.model_dump(mode='json'))
    db.commit()
    return {'ok':True}

def _receipt_extras(notes:str|None):
    import json
    txt=str(notes or '')
    if txt.startswith('__EXTRA__'):
        try:
            first,plain=(txt.split('\n',1)+[''])[:2]
            ex=json.loads(first.replace('__EXTRA__','',1)); ex['plainNotes']=plain
            return ex
        except Exception:
            return {'plainNotes':txt}
    return {'plainNotes':txt}

def _sorting_export_data(db:Session, load_id:str):
    load=db.get(models.InboundLoad,load_id)
    if not load: raise HTTPException(404,'Το φορτίο δεν βρέθηκε')
    trip=db.get(models.InboundTrip,load.trip_id)
    ses=db.scalar(select(models.SortingSession).where(models.SortingSession.inbound_load_id==load.id))
    supplier=db.get(models.Organization,load.supplier_id)
    carrier=db.get(models.Organization,trip.carrier_id) if trip and trip.carrier_id else None
    outctr=db.get(models.ContainerAsset,load.outgoing_container_id) if load.outgoing_container_id else None
    entries=db.scalars(select(models.SortingEntry).where(models.SortingEntry.session_id==ses.id)).all() if ses else []
    weights={}; pieces={}
    for e in entries:
        cat=db.get(models.WEEECategory,e.weee_category_id)
        if not cat: continue
        official_code=cat.parent_code if cat.is_internal_subcategory and cat.parent_code else cat.code
        w=e.approved_weight if e.approved_weight is not None else e.raw_weight
        weights[official_code]=weights.get(official_code,Decimal('0'))+Decimal(w or 0)
        pieces[official_code]=pieces.get(official_code,0)+int(e.piece_count or 0)
    return {'load':load,'trip':trip,'session':ses,'supplier':supplier,'carrier':carrier,'outctr':outctr,'weights':weights,'pieces':pieces,'extras':_receipt_extras(trip.notes if trip else None)}

def _export_xlsx(data:dict):
    from openpyxl import load_workbook
    from tempfile import NamedTemporaryFile
    template=Path(__file__).parent/'templates'/'sorting_report_template.xlsx'
    wb=load_workbook(template)
    ws=wb[wb.sheetnames[0]]
    for name in list(wb.sheetnames[1:]): wb.remove(wb[name])
    l,t,s=data['load'],data['trip'],data['session']; ex=data['extras']
    ws.title=str(l.dpp_number or l.order_number or 'DPP')[:31]
    def org_name(o): return (o.trade_name or o.legal_name) if o else ''
    ws['B2']=org_name(data['supplier']); ws['D2']=l.order_number or ''
    ws['B3']=org_name(data['carrier']); ws['D3']=l.seal_number or ex.get('sealNo','')
    ws['B4']=ex.get('recycler') or 'ΚΕΝΤΡΟ ΕΛΛΗΝΙΚΗΣ ΠΕΡΙΒΑΛΛΟΝΤΙΚΗΣ ΑΝΑΚΥΚΛΩΣΗΣ Α.Β.Ε.Τ.Ε.'
    ws['D4']=int(round(float(l.net_weight or 0)))
    ws['B5']=l.incoming_container_number or (data['outctr'].container_number if data['outctr'] else '') or '-'
    ws['D5']='ΝΑΙ' if s and float(s.foreign_weight or 0)>0 else 'ΟΧΙ'
    ws['B6']=l.weighbridge_number or ex.get('weighbridgeNo',''); ws['D6']=int(round(float(s.foreign_weight or 0))) if s else 0
    report_date=ex.get('reportDate') or (t.receipt_date.date().isoformat() if t else '')
    try:
        from datetime import datetime as _dt
        ws['B7']=_dt.fromisoformat(report_date).strftime('%d.%m.%Y')
    except Exception: ws['B7']=report_date
    ws['D7']='ΝΑΙ' if s and float(s.special_waste_weight or 0)>0 else 'ΟΧΙ'
    ws['B8']=l.dispatch_note_number or ex.get('dispatchNo',''); ws['D8']=int(round(float(s.special_waste_weight or 0))) if s else 0
    ws['B9']=l.dpp_number or ''; ws['D9']=t.vehicle_registration or ''
    # A10:D11 is merged in the official template; write to the top-left cell.
    ws['A10']=ex.get('plainNotes','') or (s.notes if s else '') or ''
    ws['G12']='ΝΑΙ' if s and s.check_special else 'ΟΧΙ'; ws['I12']='ΝΑΙ' if s and s.check_kday else 'ΟΧΙ'; ws['L12']='ΝΑΙ' if s and s.check_non_integer else 'ΟΧΙ'; ws['O12']='ΝΑΙ' if s and s.load_pure else 'ΟΧΙ'; ws['R12']='ΝΑΙ' if s and float(s.foreign_weight or 0)>0 else 'ΟΧΙ'
    for row in range(15,83):
        code=str(ws.cell(row=row,column=4).value or '').strip()
        if not code: continue
        ws.cell(row=row,column=15).value=int(round(float(data['weights'].get(code,0))))
        ws.cell(row=row,column=16).value=int(data['pieces'].get(code,0))
    try:
        wb.calculation.fullCalcOnLoad=True; wb.calculation.forceFullCalc=True; wb.calculation.calcMode='auto'
    except Exception: pass
    tmp=NamedTemporaryFile(delete=False,suffix='.xlsx'); tmp.close(); wb.save(tmp.name); return tmp.name

def _export_pdf(data:dict, db:Session):
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4, landscape
    from reportlab.lib.styles import getSampleStyleSheet
    from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer
    from reportlab.pdfbase.ttfonts import TTFont
    from reportlab.pdfbase import pdfmetrics
    from tempfile import NamedTemporaryFile
    import os
    font='Helvetica'
    for fp in ['/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf','C:/Windows/Fonts/arial.ttf']:
        if os.path.exists(fp):
            try: pdfmetrics.registerFont(TTFont('WEEEUnicode',fp)); font='WEEEUnicode'; break
            except Exception: pass
    l,t,s=data['load'],data['trip'],data['session']; ex=data['extras']
    def org_name(o): return (o.trade_name or o.legal_name) if o else ''
    tmp=NamedTemporaryFile(delete=False,suffix='.pdf'); tmp.close()
    doc=SimpleDocTemplate(tmp.name,pagesize=landscape(A4),leftMargin=24,rightMargin=24,topMargin=20,bottomMargin=20)
    styles=getSampleStyleSheet(); styles['Normal'].fontName=font; styles['Heading1'].fontName=font
    story=[Paragraph('ΑΝΑΦΟΡΑ ΚΑΤΑΓΡΑΦΗΣ ΠΑΡΑΛΗΦΘΕΝΤΩΝ Α.Η.Η.Ε.',styles['Heading1']),Spacer(1,8)]
    meta=[['Προμηθευτής',org_name(data['supplier']),'Αριθμός Εντολής',l.order_number or ''],['Μεταφορική',org_name(data['carrier']),'Αριθμός Σφραγίδας',ex.get('sealNo','')],['Ανακυκλωτής',ex.get('recycler') or 'ΚΕΝΤΡΟ ΕΛΛΗΝΙΚΗΣ ΠΕΡΙΒΑΛΛΟΝΤΙΚΗΣ ΑΝΑΚΥΚΛΩΣΗΣ Α.Β.Ε.Τ.Ε.','Καθαρό Βάρος ΑΗΗΕ (kg)',str(int(round(float(l.net_weight or 0))))],['Αριθμός Container',l.incoming_container_number or '-','Ξένα Υλικά','ΝΑΙ' if s and float(s.foreign_weight or 0)>0 else 'ΟΧΙ'],['Αριθμός Ζυγολογίου',ex.get('weighbridgeNo',''),'Καθαρό Βάρος Ξένων Υλικών (kg)',str(int(round(float(s.foreign_weight or 0)))) if s else '0'],['Ημερομηνία Αναφοράς',ex.get('reportDate') or t.receipt_date.date().isoformat(),'Απόβλητα ειδικής διαχείρισης','ΝΑΙ' if s and float(s.special_waste_weight or 0)>0 else 'ΟΧΙ'],['Αριθμός Δελτίου Αποστολής',ex.get('dispatchNo',''),'Καθαρό Βάρος Ειδικής Διαχείρισης (kg)',str(int(round(float(s.special_waste_weight or 0)))) if s else '0'],['Δ.Π.Π.',str(l.dpp_number or ''),'Αριθμός Οχήματος',t.vehicle_registration or '']]
    tab=Table(meta,colWidths=[115,245,180,150]); tab.setStyle(TableStyle([('FONTNAME',(0,0),(-1,-1),font),('FONTSIZE',(0,0),(-1,-1),8),('GRID',(0,0),(-1,-1),.35,colors.grey),('BACKGROUND',(0,0),(0,-1),colors.HexColor('#EAF2F7')),('BACKGROUND',(2,0),(2,-1),colors.HexColor('#EAF2F7')),('VALIGN',(0,0),(-1,-1),'MIDDLE')])); story += [tab,Spacer(1,10)]
    rows=[['Κωδικός ΑΗΗΕ','Περιγραφή','kg','Τεμάχια']]
    for code,w in sorted(data['weights'].items()):
        c=db.scalar(select(models.WEEECategory).where(models.WEEECategory.code==code))
        rows.append([code,c.description_el if c else '',str(int(round(float(w)))),str(data['pieces'].get(code,0) or '')])
    wt=Table(rows,colWidths=[90,500,80,70],repeatRows=1); wt.setStyle(TableStyle([('FONTNAME',(0,0),(-1,-1),font),('FONTSIZE',(0,0),(-1,-1),7),('GRID',(0,0),(-1,-1),.3,colors.lightgrey),('BACKGROUND',(0,0),(-1,0),colors.HexColor('#DCEEF7')),('VALIGN',(0,0),(-1,-1),'TOP')])); story.append(wt)
    doc.build(story); return tmp.name


@app.post('/reports/tables')
def reports_tables(data:dict, user:User=Depends(current_user)):
    """Κοινή «Αναφορά»: δέχεται έτοιμους πίνακες (όπως εμφανίζονται στην οθόνη) και τους επιστρέφει ως Excel ή PDF. Δεν διαβάζει/γράφει τη βάση."""
    import os, re
    from tempfile import NamedTemporaryFile
    from starlette.background import BackgroundTask
    fmt=data.get('format')
    if fmt not in ('xlsx','pdf'): raise HTTPException(422,'Μη έγκυρη μορφή')
    sheets=[x for x in (data.get('sheets') or []) if isinstance(x,dict)][:30]
    if not sheets: raise HTTPException(422,'Δεν επιλέχθηκε καρτέλα')
    title=str(data.get('title') or 'Αναφορά')[:120]; subtitle=str(data.get('subtitle') or '')[:200]
    fname=re.sub(r'[\/:*?"<>|]+','_',str(data.get('filename') or title))[:80]
    def norm_sheet(sh):
        cols=[str(c) for c in (sh.get('columns') or [])][:40]
        rows=[[('' if v is None else v) for v in list(r)[:len(cols)]] for r in (sh.get('rows') or [])[:20000] if isinstance(r,(list,tuple))]
        tot=sh.get('total'); tot=[('' if v is None else v) for v in list(tot)[:len(cols)]] if isinstance(tot,(list,tuple)) else None
        return str(sh.get('name') or 'Φύλλο'),cols,rows,tot
    parts=[norm_sheet(x) for x in sheets]
    if fmt=='xlsx':
        from openpyxl import Workbook
        from openpyxl.styles import Font, PatternFill, Alignment
        from openpyxl.utils import get_column_letter
        wb=Workbook(); wb.remove(wb.active); used=set()
        for name,cols,rows,tot in parts:
            nm=re.sub(r'[\/*?:\[\]]+','_',name)[:31] or 'Φύλλο'; base=nm; i=2
            while nm in used: nm=(base[:28]+f' {i}'); i+=1
            used.add(nm); ws=wb.create_sheet(nm)
            ws.append([title+(' · '+subtitle if subtitle else '')]); ws['A1'].font=Font(bold=True,size=13)
            ws.append([]); ws.append(cols)
            for c in ws[3]: c.font=Font(bold=True); c.fill=PatternFill('solid',fgColor='DCE6F5'); c.alignment=Alignment(wrap_text=True,vertical='center')
            for r in rows: ws.append(r)
            if tot:
                ws.append(tot)
                for c in ws[ws.max_row]: c.font=Font(bold=True)
            for ci in range(1,len(cols)+1):
                w=max([len(str(cols[ci-1]))]+[len(str(r[ci-1])) for r in rows[:300] if ci-1<len(r)])
                ws.column_dimensions[get_column_letter(ci)].width=min(60,max(10,w+2))
            ws.freeze_panes='A4'
        tmp=NamedTemporaryFile(delete=False,suffix='.xlsx'); tmp.close(); wb.save(tmp.name)
        return FileResponse(tmp.name,media_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',filename=fname+'.xlsx',background=BackgroundTask(os.unlink,tmp.name))
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4, landscape
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
    from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer, PageBreak
    from reportlab.pdfbase.ttfonts import TTFont
    from reportlab.pdfbase import pdfmetrics
    font='Helvetica'
    for fp in ['C:/Windows/Fonts/arial.ttf','/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf']:
        if os.path.exists(fp):
            try: pdfmetrics.registerFont(TTFont('WEEEReport',fp)); font='WEEEReport'; break
            except Exception: pass
    tmp=NamedTemporaryFile(delete=False,suffix='.pdf'); tmp.close()
    doc=SimpleDocTemplate(tmp.name,pagesize=landscape(A4),leftMargin=28,rightMargin=28,topMargin=34,bottomMargin=30)
    ss=getSampleStyleSheet(); h1=ParagraphStyle('h1',parent=ss['Heading1'],fontName=font,fontSize=15); h2=ParagraphStyle('h2',parent=ss['Heading2'],fontName=font,fontSize=12); nm=ParagraphStyle('nm',parent=ss['Normal'],fontName=font,fontSize=8,leading=10)
    story=[]
    for idx,(name,cols,rows,tot) in enumerate(parts):
        if idx: story.append(PageBreak())
        story+= [Paragraph(title.replace('&','&amp;').replace('<','&lt;'),h1),Paragraph(subtitle.replace('&','&amp;').replace('<','&lt;'),nm) if subtitle else Spacer(1,2),Spacer(1,6),Paragraph(name.replace('&','&amp;').replace('<','&lt;'),h2),Spacer(1,4)]
        from xml.sax.saxutils import escape as _esc
        body=[[Paragraph(_esc(str(c)),nm) for c in cols]]+[[Paragraph(_esc('{:,.0f}'.format(v).replace(',','.') if isinstance(v,(int,float)) and not isinstance(v,bool) else str(v)),nm) for v in r] for r in rows]
        if tot: body.append([Paragraph('<b>'+_esc(str(v))+'</b>',nm) for v in tot])
        W=landscape(A4)[0]-56; t=Table(body,colWidths=[W/len(cols)]*len(cols),repeatRows=1)
        st=[('GRID',(0,0),(-1,-1),.3,colors.HexColor('#C9D2E3')),('BACKGROUND',(0,0),(-1,0),colors.HexColor('#DCE6F5')),('VALIGN',(0,0),(-1,-1),'TOP')]
        if tot: st+= [('LINEABOVE',(0,len(body)-1),(-1,len(body)-1),1.6,colors.HexColor('#8d9ab4'))]
        t.setStyle(TableStyle(st)); story.append(t)
    def footer(c,d):
        c.saveState(); c.setFont(font,8); c.drawRightString(landscape(A4)[0]-28,16,f'Σελίδα {d.page}'); c.restoreState()
    doc.build(story,onFirstPage=footer,onLaterPages=footer)
    return FileResponse(tmp.name,media_type='application/pdf',filename=fname+'.pdf',background=BackgroundTask(os.unlink,tmp.name))

@app.get('/sorting/{load_id}/export')
def sorting_export(load_id:str, format:str=Query(...,pattern='^(xlsx|pdf)$'), db:Session=Depends(get_db), user=Depends(require_permission('sorting.review'))):
    import os
    from starlette.background import BackgroundTask
    data=_sorting_export_data(db,load_id)
    path=_export_xlsx(data) if format=='xlsx' else _export_pdf(data,db)
    l=data['load']; dpp=l.dpp_number or 'DPP'; ext='xlsx' if format=='xlsx' else 'pdf'
    return FileResponse(path,media_type=('application/vnd.openxmlformats-officedocument.spreadsheetml.sheet' if format=='xlsx' else 'application/pdf'),filename=f'DPP_{dpp}_{l.order_number or "order"}.{ext}',background=BackgroundTask(os.unlink,path))

@app.post('/sorting/{load_id}/confirm', response_model=schemas.SortingSessionOut)
def sorting_confirm(load_id:str, db:Session=Depends(get_db), user:User=Depends(require_permission('sorting.perform'))):
    load,ses=_session_for_load(db,load_id,False)
    if not ses or ses.status!='IN_PROGRESS': raise HTTPException(409,'Η ταξινόμηση δεν είναι σε επεξεργασία')
    entries=db.scalars(select(SortingEntry).where(SortingEntry.session_id==ses.id)).all()
    if not entries: raise HTTPException(422,'Δεν υπάρχουν καταχωρημένα υλικά')
    ses.status='LOGISTICS_REVIEW'; ses.correction=False; ses.sorting_confirmed_at=datetime.now(timezone.utc); ses.sorting_confirmed_by=user.id; load.status='SORTING_CONFIRMED'
    write_audit(db,user,'sorting_session',ses.id,'SORTING_CONFIRM',new={'entries':len(entries)}); db.commit(); return _sorting_payload(db,load,ses)

@app.post('/sorting/entries/{entry_id}/adjust', response_model=schemas.SortingEntryOut)
def sorting_adjust(entry_id:str, data:schemas.SortingAdjustmentCreate, db:Session=Depends(get_db), user:User=Depends(require_permission('sorting.review'))):
    _nonneg(data.new_weight,'Νέο βάρος')
    e=db.get(SortingEntry,entry_id)
    if not e: raise HTTPException(404,'Η εγγραφή δεν βρέθηκε')
    ses=db.get(SortingSession,e.session_id)
    if ses.status not in {'LOGISTICS_REVIEW','MANAGEMENT_REVIEW'}: raise HTTPException(409,'Δεν επιτρέπεται διόρθωση σε αυτή την κατάσταση')
    old=e.approved_weight if e.approved_weight is not None else e.raw_weight
    db.add(SortingAdjustment(sorting_entry_id=e.id,old_weight=old,new_weight=data.new_weight,reason=data.reason,changed_by=user.id))
    e.approved_weight=data.new_weight; db.flush(); _sync_entry_stock(db,e,user)
    write_audit(db,user,'sorting_entry',e.id,'ADJUST',old={'weight':str(old)},new={'weight':str(data.new_weight)},reason=data.reason); db.commit(); db.refresh(e); return e

@app.post('/sorting/{load_id}/logistics-review', response_model=schemas.SortingSessionOut)
def logistics_review(load_id:str, data:schemas.LogisticsReviewCreate, db:Session=Depends(get_db), user:User=Depends(require_permission('sorting.review'))):
    load,ses=_session_for_load(db,load_id,False)
    if not ses or ses.status!='LOGISTICS_REVIEW': raise HTTPException(409,'Η ταξινόμηση δεν περιμένει έλεγχο Logistics')
    payload=_sorting_payload(db,load,ses)
    # final accounting weight: preserve exact entry values; round only aggregate when .5 or greater fraction exists
    exact=payload.sorting_weight
    frac=exact-Decimal(int(exact))
    final=Decimal(int(exact)+1) if frac>=Decimal('0.5') else Decimal(int(exact))
    ses.final_sorting_weight=final; ses.final_difference=(final-load.net_weight) if load.net_weight is not None else None
    ses.logistics_confirmed_at=datetime.now(timezone.utc); ses.logistics_confirmed_by=user.id; ses.requires_management_approval=data.requires_management_approval; ses.notes=data.notes
    if data.requires_management_approval:
        ses.status='MANAGEMENT_REVIEW'; load.status='MANAGEMENT_REVIEW'
    else:
        ses.status='CLOSED'; ses.correction=False; load.status='CLOSED'
        _materialize_weee_stock(db, load, ses, user)
    write_audit(db,user,'sorting_session',ses.id,'LOGISTICS_REVIEW',new={'requires_management':data.requires_management_approval,'final_weight':str(final)})
    db.commit(); return _sorting_payload(db,load,ses)


@app.post('/sorting/{load_id}/mark-correction', response_model=schemas.SortingSessionOut)
def sorting_mark_correction(load_id:str, db:Session=Depends(get_db), user:User=Depends(require_permission('sorting.review'))):
    """«Προς Διόρθωση»: αλλάζει ΜΟΝΟ την κατάσταση (χρώμα) -- μένει στα Windows μέχρι την Ολοκλήρωση ή το «Προς Ταξινόμηση»."""
    load,ses=_session_for_load(db,load_id,False)
    if not ses or ses.status not in {'LOGISTICS_REVIEW','MANAGEMENT_REVIEW'}: raise HTTPException(409,'Διαθέσιμο μόνο όταν η ταξινόμηση είναι προς έλεγχο')
    ses.correction=True
    write_audit(db,user,'sorting_session',ses.id,'MARK_CORRECTION',new={'correction':True}); db.commit(); return _sorting_payload(db,load,ses)

@app.post('/sorting/{load_id}/reopen', response_model=schemas.SortingSessionOut)
def sorting_reopen(load_id:str, reason:str=Query(default='Επιστροφή για διόρθωση'), db:Session=Depends(get_db), user:User=Depends(require_permission('sorting.review'))):
    load,ses=_session_for_load(db,load_id,False)
    if not ses or ses.status not in {'LOGISTICS_REVIEW','MANAGEMENT_REVIEW'}: raise HTTPException(409,'Η ταξινόμηση δεν μπορεί να επιστραφεί σε αυτή την κατάσταση')
    old=ses.status; ses.status='IN_PROGRESS'; ses.correction=False; load.status='SORTING_IN_PROGRESS'
    write_audit(db,user,'sorting_session',ses.id,'REOPEN_TO_SORTING',old={'status':old},new={'status':'IN_PROGRESS'},reason=reason)
    db.commit(); return _sorting_payload(db,load,ses)

@app.post('/sorting/{load_id}/management-approve', response_model=schemas.SortingSessionOut)
def management_approve(load_id:str, db:Session=Depends(get_db), user:User=Depends(require_permission('sorting.approve'))):
    load,ses=_session_for_load(db,load_id,False)
    if not ses or ses.status!='MANAGEMENT_REVIEW': raise HTTPException(409,'Δεν υπάρχει εκκρεμής έγκριση Διοίκησης')
    ses.status='CLOSED'; ses.correction=False; ses.management_confirmed_at=datetime.now(timezone.utc); ses.management_confirmed_by=user.id; load.status='CLOSED'
    _materialize_weee_stock(db, load, ses, user)
    write_audit(db,user,'sorting_session',ses.id,'MANAGEMENT_APPROVE',new={'status':'CLOSED'}); db.commit(); return _sorting_payload(db,load,ses)

@app.post('/sorting/{load_id}/photos')
def sorting_photo(load_id:str, category:str=Form('GENERAL'), file:UploadFile=File(...), db:Session=Depends(get_db), user:User=Depends(require_permission('sorting.perform'))):
    load=db.get(InboundLoad,load_id)
    if not load: raise HTTPException(404,'Το φορτίο δεν βρέθηκε')
    suffix=Path(file.filename or 'photo.jpg').suffix or '.jpg'; stored=f"{uuid4()}{suffix}"; path=UPLOAD_DIR/stored
    with path.open('wb') as f: shutil.copyfileobj(file.file,f)
    obj=FileAttachment(entity_type='INBOUND_LOAD',entity_id=load_id,category=category,filename=file.filename or stored,stored_path=str(path),content_type=file.content_type,uploaded_by=user.id)
    db.add(obj); db.flush(); write_audit(db,user,'attachment',obj.id,'UPLOAD',new={'load_id':load_id,'category':category,'filename':obj.filename}); db.commit(); return {'id':obj.id,'filename':obj.filename,'category':obj.category}

@app.get('/sorting/{load_id}/photos')
def sorting_photos(load_id:str, db:Session=Depends(get_db), user=Depends(require_permission('receipt.view'))):
    rows=db.scalars(select(FileAttachment).where(FileAttachment.entity_type=='INBOUND_LOAD',FileAttachment.entity_id==load_id).order_by(FileAttachment.created_at)).all()
    return [{'id':x.id,'filename':x.filename,'category':x.category,'created_at':x.created_at.isoformat()} for x in rows]


@app.delete('/sorting/photos/{photo_id}')
def sorting_photo_delete(photo_id:str, db:Session=Depends(get_db), user:User=Depends(require_permission('sorting.perform'))):
    obj=db.get(models.FileAttachment,photo_id)
    if not obj or obj.entity_type!='INBOUND_LOAD': raise HTTPException(404,'Η φωτογραφία δεν βρέθηκε')
    path=Path(obj.stored_path); old={'load_id':obj.entity_id,'category':obj.category,'filename':obj.filename}
    write_audit(db,user,'attachment',obj.id,'DELETE',old=old); db.delete(obj); db.commit()
    try: path.unlink(missing_ok=True)
    except OSError: pass
    return {'deleted':photo_id}

@app.get('/sorting/photos/{photo_id}/file')
def sorting_photo_file(photo_id:str, token:str=Query(default=''), db:Session=Depends(get_db)):
    # Image links opened in a new tab cannot send the SPA Authorization header; validate token explicitly.
    import jwt
    from .config import settings
    try:
        payload=jwt.decode(token,settings.jwt_secret,algorithms=['HS256'])
        if not db.get(User,payload.get('sub')): raise ValueError('user')
    except Exception:
        raise HTTPException(401,'Μη εξουσιοδοτημένη πρόσβαση')
    obj=db.get(models.FileAttachment,photo_id)
    if not obj or obj.entity_type!='INBOUND_LOAD': raise HTTPException(404,'Η φωτογραφία δεν βρέθηκε')
    path=Path(obj.stored_path)
    if not path.exists(): raise HTTPException(404,'Το αρχείο φωτογραφίας δεν βρέθηκε')
    return FileResponse(path,media_type=obj.content_type or 'application/octet-stream',filename=obj.filename)

def _business_days_elapsed(start: date, end: date)->int:
    cur=start; count=0
    while cur<end:
        cur+=timedelta(days=1)
        if cur.weekday()<5: count+=1
    return count

@app.get('/workflow/day-status', response_model=list[schemas.DayStatusOut])
def workflow_day_status(db:Session=Depends(get_db), user=Depends(require_permission('receipt.view'))):
    # One joined query instead of 2 db.get()/db.scalar() calls per load: at 1000+ loads
    # the old version took seconds and queued every other request behind it.
    rows=db.execute(
        select(InboundLoad,InboundTrip,SortingSession)
        .join(InboundTrip,InboundLoad.trip_id==InboundTrip.id)
        .outerjoin(SortingSession,SortingSession.inbound_load_id==InboundLoad.id)
    ).all()
    grouped={}; today=date.today()
    for l,trip,ses in rows:
        d=trip.receipt_date.date().isoformat(); g=grouped.setdefault(d,{'total':0,'red':0,'yellow':0,'green':0,'overdue':0})
        g['total']+=1
        if ses and ses.status=='CLOSED': g['green']+=1
        elif ses and ses.status=='MANAGEMENT_REVIEW': g['yellow']+=1
        elif ses and ses.status in {'IN_PROGRESS','LOGISTICS_REVIEW'}: g['red']+=1
        else: pass
        if (not ses or ses.status!='CLOSED') and _business_days_elapsed(trip.receipt_date.date(),today)>=2: g['overdue']+=1
    out=[]
    for d,g in sorted(grouped.items(),reverse=True):
        color='RED' if g['red'] else ('YELLOW' if g['yellow'] else ('GREEN' if g['green']==g['total'] and g['total']>0 else 'GRAY'))
        out.append(schemas.DayStatusOut(date=d,color=color,total_loads=g['total'],red=g['red'],yellow=g['yellow'],green=g['green'],overdue=g['overdue']))
    return out

@app.get('/m')
def mobile_sorting_workspace():
    return _FileResponse(static_dir/'sorting.html')


# ---- Build 0.6: WEEE warehouse -> Production ----
from .models import InventoryLocation, WEEEStockLot, StockMovement, ProductionTransfer, ProductionTransferItem

def _weee_main_location(db: Session) -> InventoryLocation:
    loc=db.scalar(select(InventoryLocation).where(InventoryLocation.code=='WEEE_MAIN'))
    if not loc:
        loc=InventoryLocation(code='WEEE_MAIN',name_el='Αποθήκη ΑΗΗΕ προς ανακύκλωση',domain='WEEE'); db.add(loc); db.flush()
    return loc

def _medium_release(db:Session, medium_id):
    """Αν ένα μέσο δεν έχει πια διαθέσιμο απόθεμα ΑΗΗΕ, επιστρέφει σε «διαθέσιμο»."""
    if not medium_id: return
    m=db.get(CollectionMedium,medium_id)
    if m and m.status=='WEEE_STORAGE' and not db.scalar(select(func.count()).select_from(WEEEStockLot).where(WEEEStockLot.collection_medium_id==medium_id,WEEEStockLot.available_weight>0)):
        m.status='AVAILABLE'; m.is_closed=False       # άδειο μέσο = πάλι ανοιχτό

def _retire_lot(db:Session, lot, strict:bool=False):
    """Αφαιρεί ένα μερίδιο αποθέματος. Αν έχει ήδη καταναλωθεί (παραγωγή): strict -> σφάλμα 409, αλλιώς μένει μόνο το καταναλωμένο μέρος."""
    consumed=Decimal(lot.original_weight)-Decimal(lot.available_weight); medium_id=lot.collection_medium_id
    if consumed>0:
        if strict: raise HTTPException(409,'Μέρος του υλικού έχει ήδη χρησιμοποιηθεί στην παραγωγή -- δεν μπορεί να αλλάξει ή να διαγραφεί')
        lot.original_weight=consumed; lot.available_weight=Decimal(0); lot.status='CONSUMED'
    else:
        db.execute(StockMovement.__table__.delete().where(StockMovement.lot_id==lot.id)); db.delete(lot)
    db.flush(); _medium_release(db,medium_id)

def _sync_entry_stock(db:Session, e:SortingEntry, user:User):
    """ΖΩΝΤΑΝΟ απόθεμα: το μερίδιο ΑΗΗΕ κάθε καταχώρησης ταξινόμησης δημιουργείται/ενημερώνεται (κιλά, κατηγορία, μέσο συλλογής)
    αμέσως, με κάθε καταχώρηση/διόρθωση -- όχι μόνο στην Ολοκλήρωση. Μερίδιο που έχει ήδη καταναλωθεί στην παραγωγή δεν αλλάζει κατηγορία/μέσο
    και δεν μειώνεται κάτω από το καταναλωμένο (409)."""
    ses=db.get(SortingSession,e.session_id); load=db.get(InboundLoad,ses.inbound_load_id)
    w=e.approved_weight if e.approved_weight is not None else e.raw_weight
    w=Decimal(w) if w is not None else Decimal(0)
    lot=db.scalar(select(WEEEStockLot).where(WEEEStockLot.source_sorting_entry_id==e.id))
    if w<=0:
        if lot: _retire_lot(db,lot,strict=True)
        return
    loc=_weee_main_location(db)
    if not lot:
        lot=WEEEStockLot(source_sorting_entry_id=e.id,inbound_load_id=load.id,weee_category_id=e.weee_category_id,collection_medium_id=e.collection_medium_id,
            location_id=loc.id,original_weight=w,available_weight=w,piece_count=e.piece_count,status='AVAILABLE')
        db.add(lot); db.flush()
        db.add(StockMovement(domain='WEEE',lot_id=lot.id,movement_type='SORTING_IN',from_location_id=None,to_location_id=loc.id,weight=w,user_id=user.id,reason=None))
    else:
        consumed=Decimal(lot.original_weight)-Decimal(lot.available_weight); delta=w-Decimal(lot.original_weight)
        retarget=(lot.weee_category_id!=e.weee_category_id) or (lot.collection_medium_id!=e.collection_medium_id)
        if consumed>0 and (retarget or w<consumed): raise HTTPException(409,'Μέρος του υλικού έχει ήδη χρησιμοποιηθεί στην παραγωγή -- δεν μπορεί να αλλάξει')
        old_medium=lot.collection_medium_id
        lot.weee_category_id=e.weee_category_id; lot.collection_medium_id=e.collection_medium_id; lot.piece_count=e.piece_count
        lot.original_weight=w; lot.available_weight=Decimal(lot.available_weight)+delta
        lot.status='AVAILABLE' if lot.available_weight==lot.original_weight else ('PARTIAL' if lot.available_weight>0 else 'CONSUMED')
        if delta!=0: db.add(StockMovement(domain='WEEE',lot_id=lot.id,movement_type='SORTING_ADJUST',from_location_id=None,to_location_id=lot.location_id,weight=delta,user_id=user.id,reason=None))
        db.flush()
        if old_medium!=lot.collection_medium_id: _medium_release(db,old_medium)
    if e.collection_medium_id:
        medium=db.get(CollectionMedium,e.collection_medium_id)
        if medium: medium.status='WEEE_STORAGE'

def _materialize_weee_stock(db: Session, load: InboundLoad, ses: SortingSession, user: User):
    """Create immutable source lots once a sorting session becomes CLOSED. Idempotent by source_sorting_entry_id."""
    loc=_weee_main_location(db)
    entries=db.scalars(select(SortingEntry).where(SortingEntry.session_id==ses.id)).all()
    created=0
    for e in entries:
        if db.scalar(select(WEEEStockLot).where(WEEEStockLot.source_sorting_entry_id==e.id)):
            continue
        weight=e.approved_weight if e.approved_weight is not None else e.raw_weight
        if weight is None or Decimal(weight)<=0:
            continue
        lot=WEEEStockLot(source_sorting_entry_id=e.id,inbound_load_id=load.id,weee_category_id=e.weee_category_id,
            collection_medium_id=e.collection_medium_id,location_id=loc.id,original_weight=weight,available_weight=weight,
            piece_count=e.piece_count,status='AVAILABLE')
        db.add(lot); db.flush()
        db.add(StockMovement(domain='WEEE',lot_id=lot.id,movement_type='SORTING_IN',from_location_id=None,to_location_id=loc.id,
            weight=weight,user_id=user.id,reason=None))
        created+=1
        if e.collection_medium_id:
            medium=db.get(CollectionMedium,e.collection_medium_id)
            if medium: medium.status='WEEE_STORAGE'
    write_audit(db,user,'weee_inventory',load.id,'MATERIALIZE_FROM_SORTING',new={'lots_created':created})

def _lot_out(db: Session, lot: WEEEStockLot):
    cat=db.get(WEEECategory,lot.weee_category_id); medium=db.get(CollectionMedium,lot.collection_medium_id) if lot.collection_medium_id else None
    loc=db.get(InventoryLocation,lot.location_id)
    return schemas.WEEEStockLotOut(id=lot.id,inbound_load_id=lot.inbound_load_id,weee_category_id=lot.weee_category_id,
        weee_code=cat.code,weee_description=cat.description_el,collection_medium_id=lot.collection_medium_id,
        medium_code=medium.code if medium else None,location_code=loc.code,original_weight=lot.original_weight,
        available_weight=lot.available_weight,piece_count=lot.piece_count,status=lot.status)

_opening_stock_2025_cache=None
def _load_opening_stock_2025()->dict:
    """Documented physical inventory count at 31/12/2025, per WEEE category code.
    Supplied by the user (KENTPO EΛΛHNIKHΣ ΠEPIBAΛΛONTIKHΣ ANAKYKΛΩΣHΣ A.B.E.T.E.,
    ΑΠΟΘΕΜΑ 31/12/2025) -- see BUSINESS_RULES.md #2: real data, not an invented figure."""
    global _opening_stock_2025_cache
    if _opening_stock_2025_cache is None:
        path=Path(__file__).resolve().parent/'data'/'opening_stock_2025_12_31.json'
        raw=json.loads(path.read_text(encoding='utf-8')) if path.exists() else {}
        _opening_stock_2025_cache={k:float(v) for k,v in raw.items() if not k.startswith('_')}
    return _opening_stock_2025_cache

@app.get('/inventory/weee-dashboard')
def weee_dashboard(month:str|None=Query(default=None,pattern=r'^\d{4}-\d{2}$'), day:str|None=Query(default=None,pattern=r'^\d{4}-\d{2}-\d{2}$'), start:str|None=Query(default=None,pattern=r'^\d{4}-\d{2}-\d{2}$'), end:str|None=Query(default=None,pattern=r'^\d{4}-\d{2}-\d{2}$'), db:Session=Depends(get_db), user=Depends(require_permission('production.view'))):
    now=datetime.now()
    if start and end:
        # Month/quarter/year aggregation (Αποθήκη ΑΗΗΕ period picker): the frontend computes the
        # window boundaries the same way Production does and passes them straight through here.
        # Everything below already keys off `start`/`end` alone, so no other logic needed to change.
        s=datetime.fromisoformat(start); e=datetime.fromisoformat(end)
        start=datetime(s.year,s.month,s.day); end=datetime(e.year,e.month,e.day)+timedelta(days=1); period='range'; label=f'{s.strftime("%Y-%m-%d")}..{e.strftime("%Y-%m-%d")}'
    elif day:
        d=datetime.fromisoformat(day); start=datetime(d.year,d.month,d.day); end=start+timedelta(days=1); period='day'; label=day
    else:
        y,m=(map(int,month.split('-')) if month else (now.year,now.month)); start=datetime(y,m,1); end=datetime(y+1,1,1) if m==12 else datetime(y,m+1,1); period='month'; label=f'{y:04d}-{m:02d}'
    cats=db.scalars(select(WEEECategory).where(WEEECategory.active==True)).all()
    cat_by_id={c.id:c for c in cats}
    # Historical Παραλαβές/Ταξινόμηση data was classified only at the official parent
    # code, while historical Παραγωγή data was recorded against the finer internal
    # company subcategories of that same code (e.g. all of 6Α0000 classified as
    # 6Α0000 itself, but consumed as INT-6A-TELCO / INT-6A-PRINT / ...). Treated as
    # independent per-category ledgers this makes every such internal subcategory
    # need an inflated "carry-in" purely from a coding mismatch, not real unexplained
    # stock. Stock-balance figures are therefore pooled per *family* (official code +
    # its internal subcategories) below; period activity (classified/processed/outgoing)
    # stays reported per individual code, unchanged.
    family_of={c.id:(c.parent_code if c.is_internal_subcategory and c.parent_code else c.code) for c in cats}
    # Initial user-provided category order. Internal subcategories are placed immediately after their parent.
    official_order=['1Α1100','1Α1200','1Α2100','1Α2200','1Α3000','1Β1100','1Β1210','1Β1220','1Β1300','1Β2100','1Β2200','1Γ0000','1Δ0000','1Ε0000','1Ζ0000','2Α1110','2Α1120','2Α1210','2Α1220','2Α2110','2Α2120','2Α2210','2Α2220','2Β1000','2Β2000','2Β3000','2Β4000','3Α0000','3Β0000','4Α1000','4Α2110','4Α2120','4Α2200','4Α3100','4Α3200','4Β0000','4Γ0000','4Δ0000','4Ε0000','4Ζ0000','4Η0000','4Θ0000','4Ι0000','4Κ1000','4Κ2000','4Λ0000','5Α0000','5Β0000','5Β1000','5Γ0000','5Δ0000','5Ε0000','5Ζ0000','5Η0000','5Θ0000','5Ι1100','5Ι1200','5Ι2000','5Κ0000','6Α0000','6Β0000','6Γ0000','6Δ1000','6Δ2000','6Ε0000']
    internal_order=['INT-4D-AUDIO','INT-4D-PROJ','INT-4I-UPS','INT-4I-MON','INT-4I-CASH','INT-4L-PCSERVER','INT-4L-PRINT','INT-4L-SCAN','INT-4L-COPY','INT-4L-KEYB','INT-5D-AV','INT-5D-SPEAK','INT-5D-PROJ','INT-5I2-UPS','INT-5I2-MON','INT-5I2-CASH','INT-6A-PCSERVER','INT-6A-PRINT','INT-6A-MODEM','INT-6A-KEYB','INT-6A-TELCO']
    order_map={c:i*10 for i,c in enumerate(official_order)}
    child_pos={}
    for code in internal_order:
        c=next((x for x in cats if x.code==code),None)
        if c and c.parent_code:
            child_pos[c.parent_code]=child_pos.get(c.parent_code,0)+1;order_map[code]=order_map.get(c.parent_code,9999)+child_pos[c.parent_code]
    # Classification quantities follow receipt day, not import timestamp.
    entries=db.execute(select(models.SortingEntry,InboundTrip).join(SortingSession,models.SortingEntry.session_id==SortingSession.id).join(InboundLoad,SortingSession.inbound_load_id==InboundLoad.id).join(InboundTrip,InboundLoad.trip_id==InboundTrip.id).where(InboundTrip.receipt_date>=start,InboundTrip.receipt_date<end,InboundTrip.deleted_at.is_(None))).all()
    totals={}
    for e,trip in entries:
        w=float(e.approved_weight if e.approved_weight is not None else (e.raw_weight or 0)); totals[e.weee_category_id]=totals.get(e.weee_category_id,0)+w
    # Stock at period start = classified stock less recorded production. Production entries are the authoritative
    # consumption of WEEE (historical Excel, Android forklift or Windows).
    opening={}; current={}; outgoing={}
    processed_opening={}; processed_period={}; processed_period_hermes={}
    prod_rows=db.scalars(select(ProductionWorkEntry).where(ProductionWorkEntry.active==True,ProductionWorkEntry.work_date<end)).all()
    for pe in prod_rows:
        w=float(pe.weight_kg or 0); cid=pe.weee_category_id
        if pe.work_date<start: processed_opening[cid]=processed_opening.get(cid,0)+w
        else:
            processed_period[cid]=processed_period.get(cid,0)+w
            if pe.supplier_group=='HERMES': processed_period_hermes[cid]=processed_period_hermes.get(cid,0)+w
    # One joined query instead of thousands of db.get() calls: critical for date-to-date navigation speed.
    movements=db.execute(select(StockMovement,WEEEStockLot,InboundTrip).join(WEEEStockLot,StockMovement.lot_id==WEEEStockLot.id).join(InboundLoad,WEEEStockLot.inbound_load_id==InboundLoad.id).join(InboundTrip,InboundLoad.trip_id==InboundTrip.id).where(StockMovement.domain=='WEEE',StockMovement.created_at<end,InboundTrip.deleted_at.is_(None)).order_by(StockMovement.created_at)).all()
    for mv,lot,trip in movements:
        sign=1 if mv.movement_type=='SORTING_IN' else -1; w=sign*float(mv.weight or 0); cid=lot.weee_category_id
        # Imported 2026 SORTING_IN movements were created on import day; inventory must follow the
        # actual receipt date. Otherwise historical months start at zero and production creates false negatives.
        event_at=trip.receipt_date if mv.movement_type=='SORTING_IN' else mv.created_at
        if event_at<start: opening[cid]=opening.get(cid,0)+w
        current[cid]=current.get(cid,0)+w
        if start<=event_at<end and sign<0: outgoing[cid]=outgoing.get(cid,0)+abs(w)
    # Opening stock at 31/12/2025 is documented (user-supplied physical count), not
    # invented. Where a code isn't on that sheet, or the documented amount still isn't
    # enough to cover recorded 2026 consumption at some point in the year, the gap is
    # tracked separately (`undocumented_gap_family`) instead of being silently folded
    # into the same number -- see BUSINESS_RULES.md #2.
    documented_opening=_load_opening_stock_2025()
    documented_opening_family={}
    for c in cats:
        fam=family_of[c.id]
        documented_opening_family[fam]=documented_opening_family.get(fam,0.0)+documented_opening.get(c.code,0.0)
    carry_in={}; undocumented_gap_family={}
    all_movements=db.execute(select(StockMovement,WEEEStockLot,InboundTrip).join(WEEEStockLot,StockMovement.lot_id==WEEEStockLot.id).join(InboundLoad,WEEEStockLot.inbound_load_id==InboundLoad.id).join(InboundTrip,InboundLoad.trip_id==InboundTrip.id).where(StockMovement.domain=='WEEE',InboundTrip.deleted_at.is_(None))).all()
    events={}
    for mv,lot,trip in all_movements:
        event_at=trip.receipt_date if mv.movement_type=='SORTING_IN' else mv.created_at
        delta=(1 if mv.movement_type=='SORTING_IN' else -1)*float(mv.weight or 0)
        fam=family_of.get(lot.weee_category_id,lot.weee_category_id)
        events.setdefault(fam,[]).append((event_at,delta))
    for pe in db.scalars(select(ProductionWorkEntry).where(ProductionWorkEntry.active==True)).all():
        fam=family_of.get(pe.weee_category_id,pe.weee_category_id)
        events.setdefault(fam,[]).append((pe.work_date,-float(pe.weight_kg or 0)))
    for fam,evs in events.items():
        doc=documented_opening_family.get(fam,0.0)
        bal=doc; min_bal=doc
        for _,delta in sorted(evs,key=lambda z:z[0]):
            bal+=delta; min_bal=min(min_bal,bal)
        # Previously padded carry_in with max(0,-min_bal) so current_stock could never go negative.
        # Per explicit user direction, the real source ledger (HER's own "Απόθεμα" sheet) allows and
        # expects negative current stock -- it's a genuine signal (e.g. processing exceeded what was
        # ever received), not something to mask. undocumented_gap_family is kept only as a diagnostic
        # (how far below zero the running balance would dip) and no longer feeds into carry_in.
        undocumented_gap_family[fam]=max(0.0,-min_bal)
        carry_in[fam]=doc
    # A family with documented stock but no recorded movements at all still needs its
    # carry-in seeded (the loop above only visits families that appear in `events`).
    for fam,doc in documented_opening_family.items():
        carry_in.setdefault(fam,doc)
    # Pool the period's opening/period figures per family too, so the carry-in above
    # (a single number per family) combines with a matching family-pooled baseline
    # instead of being applied once per individual internal-subcategory row.
    opening_family={}; processed_opening_family={}; classified_family={}; processed_family={}; outgoing_family={}
    for c in cats:
        fam=family_of[c.id]
        opening_family[fam]=opening_family.get(fam,0)+opening.get(c.id,0)
        processed_opening_family[fam]=processed_opening_family.get(fam,0)+processed_opening.get(c.id,0)
        classified_family[fam]=classified_family.get(fam,0)+totals.get(c.id,0)
        processed_family[fam]=processed_family.get(fam,0)+processed_period.get(c.id,0)
        outgoing_family[fam]=outgoing_family.get(fam,0)+outgoing.get(c.id,0)
    prev_family={}; cur_family={}
    for fam in set(family_of.values()):
        pf=carry_in.get(fam,0)+opening_family.get(fam,0)-processed_opening_family.get(fam,0)
        prev_family[fam]=pf
        cur_family[fam]=pf+classified_family.get(fam,0)-processed_family.get(fam,0)-outgoing_family.get(fam,0)
    ship_official={'1Α1100','1Α1200','1Α2100','1Α2200','1Α3000','3Α0000','3Β0000','4Γ0000','5Β1000','5Γ0000','5Ι1100','6Δ1000','6Δ2000'}
    rows=[]
    for c in cats:
        # Keep the official parent row as well as the user's internal subcategories.
        # Internal rows display the parent code, while their description keeps them distinguishable.
        official=family_of[c.id]
        major=str(official or c.code)[:1]
        processed=round(processed_period.get(c.id,0),3)
        processed_hermes=round(processed_period_hermes.get(c.id,0),3)
        classified=round(totals.get(c.id,0),3)
        out=round(outgoing.get(c.id,0),3)
        # Only the official/parent row (or a standalone code with no siblings) carries
        # the family's pooled stock balance; internal-subcategory rows show '–' for it
        # (see openStockInfo/UI: their own classification/processed/outgoing stay real).
        if c.code==official:
            prev=round(prev_family.get(official,0),3); cur=round(cur_family.get(official,0),3)
            period_change=round(cur-prev,3)
            opening_documented=round(documented_opening_family.get(official,0),3)
            opening_gap=round(undocumented_gap_family.get(official,0),3)
        else:
            prev=None; cur=None; period_change=None; opening_documented=None; opening_gap=None
        rows.append({'id':c.id,'major_category':major,'category':official,'internal_code':c.code,'description':c.description_el,'her_description':c.her_description,'official_code':official,'parent_code':c.parent_code,
          'previous_stock':prev,'classification_period':classified,'classification_month':classified,'processed_period':processed,'processed_month':processed,'processed_month_hermes':processed_hermes,'outgoing_period':out,'outgoing_month':out,
          'current_stock':cur,'period_change':period_change,'month_change':period_change,
          'opening_stock_documented':opening_documented,'opening_stock_gap':opening_gap,'sort_index':order_map.get(c.code,99999)})
    rows.sort(key=lambda x:(x['sort_index'],x['description']))
    out_process=[x for x in rows if x['official_code'] not in ship_official]; out_ship=[x for x in rows if x['official_code'] in ship_official]
    trips=db.scalars(select(InboundTrip).where(InboundTrip.receipt_date>=start,InboundTrip.receipt_date<end,InboundTrip.deleted_at.is_(None))).all(); ids=[t.id for t in trips]
    receipt_total=0.0
    if ids:
        receipt_total=sum(float(l.net_weight or 0) for l in db.scalars(select(InboundLoad).where(InboundLoad.trip_id.in_(ids))).all())
    classified_process=round(sum(x['classification_period'] for x in out_process),3);classified_ship=round(sum(x['classification_period'] for x in out_ship),3)
    return {'period':period,'selected':label,'month':label[:7],'kpis':{'receipts_period':round(receipt_total,3),'receipts_month':round(receipt_total,3),'classified_total':round(classified_process+classified_ship,3),'classified_to_process':classified_process,'classified_to_ship':classified_ship,'processed_period':round(sum(x['processed_period'] for x in rows),3),'processed_month':round(sum(x['processed_period'] for x in rows),3),'processed_hermes_total':round(sum(x['processed_month_hermes'] for x in rows),3),'weee_shipments_period':round(sum(x['outgoing_period'] for x in out_ship),3),'weee_shipments_month':round(sum(x['outgoing_period'] for x in out_ship),3),'stock_to_process':round(sum(x['current_stock'] for x in out_process if x['current_stock'] is not None),3),'stock_to_ship':round(sum(x['current_stock'] for x in out_ship if x['current_stock'] is not None),3),'inferred_carry_in':round(sum(carry_in.values()),3),'opening_stock_documented_total':round(sum(documented_opening_family.values()),3),'opening_stock_gap_total':round(sum(undocumented_gap_family.values()),3),'opening_stock_period_total':round(sum(x['previous_stock'] for x in rows if x['previous_stock'] is not None),3)},'to_process':out_process,'to_ship':out_ship}


def _weee_family_code(c):
    return c.parent_code if c.is_internal_subcategory and c.parent_code else c.code

ANDROID_WEEE_DESC_KEY='android.weee_desc_mode'

SCHEDULE_KEY='app.schedule'
DEFAULT_SCHEDULE={'active':'summer','summer':{'start':'06:30','end':'14:50'},'winter':{'start':'07:15','end':'15:35'},'special':{'start':'06:30','end':'14:50'}}

def _check_time(v,label):
    import re as _re
    if not _re.fullmatch(r'([01]\d|2[0-3]):[0-5]\d',str(v or '')): raise HTTPException(422,f'{label}: μη έγκυρη ώρα (ωω:λλ)')
    return str(v)

EMPTY_BREAK={'start':'','end':''}
BREAK_GROUPS_KEY='app.break_groups'

def _brk(v):
    v=v or {}
    return {'start':str(v.get('start') or ''),'end':str(v.get('end') or '')}

def _sched_norm(d:dict)->dict:
    """Κανονικοποίηση ωραρίου. b1/b2 = διαλείμματα Τμήματος Α (τα υπάρχοντα δεδομένα), B.b1/B.b2 = Τμήματος Β (ξεκινά κενό)."""
    out={'active':d.get('active') if d.get('active') in ('summer','winter','special') else 'summer'}
    for k in ('summer','winter','special'):
        src=d.get(k) or DEFAULT_SCHEDULE[k]
        bb=src.get('B') or {}
        out[k]={'start':src.get('start') or DEFAULT_SCHEDULE[k]['start'],'end':src.get('end') or DEFAULT_SCHEDULE[k]['end'],
                'b1':_brk(src.get('b1')),'b2':_brk(src.get('b2')),'B':{'b1':_brk(bb.get('b1')),'b2':_brk(bb.get('b2'))}}
    return out

@app.get('/settings/schedule')
def schedule_get(db:Session=Depends(get_db), user:User=Depends(current_user)):
    row=db.scalar(select(AppSetting).where(AppSetting.key==SCHEDULE_KEY))
    if not row: return _sched_norm(DEFAULT_SCHEDULE)
    try: return _sched_norm(json.loads(row.value))
    except Exception: return _sched_norm(DEFAULT_SCHEDULE)

def _check_break(v,label):
    v=v or {}; st=str(v.get('start') or ''); en=str(v.get('end') or '')
    if not st and not en: return dict(EMPTY_BREAK)
    if not st or not en: raise HTTPException(422,f'{label}: συμπλήρωσε και την ώρα έναρξης και την ώρα λήξης του διαλείμματος')
    st=_check_time(st,label); en=_check_time(en,label)
    if st>=en: raise HTTPException(422,f'{label}: η ώρα λήξης πρέπει να είναι μετά την έναρξη')
    return {'start':st,'end':en}

@app.put('/settings/schedule')
def schedule_put(data:dict, db:Session=Depends(get_db), user:User=Depends(require_permission('settings.manage'))):
    active=data.get('active')
    if active not in ('summer','winter','special'): raise HTTPException(422,'Μη έγκυρη επιλογή ωραρίου')
    row=db.scalar(select(AppSetting).where(AppSetting.key==SCHEDULE_KEY))
    try: prev=_sched_norm(json.loads(row.value)) if row else _sched_norm(DEFAULT_SCHEDULE)
    except Exception: prev=_sched_norm(DEFAULT_SCHEDULE)
    payload={'active':active}
    for key,label in (('summer','Θερινό'),('winter','Χειμερινό'),('special','Έκτακτο')):
        d=data.get(key) or {}
        st=_check_time(d.get('start'),label); en=_check_time(d.get('end'),label)
        if st>=en: raise HTTPException(422,f'{label}: η ώρα λήξης πρέπει να είναι μετά την έναρξη')
        dB=d.get('B') or {}
        cells=[('A',1,_check_break(d.get('b1'),f'{label} · Τμήμα Α · Διάλειμμα 1'),prev[key]['b1']),
               ('A',2,_check_break(d.get('b2'),f'{label} · Τμήμα Α · Διάλειμμα 2'),prev[key]['b2']),
               ('B',1,_check_break(dB.get('b1'),f'{label} · Τμήμα Β · Διάλειμμα 1'),prev[key]['B']['b1']),
               ('B',2,_check_break(dB.get('b2'),f'{label} · Τμήμα Β · Διάλειμμα 2'),prev[key]['B']['b2'])]
        for grp,n,br,old in cells:
            # Μέσα στη βάρδια: ελέγχεται όταν το διάλειμμα ΑΛΛΑΖΕΙ· ένα ήδη αποθηκευμένο που βγαίνει εκτός μετά από αλλαγή βάρδιας δεν απορρίπτεται και δεν διαγράφεται
            if br['start'] and br!=_brk(old) and (br['start']<st or br['end']>en):
                raise HTTPException(422,f'{label} · Τμήμα {"Α" if grp=="A" else "Β"} · Διάλειμμα {n}: πρέπει να είναι μέσα στη βάρδια ({st}–{en})')
        for grp in ('A','B'):
            x=[c[2] for c in cells if c[0]==grp and c[2]['start']]
            if len(x)==2 and not (x[0]['end']<=x[1]['start'] or x[1]['end']<=x[0]['start']):
                raise HTTPException(422,f'{label} · Τμήμα {"Α" if grp=="A" else "Β"}: τα δύο διαλείμματα δεν πρέπει να επικαλύπτονται')
        payload[key]={'start':st,'end':en,'b1':cells[0][2],'b2':cells[1][2],'B':{'b1':cells[2][2],'b2':cells[3][2]}}
    old=row.value if row else None
    if row: row.value=json.dumps(payload,ensure_ascii=False)
    else: db.add(AppSetting(key=SCHEDULE_KEY,value=json.dumps(payload,ensure_ascii=False)))
    write_audit(db,user,'app_setting',SCHEDULE_KEY,'UPDATE',old={'schedule':old},new={'schedule':payload}); db.commit()
    return payload

@app.get('/settings/break-groups')
def break_groups_get(db:Session=Depends(get_db), user:User=Depends(current_user)):
    """Αντιστοίχιση Τμήματος -> ομάδα διαλειμμάτων (A|B). Τμήμα χωρίς εγγραφή = Α."""
    row=db.scalar(select(AppSetting).where(AppSetting.key==BREAK_GROUPS_KEY))
    try: m=json.loads(row.value) if row else {}
    except Exception: m={}
    return {k:v for k,v in m.items() if v in ('A','B')}

@app.put('/settings/break-groups')
def break_groups_put(data:dict, db:Session=Depends(get_db), user:User=Depends(require_permission('settings.manage'))):
    m={}
    for k,v in (data or {}).items():
        if v not in ('A','B'): raise HTTPException(422,'Η ομάδα διαλειμμάτων πρέπει να είναι Α ή Β')
        m[str(k)]=v
    row=db.scalar(select(AppSetting).where(AppSetting.key==BREAK_GROUPS_KEY))
    old=row.value if row else None
    if row: row.value=json.dumps(m,ensure_ascii=False)
    else: db.add(AppSetting(key=BREAK_GROUPS_KEY,value=json.dumps(m,ensure_ascii=False)))
    write_audit(db,user,'app_setting',BREAK_GROUPS_KEY,'UPDATE',old={'groups':old},new={'groups':m}); db.commit()
    return m

def _pick_folder_dialog(initial:str|None)->str|None:
    # Runs on the server's own desktop session (this app is always run interactively on the
    # office PC, same as the Electrocycle Playwright sync) -- a real native Windows folder
    # dialog, "Δημιουργία νέου φακέλου" included, since the browser itself has no way to hand
    # back a real filesystem path (the File System Access API deliberately hides it).
    import tkinter as tk
    from tkinter import filedialog
    root=tk.Tk(); root.withdraw(); root.attributes('-topmost',True)
    try:
        path=filedialog.askdirectory(title='Επιλογή φακέλου εξαγωγών', initialdir=(initial or None), mustexist=False)
    finally:
        root.destroy()
    return path or None

@app.post('/settings/export/browse')
async def export_settings_browse(data:dict|None=None, user:User=Depends(require_permission('settings.manage'))):
    path=await asyncio.to_thread(_pick_folder_dialog,(data or {}).get('initial'))
    return {'path':path}

@app.get('/settings/export')
def export_settings_get(db:Session=Depends(get_db), user:User=Depends(current_user)):
    return get_export_settings(db)

@app.put('/settings/export')
def export_settings_put(data:dict, db:Session=Depends(get_db), user:User=Depends(require_permission('settings.manage'))):
    path=(data.get('path') or '').strip()
    group=bool(data.get('group_by_month',True))
    if path:
        try:
            p=Path(path); p.mkdir(parents=True,exist_ok=True)
            probe=p/'.weee_export_test'; probe.write_text('ok',encoding='utf-8'); probe.unlink()
        except Exception as e:
            raise HTTPException(422,f'Ο φάκελος δεν είναι προσβάσιμος για εγγραφή: {e}')
    payload={'path':path or None,'group_by_month':group}
    row=db.scalar(select(AppSetting).where(AppSetting.key==EXPORT_DIR_KEY))
    old=row.value if row else None
    if row: row.value=json.dumps(payload,ensure_ascii=False)
    else: db.add(AppSetting(key=EXPORT_DIR_KEY,value=json.dumps(payload,ensure_ascii=False)))
    write_audit(db,user,'app_setting',EXPORT_DIR_KEY,'UPDATE',old={'export':old},new={'export':payload}); db.commit()
    return payload

# ---- Εμφάνιση περιγραφής υλικών (Επίσημη / Σύντομη) ανά οθόνη -- αποθηκεύεται στον server, ισχύει για ΟΛΕΣ τις συσκευές ----
MATERIAL_DESC_KEY='app.material_desc_modes'
MATERIAL_DESC_SCREENS=('ready','loading','inventory','reports','android')
MATERIAL_DESC_DEFAULTS={'ready':'official','loading':'official','inventory':'official','reports':'official','android':'short'}

def _material_desc_modes(db:Session)->dict:
    row=db.scalar(select(AppSetting).where(AppSetting.key==MATERIAL_DESC_KEY))
    try: saved=json.loads(row.value) if row else {}
    except Exception: saved={}
    return {k:(saved.get(k) if saved.get(k) in ('official','short') else MATERIAL_DESC_DEFAULTS[k]) for k in MATERIAL_DESC_SCREENS}

@app.get('/settings/material-desc')
def material_desc_get(db:Session=Depends(get_db), user:User=Depends(current_user)):
    return {'modes':_material_desc_modes(db)}

@app.put('/settings/material-desc')
def material_desc_put(data:dict, db:Session=Depends(get_db), user:User=Depends(require_permission('settings.manage'))):
    new=data.get('modes') if isinstance(data.get('modes'),dict) else {}
    for k,v in new.items():
        if k not in MATERIAL_DESC_SCREENS or v not in ('official','short'): raise HTTPException(422,'Μη έγκυρη επιλογή εμφάνισης')
    old=_material_desc_modes(db); merged={**old,**new}
    row=db.scalar(select(AppSetting).where(AppSetting.key==MATERIAL_DESC_KEY))
    if row: row.value=json.dumps(merged,ensure_ascii=False)
    else: db.add(AppSetting(key=MATERIAL_DESC_KEY,value=json.dumps(merged,ensure_ascii=False)))
    write_audit(db,user,'app_setting',MATERIAL_DESC_KEY,'UPDATE',old={'modes':old},new={'modes':merged}); db.commit()
    return {'modes':merged}

@app.get('/materials/short-names')
def material_short_names(db:Session=Depends(get_db), user:User=Depends(current_user)):
    """Υλικά που έχουν σύντομη περιγραφή: τα ονόματα με τα οποία εμφανίζονται στις οθόνες (επίσημη/εσωτερική/Galaxy) -> σύντομη."""
    rows=db.scalars(select(Material).where(Material.short_description.is_not(None))).all()
    return [{'id':m.id,'short':m.short_description.strip(),'names':[n for n in {m.official_description,m.internal_name,m.galaxy_description} if n]} for m in rows if (m.short_description or '').strip()]

@app.get('/settings/android')
def android_settings_get(db:Session=Depends(get_db), user:User=Depends(current_user)):
    row=db.scalar(select(AppSetting).where(AppSetting.key==ANDROID_WEEE_DESC_KEY))
    return {'weee_desc_mode':row.value if row and row.value in ('official','her') else 'official'}

@app.put('/settings/android')
def android_settings_put(data:dict, db:Session=Depends(get_db), user:User=Depends(require_permission('settings.manage'))):
    mode=data.get('weee_desc_mode')
    if mode not in ('official','her'): raise HTTPException(422,'Μη έγκυρη επιλογή εμφάνισης')
    row=db.scalar(select(AppSetting).where(AppSetting.key==ANDROID_WEEE_DESC_KEY))
    old=row.value if row else None
    if row: row.value=mode
    else: db.add(AppSetting(key=ANDROID_WEEE_DESC_KEY,value=mode))
    write_audit(db,user,'app_setting',ANDROID_WEEE_DESC_KEY,'UPDATE',old={'weee_desc_mode':old},new={'weee_desc_mode':mode}); db.commit()
    return {'weee_desc_mode':mode}

@app.get('/inventory/weee/media-summary')
def weee_media_summary(db:Session=Depends(get_db), user=Depends(require_permission('production.view'))):
    """Available WEEE stock lots pooled per official category family and per collection-medium type."""
    cats={c.id:c for c in db.scalars(select(WEEECategory)).all()}
    media={m.id:m for m in db.scalars(select(CollectionMedium)).all()}
    types={t.id:t for t in db.scalars(select(CollectionMediumType)).all()}
    fam={}; used={}
    for lot in db.scalars(select(WEEEStockLot).where(WEEEStockLot.available_weight>0)).all():
        c=cats.get(lot.weee_category_id)
        if not c: continue
        m=media.get(lot.collection_medium_id) if lot.collection_medium_id else None; t=types.get(m.type_id) if m else None
        if t and t.code=='BULK': m=None; t=None      # το Χύμα είναι ΜΙΑ ομάδα (και οι παλιές εγγραφές BULK-… μετράνε ως Χύμα)
        key=t.id if t else 'NONE'; used[key]=(t.name_el if t else 'Χύμα / χωρίς μέσο', t.code if t else 'NONE')
        d=fam.setdefault(_weee_family_code(c),{}); d[key]=round(d.get(key,0)+float(lot.available_weight or 0),3)
    order=['BASKET_SMALL','BASKET_LARGE','INFOCYCLE_1','INFOCYCLE_2','SACK_1KG','SACK_2KG_UN','PALLET','BOX','BULK','NONE']
    tl=sorted(({'key':k,'name':v[0],'code':v[1]} for k,v in used.items()),key=lambda x:(order.index(x['code']) if x['code'] in order else 90,x['name']))
    return {'types':tl,'families':fam}

@app.get('/inventory/weee/media-detail')
def weee_media_detail(official_code:str, type_key:str, db:Session=Depends(get_db), user=Depends(require_permission('production.view'))):
    """Media of one type that currently hold a category family, with the kg of that family in each."""
    ids={c.id for c in db.scalars(select(WEEECategory)).all() if _weee_family_code(c)==official_code}
    media={m.id:m for m in db.scalars(select(CollectionMedium)).all()}
    types={t.id:t for t in db.scalars(select(CollectionMediumType)).all()}
    groups={}; type_name='Χύμα / χωρίς μέσο'
    for lot in db.scalars(select(WEEEStockLot).where(WEEEStockLot.available_weight>0)).all():
        if lot.weee_category_id not in ids: continue
        m=media.get(lot.collection_medium_id) if lot.collection_medium_id else None; t=types.get(m.type_id) if m else None
        if t and t.code=='BULK': m=None; t=None      # Χύμα = μία γραμμή, χωρίς αριθμό
        if (t.id if t else 'NONE')!=type_key: continue
        if t: type_name=t.name_el
        g=groups.setdefault(lot.collection_medium_id or 'NONE' if not (m is None) else 'NONE',{'medium_id':lot.collection_medium_id if m else None,'code':m.code if m else 'Χύμα','kg':0.0})
        g['kg']=round(g['kg']+float(lot.available_weight or 0),3)
    def natural(x):
        import re
        return [int(p) if p.isdigit() else p.lower() for p in re.split(r'(\d+)',str(x['code']))]
    out=sorted(groups.values(),key=natural)
    return {'official_code':official_code,'type':type_name,'total':round(sum(x['kg'] for x in out),3),'media':out}

def _non_weee_cats(db):
    import re as _re
    return {c.id:c for c in db.scalars(select(WEEECategory)).all() if _re.fullmatch(r'\d{6}',str(c.code))}

@app.get('/inventory/weee/non-weee-summary')
def weee_non_weee_summary(start:str=Query(pattern=r'^\d{4}-\d{2}-\d{2}$'), end:str=Query(pattern=r'^\d{4}-\d{2}-\d{2}$'), db:Session=Depends(get_db), user=Depends(require_permission('production.view'))):
    """Pieces of the non-WEEE materials (codes 109991-109994 type A, 119999 type B): received in the period and still in stock."""
    s=datetime.fromisoformat(start); e=datetime.fromisoformat(end)+timedelta(days=1)
    cats=_non_weee_cats(db); out={c.code:{'pieces_period':0,'pieces_stock':0} for c in cats.values()}
    if not cats: return out
    rows=db.execute(select(models.SortingEntry,InboundTrip).join(SortingSession,models.SortingEntry.session_id==SortingSession.id).join(InboundLoad,SortingSession.inbound_load_id==InboundLoad.id).join(InboundTrip,InboundLoad.trip_id==InboundTrip.id).where(InboundTrip.receipt_date>=s,InboundTrip.receipt_date<e,InboundTrip.deleted_at.is_(None),models.SortingEntry.weee_category_id.in_(list(cats)))).all()
    for en,_trip in rows: out[cats[en.weee_category_id].code]['pieces_period']+=int(en.piece_count or 0)
    for lot in db.scalars(select(WEEEStockLot).where(WEEEStockLot.available_weight>0,WEEEStockLot.weee_category_id.in_(list(cats)))).all():
        orig=float(lot.original_weight or 0)
        if lot.piece_count and orig>0: out[cats[lot.weee_category_id].code]['pieces_stock']+=int(round(lot.piece_count*float(lot.available_weight or 0)/orig))
    return out

@app.get('/inventory/weee/category-history')
def weee_category_history(official_code:str, db:Session=Depends(get_db), user=Depends(require_permission('production.view'))):
    ids=[c.id for c in db.scalars(select(WEEECategory).where(WEEECategory.code==official_code)).all()]
    if not ids: raise HTTPException(404,'Άγνωστη κατηγορία')
    cat=db.get(WEEECategory,ids[0])
    labels={'SORTING_IN':'Εισαγωγή από ταξινόμηση','TO_PRODUCTION':'Προς παραγωγή','DIRECT_TO_PRODUCTION':'Απευθείας προς παραγωγή','DISPATCH':'Αποστολή','PRODUCTION_OUT':'Έξοδος από παραγωγή','DIRECT_PRODUCTION_OUT':'Απευθείας έξοδος από παραγωγή'}
    events=[]; pieces_stock=0
    for lot in db.scalars(select(WEEEStockLot).where(WEEEStockLot.weee_category_id.in_(ids)).order_by(WEEEStockLot.created_at)).all():
        load=db.get(InboundLoad,lot.inbound_load_id); trip=db.get(InboundTrip,load.trip_id) if load else None
        if trip and trip.deleted_at is not None: continue
        sup=db.get(Organization,load.supplier_id) if load else None; orig=float(lot.original_weight or 0)
        if lot.piece_count and orig>0 and float(lot.available_weight or 0)>0: pieces_stock+=int(round(lot.piece_count*float(lot.available_weight or 0)/orig))
        for mv in db.scalars(select(StockMovement).where(StockMovement.lot_id==lot.id).order_by(StockMovement.created_at)).all():
            unit=db.get(OrganizationalUnit,mv.org_unit_id) if mv.org_unit_id else None
            at=trip.receipt_date if (mv.movement_type=='SORTING_IN' and trip) else mv.created_at
            events.append({'at':at.isoformat(),'label':labels.get(mv.movement_type,mv.movement_type),'weight':(1 if mv.movement_type=='SORTING_IN' else -1)*float(mv.weight or 0),
              'pieces':lot.piece_count if mv.movement_type=='SORTING_IN' else None,'supplier':((sup.trade_name or sup.legal_name) if sup else ''),'order_number':load.order_number if load else None,
              'unit':unit.name_el if unit else None,'reason':mv.reason})
    for pe in db.scalars(select(ProductionWorkEntry).where(ProductionWorkEntry.weee_category_id.in_(ids),ProductionWorkEntry.active==True)).all():
        unit=db.get(OrganizationalUnit,pe.org_unit_id) if pe.org_unit_id else None
        events.append({'at':pe.work_date.isoformat(),'label':'Επεξεργασία (Παραγωγή)','weight':-float(pe.weight_kg or 0),'pieces':None,'supplier':'','order_number':None,'unit':unit.name_el if unit else None,'reason':pe.notes})
    events.sort(key=lambda x:x['at'],reverse=True)
    return {'category':{'code':cat.code,'description':cat.description_el},'pieces_stock':pieces_stock,'events':events}

@app.get('/inventory/weee/medium/{medium_id}/history')
def weee_medium_history(medium_id:str, db:Session=Depends(get_db), user=Depends(require_permission('production.view'))):
    med=db.get(CollectionMedium,medium_id)
    if not med: raise HTTPException(404,'Το μέσο συλλογής δεν βρέθηκε')
    mt=db.get(CollectionMediumType,med.type_id)
    labels={'SORTING_IN':'Εισαγωγή από ταξινόμηση','TO_PRODUCTION':'Προς παραγωγή','DIRECT_TO_PRODUCTION':'Απευθείας προς παραγωγή','DISPATCH':'Αποστολή','PRODUCTION_OUT':'Έξοδος από παραγωγή','DIRECT_PRODUCTION_OUT':'Απευθείας έξοδος από παραγωγή'}
    events=[]; current=0.0
    for lot in db.scalars(select(WEEEStockLot).where(WEEEStockLot.collection_medium_id==medium_id).order_by(WEEEStockLot.created_at)).all():
        load=db.get(InboundLoad,lot.inbound_load_id); trip=db.get(InboundTrip,load.trip_id) if load else None
        if trip and trip.deleted_at is not None: continue
        cat=db.get(WEEECategory,lot.weee_category_id); sup=db.get(Organization,load.supplier_id) if load else None
        current+=float(lot.available_weight or 0)
        for mv in db.scalars(select(StockMovement).where(StockMovement.lot_id==lot.id).order_by(StockMovement.created_at)).all():
            unit=db.get(OrganizationalUnit,mv.org_unit_id) if mv.org_unit_id else None
            at=trip.receipt_date if (mv.movement_type=='SORTING_IN' and trip) else mv.created_at
            events.append({'at':at.isoformat(),'type':mv.movement_type,'label':labels.get(mv.movement_type,mv.movement_type),'weight':(1 if mv.movement_type=='SORTING_IN' else -1)*float(mv.weight or 0),
              'category':cat.code if cat else '','description':cat.description_el if cat else '','supplier':((sup.trade_name or sup.legal_name) if sup else ''),'order_number':load.order_number if load else None,
              'unit':unit.name_el if unit else None,'reason':mv.reason})
    events.sort(key=lambda e:e['at'],reverse=True)
    return {'medium':{'id':med.id,'code':med.code,'type':mt.name_el if mt else '','tare_weight':float(med.tare_weight) if med.tare_weight is not None else None},'current_weight':round(current,3),'events':events}

@app.get('/inventory/weee/category/{category_id}/positions')
def weee_category_positions(category_id:str, db:Session=Depends(get_db), user=Depends(require_permission('production.view'))):
    cat=db.get(WEEECategory,category_id)
    if not cat: raise HTTPException(404,'Άγνωστη κατηγορία ΑΗΗΕ')
    lots=db.scalars(select(WEEEStockLot).where(WEEEStockLot.weee_category_id==category_id,WEEEStockLot.available_weight>0).order_by(WEEEStockLot.created_at)).all()
    groups={}
    for lot in lots:
        med=db.get(CollectionMedium,lot.collection_medium_id) if lot.collection_medium_id else None
        mt=db.get(CollectionMediumType,med.type_id) if med else None
        key=lot.collection_medium_id or 'BULK'
        g=groups.setdefault(key,{'medium_id':lot.collection_medium_id,'medium_type':mt.name_el if mt else 'Χύμα / χωρίς αριθμημένο μέσο','medium_code':med.code if med else 'Χύμα','net_weight':0.0,'lots':[]})
        g['net_weight']+=float(lot.available_weight or 0)
        load=db.get(InboundLoad,lot.inbound_load_id); trip=db.get(InboundTrip,load.trip_id) if load else None
        sup=db.get(Organization,load.supplier_id) if load else None; carrier=db.get(Organization,trip.carrier_id) if trip and trip.carrier_id else None
        entry=db.get(SortingEntry,lot.source_sorting_entry_id); ses=db.get(SortingSession,entry.session_id) if entry else None
        g['lots'].append({'lot_id':lot.id,'weight':float(lot.available_weight or 0),'supplier':(sup.trade_name or sup.legal_name) if sup else '',
          'carrier':(carrier.trade_name or carrier.legal_name) if carrier else '',
          'receipt_date':trip.receipt_date.isoformat() if trip else None,
          'sorting_date':((ses.sorting_confirmed_at or entry.created_at).isoformat()) if entry else None,
          'order_number':load.order_number if load else None})
    out=list(groups.values())
    for g in out: g['net_weight']=round(g['net_weight'],3)
    out.sort(key=lambda x:(x['medium_type'],x['medium_code']))
    return {'category_id':cat.id,'category':cat.code,'description':cat.description_el,'total_weight':round(sum(x['net_weight'] for x in out),3),'positions':out}

@app.get('/inventory/weee', response_model=list[schemas.WEEEStockLotOut])
def weee_inventory(available_only:bool=True, db:Session=Depends(get_db), user=Depends(require_permission('production.view'))):
    q=select(WEEEStockLot).order_by(WEEEStockLot.created_at,WEEEStockLot.id)
    if available_only: q=q.where(WEEEStockLot.available_weight>0)
    return [_lot_out(db,x) for x in db.scalars(q).all()]

@app.get('/inventory/weee/media-with-stock')
def weee_media_with_stock(db:Session=Depends(get_db), user=Depends(require_permission('production.view'))):
    # Mirror of weee_category_positions() (grouped by medium instead of by category) -- used by the
    # Android ΜΕΤΑΦΟΡΑ ΥΛΙΚΟΥ flow's "ΜΕΣΟ ΣΥΛΛΟΓΗΣ πρώτα" direction. Not filtered by processable/ΜΗ
    # ΑΗΗΕ here -- the frontend already owns that decision via isProducedCat(), same as every other
    # production category picker (see [[production_excludes_unprocessed_materials]]).
    lots=db.scalars(select(WEEEStockLot).where(WEEEStockLot.available_weight>0)).all()
    # Φόρτωση μία φορά (όχι ένα ερώτημα ανά μερίδιο): με χιλιάδες μερίδια το παλιό έκανε 5–7″
    _meds={m.id:m for m in db.scalars(select(CollectionMedium)).all()}; _mts={t.id:t for t in db.scalars(select(CollectionMediumType)).all()}; _cats={c.id:c for c in db.scalars(select(WEEECategory)).all()}
    groups={}
    for lot in lots:
        med=_meds.get(lot.collection_medium_id) if lot.collection_medium_id else None
        mt=_mts.get(med.type_id) if med else None
        cat=_cats[lot.weee_category_id]
        key=lot.collection_medium_id or 'BULK'
        g=groups.setdefault(key,{'medium_id':lot.collection_medium_id,'medium_type':mt.name_el if mt else 'Χύμα / χωρίς αριθμημένο μέσο','medium_type_code':mt.code if mt else 'BULK','medium_code':med.code if med else 'Χύμα','is_closed':bool(med.is_closed) if med else False,'total_weight':0.0,'categories':{}})
        g['total_weight']+=float(lot.available_weight or 0)
        c=g['categories'].setdefault(cat.id,{'category_id':cat.id,'code':cat.code,'description':cat.description_el,'weight':0.0})
        c['weight']+=float(lot.available_weight or 0)
    out=[]
    for g in groups.values():
        g['total_weight']=round(g['total_weight'],3)
        g['categories']=sorted(({**c,'weight':round(c['weight'],3)} for c in g['categories'].values()),key=lambda x:x['code'])
        out.append(g)
    out.sort(key=lambda x:(x['medium_type'],x['medium_code']))
    return out

@app.get('/inventory/weee/by-medium/{medium_id}')
def weee_inventory_medium(medium_id:str, db:Session=Depends(get_db), user=Depends(require_permission('production.view'))):
    # medium_id='BULK' is the synthetic "Χύμα" bucket (collection_medium_id IS NULL), matching the key
    # weee_category_positions()/weee_media_with_stock() already use for it. Response shape mirrors
    # weee_category_positions() (grouped by category instead of by medium) for frontend consistency.
    if medium_id=='BULK':
        med=None; lots=db.scalars(select(WEEEStockLot).where(WEEEStockLot.collection_medium_id.is_(None),WEEEStockLot.available_weight>0)).all()
    else:
        med=db.get(CollectionMedium,medium_id)
        if not med: raise HTTPException(404,'Το μέσο συλλογής δεν βρέθηκε')
        lots=db.scalars(select(WEEEStockLot).where(WEEEStockLot.collection_medium_id==medium_id,WEEEStockLot.available_weight>0)).all()
    groups={}
    for lot in lots:
        cat=db.get(WEEECategory,lot.weee_category_id)
        g=groups.setdefault(cat.id,{'category_id':cat.id,'code':cat.code,'description':cat.description_el,'weight':0.0})
        g['weight']+=float(lot.available_weight or 0)
    out=sorted(({**c,'weight':round(c['weight'],3)} for c in groups.values()),key=lambda x:x['code'])
    return {'medium_id':medium_id if medium_id!='BULK' else None,'medium_code':med.code if med else 'Χύμα','total_weight':round(sum(x['weight'] for x in out),3),'categories':out}

from decimal import ROUND_HALF_UP
def _round_kg(x):
    """Κανόνας ταξινόμησης: κάθε καταχώρηση αποθηκεύεται σε ΑΚΕΡΑΙΑ kg (από ,50 και πάνω ανεβαίνει, μέχρι ,49 κατεβαίνει). Δεν στρογγυλεύονται σύνολα."""
    if x is None: return None
    r=Decimal(x).quantize(Decimal('1'),rounding=ROUND_HALF_UP)
    if r<=0 and Decimal(x)>0: raise HTTPException(422,'Το βάρος είναι μικρότερο από 0,5 kg και στρογγυλεύεται σε 0 -- δεν μπορεί να καταχωρηθεί')
    return r

def _transfer_number(db:Session)->str:
    year=datetime.now().year
    rows=db.scalars(select(ProductionTransfer).where(ProductionTransfer.transfer_number.like(f'PRD-{year}-%'))).all()
    return f'PRD-{year}-{len(rows)+1:06d}'

def _consume_lot(db:Session, transfer_id:str, lot, qty, unit, user:User, notes:str|None):
    before=lot.available_weight; lot.available_weight=before-qty
    lot.status='CONSUMED' if lot.available_weight==0 else 'PARTIAL'
    _m=db.get(CollectionMedium,lot.collection_medium_id) if lot.collection_medium_id else None
    _tare=None
    if _m is not None:
        _tare=_m.tare_weight
        if _tare is None:
            _ty=db.get(CollectionMediumType,_m.type_id); _tare=_ty.default_tare_weight if _ty else None
    ti=ProductionTransferItem(transfer_id=transfer_id,stock_lot_id=lot.id,weight=qty,sent_weight=qty,tare_weight=_tare)   # το απόβαρο ΜΕΝΕΙ όπως ήταν την ώρα της αποστολής
    db.add(ti); db.flush()
    db.add(ProductionInputBalance(transfer_item_id=ti.id,org_unit_id=unit.id,initial_weight=qty,current_remaining_weight=qty,status='OPEN'))
    db.add(StockMovement(domain='WEEE',lot_id=lot.id,movement_type='TO_PRODUCTION',from_location_id=lot.location_id,to_location_id=None,
        weight=qty,org_unit_id=unit.id,user_id=user.id,reason=notes,created_at=_event_now()))
    cat=db.get(WEEECategory,lot.weee_category_id); medium=db.get(CollectionMedium,lot.collection_medium_id) if lot.collection_medium_id else None
    return schemas.ProductionTransferItemOut(stock_lot_id=lot.id,weight=qty,weee_code=cat.code,medium_code=medium.code if medium else None), lot.collection_medium_id

def _update_medium_lifecycle(db:Session, medium_ids:set):
    # Medium lifecycle: only mark as in production when every stock lot currently attached to it is exhausted from WEEE warehouse.
    for mid in medium_ids:
        if not mid: continue
        remaining=db.scalars(select(WEEEStockLot).where(WEEEStockLot.collection_medium_id==mid,WEEEStockLot.available_weight>0)).all()
        medium=db.get(CollectionMedium,mid)
        if medium and not remaining: medium.status='IN_PRODUCTION'

def _consume_weee_stock_for_category(db:Session, unit, category_id:str, weight, user:User, notes:str|None):
    """Auto-selects available WEEEStockLot rows for a category (oldest first) and consumes up to
    `weight` across as many lots as needed, creating a ProductionTransfer the same way a manual
    /production/transfers call would. Used by the Δελτίο Παραγωγής day-material entry, where the
    operator just types a material+kg instead of picking physical lots one by one. Returns the
    actually-consumed weight, which can be LESS than requested if sorting hasn't produced enough
    stock yet -- callers tolerate that (same "flag, don't block" convention as prodVal/flagNegativeKg
    elsewhere) rather than rejecting the entry."""
    from decimal import Decimal
    remaining=Decimal(weight)
    if remaining<=0: return Decimal(0)
    transfer=ProductionTransfer(transfer_number=_transfer_number(db),destination_org_unit_id=unit.id,created_by=user.id,notes=notes,created_at=_event_now(),present_json=_present_snapshot(db,unit.id,_event_now_local()))
    db.add(transfer); db.flush()
    lots=db.scalars(select(WEEEStockLot).where(WEEEStockLot.weee_category_id==category_id,WEEEStockLot.available_weight>0).order_by(WEEEStockLot.created_at)).all()
    consumed=Decimal(0); medium_ids=set()
    for lot in lots:
        if remaining<=0: break
        qty=min(lot.available_weight, remaining)
        _,mid=_consume_lot(db,transfer.id,lot,qty,unit,user,notes)
        medium_ids.add(mid); consumed+=qty; remaining-=qty
    _update_medium_lifecycle(db, medium_ids)
    if consumed>0: write_audit(db,user,'production_transfer',transfer.id,'CREATE',new={'transfer_number':transfer.transfer_number,'destination':unit.code,'auto':True,'weight':str(consumed)})
    return consumed

@app.post('/production/transfers', response_model=schemas.ProductionTransferOut)
def production_transfer(data:schemas.ProductionTransferCreate, db:Session=Depends(get_db), user:User=Depends(require_permission('production.move'))):
    unit=db.get(OrganizationalUnit,data.destination_org_unit_id)
    if not unit or not unit.active: raise HTTPException(422,'Άγνωστο ή ανενεργό τμήμα/υποτμήμα')
    if not data.items: raise HTTPException(422,'Δεν επιλέχθηκαν υλικά')
    transfer=ProductionTransfer(transfer_number=_transfer_number(db),destination_org_unit_id=unit.id,created_by=user.id,notes=data.notes,created_at=_event_now(),present_json=_present_snapshot(db,unit.id,_event_now_local()))
    db.add(transfer); db.flush(); out=[]; medium_ids=set()
    for req in data.items:
        lot=db.get(WEEEStockLot,req.stock_lot_id)
        if not lot or lot.available_weight<=0: raise HTTPException(409,'Το επιλεγμένο απόθεμα δεν είναι πλέον διαθέσιμο')
        qty=lot.available_weight if req.weight is None else req.weight
        if qty<=0 or qty>lot.available_weight: raise HTTPException(422,'Μη έγκυρη ποσότητα προς παραγωγή')
        item_out,mid=_consume_lot(db,transfer.id,lot,qty,unit,user,data.notes)
        out.append(item_out); medium_ids.add(mid)
    _update_medium_lifecycle(db, medium_ids)
    # Ένα βήμα (όλο ή τίποτα): μετακίνηση εργαζομένου + καταχώρηση παραγωγής μαζί με τη μεταφορά
    if data.place_employee_id:
        pe=db.get(Employee,data.place_employee_id)
        if not pe: raise HTTPException(404,'Ο εργαζόμενος δεν βρέθηκε')
        _replace_employee_units(db,pe,[unit.id]+[x for x in _emp_unit_ids(db,pe) if x!=unit.id])
        write_audit(db,user,'employee',pe.id,'PLACE_WITH_TRANSFER',new={'unit':unit.code})
    we_id=None
    if data.work_entry:
        w=data.work_entry
        if w.employee_id and not db.get(Employee,w.employee_id): raise HTTPException(404,'Ο εργαζόμενος δεν βρέθηκε')
        if not db.get(WEEECategory,w.weee_category_id): raise HTTPException(404,'Η κατηγορία ΑΗΗΕ δεν βρέθηκε')
        total=sum((Decimal(str(o.weight)) for o in out),Decimal(0))
        we=ProductionWorkEntry(created_at=_event_now(),work_date=w.work_date or _event_now_aware(),org_unit_id=unit.id,employee_id=w.employee_id,weee_category_id=w.weee_category_id,weight_kg=w.weight_kg if w.weight_kg is not None else total,source=w.source or "WINDOWS",notes=w.notes,transfer_id=transfer.id,created_by_user_id=user.id)
        db.add(we); db.flush(); we_id=we.id
    write_audit(db,user,'production_transfer',transfer.id,'CREATE',new={'transfer_number':transfer.transfer_number,'destination':unit.code,'items':len(out)})
    db.commit(); return schemas.ProductionTransferOut(id=transfer.id,transfer_number=transfer.transfer_number,destination_org_unit_id=unit.id,status=transfer.status,items=out,work_entry_id=we_id)

def _reverse_transfer_item(db:Session, ti, qty, unit_id:str|None, user:User, reason:str|None):
    """Επιστρέφει `qty` kg ενός στοιχείου μεταφοράς στο απόθεμα ΑΗΗΕ (αντίστροφο του _consume_lot)."""
    lot=db.get(WEEEStockLot,ti.stock_lot_id)
    lot.available_weight=lot.available_weight+qty
    lot.status='AVAILABLE' if lot.available_weight>=lot.original_weight else 'PARTIAL'
    bal=db.scalar(select(ProductionInputBalance).where(ProductionInputBalance.transfer_item_id==ti.id))
    if bal:
        bal.initial_weight=bal.initial_weight-qty; bal.current_remaining_weight=bal.current_remaining_weight-qty
        if bal.initial_weight<=0: bal.status='CANCELLED'
    db.add(StockMovement(domain='WEEE',lot_id=lot.id,movement_type='CANCEL_TO_PRODUCTION',from_location_id=None,to_location_id=lot.location_id,
        weight=qty,org_unit_id=unit_id,user_id=user.id,reason=reason))
    return lot.collection_medium_id

def _restore_medium_lifecycle(db:Session, medium_ids:set):
    db.flush()   # τα επιστρεφόμενα κιλά των μεριδίων πρέπει να φαίνονται στο ερώτημα παρακάτω
    for mid in medium_ids:
        if not mid: continue
        medium=db.get(CollectionMedium,mid)
        if medium and medium.status=='IN_PRODUCTION' and db.scalars(select(WEEEStockLot).where(WEEEStockLot.collection_medium_id==mid,WEEEStockLot.available_weight>0)).first():
            medium.status='WEEE_STORAGE'   # ξαναγεμάτο μέσο = όπως όταν γέμισε από την Ταξινόμηση (όχι «διαθέσιμο/άδειο»)

def _transfer_items_checked(db:Session, transfer_id:str):
    items=db.scalars(select(ProductionTransferItem).where(ProductionTransferItem.transfer_id==transfer_id)).all()
    bals={b.transfer_item_id:b for b in db.scalars(select(ProductionInputBalance).where(ProductionInputBalance.transfer_item_id.in_([i.id for i in items]))).all()} if items else {}
    return items,bals

@app.post('/production/transfers/{transfer_id}/cancel')
def cancel_production_transfer(transfer_id:str, db:Session=Depends(get_db), user:User=Depends(require_permission('production.move'))):
    """Αναίρεση μεταφοράς υλικού: το απόθεμα επιστρέφει στα ίδια μερίδια και η καταχώρηση παραγωγής ακυρώνεται."""
    t=db.get(ProductionTransfer,transfer_id)
    if not t: raise HTTPException(404,'Η μεταφορά δεν βρέθηκε')
    if t.status=='CANCELLED': raise HTTPException(409,'Η μεταφορά έχει ήδη ακυρωθεί')
    items,bals=_transfer_items_checked(db,t.id)
    for ti in items:
        b=bals.get(ti.id)
        if b and b.current_remaining_weight<ti.weight: raise HTTPException(409,'Μέρος του υλικού έχει ήδη χρησιμοποιηθεί στην παραγωγή -- δεν μπορεί να αναιρεθεί')
    medium_ids=set()
    for ti in items: medium_ids.add(_reverse_transfer_item(db,ti,ti.weight,t.destination_org_unit_id,user,'Αναίρεση μεταφοράς '+t.transfer_number))
    _restore_medium_lifecycle(db,medium_ids)
    t.status='CANCELLED'
    for e in db.scalars(select(ProductionWorkEntry).where(ProductionWorkEntry.transfer_id==t.id,ProductionWorkEntry.active==True)).all(): e.active=False
    write_audit(db,user,'production_transfer',t.id,'CANCEL',old={'status':'CONFIRMED'},new={'status':'CANCELLED','items':len(items)})
    db.commit(); return {'ok':True,'transfer_number':t.transfer_number}

@app.put('/production/transfers/{transfer_id}/weight')
def set_production_transfer_weight(transfer_id:str, data:schemas.TransferWeightIn, db:Session=Depends(get_db), user:User=Depends(require_permission('production.move'))):
    """Διόρθωση kg μιας μεταφοράς: λιγότερα -> επιστρέφει τη διαφορά στο απόθεμα (από τα τελευταία μερίδια)· περισσότερα -> παίρνει επιπλέον από το διαθέσιμο απόθεμα της ίδιας κατηγορίας."""
    from decimal import Decimal
    t=db.get(ProductionTransfer,transfer_id)
    if not t or t.status=='CANCELLED': raise HTTPException(404,'Η μεταφορά δεν βρέθηκε')
    entry=db.scalar(select(ProductionWorkEntry).where(ProductionWorkEntry.transfer_id==t.id,ProductionWorkEntry.active==True))
    if not entry: raise HTTPException(404,'Δεν βρέθηκε καταχώρηση παραγωγής για τη μεταφορά')
    new=Decimal(data.weight)
    if new<=0: raise HTTPException(422,'Τα κιλά πρέπει να είναι μεγαλύτερα από 0 (για διαγραφή χρησιμοποίησε αναίρεση)')
    items,bals=_transfer_items_checked(db,t.id)
    old=sum((i.weight for i in items),Decimal(0)); unit=db.get(OrganizationalUnit,t.destination_org_unit_id); medium_ids=set()
    if new<old:
        diff=old-new
        for ti in reversed(items):
            if diff<=0: break
            take=min(ti.weight,diff); b=bals.get(ti.id)
            if b and b.current_remaining_weight<take: raise HTTPException(409,'Μέρος του υλικού έχει ήδη χρησιμοποιηθεί στην παραγωγή')
            medium_ids.add(_reverse_transfer_item(db,ti,take,unit.id,user,'Διόρθωση kg μεταφοράς '+t.transfer_number)); ti.weight=ti.weight-take; diff-=take
        _restore_medium_lifecycle(db,medium_ids)
    elif new>old:
        need=new-old
        first=db.get(WEEEStockLot,items[0].stock_lot_id) if items else None
        lots=db.scalars(select(WEEEStockLot).where(WEEEStockLot.weee_category_id==entry.weee_category_id,WEEEStockLot.available_weight>0).order_by(WEEEStockLot.created_at)).all()
        if first: lots.sort(key=lambda l:(l.collection_medium_id!=first.collection_medium_id))
        if sum((l.available_weight for l in lots),Decimal(0))<need: raise HTTPException(409,'Δεν υπάρχει αρκετό διαθέσιμο απόθεμα')
        for lot in lots:
            if need<=0: break
            qty=min(lot.available_weight,need); _,mid=_consume_lot(db,t.id,lot,qty,unit,user,'Διόρθωση kg μεταφοράς'); medium_ids.add(mid); need-=qty
        _update_medium_lifecycle(db,medium_ids)
    entry.weight_kg=new
    write_audit(db,user,'production_transfer',t.id,'WEIGHT_CHANGE',old={'weight':str(old)},new={'weight':str(new)},reason=data.reason)
    db.commit(); return {'ok':True,'weight':str(new)}

@app.get('/production/transfer-media')
def production_transfer_media(days:int=Query(default=3,ge=1,le=60), db:Session=Depends(get_db), user=Depends(require_permission("production.view"))):
    """Ποιο μέσο συλλογής χρησιμοποιήθηκε σε κάθε μεταφορά υλικού (τελευταίες N ημέρες) -- για τη λίστα «Σημερινές καταχωρήσεις» του Android. Μόνο ανάγνωση."""
    since=datetime.utcnow()-timedelta(days=days)
    rows=db.execute(select(models.ProductionTransferItem.transfer_id,models.CollectionMediumType.code,models.CollectionMedium.code)
        .join(models.ProductionTransfer,models.ProductionTransfer.id==models.ProductionTransferItem.transfer_id)
        .join(models.WEEEStockLot,models.WEEEStockLot.id==models.ProductionTransferItem.stock_lot_id)
        .outerjoin(models.CollectionMedium,models.CollectionMedium.id==models.WEEEStockLot.collection_medium_id)
        .outerjoin(models.CollectionMediumType,models.CollectionMediumType.id==models.CollectionMedium.type_id)
        .where(models.ProductionTransfer.created_at>=since)).all()
    out={}
    for tid,tcode,mcode in rows:
        it={"type_code":tcode or 'BULK',"code":mcode}
        lst=out.setdefault(tid,[])
        if it not in lst: lst.append(it)
    return out

@app.get('/production/transfer-history')
def production_transfer_history(days:int=Query(default=60,ge=1,le=365), db:Session=Depends(get_db), user=Depends(require_permission("production.view"))):
    """Ιστορικό μεταφορών υλικού ανά τμήμα (τελευταίες N ημέρες): τμήμα προορισμού, κατηγορία ΑΗΗΕ, τύπος μέσου, πλήθος, πιο πρόσφατη.
    Μόνο ανάγνωση -- τροφοδοτεί τα «Προτεινόμενα μέσα» της Μεταφοράς υλικού στο Android."""
    since=datetime.utcnow()-timedelta(days=days)
    rows=db.execute(select(models.ProductionTransfer.destination_org_unit_id,models.WEEEStockLot.weee_category_id,models.CollectionMediumType.code,models.ProductionTransfer.created_at)
        .join(models.ProductionTransferItem,models.ProductionTransferItem.transfer_id==models.ProductionTransfer.id)
        .join(models.WEEEStockLot,models.WEEEStockLot.id==models.ProductionTransferItem.stock_lot_id)
        .outerjoin(models.CollectionMedium,models.CollectionMedium.id==models.WEEEStockLot.collection_medium_id)
        .outerjoin(models.CollectionMediumType,models.CollectionMediumType.id==models.CollectionMedium.type_id)
        .where(models.ProductionTransfer.created_at>=since,models.ProductionTransfer.status!='CANCELLED')).all()
    agg={}
    for unit,cat,tcode,at in rows:
        k=(unit,cat,tcode or 'BULK'); d=agg.setdefault(k,{"unit_id":unit,"category_id":cat,"medium_type_code":tcode or 'BULK',"n":0,"last_at":None})
        d["n"]+=1
        iso=at.isoformat() if at else None
        if iso and (d["last_at"] is None or iso>d["last_at"]): d["last_at"]=iso
    return list(agg.values())

@app.get('/production/transfers', response_model=list[schemas.ProductionTransferOut])
def production_transfers(db:Session=Depends(get_db), user=Depends(require_permission('production.view'))):
    rows=db.scalars(select(ProductionTransfer).order_by(ProductionTransfer.created_at.desc())).all(); result=[]
    for t in rows:
        items=[]
        for i in db.scalars(select(ProductionTransferItem).where(ProductionTransferItem.transfer_id==t.id)).all():
            lot=db.get(WEEEStockLot,i.stock_lot_id); cat=db.get(WEEECategory,lot.weee_category_id); med=db.get(CollectionMedium,lot.collection_medium_id) if lot.collection_medium_id else None
            items.append(schemas.ProductionTransferItemOut(stock_lot_id=lot.id,weight=i.weight,weee_code=cat.code,medium_code=med.code if med else None))
        result.append(schemas.ProductionTransferOut(id=t.id,transfer_number=t.transfer_number,destination_org_unit_id=t.destination_org_unit_id,status=t.status,items=items))
    return result

def _present_snapshot(db:Session, unit_id:str, now=None)->str:
    """Στιγμιότυπο «ποιοι ήταν παρόντες στο τμήμα τώρα» (ΜΟΝΟ αποθήκευση, για μελλοντικές αναφορές παραγωγικότητας -- δεν αλλάζει κανένα kg).
    Παρών = ανήκει στο τμήμα, κατάσταση ΠΑΡΩΝ (όχι ΑΠΩΝ/ΕΦΥΓΕ), αν είναι σε αργοπορία έχει ήδη φτάσει, και δεν είναι σε ολιγόωρη απουσία αυτή τη στιγμή.
    Χωρίς εγγραφή παρουσίας για σήμερα = ΠΑΡΩΝ (όπως στο Δελτίο)."""
    now=now or datetime.now(); today=datetime(now.year,now.month,now.day); nowm=now.hour*60+now.minute
    ids={r[0] for r in db.execute(select(employee_org_units.c.employee_id).where(employee_org_units.c.org_unit_id==unit_id)).all()}
    ids|={e.id for e in db.scalars(select(Employee).where(Employee.default_org_unit_id==unit_id)).all()}
    emps=[e for e in db.scalars(select(Employee).where(Employee.id.in_(ids) if ids else False)).all() if e.active]
    att={a.employee_id:a for a in db.scalars(select(ProductionAttendance).where(ProductionAttendance.work_date>=today,ProductionAttendance.work_date<today+timedelta(days=1))).all()}
    out=[]
    for e in sorted(emps,key=lambda x:x.id):
        a=att.get(e.id)
        if a is not None:
            if (a.status or "PRESENT")!="PRESENT": continue
            if a.late:
                am=_local_min(a.arrived_at)
                if am is None or am>nowm: continue
            if any((_hm(x.get("from")) is not None and _hm(x.get("from"))<=nowm and (not x.get("to") or nowm<(_hm(x.get("to")) or 0))) for x in _short_leaves_list(a.short_leaves)): continue
        out.append(e.id)
    return json.dumps({"at":now.isoformat(timespec="seconds"),"unit_id":unit_id,"employee_ids":out})

def _local_dt(ts):
    return ts.replace(tzinfo=timezone.utc).astimezone() if ts.tzinfo is None else ts.astimezone()

def _item_state(db,t,i,later_by_unit):
    """σε εξέλιξη (κεχριμπάρι) / άδειασε (πράσινο) / μισό: με υπόλοιπο. Το επόμενο μέσο στο ίδιο τμήμα χωρίς δηλωμένο υπόλοιπο σημαίνει ότι το προηγούμενο άδειασε."""
    if i.remainder_net is not None and i.remainder_net>0: return "PARTIAL"
    if i.emptied or i.remainder_net is not None: return "EMPTIED"
    last=later_by_unit.get(t.destination_org_unit_id)
    if last is not None and last>t.created_at: return "EMPTIED"
    return "IN_PROGRESS"

def _device_rows(db:Session, start, end, unit_id:str|None=None):
    """Συσκευές (στοιχεία μεταφοράς) από start έως end (ημερομηνίες, τοπική ώρα), νεότερη πρώτη."""
    emp_by_tr={}
    for w in db.scalars(select(ProductionWorkEntry).where(ProductionWorkEntry.transfer_id.is_not(None),ProductionWorkEntry.active==True)).all():
        if w.employee_id: emp_by_tr[w.transfer_id]=w.employee_id
    emps={e.id:f"{p.first_name or ''} {p.last_name or ''}".strip() for e,p in db.execute(select(Employee,Person).join(Person,Person.id==Employee.person_id)).all()}
    trs=db.scalars(select(ProductionTransfer).where(ProductionTransfer.status!="CANCELLED").order_by(ProductionTransfer.created_at.desc())).all()
    later_by_unit={}
    for t in trs:
        if t.created_at is not None and (t.destination_org_unit_id not in later_by_unit or t.created_at>later_by_unit[t.destination_org_unit_id]): later_by_unit[t.destination_org_unit_id]=t.created_at
    out=[]
    for t in trs:
        ts=t.created_at
        if ts is None: continue
        loc=_local_dt(ts)
        if loc.date()<start or loc.date()>end: continue
        if unit_id and t.destination_org_unit_id!=unit_id: continue
        # ΜΙΑ γραμμή ανά (ίδια αποστολή, ίδιο μέσο, ίδιο ΑΗΗΕ), ανεξάρτητα από το πόσα μερίδια του αποθέματος χρησιμοποιήθηκαν
        groups={}
        for i in db.scalars(select(ProductionTransferItem).where(ProductionTransferItem.transfer_id==t.id)).all():
            lot=db.get(WEEEStockLot,i.stock_lot_id)
            groups.setdefault((lot.collection_medium_id,lot.weee_category_id),[]).append((i,lot))
        for (mid,cid),lst in groups.items():
            its=[x[0] for x in lst]; i0=its[0]; lot0=lst[0][1]
            cat=db.get(WEEECategory,cid); med=db.get(CollectionMedium,mid) if mid else None
            eid=emp_by_tr.get(t.id)
            par=db.scalar(select(WEEECategory).where(WEEECategory.code==cat.parent_code)) if cat.parent_code else None
            off=par if cat.is_internal_subcategory and par else cat
            tare=next((x.tare_weight for x in its if x.tare_weight is not None),None); tare_src="shipment"
            if tare is None and med is not None:
                tare=med.tare_weight; tare_src="current"
            sents=[(x.sent_weight if x.sent_weight is not None else x.weight) for x in its]
            sent=sum(sents,Decimal(0)); weight=sum((x.weight for x in its),Decimal(0))
            rems=[x for x in its if x.remainder_net is not None]
            rem_net=sum((x.remainder_net for x in rems),Decimal(0)) if rems else None
            grosses=[x.remainder_gross for x in its if x.remainder_gross is not None]
            rem_gross=sum(grosses,Decimal(0)) if grosses else None
            rem_mode=next((x.remainder_mode for x in its if x.remainder_mode),None)
            rem_at=max((x.remainder_at for x in rems if x.remainder_at is not None),default=None)
            if rem_net is not None and rem_net>0: state="PARTIAL"
            elif any(x.emptied or x.remainder_net is not None for x in its): state="EMPTIED"
            else: state=_item_state(db,t,i0,later_by_unit)
            out.append({"item_id":i0.id,"item_ids":[x.id for x in its],"transfer_id":t.id,"transfer_number":t.transfer_number,"created_at":ts,"date":loc.strftime("%Y-%m-%d"),"time":loc.strftime("%H:%M"),"org_unit_id":t.destination_org_unit_id,
                "weee_category_id":cat.id,"weee_code":cat.code,"official_description":off.description_el,"her_description":off.her_description,
                "medium_id":med.id if med else None,"medium_code":med.code if med else None,
                "weight_kg":float(weight),"sent_kg":float(sent),"remainder_kg":float(rem_net) if rem_net is not None else None,
                "remainder_gross":float(rem_gross) if rem_gross is not None else None,"remainder_mode":rem_mode,"remainder_at":rem_at,
                "tare_kg":float(tare) if tare is not None else None,"tare_source":tare_src if tare is not None else None,
                "gross_sent_kg":float(sent+tare) if tare is not None else None,
                "state":state,"employee_id":eid,"employee_name":emps.get(eid)})
    return out

@app.get('/production/device-list')
def production_device_list(date:str=Query(...), unit_id:str|None=Query(default=None), db:Session=Depends(get_db), user=Depends(require_permission('production.view'))):
    """Συσκευές (μέσα με ΑΗΗΕ) που μπήκαν σε τμήματα την ημέρα, μία-μία. weight_kg = καθαρή παραγωγή (στάλθηκαν − υπόλοιπο). Κοινά για Windows και Android."""
    day=datetime.fromisoformat(date).date()
    return _device_rows(db,day,day,unit_id)

@app.get('/production/device-history')
def production_device_history(days:int=Query(default=60,ge=1,le=400), unit_id:str|None=Query(default=None), db:Session=Depends(get_db), user=Depends(require_permission('production.view'))):
    """Ιστορικό ανά ημέρα (πιο πρόσφατη πρώτα), με προαιρετικό φίλτρο τμήματος."""
    end=datetime.now().date(); start=end-timedelta(days=days)
    rows=_device_rows(db,start,end,unit_id); days_map={}
    for r in rows: days_map.setdefault(r["date"],[]).append(r)
    return [{"date":d,"items":days_map[d]} for d in sorted(days_map,reverse=True)]

@app.get('/production/returns')
def production_returns(date:str=Query(...), db:Session=Depends(get_db), user=Depends(require_permission('production.view'))):
    """Μέσα που γύρισαν «μισά» στην Αποθήκη ΑΗΗΕ την ημέρα (με καθαρό υπόλοιπο και μικτά)."""
    day=datetime.fromisoformat(date).date(); out=[]
    for r in _device_rows(db,day-timedelta(days=60),day,None):
        if r["remainder_kg"] is None or r["remainder_kg"]<=0 or r["remainder_at"] is None or _local_dt(r["remainder_at"]).date()!=day: continue
        gross=r["remainder_gross"] if r["remainder_gross"] is not None else (r["remainder_kg"]+r["tare_kg"] if r["tare_kg"] is not None else None)
        out.append({**r,"returned_at":r["remainder_at"],"returned_time":_local_dt(r["remainder_at"]).strftime("%H:%M"),"returned_net_kg":r["remainder_kg"],"returned_gross_kg":gross})
    return out

def _entry_for_transfer(db,t):
    return db.scalar(select(ProductionWorkEntry).where(ProductionWorkEntry.transfer_id==t.id,ProductionWorkEntry.active==True))

def _undo_remainder(db,i,t,user,reason):
    """Αναιρεί το δηλωμένο υπόλοιπο: τα kg ξαναπαίρνονται από το μερίδιο (αν δεν έχει σταλεί αλλού)."""
    R=i.remainder_net or Decimal(0)
    if R>0:
        lot=db.get(WEEEStockLot,i.stock_lot_id)
        if lot.available_weight<R: raise HTTPException(409,'Το υπόλοιπο έχει ήδη σταλεί ξανά στην παραγωγή -- δεν μπορεί να αναιρεθεί')
        lot.available_weight=lot.available_weight-R; lot.status='CONSUMED' if lot.available_weight==0 else 'PARTIAL'
        db.add(StockMovement(domain='WEEE',lot_id=lot.id,movement_type='TO_PRODUCTION',from_location_id=lot.location_id,to_location_id=None,weight=R,org_unit_id=t.destination_org_unit_id,user_id=user.id,reason=reason))
        mid=lot.collection_medium_id
        bal=db.scalar(select(ProductionInputBalance).where(ProductionInputBalance.transfer_item_id==i.id))
        if bal:
            bal.initial_weight=bal.initial_weight+R; bal.current_remaining_weight=bal.current_remaining_weight+R
            if bal.status=='CANCELLED': bal.status='OPEN'
        i.weight=i.weight+R
        e=_entry_for_transfer(db,t)
        if e: e.weight_kg=e.weight_kg+R
        _update_medium_lifecycle(db,{mid})
    i.remainder_net=None; i.remainder_gross=None; i.remainder_mode=None; i.remainder_at=None; i.emptied=False; i.remainder_present=None

def _group_items(db,i):
    """Οι εγγραφές της ΙΔΙΑΣ αποστολής με το ίδιο μέσο και το ίδιο ΑΗΗΕ (μία γραμμή στις οθόνες)."""
    lot=db.get(WEEEStockLot,i.stock_lot_id); res=[]
    for x in db.scalars(select(ProductionTransferItem).where(ProductionTransferItem.transfer_id==i.transfer_id)).all():
        lx=db.get(WEEEStockLot,x.stock_lot_id)
        if lx.collection_medium_id==lot.collection_medium_id and lx.weee_category_id==lot.weee_category_id: res.append(x)
    return res

@app.post('/production/transfer-items/{item_id}/remainder')
def set_item_remainder(item_id:str, data:schemas.ItemRemainderIn, db:Session=Depends(get_db), user:User=Depends(require_permission('production.move'))):
    """ΥΠΟΛΟΙΠΟ μέσου ανά ΓΡΑΜΜΗ (αποστολή + μέσο + ΑΗΗΕ): kg που περίσσεψαν, ΜΙΚΤΑ (μείον το απόβαρο της στιγμής της αποστολής) ή ΚΑΘΑΡΑ.
    Ο server το μοιράζει εσωτερικά στα μερίδια. Καθαρή παραγωγή = καθαρά kg που στάλθηκαν − καθαρό υπόλοιπο. 0 = το μέσο άδειασε.
    Με υπόλοιπο το μέσο γυρνά στην Αποθήκη ΑΗΗΕ ως «μισό»."""
    i=db.get(ProductionTransferItem,item_id)
    if not i: raise HTTPException(404,'Η καταχώρηση δεν βρέθηκε')
    t=db.get(ProductionTransfer,i.transfer_id)
    if not t or t.status=='CANCELLED': raise HTTPException(404,'Η μεταφορά έχει ακυρωθεί')
    if data.mode not in ('GROSS','NET'): raise HTTPException(422,'Επίλεξε ΜΙΚΤΑ ή ΚΑΘΑΡΑ')
    kg=Decimal(str(data.kg))
    if kg<0: raise HTTPException(422,'Τα κιλά δεν μπορεί να είναι αρνητικά')
    items=_group_items(db,i)
    sent=sum(((x.sent_weight if x.sent_weight is not None else x.weight) for x in items),Decimal(0))
    if data.mode=='GROSS':
        tare=next((x.tare_weight for x in items if x.tare_weight is not None),None)
        if tare is None:
            lot0=db.get(WEEEStockLot,i.stock_lot_id); m0=db.get(CollectionMedium,lot0.collection_medium_id) if lot0.collection_medium_id else None
            tare=m0.tare_weight if m0 is not None else None
        if tare is None: raise HTTPException(422,'Το μέσο δεν έχει απόβαρο -- δήλωσε ΚΑΘΑΡΑ κιλά')
        net=kg-tare
        if net<0: raise HTTPException(422,f'Τα μικτά ({kg} kg) είναι λιγότερα από το απόβαρο ({tare} kg)')
        gross=kg
    else:
        net=kg; gross=None
    if net>sent: raise HTTPException(422,f'Το υπόλοιπο ({net} kg) δεν μπορεί να είναι μεγαλύτερο από τα kg που στάλθηκαν ({sent} kg)')
    old=sum((x.remainder_net or Decimal(0) for x in items),Decimal(0)) if any(x.remainder_net is not None for x in items) else None
    for x in items: _undo_remainder(db,x,t,user,'Διόρθωση υπολοίπου')
    for x in items:
        if x.sent_weight is None: x.sent_weight=x.weight
    left=net; takes={}
    for x in reversed(items):                      # το υπόλοιπο μοιράζεται ξεκινώντας από το τελευταίο μερίδιο
        take=min(left,x.weight); takes[x.id]=take; left-=take
    holder=next((x for x in items if takes[x.id]>0),items[0])      # τα μικτά αποθηκεύονται σε μία εγγραφή (το απόβαρο μετρά μία φορά)
    unit=db.get(OrganizationalUnit,t.destination_org_unit_id); snap=_present_snapshot(db,t.destination_org_unit_id,_event_now_local()); mids=set()
    for x in items:
        take=takes[x.id]
        if take>0:
            bal=db.scalar(select(ProductionInputBalance).where(ProductionInputBalance.transfer_item_id==x.id))
            if bal and bal.current_remaining_weight<take: raise HTTPException(409,'Μέρος του υλικού έχει ήδη χρησιμοποιηθεί στην παραγωγή')
            mids.add(_reverse_transfer_item(db,x,take,unit.id,user,'Υπόλοιπο μέσου '+t.transfer_number))
            x.weight=x.weight-take
        x.remainder_net=take; x.remainder_gross=gross if x is holder else None; x.remainder_mode=data.mode; x.remainder_at=_event_now(); x.emptied=(net==0); x.remainder_present=snap
    if net>0:
        e=_entry_for_transfer(db,t)
        if e: e.weight_kg=e.weight_kg-net
        _restore_medium_lifecycle(db,mids)
    write_audit(db,user,'production_transfer',t.id,'REMAINDER',old={'remainder':str(old) if old is not None else None},new={'remainder':str(net),'mode':data.mode,'gross':str(gross) if gross is not None else None,'items':len(items)},reason=data.reason)
    db.commit()
    return {"ok":True,"item_id":i.id,"remainder_net":float(net),"net_production":float(sum((x.weight for x in items),Decimal(0))),"state":"PARTIAL" if net>0 else "EMPTIED"}

@app.post('/production/transfer-items/{item_id}/remainder/undo')
def undo_item_remainder(item_id:str, db:Session=Depends(get_db), user:User=Depends(require_permission('production.move'))):
    i=db.get(ProductionTransferItem,item_id)
    if not i: raise HTTPException(404,'Η καταχώρηση δεν βρέθηκε')
    t=db.get(ProductionTransfer,i.transfer_id)
    items=_group_items(db,i)
    if not any(x.remainder_net is not None or x.emptied for x in items): raise HTTPException(409,'Δεν υπάρχει δηλωμένο υπόλοιπο')
    old=sum((x.remainder_net or Decimal(0) for x in items),Decimal(0))
    for x in items: _undo_remainder(db,x,t,user,'Αναίρεση υπολοίπου')
    write_audit(db,user,'production_transfer',t.id,'REMAINDER_UNDO',old={'remainder':str(old)},new={'remainder':None})
    db.commit()
    return {"ok":True,"item_id":i.id,"net_production":float(sum((x.weight for x in items),Decimal(0)))}

@app.get('/warehouse')
def warehouse_workspace():
    return _FileResponse(static_dir/'warehouse.html')







# ---- Build 0.7: production daily balances and ready outputs ----
from .models import ProductionInputBalance, ProductionRemainderSnapshot, ReadyMaterialLot, ReadyMaterialMovement

def _production_balance_out(db:Session,b:ProductionInputBalance):
    ti=db.get(ProductionTransferItem,b.transfer_item_id); lot=db.get(WEEEStockLot,ti.stock_lot_id)
    cat=db.get(WEEECategory,lot.weee_category_id); med=db.get(CollectionMedium,lot.collection_medium_id) if lot.collection_medium_id else None
    return schemas.ProductionBalanceOut(id=b.id,transfer_item_id=b.transfer_item_id,org_unit_id=b.org_unit_id,weee_code=cat.code,
        medium_code=med.code if med else None,initial_weight=b.initial_weight,current_remaining_weight=b.current_remaining_weight,
        processed_weight=b.initial_weight-b.current_remaining_weight,status=b.status)

@app.get('/production/balances', response_model=list[schemas.ProductionBalanceOut])
def production_balances(org_unit_id:str|None=None, open_only:bool=True, db:Session=Depends(get_db), user=Depends(require_permission('production.view'))):
    q=select(ProductionInputBalance).order_by(ProductionInputBalance.created_at)
    if org_unit_id: q=q.where(ProductionInputBalance.org_unit_id==org_unit_id)
    if open_only: q=q.where(ProductionInputBalance.status=='OPEN')
    return [_production_balance_out(db,x) for x in db.scalars(q).all()]

@app.post('/production/remainders', response_model=schemas.ProductionRemainderOut)
def production_remainder(data:schemas.ProductionRemainderCreate, db:Session=Depends(get_db), user:User=Depends(require_permission('production.move'))):
    b=db.get(ProductionInputBalance,data.balance_id)
    if not b: raise HTTPException(404,'Η εισροή παραγωγής δεν βρέθηκε')
    if b.status!='OPEN': raise HTTPException(409,'Η εισροή παραγωγής έχει ήδη κλείσει')
    if data.remaining_weight<0 or data.remaining_weight>b.current_remaining_weight: raise HTTPException(422,'Το υπόλοιπο δεν μπορεί να είναι μεγαλύτερο από το προηγούμενο υπόλοιπο')
    prev=b.current_remaining_weight; processed=prev-data.remaining_weight; b.current_remaining_weight=data.remaining_weight
    if data.remaining_weight==0: b.status='CLOSED'
    snap=ProductionRemainderSnapshot(balance_id=b.id,snapshot_date=datetime.now(timezone.utc),previous_remaining_weight=prev,
        remaining_weight=data.remaining_weight,processed_since_previous=processed,recorded_by=user.id,notes=data.notes)
    db.add(snap); write_audit(db,user,'production_balance',b.id,'REMAINDER',old={'remaining':str(prev)},new={'remaining':str(data.remaining_weight),'processed':str(processed)},reason=data.notes)
    db.commit(); return schemas.ProductionRemainderOut(balance_id=b.id,previous_remaining_weight=prev,remaining_weight=data.remaining_weight,processed_since_previous=processed,status=b.status)

def _ready_main_location(db:Session):
    loc=db.scalar(select(InventoryLocation).where(InventoryLocation.code=='READY_MAIN'))
    if not loc:
        loc=InventoryLocation(code='READY_MAIN',name_el='Αποθήκη Υλικών προς Φόρτωση',domain='READY_MATERIAL'); db.add(loc); db.flush()
    return loc

def _ready_lot_number(db:Session, material:Material)->str:
    year=datetime.now().year
    prefix=''.join(ch for ch in material.internal_code if ch.isalnum())[:12] or 'MAT'
    rows=db.scalars(select(ReadyMaterialLot).where(ReadyMaterialLot.material_id==material.id,ReadyMaterialLot.lot_number.like(f'RM-{prefix}-{year}-%'))).all()
    return f'RM-{prefix}-{year}-{len(rows)+1:06d}'

def _ready_out(db:Session,x:ReadyMaterialLot):
    mat=db.get(Material,x.material_id); med=db.get(CollectionMedium,x.collection_medium_id) if x.collection_medium_id else None
    return schemas.ReadyMaterialOut(id=x.id,lot_number=x.lot_number,material_id=x.material_id,material_code=mat.internal_code,material_name=mat.internal_name,
        output_form=x.output_form,medium_code=med.code if med else None,net_weight=x.net_weight,status=x.status,source_org_unit_id=x.source_org_unit_id,
        created_at=x.created_at.isoformat())

@app.post('/production/outputs', response_model=schemas.ReadyMaterialOut)
def production_output(data:schemas.ReadyMaterialCreate, db:Session=Depends(get_db), user:User=Depends(require_permission('production.move'))):
    mat=db.get(Material,data.material_id)
    if not mat or not mat.active: raise HTTPException(422,'Άγνωστο ή ανενεργό εξερχόμενο υλικό')
    if data.source_org_unit_id and not db.get(OrganizationalUnit,data.source_org_unit_id): raise HTTPException(422,'Άγνωστο τμήμα')
    medium=None
    if data.collection_medium_id:
        medium=db.get(CollectionMedium,data.collection_medium_id)
        if not medium: raise HTTPException(422,'Άγνωστο μέσο')
    net=data.net_weight
    if net is None:
        if data.gross_weight is None: raise HTTPException(422,'Απαιτείται καθαρό βάρος ή μικτό βάρος')
        tare=data.tare_weight if data.tare_weight is not None else (medium.tare_weight if medium else Decimal('0'))
        net=data.gross_weight-(tare or Decimal('0'))
    if net<=0: raise HTTPException(422,'Το καθαρό βάρος πρέπει να είναι θετικό')
    loc=_ready_main_location(db); lot=ReadyMaterialLot(lot_number=_ready_lot_number(db,mat),material_id=mat.id,output_form=data.output_form,
        collection_medium_id=data.collection_medium_id,gross_weight=data.gross_weight,tare_weight=data.tare_weight,net_weight=net,location_id=loc.id,
        source_org_unit_id=data.source_org_unit_id,status='AVAILABLE',created_by=user.id,notes=data.notes)
    db.add(lot); db.flush(); db.add(ReadyMaterialMovement(lot_id=lot.id,movement_type='PRODUCTION_OUT',weight=net,user_id=user.id,reason=data.notes))
    if medium: medium.status='READY_STORAGE'
    write_audit(db,user,'ready_material_lot',lot.id,'CREATE',new={'lot_number':lot.lot_number,'material':mat.internal_code,'weight':str(net),'form':data.output_form})
    db.commit(); db.refresh(lot); return _ready_out(db,lot)

@app.get('/inventory/ready-materials', response_model=list[schemas.ReadyMaterialOut])
def ready_materials(available_only:bool=True, start:str|None=Query(default=None), end:str|None=Query(default=None), db:Session=Depends(get_db), user=Depends(require_permission('loading.view'))):
    q=select(ReadyMaterialLot).order_by(ReadyMaterialLot.created_at.desc())
    if available_only: q=q.where(ReadyMaterialLot.status=='AVAILABLE')
    q=q.where(ReadyMaterialLot.status!='DEMO')   # τα DEMO δεν μπαίνουν ποτέ στα πραγματικά ισοζύγια/λίστες
    if start: q=q.where(ReadyMaterialLot.created_at>=datetime.fromisoformat(start))
    if end: q=q.where(ReadyMaterialLot.created_at<datetime.fromisoformat(end)+timedelta(days=1))
    return [_ready_out(db,x) for x in db.scalars(q).all()]

@app.get('/inventory/ready-materials/stock-by-name')
def ready_materials_stock_by_name(db:Session=Depends(get_db), user=Depends(require_permission('production.view'))):
    """Available physical lot stock (kg) grouped by Material.internal_name -- lets the Υλικά page's
    'only with stock' toggle match against MaterialOutputEntry.material_label by exact name, without
    guessing a mapping for names that don't line up between the two systems (see BUSINESS_RULES)."""
    from sqlalchemy import func
    rows=db.execute(select(Material.internal_name,func.sum(ReadyMaterialLot.net_weight)).join(ReadyMaterialLot,ReadyMaterialLot.material_id==Material.id).where(ReadyMaterialLot.status=='AVAILABLE').group_by(Material.internal_name)).all()
    return {name:float(total or 0) for name,total in rows}


# ---- Build 0.8: loading orders and dispatch ----
from .models import LoadingOrder, LoadingReservation, LoadingActual

def _loading_number(db:Session)->str:
    year=datetime.now().year
    rows=db.scalars(select(LoadingOrder).where(LoadingOrder.loading_number.like(f'LOAD-{year}-%'))).all()
    return f'LOAD-{year}-{len(rows)+1:06d}'

def _next_da_number(db:Session,year:int)->int:
    """Αρ. Δ.Α.: αύξων ανά έτος, ένα κοινό ρεύμα (Πωλήσεις + Ενδοδιακίνηση) -- επόμενος μετά τον μεγαλύτερο του έτους στο Ιστορικό Δελτίων Αποστολής."""
    H=models.ShipmentHistoryEntry
    rows=db.scalars(select(H.da_number).where(H.active==True,H.work_date>=datetime(year,1,1),H.work_date<datetime(year+1,1,1))).all()
    nums=[int(x) for x in rows if x and str(x).strip().isdigit()]
    # και οι αριθμοί που έχουν ήδη δοθεί από τον χρήστη σε πρόχειρα/οριστικοποιημένα δελτία φόρτωσης του έτους
    for o in db.scalars(select(LoadingOrder).where(LoadingOrder.status.in_(['OPEN','COMPLETED']),LoadingOrder.dispatch_document_number.is_not(None))).all():
        if o.created_at and o.created_at.year==year and str(o.dispatch_document_number).strip().isdigit(): nums.append(int(o.dispatch_document_number))
    return (max(nums) if nums else 0)+1

def _da_in_use(db:Session,year:int,number:str,exclude_order_id:str|None=None)->bool:
    """Ο Αρ. Δ.Α. είναι μοναδικός ανά έτος: κατειλημμένος είτε στο Ιστορικό είτε από άλλο πρόχειρο/οριστικοποιημένο δελτίο φόρτωσης."""
    H=models.ShipmentHistoryEntry
    if db.scalar(select(func.count()).select_from(H).where(H.active==True,H.da_number==number,H.work_date>=datetime(year,1,1),H.work_date<datetime(year+1,1,1)))>0: return True
    for o in db.scalars(select(LoadingOrder).where(LoadingOrder.status.in_(['OPEN','COMPLETED']),LoadingOrder.dispatch_document_number==number)).all():
        if o.id!=exclude_order_id and o.created_at and o.created_at.year==year: return True
    return False

def _loading_totals(db:Session,o:LoadingOrder):
    reservations=db.scalars(select(LoadingReservation).where(LoadingReservation.loading_order_id==o.id,LoadingReservation.status=='RESERVED')).all()
    actuals=db.scalars(select(LoadingActual).where(LoadingActual.loading_order_id==o.id)).all()
    reserved=sum((x.reserved_weight for x in reservations),Decimal('0')); loaded=sum((x.loaded_weight for x in actuals),Decimal('0'))
    if o.status=='COMPLETED': loaded+=sum((b.weight_kg for b in db.scalars(select(models.LoadingBulkItem).where(models.LoadingBulkItem.loading_order_id==o.id)).all()),Decimal('0'))
    return reserved,loaded

def _loading_out(db:Session,o:LoadingOrder):
    reserved,loaded=_loading_totals(db,o)
    return schemas.LoadingOrderOut(id=o.id,loading_number=o.loading_number,customer_id=o.customer_id,carrier_id=o.carrier_id,vehicle_registration=o.vehicle_registration,
        max_allowed_weight=o.max_allowed_weight,selection_mode=o.selection_mode,status=o.status,reserved_weight=reserved,loaded_weight=loaded,
        remaining_capacity=o.max_allowed_weight-loaded,dispatch_reason=o.dispatch_reason,dispatch_document_number=o.dispatch_document_number,weighbridge_number=o.weighbridge_number,driver_name=o.driver_name,eka_code=o.eka_code,reptool_code=o.reptool_code,delivery_date=o.delivery_date,prep_mode=o.prep_mode,first_recipient=o.first_recipient,mgmt_operation=o.mgmt_operation,tracking_document=o.tracking_document,destination_country=o.destination_country,container_number=o.container_number,gr_notification_no=o.gr_notification_no,bill_of_lading=o.bill_of_lading)

@app.post('/loading/orders', response_model=schemas.LoadingOrderOut)
def loading_create(data:schemas.LoadingOrderCreate, db:Session=Depends(get_db), user:User=Depends(require_permission('loading.view'))):
    if data.selection_mode not in {'OFFICE_RESERVED','OPERATOR_SELECTION'}: raise HTTPException(422,'Μη έγκυρος τρόπος φόρτωσης')
    if data.max_allowed_weight<=0: raise HTTPException(422,'Το μέγιστο βάρος πρέπει να είναι θετικό')
    if not db.get(Organization,data.customer_id): raise HTTPException(422,'Άγνωστος πελάτης')
    typed=(data.dispatch_document_number or '').strip()
    if typed:
        if not typed.isdigit(): raise HTTPException(422,'Ο αριθμός Δ.Α. πρέπει να είναι αριθμός')
        if _da_in_use(db,datetime.now().year,typed): raise HTTPException(409,f'Ο αριθμός Δ.Α. {typed} υπάρχει ήδη φέτος')
        data.dispatch_document_number=typed
    else: data.dispatch_document_number=None
    o=LoadingOrder(loading_number=_loading_number(db),customer_id=data.customer_id,carrier_id=data.carrier_id,vehicle_registration=data.vehicle_registration,
        max_allowed_weight=data.max_allowed_weight,selection_mode=data.selection_mode,status='OPEN',dispatch_reason=data.dispatch_reason,weighbridge_number=data.weighbridge_number,
        dispatch_document_number=data.dispatch_document_number,created_by=user.id,notes=data.notes,
        first_recipient=(data.first_recipient or None),mgmt_operation=(data.mgmt_operation or None),tracking_document=(data.tracking_document or None),destination_country=(data.destination_country or None),container_number=(data.container_number or None),gr_notification_no=(data.gr_notification_no or None),bill_of_lading=(data.bill_of_lading or None))
    if not o.destination_country:   # προσυμπλήρωση από τη χώρα του πελάτη στο Μητρώο (αν υπάρχει)
        _d=db.scalar(select(models.OrganizationRegistryDetail).where(models.OrganizationRegistryDetail.organization_id==data.customer_id))
        if _d and _d.country_code: o.destination_country=_d.country_code
    db.add(o); db.flush(); write_audit(db,user,'loading_order',o.id,'CREATE',new={'loading_number':o.loading_number,'mode':o.selection_mode,'max_weight':str(o.max_allowed_weight)})
    db.commit(); return _loading_out(db,o)

@app.get('/loading/orders', response_model=list[schemas.LoadingOrderOut])
def loading_list(db:Session=Depends(get_db), user=Depends(require_permission('loading.view'))):
    return [_loading_out(db,o) for o in db.scalars(select(LoadingOrder).order_by(LoadingOrder.created_at.desc())).all()]

@app.post('/loading/orders/{order_id}/reserve', response_model=schemas.LoadingOrderOut)
def loading_reserve(order_id:str,data:schemas.LoadingLotAction,db:Session=Depends(get_db),user:User=Depends(require_permission('loading.view'))):
    o=db.get(LoadingOrder,order_id)
    if not o or o.status!='OPEN': raise HTTPException(409,'Η φόρτωση δεν είναι ανοικτή')
    if o.selection_mode!='OFFICE_RESERVED': raise HTTPException(409,'Η φόρτωση έχει οριστεί για επιλογή από τον χειριστή')
    lot=db.get(ReadyMaterialLot,data.ready_material_lot_id)
    if not lot or lot.status!='AVAILABLE': raise HTTPException(409,'Το υλικό δεν είναι διαθέσιμο')
    if db.scalar(select(LoadingReservation).where(LoadingReservation.ready_material_lot_id==lot.id,LoadingReservation.status=='RESERVED')): raise HTTPException(409,'Το υλικό είναι ήδη δεσμευμένο')
    qty=lot.net_weight if data.weight is None else data.weight
    if qty<=0 or qty>lot.net_weight: raise HTTPException(422,'Μη έγκυρο βάρος δέσμευσης')
    reserved,_=_loading_totals(db,o)
    if reserved+qty>o.max_allowed_weight: raise HTTPException(422,f'Υπέρβαση μέγιστου βάρους κατά {reserved+qty-o.max_allowed_weight} kg')
    r=LoadingReservation(loading_order_id=o.id,ready_material_lot_id=lot.id,reserved_weight=qty,created_by=user.id); db.add(r); lot.status='RESERVED'
    write_audit(db,user,'loading_order',o.id,'RESERVE',new={'lot':lot.lot_number,'weight':str(qty)})
    db.commit(); return _loading_out(db,o)

@app.post('/loading/orders/{order_id}/load', response_model=schemas.LoadingOrderOut)
def loading_actual(order_id:str,data:schemas.LoadingLotAction,db:Session=Depends(get_db),user:User=Depends(require_permission('loading.execute'))):
    o=db.get(LoadingOrder,order_id)
    if not o or o.status!='OPEN': raise HTTPException(409,'Η φόρτωση δεν είναι ανοικτή')
    lot=db.get(ReadyMaterialLot,data.ready_material_lot_id)
    if not lot: raise HTTPException(404,'Το υλικό δεν βρέθηκε')
    if db.scalar(select(LoadingActual).where(LoadingActual.loading_order_id==o.id,LoadingActual.ready_material_lot_id==lot.id)): raise HTTPException(409,'Το υλικό έχει ήδη καταγραφεί ως φορτωμένο')
    reservation=db.scalar(select(LoadingReservation).where(LoadingReservation.loading_order_id==o.id,LoadingReservation.ready_material_lot_id==lot.id,LoadingReservation.status=='RESERVED'))
    if o.selection_mode=='OFFICE_RESERVED' and not reservation: raise HTTPException(409,'Το υλικό δεν έχει δεσμευτεί από το Logistics')
    if o.selection_mode=='OPERATOR_SELECTION' and lot.status!='AVAILABLE': raise HTTPException(409,'Το υλικό δεν είναι διαθέσιμο για επιλογή')
    max_lot=reservation.reserved_weight if reservation else lot.net_weight
    qty=max_lot if data.weight is None else data.weight
    if qty<=0 or qty>max_lot: raise HTTPException(422,'Μη έγκυρο βάρος φόρτωσης')
    _,loaded=_loading_totals(db,o)
    if loaded+qty>o.max_allowed_weight: raise HTTPException(422,f'Υπέρβαση μέγιστου βάρους κατά {loaded+qty-o.max_allowed_weight} kg')
    db.add(LoadingActual(loading_order_id=o.id,ready_material_lot_id=lot.id,loaded_weight=qty,loaded_by=user.id)); lot.status='LOADING'
    if reservation: reservation.status='LOADED'
    write_audit(db,user,'loading_order',o.id,'LOAD_ITEM',new={'lot':lot.lot_number,'weight':str(qty)})
    db.commit(); return _loading_out(db,o)

@app.post('/loading/orders/{order_id}/complete', response_model=schemas.LoadingOrderOut)
def loading_complete(order_id:str,db:Session=Depends(get_db),user:User=Depends(require_permission('loading.execute'))):
    o=db.get(LoadingOrder,order_id)
    if not o or o.status!='OPEN': raise HTTPException(409,'Η φόρτωση δεν είναι ανοικτή')
    actuals=db.scalars(select(LoadingActual).where(LoadingActual.loading_order_id==o.id)).all()
    bulk=_prep_bulk_items(db,o)
    if not actuals and not bulk: raise HTTPException(422,'Δεν έχει καταγραφεί κανένα φορτωμένο υλικό')
    for a in actuals:
        lot=db.get(ReadyMaterialLot,a.ready_material_lot_id)
        if a.loaded_weight==lot.net_weight: lot.status='DISPATCHED'
        else: lot.net_weight=lot.net_weight-a.loaded_weight; lot.status='AVAILABLE'
        db.add(ReadyMaterialMovement(lot_id=lot.id,movement_type='DISPATCH',weight=a.loaded_weight,user_id=user.id,reason=o.loading_number))
    for r in db.scalars(select(LoadingReservation).where(LoadingReservation.loading_order_id==o.id,LoadingReservation.status=='RESERVED')).all():
        lot=db.get(ReadyMaterialLot,r.ready_material_lot_id); r.status='RELEASED'
        if lot and lot.status=='RESERVED': lot.status='AVAILABLE'
    o.status='COMPLETED'; write_audit(db,user,'loading_order',o.id,'COMPLETE',new={'actual_items':len(actuals),'loaded_weight':str(_loading_totals(db,o)[1])})
    # Οριστικοποίηση = αυτόματος Αρ. Δ.Α. (αύξων ανά έτος) και μετάβαση στο Ιστορικό Δελτίων Αποστολής: μία γραμμή ανά υλικό, όλες με τον ίδιο αριθμό
    now=datetime.now(); typed=(o.dispatch_document_number or '').strip()
    wd=now
    if o.delivery_date:
        try: wd=datetime.fromisoformat(o.delivery_date)
        except Exception: wd=now
    if typed:
        if not typed.isdigit() or _da_in_use(db,wd.year,typed,o.id): raise HTTPException(409,f'Ο αριθμός Δ.Α. {typed} υπάρχει ήδη φέτος')
        number=typed
    else: number=str(_next_da_number(db,wd.year))
    o.dispatch_document_number=number
    cust=db.get(Organization,o.customer_id); carr=db.get(Organization,o.carrier_id) if o.carrier_id else None
    orgname=lambda x:(x.trade_name or x.legal_name) if x else None
    per_mat={}
    for a in actuals:
        lot=db.get(ReadyMaterialLot,a.ready_material_lot_id); mat=db.get(models.Material,lot.material_id) if lot else None
        key=mat.id if mat else (lot.id if lot else a.id)
        d=per_mat.setdefault(key,{'mat':mat,'w':Decimal('0')}); d['w']+=a.loaded_weight
    # Χύμα κιλά: αφαίρεση από το απόθεμα των Υλικών (εγγραφή αποστολής υλικού, ίδιος πίνακας που αφαιρεί ο υπολογισμός «Τρέχον απόθεμα») + γραμμή στο Ιστορικό Δ.Α.
    for b in bulk:
        db.add(models.MaterialShipmentEntry(work_date=wd,category_group=b.category_group,material_label=b.material_label,weight_kg=b.weight_kg,source='LOADING',notes='LOADING:'+o.id,created_by_user_id=user.id,active=True))
        db.add(models.ShipmentHistoryEntry(work_date=wd,da_number=number,weighbridge_number=o.weighbridge_number,transporter=orgname(carr),recipient=orgname(cust),
            description=b.material_label,weight_kg=b.weight_kg,eka_code=o.eka_code,reptool_code=o.reptool_code,
            kind='MATERIAL',source='LOADING',active=True,first_recipient=o.first_recipient,mgmt_operation=o.mgmt_operation,tracking_document=o.tracking_document,destination_country=o.destination_country,container_number=o.container_number,gr_notification_no=o.gr_notification_no,bill_of_lading=o.bill_of_lading))
    for d in per_mat.values():
        m=d['mat']
        db.add(models.ShipmentHistoryEntry(work_date=wd,da_number=number,weighbridge_number=o.weighbridge_number,transporter=orgname(carr),recipient=orgname(cust),
            description=((m.official_description or m.internal_name) if m else 'Υλικό'),weight_kg=d['w'],eka_code=(o.eka_code or (m.eka_code if m else None)),reptool_code=(o.reptool_code or (m.reptool_code if m else None)),
            kind='MATERIAL',source='LOADING',active=True,first_recipient=o.first_recipient,mgmt_operation=o.mgmt_operation,tracking_document=o.tracking_document,destination_country=o.destination_country,container_number=o.container_number,gr_notification_no=o.gr_notification_no,bill_of_lading=o.bill_of_lading))
    _enqueue_sync(db,'LOADING_ORDER',o.id,'UPSERT',{'loading_number':o.loading_number,'status':o.status,'loaded_weight':str(_loading_totals(db,o)[1])})
    db.commit(); return _loading_out(db,o)

@app.put('/loading/orders/{order_id}/da-details', response_model=schemas.LoadingOrderOut)
def loading_set_da_details(order_id:str,data:schemas.LoadingDaDetailsIn,db:Session=Depends(get_db),user:User=Depends(require_permission('loading.execute'))):
    o=db.get(LoadingOrder,order_id)
    if not o or o.status not in ('OPEN','COMPLETED'): raise HTTPException(409,'Τα στοιχεία δελτίου αλλάζουν μόνο σε πρόχειρο ή οριστικοποιημένο δελτίο')
    vals={f:((getattr(data,f) or '').strip() or None) for f in ['first_recipient', 'mgmt_operation', 'tracking_document', 'destination_country', 'container_number', 'gr_notification_no', 'bill_of_lading']}
    old={f:getattr(o,f) for f in vals}
    for f,v in vals.items(): setattr(o,f,v)
    if o.status=='COMPLETED' and o.dispatch_document_number:
        H=models.ShipmentHistoryEntry
        for r in db.scalars(select(H).where(H.source=='LOADING',H.da_number==o.dispatch_document_number,H.active==True)).all():
            for f,v in vals.items(): setattr(r,f,v)
    write_audit(db,user,'loading_order',o.id,'EDIT_DA_DETAILS',old=old,new=vals); db.commit()
    return _loading_out(db,o)


# ---- Προετοιμασία φόρτωσης: σχέδιο (δεν δεσμεύει αποθήκη) -> οριστικοποίηση με την υπάρχουσα λογική φορτώσεων ----
_PREP_PURPOSES=('Τελική διάθεση','Διασυνοριακή μεταφορά','Ενδοδιακίνηση','Πώληση')

def _prep_lot_info(db:Session,lot,cache:dict):
    md=db.get(CollectionMedium,lot.collection_medium_id) if lot.collection_medium_id else None
    label='Χύμα'
    if md:
        t=cache.get(md.type_id)
        if t is None:
            t=db.get(models.CollectionMediumType,md.type_id); cache[md.type_id]=t
        label={'PALLET':'Παλέτα','SACK_1KG':'Σάκος 1 kg','SACK_2KG_UN':'Σάκος 2 kg'}.get(t.code if t else '', (t.name_el if t else 'Μέσο'))
    return {'lot_id':lot.id,'lot_number':lot.lot_number,'label':label,'code':md.code if md else None,'kg':float(lot.net_weight)}

# ---- Χύμα κιλά στη Φόρτωση: ίδιος υπολογισμός με το «Τρέχον απόθεμα» των Υλικών (παραγωγή − αποστολές, ανά ετικέτα υλικού) ----
_BULK_GROUP_ORDER={'AXIOPOIISIMA':0,'EIDIKIS_DIACHEIRISIS':1,'APORRIPSI':2}
def _bulk_balances(db:Session)->dict:
    bal={}
    for e in db.scalars(select(models.MaterialOutputEntry).where(models.MaterialOutputEntry.active==True)).all():
        b=bal.setdefault(e.material_label,{'group':e.category_group,'kg':Decimal('0')}); b['kg']+=(e.weight_kg or Decimal('0'))
    for e in db.scalars(select(models.MaterialShipmentEntry).where(models.MaterialShipmentEntry.active==True)).all():
        b=bal.setdefault(e.material_label,{'group':e.category_group,'kg':Decimal('0')}); b['kg']-=(e.weight_kg or Decimal('0'))
    # διορθώσεις (χειροκίνητες κινήσεις +/-) μετράνε στο «Τρέχον απόθεμα» των Υλικών: ταίριασμα ετικέτας όπως στην οθόνη (trim + κεφαλαία)
    corr={}
    for e in db.scalars(select(models.MaterialCorrectionEntry)).all():
        k=(e.material_label or '').strip().upper(); corr[k]=corr.get(k,Decimal('0'))+(e.weight_kg_delta or Decimal('0'))
    for lb,b in bal.items(): b['kg']+=corr.get(lb.strip().upper(),Decimal('0'))
    return bal
def _prep_bulk_items(db:Session,o:LoadingOrder)->list:
    return list(db.scalars(select(models.LoadingBulkItem).where(models.LoadingBulkItem.loading_order_id==o.id).order_by(models.LoadingBulkItem.material_label)).all())
def _prep_replace_bulk(db:Session,o:LoadingOrder,items:list):
    for it in _prep_bulk_items(db,o): db.delete(it)
    db.flush()
    bal=_bulk_balances(db); merged={}
    for x in items:
        lb=(x.material_label or '').strip()
        if lb not in bal: raise HTTPException(422,f'Άγνωστο χύμα υλικό «{lb}»')
        if x.weight_kg<=0: raise HTTPException(422,f'Τα κιλά για «{lb}» πρέπει να είναι θετικά')
        merged[lb]=merged.get(lb,Decimal('0'))+x.weight_kg
    for lb,kg in merged.items(): db.add(models.LoadingBulkItem(loading_order_id=o.id,category_group=bal[lb]['group'],material_label=lb,weight_kg=kg))
def _release_bulk(db:Session,o:LoadingOrder):
    """Επιστροφή χύμα κιλών στο απόθεμα: οι εγγραφές αποστολής αυτής της φόρτωσης γίνονται ανενεργές."""
    n=0
    for e in db.scalars(select(models.MaterialShipmentEntry).where(models.MaterialShipmentEntry.source=='LOADING',models.MaterialShipmentEntry.notes=='LOADING:'+o.id,models.MaterialShipmentEntry.active==True)).all():
        e.active=False; n+=1
    return n

@app.get('/loading/prep/stock')
def loading_prep_stock(db:Session=Depends(get_db),user=Depends(require_permission('loading.view'))):
    """Διαθέσιμα μέσα συλλογής (lots με status AVAILABLE) ανά κατηγορία αποθήκης και υλικό."""
    lots=db.scalars(select(ReadyMaterialLot).where(ReadyMaterialLot.status=='AVAILABLE',ReadyMaterialLot.entry_type!='INVENTORY').order_by(ReadyMaterialLot.created_at)).all()
    mats={m.id:m for m in db.scalars(select(Material)).all()}
    groups={g.id:g for g in db.scalars(select(models.StorageGroup)).all()}
    cache={}; cats={}
    for l in lots:
        m=mats.get(l.material_id)
        if not m: continue
        g=groups.get(m.storage_group_id)
        cname=g.name if g else 'Χωρίς κατηγορία'
        c=cats.setdefault(cname,{'category':cname,'sort':g.sort_order if g else 9999,'mats':{}})
        mm=c['mats'].setdefault(m.id,{'material_id':m.id,'material':m.official_description or m.internal_name,'items':[]})
        mm['items'].append(_prep_lot_info(db,l,cache))
    out=[]
    for c in sorted(cats.values(),key=lambda c:(c['sort'],c['category'])):
        ms=sorted(c['mats'].values(),key=lambda x:x['material'])
        for m in ms: m['pieces']=sum(1 for i in m['items'] if i['code']); m['kg']=round(sum(i['kg'] for i in m['items']),3)
        out.append({'category':c['category'],'materials':ms})
    bulk=[{'material_label':lb,'category_group':b['group'],'kg':float(b['kg'])} for lb,b in _bulk_balances(db).items() if b['kg']>0]
    bulk.sort(key=lambda x:(_BULK_GROUP_ORDER.get(x['category_group'],9),x['material_label']))
    return {'categories':out,'bulk':bulk}

@app.get('/loading/prep/frequent')
def loading_prep_frequent(customer_id:str,db:Session=Depends(get_db),user=Depends(require_permission('loading.view'))):
    """Συνήθη υλικά του πελάτη από το ιστορικό δελτίων του (τελευταίες 4 φορτώσεις)."""
    org=db.get(Organization,customer_id)
    if not org: return {'of':0,'items':[]}
    names={n.strip().casefold() for n in (org.trade_name,org.legal_name) if n}
    H=models.ShipmentHistoryEntry
    rows=[r for r in db.scalars(select(H).where(H.active==True).order_by(H.work_date.desc())).all() if (r.recipient or '').strip().casefold() in names]
    das=[]; by_da={}
    for r in rows:
        if r.da_number not in by_da: by_da[r.da_number]=[]; das.append(r.da_number)
        by_da[r.da_number].append(r)
    last=das[:4]
    if not last: return {'of':0,'items':[]}
    mats=db.scalars(select(Material)).all()
    def match(desc):
        d=(desc or '').strip().casefold()
        for m in mats:
            for nm in (m.official_description,m.internal_name,m.her_description,m.galaxy_description):
                if nm and nm.strip().casefold()==d: return m
        return None
    cnt={}
    for da in last:
        seen=set()
        for r in by_da[da]:
            m=match(r.description)
            if m and m.id not in seen:
                seen.add(m.id); cnt[m.id]=cnt.get(m.id,0)+1
    avail={}
    for l in db.scalars(select(ReadyMaterialLot).where(ReadyMaterialLot.status=='AVAILABLE',ReadyMaterialLot.entry_type!='INVENTORY')).all():
        a=avail.setdefault(l.material_id,{'kg':0.0,'lot_ids':[]}); a['kg']+=float(l.net_weight); a['lot_ids'].append(l.id)
    mm={m.id:m for m in mats}
    items=[{'material_id':mid,'material':mm[mid].official_description or mm[mid].internal_name,'count':c,'kg':round(avail.get(mid,{}).get('kg',0.0),3),'lot_ids':avail.get(mid,{}).get('lot_ids',[])}
           for mid,c in sorted(cnt.items(),key=lambda x:-x[1])[:6]]
    return {'of':len(last),'items':items}

def _prep_apply(db:Session,o:LoadingOrder,data:schemas.LoadingPrepIn):
    if not db.get(Organization,data.customer_id): raise HTTPException(422,'Άγνωστος πελάτης')
    typed=(data.dispatch_document_number or '').strip()
    year=datetime.now().year
    if data.delivery_date:
        try: year=datetime.fromisoformat(data.delivery_date).year
        except Exception: raise HTTPException(422,'Μη έγκυρη ημερομηνία')
    if typed:
        if not typed.isdigit(): raise HTTPException(422,'Ο αριθμός Δ.Α. πρέπει να είναι αριθμός')
        if _da_in_use(db,year,typed,o.id if o.id else None): raise HTTPException(409,f'Ο αριθμός Δ.Α. {typed} υπάρχει ήδη φέτος')
    if data.max_allowed_weight<=0: raise HTTPException(422,'Το μέγιστο βάρος πρέπει να είναι θετικό')
    o.customer_id=data.customer_id; o.carrier_id=data.carrier_id or None
    o.vehicle_registration=(data.vehicle_registration or '').strip() or None
    o.driver_name=(data.driver_name or '').strip() or None
    o.dispatch_reason=(data.dispatch_reason or '').strip() or None
    o.eka_code=(data.eka_code or '').strip() or None; o.reptool_code=(data.reptool_code or '').strip() or None
    o.dispatch_document_number=typed or None; o.delivery_date=(data.delivery_date or '').strip()[:10] or None
    o.notes=(data.notes or '').strip() or None; o.max_allowed_weight=data.max_allowed_weight

def _prep_replace_items(db:Session,o:LoadingOrder,lot_ids:list):
    for it in db.scalars(select(models.LoadingPlanItem).where(models.LoadingPlanItem.loading_order_id==o.id)).all(): db.delete(it)
    db.flush()
    for lid in dict.fromkeys(lot_ids):
        if db.get(ReadyMaterialLot,lid): db.add(models.LoadingPlanItem(loading_order_id=o.id,ready_material_lot_id=lid))

@app.post('/loading/prep',response_model=schemas.LoadingOrderOut)
def loading_prep_create(data:schemas.LoadingPrepIn,db:Session=Depends(get_db),user:User=Depends(require_permission('loading.view'))):
    o=LoadingOrder(loading_number=_loading_number(db),status='OPEN',selection_mode='OFFICE_RESERVED',prep_mode='PREP',created_by=user.id,customer_id=data.customer_id,max_allowed_weight=data.max_allowed_weight)
    _prep_apply(db,o,data); db.add(o); db.flush()
    _prep_replace_items(db,o,data.lot_ids); _prep_replace_bulk(db,o,data.bulk_items)
    write_audit(db,user,'loading_order',o.id,'PREP_CREATE',new={'loading_number':o.loading_number,'items':len(data.lot_ids),'bulk':len(data.bulk_items)})
    db.commit(); return _loading_out(db,o)

def _prep_order(db:Session,order_id:str)->LoadingOrder:
    o=db.get(LoadingOrder,order_id)
    if not o or o.prep_mode!='PREP': raise HTTPException(404,'Δεν βρέθηκε πρόχειρο προετοιμασίας')
    if o.status!='OPEN': raise HTTPException(409,'Το πρόχειρο δεν είναι πια ανοιχτό')
    return o

@app.put('/loading/prep/{order_id}',response_model=schemas.LoadingOrderOut)
def loading_prep_update(order_id:str,data:schemas.LoadingPrepIn,db:Session=Depends(get_db),user:User=Depends(require_permission('loading.view'))):
    o=_prep_order(db,order_id)
    _prep_apply(db,o,data); _prep_replace_items(db,o,data.lot_ids); _prep_replace_bulk(db,o,data.bulk_items)
    write_audit(db,user,'loading_order',o.id,'PREP_UPDATE',new={'items':len(data.lot_ids),'bulk':len(data.bulk_items)})
    db.commit(); return _loading_out(db,o)

@app.get('/loading/prep/{order_id}')
def loading_prep_get(order_id:str,db:Session=Depends(get_db),user=Depends(require_permission('loading.view'))):
    o=db.get(LoadingOrder,order_id)
    if not o or o.prep_mode!='PREP': raise HTTPException(404,'Δεν βρέθηκε πρόχειρο προετοιμασίας')
    cache={}; items=[]
    mats={m.id:m for m in db.scalars(select(Material)).all()}
    for it in db.scalars(select(models.LoadingPlanItem).where(models.LoadingPlanItem.loading_order_id==o.id)).all():
        l=db.get(ReadyMaterialLot,it.ready_material_lot_id)
        if not l: continue
        m=mats.get(l.material_id)
        info=_prep_lot_info(db,l,cache); info['material_id']=l.material_id; info['material']=(m.official_description or m.internal_name) if m else None
        info['available']=(l.status=='AVAILABLE'); items.append(info)
    return {'order':_loading_out(db,o),'items':items,'bulk':[{'material_label':b.material_label,'category_group':b.category_group,'kg':float(b.weight_kg)} for b in _prep_bulk_items(db,o)]}

@app.post('/loading/prep/{order_id}/finalize',response_model=schemas.LoadingOrderOut)
def loading_prep_finalize(order_id:str,data:schemas.LoadingPrepIn,db:Session=Depends(get_db),user:User=Depends(require_permission('loading.execute'))):
    """Οριστικοποίηση: δέσμευση ανά lot (έλεγχος διαθεσιμότητας και μέγιστου βάρους), στάδιο «Φορτωμένο» και ολοκλήρωση με την υπάρχουσα λογική."""
    o=_prep_order(db,order_id)
    _prep_apply(db,o,data); _prep_replace_items(db,o,data.lot_ids); _prep_replace_bulk(db,o,data.bulk_items); db.flush()
    plan=[it.ready_material_lot_id for it in db.scalars(select(models.LoadingPlanItem).where(models.LoadingPlanItem.loading_order_id==o.id)).all()]
    bulk=_prep_bulk_items(db,o)
    if not plan and not bulk: raise HTTPException(422,'Το φορτίο είναι κενό')
    mats={m.id:m for m in db.scalars(select(Material)).all()}; cache={}; missing=[]; lots=[]
    for lid in plan:
        l=db.get(ReadyMaterialLot,lid)
        if not l: missing.append('μέσο που δεν υπάρχει πια'); continue
        info=_prep_lot_info(db,l,cache); m=mats.get(l.material_id)
        if l.status!='AVAILABLE':
            why={'RESERVED':'έχει δεσμευτεί από άλλη φόρτωση','LOADING':'φορτώνεται σε άλλη φόρτωση','DISPATCHED':'έχει ήδη αποσταλεί'}.get(l.status,'δεν είναι διαθέσιμο')
            missing.append(f"{info['label']} {info['code'] or ''} · {(m.official_description or m.internal_name) if m else ''} · {info['kg']:g} kg — {why}".replace('  ',' '))
        else: lots.append(l)
    if missing: raise HTTPException(409,'Δεν μπορεί να οριστικοποιηθεί. Λείπουν μέσα: '+'; '.join(missing)+'. Αφαίρεσέ τα από το φορτίο και ξαναδοκίμασε. Το πρόχειρο έχει αποθηκευτεί.')
    # Υπέρβαση χύμα αποθέματος: ξαναϋπολογίζεται εδώ (ίδια συναλλαγή)· χωρίς ρητή επιβεβαίωση + λόγο η οριστικοποίηση δεν προχωρά
    short=[]
    if bulk:
        bal=_bulk_balances(db)
        for b in bulk:
            av=max(bal.get(b.material_label,{'kg':Decimal('0')})['kg'],Decimal('0'))
            if b.weight_kg>av: short.append((b,av,b.weight_kg-av))
            b.shortage_kg=Decimal('0'); b.shortage_reason=None
    if short:
        reason=(data.shortage_reason or '').strip()
        if not data.allow_shortage:
            raise HTTPException(409,{'code':'BULK_SHORTAGE','message':'Δεν επαρκεί το διαθέσιμο χύμα: '+'; '.join(f"«{b.material_label}»: ζητήθηκαν {float(b.weight_kg):g} kg, διαθέσιμα {float(av):g} kg" for b,av,ov in short)+'. Το πρόχειρο έχει αποθηκευτεί.',
                'items':[{'material_label':b.material_label,'requested':float(b.weight_kg),'available':float(av),'over':float(ov)} for b,av,ov in short]})
        if not reason: raise HTTPException(422,'Γράψε τον λόγο της υπέρβασης.')
        for b,av,ov in short: b.shortage_kg=ov; b.shortage_reason=reason
        write_audit(db,user,'loading_order',o.id,'BULK_SHORTAGE_CONFIRMED',new={'reason':reason,'items':[{'material':b.material_label,'requested':str(b.weight_kg),'available':str(av),'over':str(ov)} for b,av,ov in short]})
    total=sum((l.net_weight for l in lots),Decimal('0'))+sum((b.weight_kg for b in bulk),Decimal('0'))
    if total>o.max_allowed_weight: raise HTTPException(422,f'Υπέρβαση μέγιστου βάρους κατά {float(total-o.max_allowed_weight):g} kg')
    for l in lots:
        db.add(LoadingReservation(loading_order_id=o.id,ready_material_lot_id=l.id,reserved_weight=l.net_weight,created_by=user.id,status='LOADED'))
        db.add(LoadingActual(loading_order_id=o.id,ready_material_lot_id=l.id,loaded_weight=l.net_weight,loaded_by=user.id)); l.status='LOADING'
    for it in db.scalars(select(models.LoadingPlanItem).where(models.LoadingPlanItem.loading_order_id==o.id)).all(): db.delete(it)
    db.flush()
    try:
        return loading_complete(order_id,db,user)
    except Exception:
        db.rollback(); raise

class DaNumberIn(schemas.BaseModel):
    number:str

@app.put('/loading/orders/{order_id}/dispatch-number', response_model=schemas.LoadingOrderOut)
def loading_set_da_number(order_id:str,data:DaNumberIn,db:Session=Depends(get_db),user:User=Depends(require_permission('loading.execute'))):
    o=db.get(LoadingOrder,order_id)
    if not o or o.status!='COMPLETED' or not o.dispatch_document_number: raise HTTPException(409,'Ο αριθμός Δ.Α. αλλάζει μόνο σε οριστικοποιημένο δελτίο')
    new=(data.number or '').strip()
    if not new.isdigit(): raise HTTPException(422,'Ο αριθμός Δ.Α. πρέπει να είναι αριθμός')
    old=o.dispatch_document_number
    if new!=old:
        H=models.ShipmentHistoryEntry
        rows=db.scalars(select(H).where(H.source=='LOADING',H.da_number==old,H.active==True)).all()
        year=rows[0].work_date.year if rows else datetime.now().year
        if _da_in_use(db,year,new,o.id): raise HTTPException(409,f'Ο αριθμός Δ.Α. {new} υπάρχει ήδη')
        for r in rows: r.da_number=new
        o.dispatch_document_number=new
        write_audit(db,user,'loading_order',o.id,'EDIT_DA_NUMBER',old={'da':old},new={'da':new})
        db.commit()
    return _loading_out(db,o)

@app.get('/loading/orders/{order_id}', response_model=schemas.LoadingOrderOut)
def loading_detail(order_id:str,db:Session=Depends(get_db),user=Depends(require_permission('loading.view'))):
    o=db.get(LoadingOrder,order_id)
    if not o: raise HTTPException(404,'Άγνωστη φόρτωση')
    return _loading_out(db,o)

@app.get('/loading/orders/{order_id}/items')
def loading_items(order_id:str,db:Session=Depends(get_db),user=Depends(require_permission('loading.view'))):
    o=db.get(LoadingOrder,order_id)
    if not o: raise HTTPException(404,'Άγνωστη φόρτωση')
    reservations=db.scalars(select(LoadingReservation).where(LoadingReservation.loading_order_id==o.id,LoadingReservation.status=='RESERVED')).all()
    actuals=db.scalars(select(LoadingActual).where(LoadingActual.loading_order_id==o.id)).all()
    def lot_out(lot_id):
        lot=db.get(ReadyMaterialLot,lot_id)
        if not lot: return {'lot_number':None,'material':None}
        mat=db.get(Material,lot.material_id) if lot.material_id else None
        return {'lot_number':lot.lot_number,'material':(mat.her_description or mat.official_description or mat.internal_name) if mat else None}
    return {'reservations':[{'id':r.id,'ready_material_lot_id':r.ready_material_lot_id,'reserved_weight':str(r.reserved_weight),**lot_out(r.ready_material_lot_id)} for r in reservations],
            'actuals':[{'id':a.id,'ready_material_lot_id':a.ready_material_lot_id,'loaded_weight':str(a.loaded_weight),**lot_out(a.ready_material_lot_id)} for a in actuals]}

@app.post('/loading/orders/{order_id}/cancel', response_model=schemas.LoadingOrderOut)
def loading_cancel(order_id:str,db:Session=Depends(get_db),user:User=Depends(require_permission('loading.view'))):
    o=db.get(LoadingOrder,order_id)
    if not o or o.status!='OPEN': raise HTTPException(409,'Η φόρτωση δεν είναι ανοικτή')
    for r in db.scalars(select(LoadingReservation).where(LoadingReservation.loading_order_id==o.id,LoadingReservation.status=='RESERVED')).all():
        lot=db.get(ReadyMaterialLot,r.ready_material_lot_id); r.status='RELEASED'
        if lot and lot.status in ('RESERVED','LOADING'): lot.status='AVAILABLE'
    for a in db.scalars(select(LoadingActual).where(LoadingActual.loading_order_id==o.id)).all():
        lot=db.get(ReadyMaterialLot,a.ready_material_lot_id)
        if lot and lot.status=='LOADING': lot.status='AVAILABLE'
    o.status='CANCELLED'; released=_release_bulk(db,o); write_audit(db,user,'loading_order',o.id,'CANCEL',new={'bulk_released':released})
    db.commit(); return _loading_out(db,o)

@app.get('/loading/bulk-shortages')
def loading_bulk_shortages(label:str,db:Session=Depends(get_db),user=Depends(require_permission('production.view'))):
    """Υπερβάσεις χύμα αποθέματος που επιβεβαιώθηκαν σε οριστικοποιημένες φορτώσεις, για ένα υλικό (νεότερη πρώτη)."""
    rows=db.execute(select(models.LoadingBulkItem,LoadingOrder).join(LoadingOrder,LoadingOrder.id==models.LoadingBulkItem.loading_order_id).where(models.LoadingBulkItem.material_label==label,models.LoadingBulkItem.shortage_kg>0,LoadingOrder.status=='COMPLETED').order_by(LoadingOrder.created_at.desc())).all()
    return [{'order_id':lo.id,'loading_number':lo.loading_number,'da_number':lo.dispatch_document_number,'date':((lo.delivery_date or lo.created_at.date().isoformat())[:10]),'kg':float(bi.shortage_kg),'reason':bi.shortage_reason or ''} for bi,lo in rows]

@app.get('/loading/shipment-history')
def loading_shipment_history(start:str|None=Query(default=None), end:str|None=Query(default=None), kind:str|None=Query(default=None), q:str|None=Query(default=None), db:Session=Depends(get_db), user=Depends(require_permission('loading.view'))):
    stmt=select(models.ShipmentHistoryEntry).where(models.ShipmentHistoryEntry.active==True)
    if start: stmt=stmt.where(models.ShipmentHistoryEntry.work_date>=datetime.fromisoformat(start))
    if end: stmt=stmt.where(models.ShipmentHistoryEntry.work_date<datetime.fromisoformat(end)+timedelta(days=1))
    if kind: stmt=stmt.where(models.ShipmentHistoryEntry.kind==kind)
    rows=db.scalars(stmt.order_by(models.ShipmentHistoryEntry.work_date.desc(),models.ShipmentHistoryEntry.created_at.desc())).all()
    ql=(q or '').strip().lower()
    _orgs={}
    for og in db.scalars(select(Organization)).all():
        for nm in (og.trade_name,og.legal_name):
            if nm:
                k=nm.strip().casefold(); ex=_orgs.get(k)
                if ex is None or (not ex.permit_number and og.permit_number): _orgs[k]=og   # προτιμάται η εγγραφή με άδεια όταν υπάρχουν διπλά ονόματα
    def _perm(name):
        og=_orgs.get((name or '').strip().casefold())
        return (og.permit_number,og.permit_ada) if og else (None,None)
    # Σκοπός φόρτωσης ανά δελτίο: από την οριστικοποιημένη φόρτωση (dispatch_reason)· για παλιές εγγραφές από το είδος (Πώληση / Ενδοδιακίνηση)
    _reason={}
    for lo in db.scalars(select(LoadingOrder).where(LoadingOrder.status=='COMPLETED',LoadingOrder.dispatch_document_number.is_not(None))).all():
        try: y=datetime.fromisoformat(lo.delivery_date).year if lo.delivery_date else lo.created_at.year
        except Exception: y=lo.created_at.year
        _reason[(lo.dispatch_document_number,y)]=(lo.dispatch_reason or '').strip()
    # Υπέρβαση χύμα αποθέματος: σημείωση «Υπέρβαση N kg: λόγος» ανά (Δ.Α., έτος, υλικό)
    _over={}
    for bi,lo in db.execute(select(models.LoadingBulkItem,LoadingOrder).join(LoadingOrder,LoadingOrder.id==models.LoadingBulkItem.loading_order_id).where(LoadingOrder.status=='COMPLETED',LoadingOrder.dispatch_document_number.is_not(None),models.LoadingBulkItem.shortage_kg>0)).all():
        try: y=datetime.fromisoformat(lo.delivery_date).year if lo.delivery_date else lo.created_at.year
        except Exception: y=lo.created_at.year
        _over[(lo.dispatch_document_number,y,bi.material_label)]=f"Υπέρβαση {float(bi.shortage_kg):g} kg: {bi.shortage_reason or ''}".strip()
    def _purpose(r):
        v=_reason.get((r.da_number,r.work_date.year))
        if v: return v
        if r.source=='LOADING': return ''
        return 'Ενδοδιακίνηση' if r.kind=='WEEE_TO_UNIT' else 'Πώληση'
    out=[{"id":r.id,"work_date":r.work_date.isoformat(),"da_number":r.da_number,"weighbridge_number":r.weighbridge_number,
          "transporter":r.transporter,"recipient":r.recipient,"description":r.description,"weight_kg":float(r.weight_kg or 0),
          "eka_code":r.eka_code,"reptool_code":r.reptool_code,"kind":r.kind,"purpose":_purpose(r),"overrun_note":_over.get((r.da_number,r.work_date.year,r.description)),"source":r.source,"first_recipient":r.first_recipient,"mgmt_operation":r.mgmt_operation,"tracking_document":r.tracking_document,"destination_country":r.destination_country,"container_number":r.container_number,"gr_notification_no":r.gr_notification_no,"bill_of_lading":r.bill_of_lading,
          "transporter_permit":_perm(r.transporter)[0],"transporter_ada":_perm(r.transporter)[1],"recipient_permit":_perm(r.recipient)[0],"recipient_ada":_perm(r.recipient)[1]} for r in rows]
    if ql:
        out=[r for r in out if ql in ' '.join(str(r.get(k) or '') for k in ('da_number','transporter','recipient','description','eka_code','reptool_code')).lower()]
    return out


# ---- Build 0.9: Galaxy integration layer (adapter-neutral) ----
import json
from .models import IntegrationMapping, SyncEvent

def _enqueue_sync(db:Session, entity_type:str, entity_id:str, operation:str='UPSERT', payload:dict|None=None):
    key=f'GALAXY:{entity_type}:{entity_id}:{operation}'
    existing=db.scalar(select(SyncEvent).where(SyncEvent.idempotency_key==key))
    if existing: return existing
    ev=SyncEvent(system='GALAXY',entity_type=entity_type,entity_id=entity_id,operation=operation,idempotency_key=key,
        payload_json=json.dumps(payload or {},ensure_ascii=False,default=str),status='PENDING')
    db.add(ev); db.flush(); return ev

@app.get('/integration/galaxy/status', response_model=schemas.GalaxyStatusOut)
def galaxy_status(db:Session=Depends(get_db), user=Depends(require_permission('galaxy.view'))):
    rows=db.scalars(select(SyncEvent).where(SyncEvent.system=='GALAXY')).all(); maps=db.scalars(select(IntegrationMapping).where(IntegrationMapping.system=='GALAXY',IntegrationMapping.active==True)).all()
    return schemas.GalaxyStatusOut(connector_configured=False,pending=sum(x.status in {'PENDING','RETRY'} for x in rows),failed=sum(x.status=='FAILED' for x in rows),
        synced=sum(x.status=='SYNCED' for x in rows),mappings=len(maps),note='Το integration layer είναι έτοιμο. Απαιτούνται τα επίσημα στοιχεία/API της συγκεκριμένης εγκατάστασης Galaxy για τον production adapter.')

@app.get('/integration/galaxy/mappings', response_model=list[schemas.IntegrationMappingOut])
def galaxy_mappings(db:Session=Depends(get_db), user=Depends(require_permission('galaxy.view'))):
    return db.scalars(select(IntegrationMapping).where(IntegrationMapping.system=='GALAXY').order_by(IntegrationMapping.mapping_type,IntegrationMapping.internal_key)).all()

@app.post('/integration/galaxy/mappings', response_model=schemas.IntegrationMappingOut)
def galaxy_mapping_create(data:schemas.IntegrationMappingCreate, db:Session=Depends(get_db), user:User=Depends(require_permission('galaxy.manage'))):
    old=db.scalar(select(IntegrationMapping).where(IntegrationMapping.system=='GALAXY',IntegrationMapping.mapping_type==data.mapping_type,IntegrationMapping.internal_key==data.internal_key))
    if old:
        old.external_key=data.external_key; old.active=True; obj=old; action='UPDATE'
    else:
        obj=IntegrationMapping(system='GALAXY',**data.model_dump()); db.add(obj); db.flush(); action='CREATE'
    write_audit(db,user,'integration_mapping',obj.id,action,new=data.model_dump()); db.commit(); db.refresh(obj); return obj

@app.post('/integration/galaxy/enqueue', response_model=schemas.SyncEventOut)
def galaxy_enqueue(data:schemas.SyncEnqueueCreate, db:Session=Depends(get_db), user:User=Depends(require_permission('galaxy.manage'))):
    ev=_enqueue_sync(db,data.entity_type,data.entity_id,data.operation,data.payload); write_audit(db,user,'sync_event',ev.id,'ENQUEUE',new={'entity_type':data.entity_type,'entity_id':data.entity_id,'operation':data.operation}); db.commit(); db.refresh(ev); return ev

@app.get('/integration/galaxy/queue', response_model=list[schemas.SyncEventOut])
def galaxy_queue(status:str|None=None, db:Session=Depends(get_db), user=Depends(require_permission('galaxy.view'))):
    q=select(SyncEvent).where(SyncEvent.system=='GALAXY').order_by(SyncEvent.created_at.desc())
    if status: q=q.where(SyncEvent.status==status)
    return db.scalars(q).all()

@app.post('/integration/galaxy/events/{event_id}/retry', response_model=schemas.SyncEventOut)
def galaxy_retry(event_id:str,db:Session=Depends(get_db),user:User=Depends(require_permission('galaxy.manage'))):
    ev=db.get(SyncEvent,event_id)
    if not ev or ev.system!='GALAXY': raise HTTPException(404,'Το sync event δεν βρέθηκε')
    ev.status='RETRY'; ev.error_message=None; write_audit(db,user,'sync_event',ev.id,'RETRY'); db.commit(); db.refresh(ev); return ev


# ---- Build 1.0: direct processing + operational dashboard ----
from .models import DirectProcessingMapping, DirectProcessingEvent

@app.get('/master/direct-processing-mappings', response_model=list[schemas.DirectProcessingMappingOut])
def direct_mappings(db:Session=Depends(get_db), user=Depends(require_permission('production.view'))):
    return db.scalars(select(DirectProcessingMapping).where(DirectProcessingMapping.active==True)).all()

@app.post('/master/direct-processing-mappings', response_model=schemas.DirectProcessingMappingOut)
def direct_mapping_create(data:schemas.DirectProcessingMappingCreate, db:Session=Depends(get_db), user:User=Depends(require_permission('settings.manage'))):
    if not db.get(WEEECategory,data.weee_category_id): raise HTTPException(422,'Άγνωστη κατηγορία ΑΗΗΕ')
    if not db.get(Material,data.output_material_id): raise HTTPException(422,'Άγνωστο εξερχόμενο υλικό')
    old=db.scalar(select(DirectProcessingMapping).where(DirectProcessingMapping.weee_category_id==data.weee_category_id))
    if old:
        old.output_material_id=data.output_material_id; old.output_form=data.output_form; old.requires_confirmation=data.requires_confirmation; old.active=True; obj=old; action='UPDATE'
    else:
        obj=DirectProcessingMapping(**data.model_dump()); db.add(obj); db.flush(); action='CREATE'
    write_audit(db,user,'direct_processing_mapping',obj.id,action,new=data.model_dump()); db.commit(); db.refresh(obj); return obj

@app.post('/production/direct-process/{stock_lot_id}', response_model=schemas.ReadyMaterialOut)
def direct_process(stock_lot_id:str,data:schemas.DirectProcessCreate,db:Session=Depends(get_db),user:User=Depends(require_permission('production.move'))):
    lot=db.get(WEEEStockLot,stock_lot_id)
    if not lot or lot.available_weight<=0: raise HTTPException(409,'Το απόθεμα ΑΗΗΕ δεν είναι διαθέσιμο')
    mapping=db.scalar(select(DirectProcessingMapping).where(DirectProcessingMapping.weee_category_id==lot.weee_category_id,DirectProcessingMapping.active==True))
    if not mapping: raise HTTPException(422,'Δεν υπάρχει ενεργή αντιστοίχιση άμεσης παραγωγής για αυτή την κατηγορία')
    if mapping.requires_confirmation and not data.confirm: raise HTTPException(409,'Απαιτείται επιβεβαίωση για την άμεση παραγωγή/εξαγωγή')
    mat=db.get(Material,mapping.output_material_id); ready_loc=_ready_main_location(db); qty=lot.available_weight
    output=ReadyMaterialLot(lot_number=_ready_lot_number(db,mat),material_id=mat.id,output_form=mapping.output_form,collection_medium_id=lot.collection_medium_id,
        net_weight=qty,location_id=ready_loc.id,source_org_unit_id=data.source_org_unit_id,status='AVAILABLE',created_by=user.id,notes=data.notes)
    db.add(output); db.flush(); db.add(ReadyMaterialMovement(lot_id=output.id,movement_type='DIRECT_PRODUCTION_OUT',weight=qty,user_id=user.id,reason=data.notes))
    db.add(StockMovement(domain='WEEE',lot_id=lot.id,movement_type='DIRECT_TO_PRODUCTION',from_location_id=lot.location_id,to_location_id=None,weight=qty,
        org_unit_id=data.source_org_unit_id,user_id=user.id,reason=data.notes))
    lot.available_weight=Decimal('0'); lot.status='CONSUMED'
    db.add(DirectProcessingEvent(source_stock_lot_id=lot.id,mapping_id=mapping.id,output_lot_id=output.id,processed_weight=qty,user_id=user.id))
    if lot.collection_medium_id:
        med=db.get(CollectionMedium,lot.collection_medium_id)
        if med: med.status='READY_STORAGE'
    write_audit(db,user,'direct_processing_event',output.id,'CREATE',new={'source_lot':lot.id,'output_lot':output.lot_number,'weight':str(qty)})
    db.commit(); db.refresh(output); return _ready_out(db,output)

@app.get('/dashboard/operations', response_model=schemas.OperationalDashboardOut)
def operations_dashboard(db:Session=Depends(get_db), user=Depends(require_permission('receipt.view'))):
    active_trip_ids=select(InboundTrip.id).where(InboundTrip.deleted_at.is_(None)); loads=db.scalars(select(InboundLoad).where(InboundLoad.trip_id.in_(active_trip_ids))).all(); sessions=db.scalars(select(SortingSession).join(InboundLoad,SortingSession.inbound_load_id==InboundLoad.id).where(InboundLoad.trip_id.in_(active_trip_ids))).all()
    _sess_with_entries=set(db.scalars(select(SortingEntry.session_id).distinct()).all())
    weee=db.scalars(select(WEEEStockLot).where(WEEEStockLot.available_weight>0)).all()
    prod=db.scalars(select(ProductionInputBalance).where(ProductionInputBalance.status=='OPEN')).all()
    ready=db.scalars(select(ReadyMaterialLot).where(ReadyMaterialLot.status=='AVAILABLE')).all()
    loadings=db.scalars(select(LoadingOrder).where(LoadingOrder.status=='OPEN')).all()
    sync=db.scalars(select(SyncEvent).where(SyncEvent.system=='GALAXY',SyncEvent.status.in_(['PENDING','RETRY']))).all()
    return schemas.OperationalDashboardOut(
        open_receipt_loads=sum(x.status!='CLOSED' for x in loads),
        # ίδιος κανόνας με τη λίστα Ταξινόμησης: «σε εξέλιξη» μόνο όταν η συνεδρία έχει τουλάχιστον μία καταχώρηση
        sorting_in_progress=sum(x.status=='IN_PROGRESS' and x.id in _sess_with_entries for x in sessions),
        waiting_logistics=sum(x.status=='LOGISTICS_REVIEW' for x in sessions),
        waiting_management=sum(x.status=='MANAGEMENT_REVIEW' for x in sessions),
        weee_stock_kg=sum((x.available_weight for x in weee),Decimal('0')),
        production_open_kg=sum((x.current_remaining_weight for x in prod),Decimal('0')),
        ready_stock_kg=sum((x.net_weight for x in ready),Decimal('0')),
        open_loadings=len(loadings),galaxy_pending=len(sync),**_today_orders_progress(db))

def _today_orders_progress(db:Session)->dict:
    """Παραλαβές ημέρας x/y: x = εντολές που παραλήφθηκαν σήμερα, y = x + όσες απομένουν στη ζωντανή ροή (Electrocycle).
    Το y μεγαλώνει όσο ανοίγουν νέες εντολές μέσα στην ημέρα."""
    now=datetime.now(); start=datetime(now.year,now.month,now.day)
    active=InboundTrip.deleted_at.is_(None)
    received={o for (o,) in db.execute(select(InboundLoad.order_number).join(InboundTrip,InboundLoad.trip_id==InboundTrip.id)
        .where(active,InboundLoad.order_number.is_not(None),InboundTrip.receipt_date>=start,InboundTrip.receipt_date<start+timedelta(days=1))).all()}
    used={o for (o,) in db.execute(select(InboundLoad.order_number).join(InboundTrip,InboundLoad.trip_id==InboundTrip.id).where(active,InboundLoad.order_number.is_not(None))).all()}
    feed={o for (o,) in db.execute(select(ElectrocycleOrder.order_no).where(ElectrocycleOrder.source_date==start.date().isoformat(),
        ~func.coalesce(ElectrocycleOrder.sender,'').like('%ΠΡ00959%'))).all()}
    # Μόνο η ζωντανή ροή των Παραλαβών: οι εντολές του αποστολέα ΠΡ00959 ανήκουν στη ζωντανή ροή των Φορτώσεων και δεν μετράνε εδώ.
    loading_orders={o for (o,) in db.execute(select(ElectrocycleOrder.order_no).where(func.coalesce(ElectrocycleOrder.sender,'').like('%ΠΡ00959%'))).all()}
    received-=loading_orders
    return {"today_received":len(received),"today_remaining":len(feed-used)}


# ---- Equipment / PPE / Consumables ----
def _equipment_out(db:Session,item:EquipmentItem)->dict:
    emp=db.get(Employee,item.assigned_employee_id) if item.assigned_employee_id else None
    emp_person=db.get(Person,emp.person_id) if emp else None
    return {"id":item.id,"kind":item.kind,"code":item.code,"name":item.name,"category":item.category,
            "status":item.status,"assigned_employee_id":item.assigned_employee_id,
            "assigned_employee_name":((emp_person.first_name+" "+emp_person.last_name).strip() if emp_person else None),
            "assigned_at":item.assigned_at.isoformat() if item.assigned_at else None,
            "certification_expiry":item.certification_expiry.isoformat() if item.certification_expiry else None,
            "notes":item.notes,"active":item.active}

@app.get("/equipment/items")
def list_equipment_items(kind:str|None=Query(default=None),employee_id:str|None=Query(default=None),include_inactive:bool=Query(default=False),db:Session=Depends(get_db),user=Depends(require_permission("equipment.view"))):
    stmt=select(EquipmentItem)
    if not include_inactive: stmt=stmt.where(EquipmentItem.active==True)
    if kind: stmt=stmt.where(EquipmentItem.kind==kind)
    if employee_id: stmt=stmt.where(EquipmentItem.assigned_employee_id==employee_id)
    rows=db.scalars(stmt.order_by(EquipmentItem.code)).all()
    return [_equipment_out(db,r) for r in rows]

@app.post("/equipment/items")
def create_equipment_item(data:schemas.EquipmentItemCreate,db:Session=Depends(get_db),user:User=Depends(require_permission("equipment.edit"))):
    if data.kind not in ("TOOL","PPE"): raise HTTPException(422,"Μη έγκυρο είδος (TOOL ή PPE)")
    if db.scalar(select(EquipmentItem).where(EquipmentItem.code==data.code)): raise HTTPException(409,"Ο κωδικός υπάρχει ήδη")
    obj=EquipmentItem(**data.model_dump()); db.add(obj); db.flush()
    write_audit(db,user,"equipment_item",obj.id,"CREATE",new=data.model_dump(mode="json")); db.commit(); db.refresh(obj)
    return _equipment_out(db,obj)

@app.put("/equipment/items/{item_id}")
def update_equipment_item(item_id:str,data:schemas.EquipmentItemUpdate,db:Session=Depends(get_db),user:User=Depends(require_permission("equipment.edit"))):
    obj=db.get(EquipmentItem,item_id)
    if not obj: raise HTTPException(404,"Δεν βρέθηκε")
    fields=data.model_dump(exclude_unset=True)
    old=_equipment_out(db,obj)
    for k,v in fields.items(): setattr(obj,k,v)
    write_audit(db,user,"equipment_item",obj.id,"UPDATE",old=old,new=_equipment_out(db,obj))
    db.commit(); db.refresh(obj)
    return _equipment_out(db,obj)

@app.post("/equipment/items/{item_id}/assign")
def assign_equipment_item(item_id:str,data:schemas.EquipmentAssignCreate,db:Session=Depends(get_db),user:User=Depends(require_permission("equipment.edit"))):
    obj=db.get(EquipmentItem,item_id)
    if not obj: raise HTTPException(404,"Δεν βρέθηκε")
    if not db.get(Employee,data.employee_id): raise HTTPException(404,"Ο εργαζόμενος δεν βρέθηκε")
    if obj.status=="ASSIGNED": raise HTTPException(409,"Το είδος είναι ήδη χρεωμένο")
    obj.assigned_employee_id=data.employee_id; obj.assigned_at=datetime.utcnow(); obj.status="ASSIGNED"
    write_audit(db,user,"equipment_item",obj.id,"ASSIGN",new={"employee_id":data.employee_id})
    db.commit(); db.refresh(obj)
    return _equipment_out(db,obj)

@app.post("/equipment/items/{item_id}/return")
def return_equipment_item(item_id:str,db:Session=Depends(get_db),user:User=Depends(require_permission("equipment.edit"))):
    obj=db.get(EquipmentItem,item_id)
    if not obj: raise HTTPException(404,"Δεν βρέθηκε")
    old_emp=obj.assigned_employee_id
    obj.assigned_employee_id=None; obj.assigned_at=None; obj.status="AVAILABLE"
    write_audit(db,user,"equipment_item",obj.id,"RETURN",old={"employee_id":old_emp})
    db.commit(); db.refresh(obj)
    return _equipment_out(db,obj)

@app.delete("/equipment/items/{item_id}")
def deactivate_equipment_item(item_id:str,db:Session=Depends(get_db),user:User=Depends(require_permission("equipment.edit"))):
    obj=db.get(EquipmentItem,item_id)
    if not obj: raise HTTPException(404,"Δεν βρέθηκε")
    obj.active=False
    write_audit(db,user,"equipment_item",obj.id,"DEACTIVATE")
    db.commit(); return {"ok":True}

@app.post("/equipment/items/{item_id}/activate")
def activate_equipment_item(item_id:str,db:Session=Depends(get_db),user:User=Depends(require_permission("equipment.edit"))):
    obj=db.get(EquipmentItem,item_id)
    if not obj: raise HTTPException(404,"Δεν βρέθηκε")
    obj.active=True
    write_audit(db,user,"equipment_item",obj.id,"ACTIVATE")
    db.commit(); return {"ok":True}

def _consumable_type_out(db:Session,ct:ConsumableType)->dict:
    lots=db.scalars(select(ConsumableLot).where(ConsumableLot.consumable_type_id==ct.id,ConsumableLot.active==True)).all()
    total=sum((l.quantity for l in lots),Decimal('0'))
    now=datetime.utcnow()
    expired=[l for l in lots if l.expiry_date and l.expiry_date<now]
    return {"id":ct.id,"code":ct.code,"name":ct.name,"unit":ct.unit,
            "low_stock_threshold":float(ct.low_stock_threshold) if ct.low_stock_threshold is not None else None,
            "current_stock":float(total),"low_stock":bool(ct.low_stock_threshold is not None and total<ct.low_stock_threshold),
            "expired_lots":len(expired),"notes":ct.notes,"active":ct.active}

@app.get("/equipment/consumables")
def list_consumable_types(include_inactive:bool=Query(default=False),db:Session=Depends(get_db),user=Depends(require_permission("equipment.view"))):
    stmt=select(ConsumableType)
    if not include_inactive: stmt=stmt.where(ConsumableType.active==True)
    rows=db.scalars(stmt.order_by(ConsumableType.code)).all()
    return [_consumable_type_out(db,r) for r in rows]

@app.post("/equipment/consumables")
def create_consumable_type(data:schemas.ConsumableTypeCreate,db:Session=Depends(get_db),user:User=Depends(require_permission("equipment.edit"))):
    if db.scalar(select(ConsumableType).where(ConsumableType.code==data.code)): raise HTTPException(409,"Ο κωδικός υπάρχει ήδη")
    obj=ConsumableType(**data.model_dump()); db.add(obj); db.flush()
    write_audit(db,user,"consumable_type",obj.id,"CREATE",new=data.model_dump(mode="json")); db.commit(); db.refresh(obj)
    return _consumable_type_out(db,obj)

@app.put("/equipment/consumables/{type_id}")
def update_consumable_type(type_id:str,data:schemas.ConsumableTypeUpdate,db:Session=Depends(get_db),user:User=Depends(require_permission("equipment.edit"))):
    obj=db.get(ConsumableType,type_id)
    if not obj: raise HTTPException(404,"Δεν βρέθηκε")
    fields=data.model_dump(exclude_unset=True)
    for k,v in fields.items(): setattr(obj,k,v)
    write_audit(db,user,"consumable_type",obj.id,"UPDATE",new=fields)
    db.commit(); db.refresh(obj)
    return _consumable_type_out(db,obj)

@app.delete("/equipment/consumables/{type_id}")
def deactivate_consumable_type(type_id:str,db:Session=Depends(get_db),user:User=Depends(require_permission("equipment.edit"))):
    obj=db.get(ConsumableType,type_id)
    if not obj: raise HTTPException(404,"Δεν βρέθηκε")
    obj.active=False
    write_audit(db,user,"consumable_type",obj.id,"DEACTIVATE")
    db.commit(); return {"ok":True}

@app.post("/equipment/consumables/{type_id}/activate")
def activate_consumable_type(type_id:str,db:Session=Depends(get_db),user:User=Depends(require_permission("equipment.edit"))):
    obj=db.get(ConsumableType,type_id)
    if not obj: raise HTTPException(404,"Δεν βρέθηκε")
    obj.active=True
    write_audit(db,user,"consumable_type",obj.id,"ACTIVATE")
    db.commit(); return {"ok":True}

@app.get("/equipment/consumables/{type_id}/lots")
def list_consumable_lots(type_id:str,db:Session=Depends(get_db),user=Depends(require_permission("equipment.view"))):
    rows=db.scalars(select(ConsumableLot).where(ConsumableLot.consumable_type_id==type_id,ConsumableLot.active==True).order_by(ConsumableLot.received_date)).all()
    return [{"id":l.id,"quantity":float(l.quantity),"received_date":l.received_date.isoformat(),
             "expiry_date":l.expiry_date.isoformat() if l.expiry_date else None,"notes":l.notes} for l in rows]

@app.post("/equipment/consumables/{type_id}/lots")
def add_consumable_lot(type_id:str,data:schemas.ConsumableLotCreate,db:Session=Depends(get_db),user:User=Depends(require_permission("equipment.edit"))):
    ct=db.get(ConsumableType,type_id)
    if not ct: raise HTTPException(404,"Το αναλώσιμο δεν βρέθηκε")
    obj=ConsumableLot(consumable_type_id=type_id,**data.model_dump()); db.add(obj); db.flush()
    write_audit(db,user,"consumable_lot",obj.id,"CREATE",new=data.model_dump(mode="json"))
    db.commit(); db.refresh(obj)
    return {"id":obj.id,"quantity":float(obj.quantity),"received_date":obj.received_date.isoformat(),"expiry_date":obj.expiry_date.isoformat() if obj.expiry_date else None}

@app.delete("/equipment/consumables/lots/{lot_id}")
def remove_consumable_lot(lot_id:str,db:Session=Depends(get_db),user:User=Depends(require_permission("equipment.edit"))):
    obj=db.get(ConsumableLot,lot_id)
    if not obj: raise HTTPException(404,"Δεν βρέθηκε")
    obj.active=False
    write_audit(db,user,"consumable_lot",obj.id,"DEACTIVATE")
    db.commit(); return {"ok":True}

@app.get("/equipment/alerts")
def equipment_alerts(days_ahead:int=Query(default=30,ge=1,le=365),db:Session=Depends(get_db),user=Depends(require_permission("equipment.view"))):
    now=datetime.utcnow(); horizon=now+timedelta(days=days_ahead)
    ppe_expiring=db.scalars(select(EquipmentItem).where(EquipmentItem.active==True,EquipmentItem.kind=='PPE',EquipmentItem.certification_expiry.isnot(None),EquipmentItem.certification_expiry<=horizon)).all()
    types=db.scalars(select(ConsumableType).where(ConsumableType.active==True)).all()
    low_stock=[]; expiring_lots=[]
    for ct in types:
        info=_consumable_type_out(db,ct)
        if info["low_stock"]: low_stock.append(info)
        lots=db.scalars(select(ConsumableLot).where(ConsumableLot.consumable_type_id==ct.id,ConsumableLot.active==True,ConsumableLot.expiry_date.isnot(None),ConsumableLot.expiry_date<=horizon)).all()
        for l in lots: expiring_lots.append({"consumable_type_id":ct.id,"consumable_name":ct.name,"lot_id":l.id,"quantity":float(l.quantity),"expiry_date":l.expiry_date.isoformat()})
    return {"ppe_certification_expiring":[_equipment_out(db,x) for x in ppe_expiring],"consumables_low_stock":low_stock,"consumable_lots_expiring":expiring_lots}

# ---- Αναφορές και Στατιστικά: έτοιμες φόρμες αναφορών (Excel/PDF) ανά κατηγορία ----
REPORT_CATEGORIES={"receipts","processing","dispatch","statistics","recycling"}
REPORT_EXTENSIONS={".xlsx",".xlsm",".xls",".csv",".pdf"}
REPORT_MAX_BYTES=25*1024*1024

def _report_dir(category:str)->Path:
    if category not in REPORT_CATEGORIES: raise HTTPException(404,"Άγνωστη κατηγορία αναφορών")
    d=Path(settings.report_templates_dir)/category; d.mkdir(parents=True,exist_ok=True); return d

def _report_kind(name:str)->str:
    n=name.strip().lower()
    if n.startswith("ημερήσι"): return "DAILY"
    if n.startswith("μηνιαί"): return "MONTHLY"
    return "OTHER"

@app.get("/reports/templates/{category}")
def list_report_templates(category:str, user:User=Depends(current_user)):
    d=_report_dir(category)
    out=[{"name":p.name,"size":p.stat().st_size,"modified":datetime.fromtimestamp(p.stat().st_mtime).isoformat(),"kind":_report_kind(p.name)} for p in d.iterdir() if p.is_file() and p.suffix.lower() in REPORT_EXTENSIONS]
    return sorted(out,key=lambda x:x["name"].casefold())

@app.get("/reports/templates/{category}/file")
def download_report_template(category:str, name:str=Query(...), user:User=Depends(current_user)):
    p=_report_dir(category)/Path(name).name
    if not p.is_file(): raise HTTPException(404,"Το αρχείο δεν βρέθηκε")
    return FileResponse(p,filename=p.name)

@app.post("/reports/templates/{category}")
async def upload_report_template(category:str, file:UploadFile=File(...), db:Session=Depends(get_db), user:User=Depends(require_permission("reports.manage"))):
    d=_report_dir(category)
    name=Path(file.filename or "").name
    if not name or Path(name).suffix.lower() not in REPORT_EXTENSIONS: raise HTTPException(422,"Επιτρέπονται αρχεία Excel (.xlsx, .xlsm, .xls), .csv ή .pdf")
    data=await file.read(REPORT_MAX_BYTES+1)
    if len(data)>REPORT_MAX_BYTES: raise HTTPException(413,"Το αρχείο ξεπερνά τα 25 MB")
    (d/name).write_bytes(data)
    write_audit(db,user,"report_template",None,"UPLOAD",new={"category":category,"name":name,"size":len(data)}); db.commit()
    return {"name":name,"size":len(data),"kind":_report_kind(name)}

@app.delete("/reports/templates/{category}")
def delete_report_template(category:str, name:str=Query(...), db:Session=Depends(get_db), user:User=Depends(require_permission("reports.manage"))):
    p=_report_dir(category)/Path(name).name
    if not p.is_file(): raise HTTPException(404,"Το αρχείο δεν βρέθηκε")
    p.unlink()
    write_audit(db,user,"report_template",None,"DELETE",old={"category":category,"name":p.name}); db.commit()
    return {"ok":True}

from . import report_generators
for _r in report_generators.router.routes: app.add_api_route(_r.path,_r.endpoint,methods=list(_r.methods))

@app.get("/common/search-norm.js")
def common_search_norm_js():
    """Κοινή κανονικοποίηση αναζήτησης (ελληνικά ≡ λατινικά ομοιόμορφα γράμματα) για Windows και Android."""
    return FileResponse(static_dir / "search_norm.js", media_type="application/javascript", headers={"Cache-Control":"no-store, no-cache, must-revalidate, max-age=0"})

@app.get("/mobile")
def mobile_workspace():
    return FileResponse(static_dir / "mobile_v12.html", headers={"Cache-Control":"no-store, no-cache, must-revalidate, max-age=0","Pragma":"no-cache","Expires":"0","X-WEEE-Build":"1.9"})
