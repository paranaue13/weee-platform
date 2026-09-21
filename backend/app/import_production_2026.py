from pathlib import Path
from datetime import datetime
from decimal import Decimal
import json
from sqlalchemy import select, delete, func
from sqlalchemy.orm import Session
from . import models

REVISION='REAL_PRODUCTION_2026_01_08_V1'

def ensure_real_production_2026_import(db:Session):
    path=Path(__file__).parent/'data'/'production_2026_1_8.json'
    if not path.exists(): return False
    rows=json.loads(path.read_text(encoding='utf-8'))
    marker=db.scalar(select(models.AppSetting).where(models.AppSetting.key=='data.production.import_revision'))
    existing=db.scalar(select(func.count(models.ProductionWorkEntry.id)).where(models.ProductionWorkEntry.source=='HISTORICAL_2026')) or 0
    if marker and marker.value==REVISION and existing==len(rows): return False
    db.execute(delete(models.ProductionWorkEntry).where(models.ProductionWorkEntry.source=='HISTORICAL_2026'))
    unit=db.scalar(select(models.OrganizationalUnit).where(models.OrganizationalUnit.code=='HIST_PROD'))
    if not unit:
        unit=models.OrganizationalUnit(code='HIST_PROD',name_el='Ιστορική παραγωγή',name_en='Historical production',sort_order=9999,active=False)
        db.add(unit); db.flush()
    cats={c.code:c for c in db.scalars(select(models.WEEECategory)).all()}
    for r in rows:
        cat=cats.get(r['code'])
        if not cat: continue
        db.add(models.ProductionWorkEntry(work_date=datetime.fromisoformat(r['date']+'T12:00:00'),org_unit_id=unit.id,weee_category_id=cat.id,
            weight_kg=Decimal(str(r['kg'])),supplier_group=r['supplier_group'],source='HISTORICAL_2026',
            notes=('Διόρθωση αρχείου παραγωγής' if r.get('correction') else None)))
    if marker: marker.value=REVISION
    else: db.add(models.AppSetting(key='data.production.import_revision',value=REVISION))
    db.commit(); return True
