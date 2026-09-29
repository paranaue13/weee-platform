import asyncio, logging
from contextlib import asynccontextmanager
from datetime import datetime, timezone, timedelta
from fastapi import FastAPI, Depends, HTTPException, Query, Request
from sqlalchemy import select, inspect, text, update
from sqlalchemy.orm import Session, aliased
from .db import Base, engine, get_db, SessionLocal
from . import models, schemas
from .models import User, OrganizationalUnit, Organization, WEEECategory, Material, CollectionMediumType, CollectionMedium, AppSetting, Employee, Person, ProductionWorkEntry, MaterialOutputEntry, OrgUnitPosition, employee_org_units, EquipmentItem, ConsumableType, ConsumableLot, MaterialOpeningStock, ElectrocycleOrder, ElectrocycleSyncStatus
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
    # Small forward-compatible migration for existing 1.x SQLite/PostgreSQL databases.
    inspector=inspect(engine)
    cols={c["name"] for c in inspector.get_columns("collection_media")} if "collection_media" in inspector.get_table_names() else set()
    if "linked_loading_order_id" not in cols:
        with engine.begin() as conn:
            conn.execute(text("ALTER TABLE collection_media ADD COLUMN linked_loading_order_id VARCHAR(36)"))
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
        if "organizational_units" in tables:
            org_cols={c["name"] for c in inspect(engine).get_columns("organizational_units")}
            if "position" not in org_cols: conn.execute(text("ALTER TABLE organizational_units ADD COLUMN position VARCHAR(150)"))
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

@app.get("/health")
def health(): return {"status":"ok","version":"2.5.35"}

@app.post("/auth/token", response_model=schemas.Token)
def login(req: schemas.LoginRequest, db: Session=Depends(get_db)):
    user=db.scalar(select(User).where(User.username==req.username))
    if not user or not user.active or not verify_password(req.password,user.password_hash):
        raise HTTPException(401,"Λάθος στοιχεία σύνδεσης")
    user.last_login=datetime.now(timezone.utc); db.commit()
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
        out.append({"id":u.id,"code":u.code,"name_el":u.name_el,"name_en":u.name_en,"parent_id":u.parent_id,"sort_order":u.sort_order,"position":u.position,"positions":[x.name for x in poss],"active":u.active})
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
    payload=data.model_dump(exclude={"positions"}); obj=OrganizationalUnit(**payload); db.add(obj); db.flush(); _replace_org_positions(db,obj.id,data.positions)
    write_audit(db,user,"organizational_unit",obj.id,"CREATE",new=data.model_dump()); db.commit();
    rows=list_org_units(True,db,user); return next(x for x in rows if x["id"]==obj.id)

@app.put("/master/org-units/{unit_id}", response_model=schemas.OrgUnitOut)
def update_org_unit(unit_id:str, data:schemas.OrgUnitCreate, db:Session=Depends(get_db), user:User=Depends(require_permission("master.edit"))):
    obj=db.get(OrganizationalUnit,unit_id)
    if not obj: raise HTTPException(404,"Το τμήμα δεν βρέθηκε")
    old={"code":obj.code,"name_el":obj.name_el,"name_en":obj.name_en,"parent_id":obj.parent_id,"sort_order":obj.sort_order,"position":obj.position}
    for k,v in data.model_dump(exclude={"positions"}).items(): setattr(obj,k,v)
    if "positions" in data.model_fields_set: _replace_org_positions(db,obj.id,data.positions)
    write_audit(db,user,"organizational_unit",obj.id,"UPDATE",old=old,new=data.model_dump(exclude={"positions"}))
    db.commit()
    rows=list_org_units(True,db,user); return next(x for x in rows if x["id"]==obj.id)

