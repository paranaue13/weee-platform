"""Live mirror of today's pickup orders from the Ανακύκλωση Συσκευών Α.Ε. portal
(eweee.electrocycle.gr), 'Αναφορές -> Ροή Εντολών', filtered to our company and
delivery point 001, Παράδοση από/έως = today.

This is a READ-ONLY monitoring feed: rows are cached in ElectrocycleOrder and shown
next to (never merged into) our own Παραλαβές ledger, per the user's request to just
see "what's been entered on the external system today" refreshed live.

Login uses a persistent Chromium profile (settings.electrocycle_profile_dir) so the
one-time "Θυμήσου αυτή τη συσκευή" login lets later runs skip the OTP-by-email step
entirely. If that trust ever lapses, fetch_today_orders() raises ElectrocycleAuthError
instead of hanging or guessing -- sync_electrocycle_orders() then records that failure
in ElectrocycleSyncStatus so the UI can tell the user a person needs to log in again.
"""
from __future__ import annotations
import csv, io, json, logging
from datetime import datetime, date
from pathlib import Path

from sqlalchemy import select, delete
from sqlalchemy.orm import Session

from .config import settings
from . import models

log = logging.getLogger("electrocycle")

LOGIN_URL = "https://eweee.electrocycle.gr/Trash/login.aspx?ReturnUrl=%2fTrash%2fdefault.aspx"
FLOW_URL = "https://eweee.electrocycle.gr/Trash/StatementFlow.aspx"

# CSV export column order confirmed by inspecting a real export (Build 2.5.36):
# Α/Α Εντολής, Δρομ. Εκτέλεσης, Δρομ. Παράδοσης, Αποστολέας, Σημείο Παραλαβής,
# Διεύθυνση Αποστ., Πόλη Αποστ., Τ.Κ. Αποστ., (wide/region/prefecture area cols),
# Μεταφορέας, Μέσο Συλλογής, ...(our own company/address columns, dates, status,
# contact, driver -- kept only in raw_json, not worth a fragile per-column mapping).
COL_ORDER_NO = 0
COL_EXEC_ROUTE = 1
COL_DELIVERY_ROUTE = 2
COL_SENDER = 3
COL_PICKUP_POINT = 4
COL_ADDRESS = 5
COL_CITY = 6
COL_POSTAL_CODE = 7
COL_CARRIER = 11
COL_COLLECTION_MEDIUM = 12


class ElectrocycleAuthError(RuntimeError):
    """The portal asked for username/password or an OTP code -- the remembered-device
    trust in the saved browser profile has lapsed and needs a person to log in once
    more (same interactive flow used to set it up) before syncing can resume."""


def _fetch_orders_csv(target_date: date) -> bytes:
    from playwright.sync_api import sync_playwright

    target_str = target_date.strftime("%d/%m/%Y")
    profile_dir = settings.electrocycle_profile_dir
    Path(profile_dir).mkdir(parents=True, exist_ok=True)

    with sync_playwright() as p:
        ctx = p.chromium.launch_persistent_context(
            profile_dir, viewport={"width": 1600, "height": 1000}, accept_downloads=True
        )
        try:
            pg = ctx.pages[0] if ctx.pages else ctx.new_page()
            pg.goto(FLOW_URL, wait_until="networkidle", timeout=30000)
            pg.wait_for_timeout(800)

            if ("login.aspx" in pg.url.lower() or pg.query_selector("#MainContent_login1_UserName") or pg.query_selector("#MainContent_TxtExtraPin")
                    or pg.query_selector("#MainContent_TxtEmail")):
                raise ElectrocycleAuthError(
                    "Το portal ζήτησε σύνδεση/OTP -- η εμπιστοσύνη της συσκευής έχει λήξει, "
                    "χρειάζεται νέα χειροκίνητη σύνδεση."
                )

            # The company dropdown can render a bit after "networkidle" on a slow postback --
            # wait for it explicitly instead of hoping the fixed 800ms above was long enough
            # (that's what was timing out generically inside select_option before).
            pg.wait_for_selector("#MainContent_DDCompanies", timeout=20000)
            pg.select_option("#MainContent_DDCompanies", settings.electrocycle_company_value)
            pg.wait_for_timeout(1200)
            pg.select_option("#MainContent_DDCompaniesDelv", settings.electrocycle_delivery_point_value)
            pg.fill("#MainContent_TxtParadDtmvFrom", target_str)
            pg.fill("#MainContent_TxtParadDtmvTo", target_str)
            pg.click("text=Αναζήτηση")
            pg.wait_for_timeout(5000)

            export_link = None
            for el in pg.query_selector_all("[title*='xport' i]"):
                if el.is_visible() and pg.evaluate("e => e.tagName", el) == "A":
                    export_link = el
                    break
            if not export_link:
                # No export control rendered at all: most likely zero matching rows today.
                return b""

            export_link.click()
            pg.wait_for_timeout(600)
            csv_link = pg.query_selector("text=CSV (comma delimited)")
            if not csv_link:
                return b""
            with pg.expect_download(timeout=20000) as dl_info:
                csv_link.click()
            download = dl_info.value
            tmp_path = download.path()
            return Path(tmp_path).read_bytes()
        finally:
            ctx.close()


