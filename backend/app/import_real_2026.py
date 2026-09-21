from __future__ import annotations
from pathlib import Path
from datetime import datetime, timezone
from decimal import Decimal
import json, re, unicodedata
from sqlalchemy import select, delete, func
from sqlalchemy.orm import Session
from . import models

REVISION='REAL_RECEIPTS_2026_01_08_V3_INTEGRITY_CHECKED'

def _norm(s:str|None)->str:
    s=(s or '').upper().strip()
    return ''.join(ch for ch in unicodedata.normalize('NFD',s) if unicodedata.category(ch)!='Mn')

def _get_or_create_org(db:Session,name:str,role:str):
    key=_norm(name)
    cache=db.info.get('real2026_org_cache')
    if cache is None:
        cache={}
        for o in db.scalars(select(models.Organization)).all():
            cache[_norm(o.trade_name or o.legal_name)]=o
            cache[_norm(o.legal_name)]=o
        db.info['real2026_org_cache']=cache
    obj=cache.get(key)
    if not obj:
        obj=models.Organization(legal_name=name,trade_name=name,active=True); db.add(obj); db.flush(); cache[key]=obj
    role_cache=db.info.setdefault('real2026_role_cache',set(db.execute(select(models.organization_roles.c.organization_id,models.organization_roles.c.role)).all()))
    pair=(obj.id,role)
    if pair not in role_cache:
        db.execute(models.organization_roles.insert().values(organization_id=obj.id,role=role)); role_cache.add(pair)
    return obj

def _wipe_operational(db:Session):
    # Remove derived operational data first, preserving all Master Data, users and registry edits.
    for cls in [
        models.DirectProcessingEvent, models.ProductionRemainderSnapshot, models.ProductionInputBalance, models.ProductionTransferItem,
        models.ProductionTransfer, models.StockMovement, models.WEEEStockLot, models.SortingAdjustment,
        models.SortingEntry, models.SortingSession, models.InboundLoad, models.InboundTrip
    ]:
        db.execute(delete(cls))
    db.execute(delete(models.FileAttachment).where(models.FileAttachment.entity_type.in_(['INBOUND_LOAD','sorting_session'])))
    db.execute(delete(models.VisitorLog).where(models.VisitorLog.source_type=='RECEIPT'))