@app.delete("/master/org-units/{unit_id}")
def delete_org_unit(unit_id:str, db:Session=Depends(get_db), user:User=Depends(require_permission("master.edit"))):
    obj=db.get(OrganizationalUnit,unit_id)
    if not obj: raise HTTPException(404,"Το τμήμα δεν βρέθηκε")
    obj.active=False; write_audit(db,user,"organizational_unit",obj.id,"DEACTIVATE",old={"active":True},new={"active":False}); db.commit(); return {"ok":True}

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
        if k in ("supplier_kind","supplier_source") and k not in data.model_fields_set: continue
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
    used=db.scalar(select(InboundLoad.id).where(InboundLoad.supplier_id==organization_id).limit(1)) or db.scalar(select(InboundTrip.id).where(InboundTrip.carrier_id==organization_id).limit(1))
    if used: raise HTTPException(409,"Η εγγραφή έχει χρησιμοποιηθεί. Χρησιμοποίησε «Μη ενεργό» για να διατηρηθεί το ιστορικό.")
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
    old={"code":obj.code,"description_el":obj.description_el,"her_description":obj.her_description,"eka_code":obj.eka_code,"processable":obj.processable}
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

@app.get("/master/media", response_model=list[schemas.MediumOut])
def list_media(include_inactive:bool=Query(default=False), db:Session=Depends(get_db), user=Depends(require_permission("master.view"))):
    stmt=select(CollectionMedium)
    if not include_inactive: stmt=stmt.where(CollectionMedium.active==True)
    return db.scalars(stmt.order_by(CollectionMedium.code)).all()

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
    if not code: raise HTTPException(422,"Απαιτείται κωδικός μέσου")
    if db.scalar(select(CollectionMedium).where(CollectionMedium.code==code)): raise HTTPException(409,"Ο κωδικός μέσου υπάρχει ήδη")
    if data.linked_loading_order_id and not db.get(models.LoadingOrder,data.linked_loading_order_id): raise HTTPException(422,"Άγνωστο δελτίο φόρτωσης")
    tare=data.tare_weight if data.tare_weight is not None else mt.default_tare_weight
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
    x.type_id=data.type_id; x.code=data.code or x.code; x.tare_weight=data.tare_weight; x.linked_loading_order_id=data.linked_loading_order_id
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
    for k,v in data.model_dump().items(): setattr(x,k,v)
    _apply_material_rules(x)
    write_audit(db,user,"material",x.id,"UPDATE",old=old,new=data.model_dump())
    db.commit(); db.refresh(x); return x

@app.get("/master/materials/{item_id}/history")
def material_history(item_id:str, db:Session=Depends(get_db), user=Depends(require_permission("master.view"))):
    events=db.scalars(select(models.AuditEvent).where(models.AuditEvent.entity_type=="material",models.AuditEvent.entity_id==item_id).order_by(models.AuditEvent.created_at.desc())).all()
    uids={e.user_id for e in events if e.user_id}
    users={u.id:u.username for u in db.scalars(select(User).where(User.id.in_(uids))).all()} if uids else {}
    return [{"action":e.action,"old_values":json.loads(e.old_values) if e.old_values else None,"new_values":json.loads(e.new_values) if e.new_values else None,"reason":e.reason,"user":users.get(e.user_id),"created_at":e.created_at.isoformat()} for e in events]

MASTER_HISTORY_ENTITY_TYPES={"container","collection_medium","material","weee_category","organizational_unit","employee"}
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


def _employee_public(db:Session,e:Employee,p:Person):
    ids=[r[0] for r in db.execute(select(employee_org_units.c.org_unit_id).where(employee_org_units.c.employee_id==e.id)).all()]
    units=db.scalars(select(OrganizationalUnit).where(OrganizationalUnit.id.in_(ids))).all() if ids else []
    names=[u.name_el for u in sorted(units,key=lambda u:u.name_el)]
    return {"id":e.id,"employee_code":e.employee_code,"full_name":((p.first_name+" "+p.last_name).strip()),"phone":p.phone,"default_org_unit_id":e.default_org_unit_id,"org_unit_ids":ids,"org_unit_names":names,"active":bool(e.active and p.active)}

def _replace_employee_units(db:Session,emp:Employee,ids:list[str]):
    clean=[]
    for unit_id in ids or []:
        if unit_id and unit_id not in clean:
            if not db.get(OrganizationalUnit,unit_id): raise HTTPException(422,"Άγνωστο τμήμα")
            clean.append(unit_id)
    db.execute(employee_org_units.delete().where(employee_org_units.c.employee_id==emp.id))
    for unit_id in clean: db.execute(employee_org_units.insert().values(employee_id=emp.id,org_unit_id=unit_id))
    emp.default_org_unit_id=clean[0] if clean else None

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
    obj=ProductionWorkEntry(**data.model_dump(),created_by_user_id=user.id); db.add(obj); db.commit(); db.refresh(obj); return obj

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

