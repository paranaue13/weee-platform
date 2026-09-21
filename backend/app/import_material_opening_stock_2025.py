from pathlib import Path
from datetime import datetime
from decimal import Decimal
import json
from sqlalchemy import select, delete, func
from sqlalchemy.orm import Session
from . import models

REVISION='REAL_MATERIAL_OPENING_STOCK_2025_12_31_V2_APOGRAFI2026'
AS_OF_DATE='2025-12-31T00:00:00'

def ensure_material_opening_stock_2025_import(db:Session):
    path=Path(__file__).parent/'data'/'material_opening_stock_2025_12_31.json'
    if not path.exists(): return False
    rows=json.loads(path.read_text(encoding='utf-8'))
    marker=db.scalar(select(models.AppSetting).where(models.AppSetting.key=='data.material_opening_stock.import_revision'))
    existing=db.scalar(select(func.count(models.MaterialOpeningStock.id)).where(models.MaterialOpeningStock.source=='HISTORICAL_2025')) or 0
    if marker and marker.value==REVISION and existing==len(rows): return False
    db.execute(delete(models.MaterialOpeningStock).where(models.MaterialOpeningStock.source=='HISTORICAL_2025'))
    as_of=datetime.fromisoformat(AS_OF_DATE)
    for r in rows:
        db.add(models.MaterialOpeningStock(as_of_date=as_of,category_group=r['group'],material_label=r['material_label'],
            kg=Decimal(str(r['kg'])),reptool_code=r.get('reptool_code'),her_description=r.get('her_description'),
            source='HISTORICAL_2025',notes='Πραγματική φυσική απογραφή 31/12/2025' if not r.get('reptool_code') else None))
    if marker: marker.value=REVISION
    else: db.add(models.AppSetting(key='data.material_opening_stock.import_revision',value=REVISION))
    db.commit(); return True