def _parse_csv(raw: bytes) -> list[dict]:
    if not raw:
        return []
    text = raw.decode("utf-8-sig", errors="replace")
    rows = list(csv.reader(io.StringIO(text)))
    if len(rows) < 2:
        return []
    out = []
    for r in rows[1:]:
        if not r or not any(c.strip() for c in r):
            continue
        def col(i):
            return r[i].strip() if i < len(r) and r[i].strip() else None
        out.append({
            "order_no": col(COL_ORDER_NO) or "",
            "execution_route": col(COL_EXEC_ROUTE),
            "delivery_route": col(COL_DELIVERY_ROUTE),
            "sender": col(COL_SENDER),
            "pickup_point": col(COL_PICKUP_POINT),
            "address": col(COL_ADDRESS),
            "city": col(COL_CITY),
            "postal_code": col(COL_POSTAL_CODE),
            "carrier": col(COL_CARRIER),
            "collection_medium": col(COL_COLLECTION_MEDIUM),
            "raw_json": json.dumps(r, ensure_ascii=False),
        })
    return out


def sync_electrocycle_orders(db: Session, target_date: date | None = None) -> dict:
    target_date = target_date or date.today()
    target_iso = target_date.isoformat()
    is_today = target_date == date.today()
    status = db.scalar(select(models.ElectrocycleSyncStatus))
    if not status:
        status = models.ElectrocycleSyncStatus()
        db.add(status)
    status.last_attempt_at = datetime.now()

    try:
        raw = _fetch_orders_csv(target_date)
        rows = _parse_csv(raw)
    except ElectrocycleAuthError as e:
        status.ok = False
        status.message = str(e)
        db.commit()
        log.warning("electrocycle sync auth failure: %s", e)
        return {"ok": False, "message": str(e), "count": 0}
    except Exception as e:
        status.ok = False
        status.message = f"Σφάλμα συγχρονισμού: {e}"
        db.commit()
        log.exception("electrocycle sync failed")
        return {"ok": False, "message": status.message, "count": 0}

    db.execute(delete(models.ElectrocycleOrder).where(models.ElectrocycleOrder.source_date == target_iso))
    for r in rows:
        db.add(models.ElectrocycleOrder(source_date=target_iso, synced_at=datetime.now(), **r))
    # last_success_at/status.message reflect the sync run itself (used by the UI's "last updated"
    # line) -- only overwrite them for today's own sync, so refreshing a future day's live feed on
    # demand doesn't make today's status line silently report about a different day.
    if is_today:
        status.ok = True
        status.last_success_at = datetime.now()
        status.message = f"{len(rows)} εντολές σήμερα" if rows else "Καμία εντολή σήμερα"
    db.commit()
    return {"ok": True, "message": f"{len(rows)} εντολές" if rows else "Καμία εντολή αυτή την ημέρα", "count": len(rows)}