@app.get("/inventory/material-corrections")
def list_material_corrections(year:int=Query(...), month:int=Query(...), db:Session=Depends(get_db), user=Depends(require_permission("production.view"))):
    start=datetime(year,month,1); end=datetime(year+1,1,1) if month==12 else datetime(year,month+1,1)
    rows=db.scalars(select(models.MaterialCorrectionEntry).where(models.MaterialCorrectionEntry.work_date>=start,models.MaterialCorrectionEntry.work_date<end).order_by(models.MaterialCorrectionEntry.work_date)).all()
    uids={r.created_by_user_id for r in rows if r.created_by_user_id}
    users={u.id:u.username for u in db.scalars(select(User).where(User.id.in_(uids))).all()} if uids else {}
    return [schemas.MaterialCorrectionOut(id=r.id,work_date=r.work_date.date().isoformat(),material_label=r.material_label,weight_kg_delta=r.weight_kg_delta,piece_delta=r.piece_delta,reason=r.reason,created_by=users.get(r.created_by_user_id)) for r in rows]

@app.post("/inventory/material-corrections", response_model=schemas.MaterialCorrectionOut)
def create_material_correction(data:schemas.MaterialCorrectionIn, db:Session=Depends(get_db), user:User=Depends(require_permission("production.move"))):
    wd=datetime.fromisoformat(data.work_date)
    obj=models.MaterialCorrectionEntry(work_date=wd,material_label=data.material_label,weight_kg_delta=data.weight_kg_delta,piece_delta=data.piece_delta,reason=data.reason,created_by_user_id=user.id)
    db.add(obj); db.flush()
    write_audit(db,user,'material_correction',obj.id,'CREATE',new={'material':data.material_label,'kg':str(data.weight_kg_delta),'pieces':data.piece_delta,'reason':data.reason})
    db.commit(); db.refresh(obj)
    return schemas.MaterialCorrectionOut(id=obj.id,work_date=obj.work_date.date().isoformat(),material_label=obj.material_label,weight_kg_delta=obj.weight_kg_delta,piece_delta=obj.piece_delta,reason=obj.reason,created_by=user.username)

