"""Αναφορές Παραλαβών που συμπληρώνονται από τις καταγραφές μας πάνω στις φόρμες του χρήστη (Excel)."""
import os
from datetime import datetime, timedelta
from pathlib import Path
from tempfile import NamedTemporaryFile
from copy import copy

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import FileResponse
from openpyxl import load_workbook
from sqlalchemy import select
from sqlalchemy.orm import Session
from starlette.background import BackgroundTask

from . import models
from .db import get_db
from .security import require_permission

router = APIRouter()
TEMPLATES = Path(__file__).parent / "templates"
XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"

# Υλικά ΜΗ ΑΗΗΕ (κατηγορίες ταξινόμησης στα Μητρώα ΑΗΗΕ)
NON_WEEE_TYPE_A = {"109991", "109992", "109993", "109994"}
NON_WEEE_TYPE_B = {"119999"}
NON_WEEE = NON_WEEE_TYPE_A | NON_WEEE_TYPE_B


def _org_name(o):
    return ((o.trade_name or o.legal_name) if o else "") or ""


def _loads(db: Session, start: datetime, end: datetime):
    return db.scalars(
        select(models.InboundLoad)
        .join(models.InboundTrip, models.InboundLoad.trip_id == models.InboundTrip.id)
        .where(models.InboundTrip.receipt_date >= start, models.InboundTrip.receipt_date < end, models.InboundTrip.deleted_at.is_(None))
        .order_by(models.InboundLoad.dpp_number.is_(None), models.InboundLoad.dpp_number, models.InboundTrip.receipt_date, models.InboundLoad.created_at)
    ).all()


def _split_kg(data: dict):
    """(ΑΗΗΕ kg, ΜΗ ΑΗΗΕ Τύπου Α kg, ΜΗ ΑΗΗΕ Τύπου Β kg) για ένα φορτίο.

    Χωρίς ταξινόμηση: όλο το καθαρό βάρος θεωρείται ΑΗΗΕ. Τα ιστορικά «ξένα υλικά» (πεδίο ελέγχου
    ταξινόμησης, εκτός καθαρού βάρους) μετράνε ως ΜΗ ΑΗΗΕ μόνο όταν δεν υπάρχουν εγγραφές στις
    κατηγορίες ΜΗ ΑΗΗΕ, ώστε να μην διπλομετριούνται.
    """
    load, ses, weights = data["load"], data["session"], data["weights"]
    a = sum(float(w) for c, w in weights.items() if c in NON_WEEE_TYPE_A)
    b = sum(float(w) for c, w in weights.items() if c in NON_WEEE_TYPE_B)
    if ses is None or not weights:
        return float(load.net_weight or 0), 0.0, 0.0
    weee = sum(float(w) for c, w in weights.items() if c not in NON_WEEE)
    if a + b == 0 and float(ses.foreign_weight or 0) > 0:
        return weee, 0.0, float(ses.foreign_weight)
    return weee, a, b


def _insert_rows(ws, at: int, n: int, style_row: int, merge_ranges=()):
    """Εισαγωγή n γραμμών πριν τη γραμμή `at` διατηρώντας συγχωνεύσεις/μορφοποίηση των γραμμών από κάτω."""
    if n <= 0:
        return
    lower = [r for r in list(ws.merged_cells.ranges) if r.min_row >= at]
    for r in lower:
        ws.unmerge_cells(str(r))
    heights = {r: ws.row_dimensions[r].height for r in range(at, ws.max_row + 1) if ws.row_dimensions[r].height}
    ws.insert_rows(at, n)
    for r in lower:
        ws.merge_cells(start_row=r.min_row + n, end_row=r.max_row + n, start_column=r.min_col, end_column=r.max_col)
    for r, h in heights.items():
        ws.row_dimensions[r + n].height = h
    for i in range(n):
        row = at + i
        ws.row_dimensions[row].height = ws.row_dimensions[style_row].height
        for col in range(1, ws.max_column + 1):
            src, dst = ws.cell(style_row, col), ws.cell(row, col)
            if src.has_style:
                dst._style = copy(src._style)
        for c1, c2 in merge_ranges:
            ws.merge_cells(start_row=row, end_row=row, start_column=c1, end_column=c2)


def _response(wb, filename: str):
    tmp = NamedTemporaryFile(delete=False, suffix=".xlsx")
    tmp.close()
    wb.save(tmp.name)
    return FileResponse(tmp.name, media_type=XLSX, filename=filename, background=BackgroundTask(os.unlink, tmp.name))


