import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import os
DB=Path('./test_build05.db')
if DB.exists(): DB.unlink()
os.environ['DATABASE_URL']='sqlite:///./test_build05.db'
os.environ['JWT_SECRET']='test-secret'
os.environ['BOOTSTRAP_ADMIN_USERNAME']='admin'
os.environ['BOOTSTRAP_ADMIN_PASSWORD']='testpass'

import pytest


@pytest.fixture(autouse=True, scope="module")
def _isolated_module_database():
    """Give every test module a fresh database instead of sharing one file
    (and its accumulated master-data rows) across the whole pytest session.

    The app's engine is a process-wide singleton created on first import of
    app.db, so we can't just point each module at its own file; instead we
    dispose the pooled connection and delete the backing SQLite file before
    each module runs. The next `with TestClient(app) as c:` in that module
    re-triggers the FastAPI lifespan, which recreates the schema and reseeds
    (including the idempotent historical receipts/production imports).
    """
    from app.db import engine
    engine.dispose()
    if DB.exists(): DB.unlink()
    yield
    engine.dispose()