def ensure_real_2026_import(db:Session):
    marker=db.scalar(select(models.AppSetting).where(models.AppSetting.key=='data.receipts.import_revision'))
    path=Path(__file__).parent/'data'/'receipts_2026_1_8.json'
    if not path.exists(): return False
    rows=json.loads(path.read_text(encoding='utf-8'))
    # Never trust only the revision marker: 2.5.24/25 could leave a partial Jan-Jul DB marked complete.
    # Use >= rather than == on the count: later months (e.g. September) get imported additively on
    # top of this Jan-Aug dataset via separate one-off scripts, which legitimately grows InboundTrip
    # beyond len(rows) -- treating that growth as "incomplete" would wipe_operational() and destroy
    # that later data on every subsequent app restart (this happened once; see BUSINESS_RULES).
    existing_count=db.scalar(select(func.count(models.InboundTrip.id)).where(models.InboundTrip.deleted_at.is_(None))) or 0
    existing_max=db.scalar(select(func.max(models.InboundTrip.receipt_date)).where(models.InboundTrip.deleted_at.is_(None)))
    expected_count=len(rows)
    expected_max=max((r.get('date') or '') for r in rows) if rows else ''
    complete=(existing_count>=expected_count and existing_max is not None and existing_max.date().isoformat()>=expected_max)
    if marker and marker.value==REVISION and complete:
        return False
    _wipe_operational(db); db.flush()
    admin=db.scalar(select(models.User).where(models.User.username=='admin'))
    loc=db.scalar(select(models.InventoryLocation).where(models.InventoryLocation.code=='WEEE_MAIN'))
    if not loc:
        loc=models.InventoryLocation(code='WEEE_MAIN',name_el='Αποθήκη ΑΗΗΕ προς ανακύκλωση',domain='WEEE',active=True);db.add(loc);db.flush()
    cat_by_code={c.code:c for c in db.scalars(select(models.WEEECategory)).all()}
    for i,row in enumerate(rows,1):
        supplier=_get_or_create_org(db,row['supplier'],'SUPPLIER')
        carrier=_get_or_create_org(db,row['carrier'],'CARRIER')
        # Source workbooks do not contain an arrival time. Noon is a neutral storage value; UI marks time as unavailable.
        dt=datetime.fromisoformat(row['date']+'T12:00:00')
        extras={
          'sealNo':row.get('seal_number') or '', 'weighbridgeNo':row.get('weighbridge_number') or '',
          'reportDate':row['date'], 'dispatchNo':row.get('dispatch_note_number') or '',
          'foreignMaterials':'ΝΑΙ' if row.get('foreign_materials') else 'ΟΧΙ','foreignWeight':row.get('foreign_weight') or 0,
          'specialWaste':'ΝΑΙ' if row.get('special_waste') else 'ΟΧΙ','specialWasteWeight':row.get('special_waste_weight') or 0,
          'dppNo':row.get('dpp_number') or '', 'checkSpecial':bool(row.get('check_special')),
          'checkKday':bool(row.get('check_kday')),'checkNonInteger':bool(row.get('check_non_integer')),
          'loadPure':bool(row.get('load_pure')),'sourceTimeKnown':False,'sourceFile':row.get('source_file'),'sourceSheet':row.get('source_sheet')
        }
        plain=(row.get('branch_notes') or '').strip()
        trip=models.InboundTrip(id=models.uid(),receipt_number=row['order_number'],receipt_type=row['receipt_type'],receipt_date=dt,
            carrier_id=carrier.id,driver_name=None,vehicle_registration=row.get('vehicle'),status='CLOSED',created_by=(admin.id if admin else None),
            notes='__EXTRA__'+json.dumps(extras,ensure_ascii=False,separators=(',',':'))+'\n'+plain)
        # Preserve source chronology instead of import timestamp.
        trip.created_at=dt;trip.updated_at=dt;db.add(trip);db.flush()
        load=models.InboundLoad(id=models.uid(),trip_id=trip.id,load_sequence=1,supplier_id=supplier.id,order_number=row['order_number'],
            incoming_container_number=row.get('container_number'),incoming_container_tare=None,outgoing_container_id=None,outgoing_container_tare=None,
            gross_weight=None,tare_weight=None,net_weight=Decimal(str(row['net_weee_weight'])),status='CLOSED',ready_for_sorting_at=dt,
            notes=(row.get('load_notes') or None),dpp_number=row.get('dpp_number'),weighbridge_number=row.get('weighbridge_number'),
            dispatch_note_number=row.get('dispatch_note_number'),seal_number=row.get('seal_number'))
        load.created_at=dt;load.updated_at=dt;db.add(load);db.flush()
        ses=models.SortingSession(id=models.uid(),inbound_load_id=load.id,status='CLOSED',started_at=dt,started_by=(admin.id if admin else None),
            sorting_confirmed_at=dt,sorting_confirmed_by=(admin.id if admin else None),logistics_confirmed_at=dt,logistics_confirmed_by=(admin.id if admin else None),
            requires_management_approval=False,final_sorting_weight=Decimal(str(row['net_weee_weight'])),final_difference=Decimal('0'),
            notes=None,foreign_materials=('ΝΑΙ' if row.get('foreign_materials') else 'ΟΧΙ'),
            foreign_weight=Decimal(str(row.get('foreign_weight') or 0)),special_waste=('ΝΑΙ' if row.get('special_waste') else 'ΟΧΙ'),
            special_waste_weight=Decimal(str(row.get('special_waste_weight') or 0)),load_pure=bool(row.get('load_pure')),check_special=bool(row.get('check_special')),
            check_kday=bool(row.get('check_kday')),check_non_integer=bool(row.get('check_non_integer')))
        ses.created_at=dt;ses.updated_at=dt;db.add(ses);db.flush()
        for catrow in row.get('categories') or []:
            cat=cat_by_code.get(catrow['code'])
            if not cat: continue
            e=models.SortingEntry(id=models.uid(),session_id=ses.id,weee_category_id=cat.id,collection_medium_id=None,entry_type='HISTORICAL',
                raw_weight=Decimal(str(catrow['weight'])),approved_weight=Decimal(str(catrow['weight'])),piece_count=(int(catrow['pieces']) if catrow.get('pieces') is not None else None),
                created_by=(admin.id if admin else None),notes='Εισαγωγή 2026')
            e.created_at=dt;e.updated_at=dt;db.add(e);db.flush()
            lot=models.WEEEStockLot(id=models.uid(),source_sorting_entry_id=e.id,inbound_load_id=load.id,weee_category_id=cat.id,collection_medium_id=None,
                location_id=loc.id,original_weight=Decimal(str(catrow['weight'])),available_weight=Decimal(str(catrow['weight'])),piece_count=e.piece_count,status='AVAILABLE')
            lot.created_at=dt;lot.updated_at=dt;db.add(lot);db.flush()
            mv=models.StockMovement(id=models.uid(),domain='WEEE',lot_id=lot.id,movement_type='SORTING_IN',from_location_id=None,to_location_id=loc.id,
                weight=Decimal(str(catrow['weight'])),org_unit_id=None,user_id=(admin.id if admin else None),reason='Ιστορική ταξινόμηση 2026',created_at=dt)
            db.add(mv)
    if marker: marker.value=REVISION
    else: db.add(models.AppSetting(key='data.receipts.import_revision',value=REVISION))
    db.commit()
    return True