@router.get("/reports/generate/daily-summary")
def daily_summary(day: str = Query(..., pattern=r"^\d{4}-\d{2}-\d{2}$"), db: Session = Depends(get_db), user=Depends(require_permission("sorting.review"))):
    """Ημερήσιο Συγκεντρωτικό: μία γραμμή ανά φορτίο, κιλά παραλαβής ΑΗΗΕ / ΜΗ ΑΗΗΕ ανά τύπο προμηθευτή."""
    from .main import _sorting_export_data
    d = datetime.fromisoformat(day)
    start = datetime(d.year, d.month, d.day)
    loads = _loads(db, start, start + timedelta(days=1))
    wb = load_workbook(TEMPLATES / "daily_summary_template.xlsx")
    ws = wb.worksheets[0]
    ws["A2"] = "Ημερομηνία: " + d.strftime("%d/%m/%Y")
    first, cap = 5, 15
    extra = max(0, len(loads) - cap)
    _insert_rows(ws, first + cap, extra, first + cap - 1, merge_ranges=[(4, 6)])
    last = first + cap - 1 + extra
    for i, l in enumerate(loads):
        data = _sorting_export_data(db, l.id)
        ex = data["extras"]
        weee, na, nb = _split_kg(data)
        scrap = bool(data["supplier"] and data["supplier"].supplier_kind == "SCRAP_DEALER")
        r = first + i
        ws.cell(r, 1).value = i + 1
        ws.cell(r, 2).value = l.dispatch_note_number or ex.get("dispatchNo", "") or None
        ws.cell(r, 3).value = data["trip"].vehicle_registration if data["trip"] else None
        ws.cell(r, 4).value = _org_name(data["supplier"])
        c_aee, c_non = (9, 10) if scrap else (7, 8)
        ws.cell(r, c_aee).value = int(round(weee)) or None
        ws.cell(r, c_non).value = int(round(na + nb)) or None
    t = last + 1
    for col in "GHIJ":
        ws[f"{col}{t}"] = f"=SUM({col}{first}:{col}{last})"
    ws[f"G{t+1}"] = f"=G{t}+H{t}"
    ws[f"I{t+1}"] = f"=I{t}+J{t}"
    ws[f"G{t+2}"] = f"=G{t+1}+I{t+1}"
    try:
        wb.calculation.fullCalcOnLoad = True
    except Exception:
        pass
    return _response(wb, "Ημερήσιο Συγκεντρωτικό " + d.strftime("%d.%m.%Y") + ".xlsx")


@router.get("/reports/generate/non-weee-by-supplier")
def non_weee_by_supplier(month: str = Query(..., pattern=r"^\d{4}-\d{2}$"), db: Session = Depends(get_db), user=Depends(require_permission("sorting.review"))):
    """Συγκεντρωτικός Πίνακας Υλικών ΜΗ ΑΗΗΕ Τύπου Α’ & Τύπου Β’ ανά προμηθευτή για τον επιλεγμένο μήνα."""
    from .main import _sorting_export_data
    y, m = int(month[:4]), int(month[5:])
    start = datetime(y, m, 1)
    end = datetime(y + (m == 12), (m % 12) + 1, 1)
    per = {"A": {}, "B": {}}
    for l in _loads(db, start, end):
        data = _sorting_export_data(db, l.id)
        _, na, nb = _split_kg(data)
        name = _org_name(data["supplier"]) or "—"
        if na:
            per["A"][name] = per["A"].get(name, 0.0) + na
        if nb:
            per["B"][name] = per["B"].get(name, 0.0) + nb
    wb = load_workbook(TEMPLATES / "non_weee_by_supplier_template.xlsx")
    for ws, key, cap in ((wb.worksheets[0], "A", 5), (wb.worksheets[1], "B", 13)):
        rows = sorted(per[key].items(), key=lambda kv: kv[0].casefold())
        extra = max(0, len(rows) - cap)
        _insert_rows(ws, 2 + cap, extra, 1 + cap)
        for i, (name, kg) in enumerate(rows):
            ws.cell(2 + i, 1).value = name
            ws.cell(2 + i, 2).value = int(round(kg))
        tot = 2 + cap + extra
        ws.cell(tot, 2).value = f"=SUM(B2:B{tot-1})"
    return _response(wb, f"Υλικά ΜΗ ΑΗΗΕ ανά προμηθευτή {m:02d}.{y}.xlsx")


@router.get("/reports/generate/monthly-received")
def monthly_received(month: str = Query(..., pattern=r"^\d{4}-\d{2}$"), db: Session = Depends(get_db), user=Depends(require_permission("sorting.review"))):
    """Μηνιαία Αναφορά Παραληφθέντων ΑΗΗΕ: ένα φύλλο ανά φορτίο και τελικό «Σύνολο Μήνα»."""
    from .main import _received_workbook_response
    y, m = int(month[:4]), int(month[5:])
    start = datetime(y, m, 1)
    end = datetime(y + (m == 12), (m % 12) + 1, 1)
    return _received_workbook_response(db, start, end, "Σύνολο Μήνα", f"Μηνιαία Αναφορά Παραληφθέντων ΑΗΗΕ {m:02d}.{y}.xlsx")
