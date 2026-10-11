"""Periodic safety-net backup of the live SQLite database.

Runs standalone (via Windows Task Scheduler, every 15 minutes -- see
backend/scripts/install_backup_task.ps1), independent of the app process.
Uses sqlite3's own online backup API, which is safe to run against a database
the server is actively reading/writing (a plain file copy is not: it can grab
a half-written page and produce a corrupt snapshot).

This protects DATA (weee_dev.db). It has nothing to do with git, which only
tracks the application CODE and never the database file (see .gitignore).

Retention, to keep disk usage bounded while still holding a full year of history:
  - every snapshot from the last 24h is kept (4/hour x 24h = up to 96 files)
  - beyond 24h, only the first snapshot of each day is kept, for 365 days
  - anything older than 365 days is deleted
"""
import os, sqlite3, sys
from datetime import datetime, timedelta
from pathlib import Path

def live_db_path() -> Path:
    env_url = os.environ.get("DATABASE_URL")
    if env_url and env_url.startswith("sqlite:///"):
        return Path(env_url[len("sqlite:///"):])
    base = Path(os.environ.get("LOCALAPPDATA") or (Path.home() / "AppData" / "Local"))
    return base / "WEEE Platform" / "data" / "weee_dev.db"

def backup_dir_for(db_path: Path) -> Path:
    d = db_path.parent / "backups"
    d.mkdir(parents=True, exist_ok=True)
    return d

def do_backup(db_path: Path, out_dir: Path, max_seconds: float = 180.0) -> Path:
    """Αντίγραφο με το online backup API της sqlite (σωστό και με WAL: παίρνει συνεπές στιγμιότυπο, όχι μόνο το κύριο αρχείο).
    Αν η βάση μείνει κλειδωμένη, το backup API ξαναδοκιμάζει για πάντα -- γι' αυτό υπάρχει όριο χρόνου: μετά από max_seconds
    η προσπάθεια σταματά, το ημιτελές αρχείο σβήνεται και το σενάριο τελειώνει με σφάλμα (δεν «κολλάει» ούτε αφήνει αρχεία 0 bytes)."""
    import time
    stamp = datetime.now().strftime("%Y%m%d_%H%M")
    dest = out_dir / f"weee_dev_{stamp}.db"
    src = sqlite3.connect(str(db_path), timeout=30)
    dst = sqlite3.connect(str(dest))
    t0 = time.time()
    ok = False
    def progress(status, remaining, total):
        if time.time() - t0 > max_seconds:
            raise TimeoutError(f"backup > {max_seconds:.0f}s (η βάση είναι κλειδωμένη;)")
    try:
        src.backup(dst, pages=2000, progress=progress, sleep=0.25)
        ok = True
    finally:
        dst.close(); src.close()
        if not ok:
            try: dest.unlink(missing_ok=True)
            except Exception: pass
    if dest.stat().st_size == 0:
        dest.unlink(missing_ok=True)
        raise RuntimeError("backup file is empty")
    return dest

def prune(out_dir: Path):
    now = datetime.now()
    cutoff_full = now - timedelta(hours=24)
    cutoff_daily = now - timedelta(days=365)
    files = sorted(out_dir.glob("weee_dev_*.db"))
    kept_day_for_older = set()
    for f in files:
        try:
            stamp = f.stem.replace("weee_dev_", "")
            ts = datetime.strptime(stamp, "%Y%m%d_%H%M")
        except ValueError:
            continue
        if ts >= cutoff_full:
            continue  # within last 24h: always keep
        if ts < cutoff_daily:
            f.unlink(missing_ok=True); continue
        day = ts.date()
        if day in kept_day_for_older:
            f.unlink(missing_ok=True)
        else:
            kept_day_for_older.add(day)  # first snapshot seen for that day (files are sorted) is kept

def main():
    db_path = live_db_path()
    if not db_path.exists():
        print(f"[backup_db] no database at {db_path}, skipping", file=sys.stderr)
        return 1
    out_dir = backup_dir_for(db_path)
    dest = do_backup(db_path, out_dir)
    prune(out_dir)
    print(f"[backup_db] backed up {db_path} -> {dest}")
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
