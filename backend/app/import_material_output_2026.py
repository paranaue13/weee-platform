from pathlib import Path
from datetime import datetime
from decimal import Decimal
import json
from sqlalchemy import select, delete, func
from sqlalchemy.orm import Session
from . import models

REVISION='REAL_MATERIAL_OUTPUT_2026_01_08_V1'

def ensure_material_output_2026_import(db:Session):
    path=Path(__file__).parent/'data'/'material_output_2026_1_8.json'
    if not path.exists(): return False
    rows=json.loads(path.read_text(encoding='utf-8'))
    marker=db.scalar(select(models.AppSetting).where(models.AppSetting.key=='data.material_output.import_revision'))
    existing=db.scalar(select(func.count(models.MaterialOutputEntry.id)).where(models.MaterialOutputEntry.source=='HISTORICAL_2026')) or 0
    if marker and marker.value==REVISION and existing==len(rows): return False
    db.execute(delete(models.MaterialOutputEntry).where(models.MaterialOutputEntry.source=='HISTORICAL_2026'))
    for r in rows:
        db.add(models.MaterialOutputEntry(work_date=datetime.fromisoformat(r['date']+'T12:00:00'),category_group=r['group'],
            material_label=r['material_label'],weight_kg=Decimal(str(r['kg'])),source='HISTORICAL_2026',
            notes=('Διόρθωση μηνός (ΔΙΑΦΟΡΕΣ)' if r.get('correction') else None)))
    if marker: marker.value=REVISION
    else: db.add(models.AppSetting(key='data.material_output.import_revision',value=REVISION))
    db.commit(); return True
