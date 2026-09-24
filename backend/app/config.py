from pathlib import Path
import os, shutil
from pydantic_settings import BaseSettings, SettingsConfigDict

def _default_database_url() -> str:
    # Explicit DATABASE_URL still wins through pydantic-settings.
    bundled = Path(__file__).resolve().parents[1] / "weee_dev.db"
    if os.name != "nt":
        return f"sqlite:///{bundled.as_posix()}"

    base = Path(os.environ.get("LOCALAPPDATA") or (Path.home() / "AppData" / "Local"))
    data_dir = base / "WEEE Platform" / "data"
    data_dir.mkdir(parents=True, exist_ok=True)
    persistent = data_dir / "weee_dev.db"

    # First run of 2.5.20+: seed the persistent DB from the populated DB shipped with the build.
    # Future builds reuse this same persistent file, so edits in registries/receipts survive upgrades.
    if not persistent.exists() and bundled.exists():
        shutil.copy2(bundled, persistent)

    return f"sqlite:///{persistent.as_posix()}"

def _default_electrocycle_profile_dir() -> str:
    base = Path(os.environ.get("LOCALAPPDATA") or (Path.home() / "AppData" / "Local"))
    data_dir = base / "WEEE Platform" / "data"
    data_dir.mkdir(parents=True, exist_ok=True)
    return str(data_dir / "electrocycle_profile")

def _default_report_templates_dir() -> str:
    base = Path(os.environ.get("LOCALAPPDATA") or (Path.home() / "AppData" / "Local"))
    return str(base / "WEEE Platform" / "data" / "report_templates")

class Settings(BaseSettings):
    database_url: str = _default_database_url()
    report_templates_dir: str = _default_report_templates_dir()
    jwt_secret: str = "dev-only-change-me"
    access_token_minutes: int = 480
    bootstrap_admin_username: str = "admin"
    bootstrap_admin_password: str = "ChangeMe123!"
    # Ανακύκλωση Συσκευών Α.Ε. (electrocycle.itn.services) portal — read-only mirror of
    # today's "Ροή Εντολών" pickup orders. The persistent browser profile below is what
    # lets a scheduled sync skip the OTP step after the one-time "Θυμήσου αυτή τη συσκευή"
    # login; if that trust ever expires the sync fails visibly (see integrations/electrocycle.py)
    # rather than silently, and a person must log in once more through the same flow.
    # Real credentials live in backend/.env (gitignored), never in source -- see .env.example.
    electrocycle_username: str = ""
    electrocycle_password: str = ""
    electrocycle_otp_email: str = ""
    electrocycle_company_value: str = "ΠΡΟΜ|ΠΡ00959"
    electrocycle_delivery_point_value: str = "ΠΡΟΜ|ΠΡ00959|001"
    electrocycle_profile_dir: str = _default_electrocycle_profile_dir()
    electrocycle_sync_minutes: int = 5
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

settings = Settings()