@app.delete("/inventory/material-corrections/{entry_id}")
def delete_material_correction(entry_id:str, db:Session=Depends(get_db), user:User=Depends(require_permission("production.move"))):
    obj=db.get(models.MaterialCorrectionEntry,entry_id)
    if not obj: raise HTTPException(404,"Δεν βρέθηκε")
    write_audit(db,user,'material_correction',obj.id,'DELETE',old={'material':obj.material_label,'kg':str(obj.weight_kg_delta),'pieces':obj.piece_delta})
    db.delete(obj); db.commit()
    return {"ok":True}

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
    trip.deleted_at=None; write_audit(db,user,"receipt",receipt_id,"RESTORE",new={"deleted":False}); db.commit()
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
          'piece_count':e.piece_count,'notes':e.notes,'created_at':e.created_at.isoformat()})
    photos=db.scalars(select(FileAttachment).where(FileAttachment.entity_type=='INBOUND_LOAD',FileAttachment.entity_id==load.id).order_by(FileAttachment.created_at)).all()
    audits=db.scalars(select(models.AuditEvent).where(models.AuditEvent.entity_type.in_(['sorting_session','sorting_entry'])).order_by(models.AuditEvent.created_at.desc()).limit(100)).all()
    return {'load_id':load.id,'receipt_id':trip.id,'status':(ses.status if ses else load.status),'receipt_number':trip.receipt_number,'receipt_type':trip.receipt_type,'receipt_date':trip.receipt_date.isoformat(),
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
    if ses.status!='IN_PROGRESS': raise HTTPException(409,'Η ταξινόμηση δεν είναι σε επεξεργασία')
    cat=db.get(WEEECategory,data.weee_category_id)
    if not cat: raise HTTPException(422,'Άγνωστη κατηγορία ΑΗΗΕ')
    if data.collection_medium_id and not db.get(CollectionMedium,data.collection_medium_id): raise HTTPException(422,'Άγνωστο μέσο συλλογής')
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
    obj=SortingEntry(session_id=ses.id,weee_category_id=data.weee_category_id,collection_medium_id=data.collection_medium_id,
      entry_type=data.entry_type,raw_weight=raw,piece_count=data.piece_count,created_by=user.id,notes=data.notes)
    db.add(obj); db.flush(); write_audit(db,user,'sorting_entry',obj.id,'CREATE',new={'load_id':load_id,'category':cat.code,'weight':str(raw),'pieces':data.piece_count})
    db.commit(); db.refresh(obj); return obj

@app.put('/sorting/entries/{entry_id}', response_model=schemas.SortingEntryOut)
def sorting_edit_entry(entry_id:str, data:schemas.SortingEntryCreate, db:Session=Depends(get_db), user:User=Depends(require_permission('sorting.perform'))):
    _nonneg(data.raw_weight,'Βάρος'); _nonneg(data.piece_count,'Τεμάχια')
    e=db.get(SortingEntry,entry_id)
    if not e: raise HTTPException(404,'Η εγγραφή δεν βρέθηκε')
    ses=db.get(SortingSession,e.session_id)
    if not ses or ses.status!='IN_PROGRESS': raise HTTPException(409,'Η ταξινόμηση έχει ήδη επιβεβαιωθεί')
    cat=db.get(WEEECategory,data.weee_category_id)
    if not cat: raise HTTPException(422,'Άγνωστη κατηγορία ΑΗΗΕ')
    old={'category_id':e.weee_category_id,'medium_id':e.collection_medium_id,'weight':str(e.raw_weight),'pieces':e.piece_count}
    e.weee_category_id=data.weee_category_id; e.collection_medium_id=data.collection_medium_id; e.entry_type=data.entry_type
    e.raw_weight=data.raw_weight; e.piece_count=data.piece_count; e.notes=data.notes
    if data.entry_type=='BULK' and data.piece_count is not None:
        if cat.average_weight is None: raise HTTPException(422,'Δεν υπάρχει μέσο βάρος για το χύμα υλικό')
        e.raw_weight=Decimal(data.piece_count)*cat.average_weight
    write_audit(db,user,'sorting_entry',e.id,'EDIT_DRAFT',old=old,new={'category_id':e.weee_category_id,'medium_id':e.collection_medium_id,'weight':str(e.raw_weight),'pieces':e.piece_count})
    db.commit(); db.refresh(e); return e

@app.get('/sorting/{load_id}/medium-type-suggestions')
def sorting_medium_type_suggestions(load_id:str, weee_category_id:str, db:Session=Depends(get_db), user:User=Depends(require_permission('sorting.perform'))):
    from sqlalchemy import func
    rows=db.execute(select(CollectionMedium.type_id, func.count(models.SortingEntry.id).label('n')).join(models.SortingEntry, models.SortingEntry.collection_medium_id==CollectionMedium.id).where(models.SortingEntry.weee_category_id==weee_category_id, CollectionMedium.active==True).group_by(CollectionMedium.type_id).order_by(func.count(models.SortingEntry.id).desc())).all()
    types={x.id:x for x in db.scalars(select(CollectionMediumType).where(CollectionMediumType.active==True)).all()}
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
    code=(data.code or '').strip()
    if mt.code=='BULK' and not code:
        seq=len(db.scalars(select(CollectionMedium).where(CollectionMedium.code.like('BULK-%'))).all())+1
        code=f'BULK-{datetime.now().year}-{seq:06d}'
    if not code: raise HTTPException(422,'Γράψε αριθμό / κωδικό μέσου')
    existing=db.scalar(select(CollectionMedium).where(CollectionMedium.code==code,CollectionMedium.active==True))
    if existing:
        if existing.type_id!=data.type_id: raise HTTPException(409,'Ο κωδικός χρησιμοποιείται από άλλο τύπο μέσου')
        return existing
    tare=data.tare_weight if data.tare_weight is not None else mt.default_tare_weight
    obj=CollectionMedium(type_id=data.type_id,code=code,tare_weight=tare,linked_loading_order_id=data.linked_loading_order_id)
    db.add(obj); db.flush(); write_audit(db,user,'collection_medium',obj.id,'CREATE_FROM_SORTING',new={'code':code,'type':mt.code,'tare':str(tare) if tare is not None else None}); db.commit(); db.refresh(obj); return obj

@app.get('/sorting/{load_id}/medium-suggestions')
def sorting_medium_suggestions(load_id:str, weee_category_id:str, db:Session=Depends(get_db), user:User=Depends(require_permission('sorting.perform'))):
    load,ses=_session_for_load(db,load_id,False)
    if not ses: return []
    entries=db.scalars(select(SortingEntry).where(SortingEntry.weee_category_id==weee_category_id,SortingEntry.collection_medium_id.is_not(None)).order_by(SortingEntry.created_at.desc())).all()
    seen=set(); out=[]
    for e in entries:
        if e.collection_medium_id in seen: continue
        med=db.get(CollectionMedium,e.collection_medium_id)
        if not med or not med.active: continue
        seen.add(med.id)
        out.append({'id':med.id,'type_id':med.type_id,'code':med.code,'tare_weight':float(med.tare_weight) if med.tare_weight is not None else None,'used_by_me':e.created_by==user.id,'last_used_at':e.created_at.isoformat()})
    out.sort(key=lambda x:(not x['used_by_me'], x['last_used_at']), reverse=False)
    return out

@app.delete('/sorting/entries/{entry_id}')
def sorting_delete_entry(entry_id:str, db:Session=Depends(get_db), user:User=Depends(require_permission('sorting.perform'))):
    e=db.get(SortingEntry,entry_id)
    if not e: raise HTTPException(404,'Η εγγραφή δεν βρέθηκε')
    ses=db.get(SortingSession,e.session_id)
    if ses.status!='IN_PROGRESS': raise HTTPException(409,'Η ταξινόμηση έχει ήδη επιβεβαιωθεί')
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
    ses.status='LOGISTICS_REVIEW'; ses.sorting_confirmed_at=datetime.now(timezone.utc); ses.sorting_confirmed_by=user.id; load.status='SORTING_CONFIRMED'
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
    e.approved_weight=data.new_weight
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
        ses.status='CLOSED'; load.status='CLOSED'
        _materialize_weee_stock(db, load, ses, user)
    write_audit(db,user,'sorting_session',ses.id,'LOGISTICS_REVIEW',new={'requires_management':data.requires_management_approval,'final_weight':str(final)})
    db.commit(); return _sorting_payload(db,load,ses)


@app.post('/sorting/{load_id}/reopen', response_model=schemas.SortingSessionOut)
def sorting_reopen(load_id:str, reason:str=Query(default='Επιστροφή για διόρθωση'), db:Session=Depends(get_db), user:User=Depends(require_permission('sorting.review'))):
    load,ses=_session_for_load(db,load_id,False)
    if not ses or ses.status not in {'LOGISTICS_REVIEW','MANAGEMENT_REVIEW'}: raise HTTPException(409,'Η ταξινόμηση δεν μπορεί να επιστραφεί σε αυτή την κατάσταση')
    old=ses.status; ses.status='IN_PROGRESS'; load.status='SORTING_IN_PROGRESS'
    write_audit(db,user,'sorting_session',ses.id,'REOPEN_TO_SORTING',old={'status':old},new={'status':'IN_PROGRESS'},reason=reason)
    db.commit(); return _sorting_payload(db,load,ses)

@app.post('/sorting/{load_id}/management-approve', response_model=schemas.SortingSessionOut)
def management_approve(load_id:str, db:Session=Depends(get_db), user:User=Depends(require_permission('sorting.approve'))):
    load,ses=_session_for_load(db,load_id,False)
    if not ses or ses.status!='MANAGEMENT_REVIEW': raise HTTPException(409,'Δεν υπάρχει εκκρεμής έγκριση Διοίκησης')
    ses.status='CLOSED'; ses.management_confirmed_at=datetime.now(timezone.utc); ses.management_confirmed_by=user.id; load.status='CLOSED'
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

@app.get('/settings/schedule')
def schedule_get(db:Session=Depends(get_db), user:User=Depends(current_user)):
    row=db.scalar(select(AppSetting).where(AppSetting.key==SCHEDULE_KEY))
    if not row: return DEFAULT_SCHEDULE
    try: return json.loads(row.value)
    except Exception: return DEFAULT_SCHEDULE

@app.put('/settings/schedule')
def schedule_put(data:dict, db:Session=Depends(get_db), user:User=Depends(require_permission('settings.manage'))):
    active=data.get('active')
    if active not in ('summer','winter','special'): raise HTTPException(422,'Μη έγκυρη επιλογή ωραρίου')
    summer={'start':_check_time((data.get('summer') or {}).get('start'),'Θερινό'),'end':_check_time((data.get('summer') or {}).get('end'),'Θερινό')}
    winter={'start':_check_time((data.get('winter') or {}).get('start'),'Χειμερινό'),'end':_check_time((data.get('winter') or {}).get('end'),'Χειμερινό')}
    special={'start':_check_time((data.get('special') or {}).get('start'),'Έκτακτο'),'end':_check_time((data.get('special') or {}).get('end'),'Έκτακτο')}
    if summer['start']>=summer['end']: raise HTTPException(422,'Θερινό: η ώρα λήξης πρέπει να είναι μετά την έναρξη')
    if winter['start']>=winter['end']: raise HTTPException(422,'Χειμερινό: η ώρα λήξης πρέπει να είναι μετά την έναρξη')
    if special['start']>=special['end']: raise HTTPException(422,'Έκτακτο: η ώρα λήξης πρέπει να είναι μετά την έναρξη')
    payload={'active':active,'summer':summer,'winter':winter,'special':special}
    row=db.scalar(select(AppSetting).where(AppSetting.key==SCHEDULE_KEY))
    old=row.value if row else None
    if row: row.value=json.dumps(payload,ensure_ascii=False)
    else: db.add(AppSetting(key=SCHEDULE_KEY,value=json.dumps(payload,ensure_ascii=False)))
    write_audit(db,user,'app_setting',SCHEDULE_KEY,'UPDATE',old={'schedule':old},new={'schedule':payload}); db.commit()
    return payload

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
        if (t.id if t else 'NONE')!=type_key: continue
        if t: type_name=t.name_el
        g=groups.setdefault(lot.collection_medium_id or 'NONE',{'medium_id':lot.collection_medium_id,'code':m.code if m else 'Χύμα','kg':0.0})
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

@app.get('/inventory/weee/by-medium/{medium_id}', response_model=list[schemas.WEEEStockLotOut])
def weee_inventory_medium(medium_id:str, db:Session=Depends(get_db), user=Depends(require_permission('production.view'))):
    rows=db.scalars(select(WEEEStockLot).where(WEEEStockLot.collection_medium_id==medium_id,WEEEStockLot.available_weight>0)).all()
    return [_lot_out(db,x) for x in rows]

def _transfer_number(db:Session)->str:
    year=datetime.now().year
    rows=db.scalars(select(ProductionTransfer).where(ProductionTransfer.transfer_number.like(f'PRD-{year}-%'))).all()
    return f'PRD-{year}-{len(rows)+1:06d}'

@app.post('/production/transfers', response_model=schemas.ProductionTransferOut)
def production_transfer(data:schemas.ProductionTransferCreate, db:Session=Depends(get_db), user:User=Depends(require_permission('production.move'))):
    unit=db.get(OrganizationalUnit,data.destination_org_unit_id)
    if not unit or not unit.active: raise HTTPException(422,'Άγνωστο ή ανενεργό τμήμα/υποτμήμα')
    if not data.items: raise HTTPException(422,'Δεν επιλέχθηκαν υλικά')
    transfer=ProductionTransfer(transfer_number=_transfer_number(db),destination_org_unit_id=unit.id,created_by=user.id,notes=data.notes)
    db.add(transfer); db.flush(); out=[]
    for req in data.items:
        lot=db.get(WEEEStockLot,req.stock_lot_id)
        if not lot or lot.available_weight<=0: raise HTTPException(409,'Το επιλεγμένο απόθεμα δεν είναι πλέον διαθέσιμο')
        qty=lot.available_weight if req.weight is None else req.weight
        if qty<=0 or qty>lot.available_weight: raise HTTPException(422,'Μη έγκυρη ποσότητα προς παραγωγή')
        before=lot.available_weight; lot.available_weight=before-qty
        lot.status='CONSUMED' if lot.available_weight==0 else 'PARTIAL'
        ti=ProductionTransferItem(transfer_id=transfer.id,stock_lot_id=lot.id,weight=qty)
        db.add(ti); db.flush()
        db.add(ProductionInputBalance(transfer_item_id=ti.id,org_unit_id=unit.id,initial_weight=qty,current_remaining_weight=qty,status='OPEN'))
        db.add(StockMovement(domain='WEEE',lot_id=lot.id,movement_type='TO_PRODUCTION',from_location_id=lot.location_id,to_location_id=None,
            weight=qty,org_unit_id=unit.id,user_id=user.id,reason=data.notes))
        cat=db.get(WEEECategory,lot.weee_category_id); medium=db.get(CollectionMedium,lot.collection_medium_id) if lot.collection_medium_id else None
        out.append(schemas.ProductionTransferItemOut(stock_lot_id=lot.id,weight=qty,weee_code=cat.code,medium_code=medium.code if medium else None))
    # Medium lifecycle: only mark as in production when every stock lot currently attached to it is exhausted from WEEE warehouse.
    medium_ids={db.get(WEEEStockLot,x.stock_lot_id).collection_medium_id for x in data.items}
    for mid in medium_ids:
        if not mid: continue
        remaining=db.scalars(select(WEEEStockLot).where(WEEEStockLot.collection_medium_id==mid,WEEEStockLot.available_weight>0)).all()
        medium=db.get(CollectionMedium,mid)
        if medium and not remaining: medium.status='IN_PRODUCTION'
    write_audit(db,user,'production_transfer',transfer.id,'CREATE',new={'transfer_number':transfer.transfer_number,'destination':unit.code,'items':len(out)})
    db.commit(); return schemas.ProductionTransferOut(id=transfer.id,transfer_number=transfer.transfer_number,destination_org_unit_id=unit.id,status=transfer.status,items=out)

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

def _loading_totals(db:Session,o:LoadingOrder):
    reservations=db.scalars(select(LoadingReservation).where(LoadingReservation.loading_order_id==o.id,LoadingReservation.status=='RESERVED')).all()
    actuals=db.scalars(select(LoadingActual).where(LoadingActual.loading_order_id==o.id)).all()
    reserved=sum((x.reserved_weight for x in reservations),Decimal('0')); loaded=sum((x.loaded_weight for x in actuals),Decimal('0'))
    return reserved,loaded

def _loading_out(db:Session,o:LoadingOrder):
    reserved,loaded=_loading_totals(db,o)
    return schemas.LoadingOrderOut(id=o.id,loading_number=o.loading_number,customer_id=o.customer_id,carrier_id=o.carrier_id,vehicle_registration=o.vehicle_registration,
        max_allowed_weight=o.max_allowed_weight,selection_mode=o.selection_mode,status=o.status,reserved_weight=reserved,loaded_weight=loaded,
        remaining_capacity=o.max_allowed_weight-loaded,dispatch_reason=o.dispatch_reason)

@app.post('/loading/orders', response_model=schemas.LoadingOrderOut)
def loading_create(data:schemas.LoadingOrderCreate, db:Session=Depends(get_db), user:User=Depends(require_permission('loading.view'))):
    if data.selection_mode not in {'OFFICE_RESERVED','OPERATOR_SELECTION'}: raise HTTPException(422,'Μη έγκυρος τρόπος φόρτωσης')
    if data.max_allowed_weight<=0: raise HTTPException(422,'Το μέγιστο βάρος πρέπει να είναι θετικό')
    if not db.get(Organization,data.customer_id): raise HTTPException(422,'Άγνωστος πελάτης')
    o=LoadingOrder(loading_number=_loading_number(db),customer_id=data.customer_id,carrier_id=data.carrier_id,vehicle_registration=data.vehicle_registration,
        max_allowed_weight=data.max_allowed_weight,selection_mode=data.selection_mode,status='OPEN',dispatch_reason=data.dispatch_reason,weighbridge_number=data.weighbridge_number,
        dispatch_document_number=data.dispatch_document_number,created_by=user.id,notes=data.notes)
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
    if not actuals: raise HTTPException(422,'Δεν έχει καταγραφεί κανένα φορτωμένο υλικό')
    for a in actuals:
        lot=db.get(ReadyMaterialLot,a.ready_material_lot_id)
        if a.loaded_weight==lot.net_weight: lot.status='DISPATCHED'
        else: lot.net_weight=lot.net_weight-a.loaded_weight; lot.status='AVAILABLE'
        db.add(ReadyMaterialMovement(lot_id=lot.id,movement_type='DISPATCH',weight=a.loaded_weight,user_id=user.id,reason=o.loading_number))
    for r in db.scalars(select(LoadingReservation).where(LoadingReservation.loading_order_id==o.id,LoadingReservation.status=='RESERVED')).all():
        lot=db.get(ReadyMaterialLot,r.ready_material_lot_id); r.status='RELEASED'
        if lot and lot.status=='RESERVED': lot.status='AVAILABLE'
    o.status='COMPLETED'; write_audit(db,user,'loading_order',o.id,'COMPLETE',new={'actual_items':len(actuals),'loaded_weight':str(_loading_totals(db,o)[1])})
    _enqueue_sync(db,'LOADING_ORDER',o.id,'UPSERT',{'loading_number':o.loading_number,'status':o.status,'loaded_weight':str(_loading_totals(db,o)[1])})
    db.commit(); return _loading_out(db,o)

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
    o.status='CANCELLED'; write_audit(db,user,'loading_order',o.id,'CANCEL',new={})
    db.commit(); return _loading_out(db,o)

@app.get('/loading/shipment-history')
def loading_shipment_history(start:str|None=Query(default=None), end:str|None=Query(default=None), kind:str|None=Query(default=None), q:str|None=Query(default=None), db:Session=Depends(get_db), user=Depends(require_permission('loading.view'))):
    stmt=select(models.ShipmentHistoryEntry).where(models.ShipmentHistoryEntry.active==True)
    if start: stmt=stmt.where(models.ShipmentHistoryEntry.work_date>=datetime.fromisoformat(start))
    if end: stmt=stmt.where(models.ShipmentHistoryEntry.work_date<datetime.fromisoformat(end)+timedelta(days=1))
    if kind: stmt=stmt.where(models.ShipmentHistoryEntry.kind==kind)
    rows=db.scalars(stmt.order_by(models.ShipmentHistoryEntry.work_date.desc(),models.ShipmentHistoryEntry.created_at.desc())).all()
    ql=(q or '').strip().lower()
    out=[{"id":r.id,"work_date":r.work_date.isoformat(),"da_number":r.da_number,"weighbridge_number":r.weighbridge_number,
          "transporter":r.transporter,"recipient":r.recipient,"description":r.description,"weight_kg":float(r.weight_kg or 0),
          "eka_code":r.eka_code,"reptool_code":r.reptool_code,"kind":r.kind} for r in rows]
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
    weee=db.scalars(select(WEEEStockLot).where(WEEEStockLot.available_weight>0)).all()
    prod=db.scalars(select(ProductionInputBalance).where(ProductionInputBalance.status=='OPEN')).all()
    ready=db.scalars(select(ReadyMaterialLot).where(ReadyMaterialLot.status=='AVAILABLE')).all()
    loadings=db.scalars(select(LoadingOrder).where(LoadingOrder.status=='OPEN')).all()
    sync=db.scalars(select(SyncEvent).where(SyncEvent.system=='GALAXY',SyncEvent.status.in_(['PENDING','RETRY']))).all()
    return schemas.OperationalDashboardOut(
        open_receipt_loads=sum(x.status!='CLOSED' for x in loads),
        sorting_in_progress=sum(x.status=='IN_PROGRESS' for x in sessions),
        waiting_logistics=sum(x.status=='LOGISTICS_REVIEW' for x in sessions),
        waiting_management=sum(x.status=='MANAGEMENT_REVIEW' for x in sessions),
        weee_stock_kg=sum((x.available_weight for x in weee),Decimal('0')),
        production_open_kg=sum((x.current_remaining_weight for x in prod),Decimal('0')),
        ready_stock_kg=sum((x.net_weight for x in ready),Decimal('0')),
        open_loadings=len(loadings),galaxy_pending=len(sync))


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

@app.get("/mobile")
def mobile_workspace():
    return FileResponse(static_dir / "mobile_v12.html", headers={"Cache-Control":"no-store, no-cache, must-revalidate, max-age=0","Pragma":"no-cache","Expires":"0","X-WEEE-Build":"1.9"})
