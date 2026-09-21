from pathlib import Path
from sqlalchemy import create_engine, select, func
from sqlalchemy.orm import sessionmaker
from app.db import Base
from app.seed import seed
from app.models import SupplierBranch, OrganizationRegistryDetail, organization_roles

def test_imported_registries():
    # Uses a dedicated local db file instead of pytest's `tmp_path` fixture:
    # tmp_path's cleanup walks the shared OS temp root, which can be
    # ACL-restricted in locked-down environments unrelated to this test.
    db_path=Path(__file__).parent/'_tmp_build24_registries.db'
    if db_path.exists(): db_path.unlink()
    eng=create_engine(f"sqlite:///{db_path}")
    try:
        Base.metadata.create_all(eng)
        Session=sessionmaker(bind=eng)
        with Session() as db:
            seed(db); db.commit()
            assert db.scalar(select(func.count()).select_from(OrganizationRegistryDetail)) == 84
            assert db.scalar(select(func.count()).select_from(SupplierBranch)) == 362
            assert db.scalar(select(func.count()).select_from(organization_roles).where(organization_roles.c.role=='SUPPLIER')) >= 200
            assert db.scalar(select(func.count()).select_from(organization_roles).where(organization_roles.c.role=='PARTNER')) >= 80
    finally:
        eng.dispose()
        if db_path.exists(): db_path.unlink()
