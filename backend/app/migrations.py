"""Bridge between the app's startup schema bootstrap and Alembic.

Historically every schema change shipped as a hand-written `ALTER TABLE ...`
guard inside `main.lifespan()` (see the block right above where this module
is called from). That code is left exactly as-is here -- it is what already
brought every existing database, fresh or years-old, to exactly the schema
described by `baseline_2_5_35` in alembic/versions/.

From this point on, *new* schema changes should be written as real Alembic
migrations (`alembic revision --autogenerate -m "..."`) instead of another
ad-hoc ALTER TABLE block. This module makes that possible without any manual
step for the end user (who just launches the desktop app):

- A database that has never seen Alembic (no `alembic_version` table) is, by
  construction, already sitting at exactly the CURRENT `Base.metadata` schema
  -- `Base.metadata.create_all()` (called right before this, in main.lifespan)
  always creates every table described by the models as they exist *today*,
  including any added after the baseline, not just the ones present when
  `baseline_2_5_35` was frozen. So we stamp at "head", not at the fixed
  baseline id, or `upgrade("head")` below would try to re-run every
  post-baseline migration's `CREATE TABLE` against a database that already
  has those tables from `create_all()`, and crash. `stamp` only writes a row
  to `alembic_version` and runs no DDL, so it cannot touch or lose any
  existing data either way.
- We then always call `upgrade("head")`, which is a no-op right after a
  stamp-at-head, but will apply any migrations added after that the next
  time this module is touched.
"""
from pathlib import Path
from sqlalchemy import inspect
from sqlalchemy.engine import Engine
from alembic.config import Config as AlembicConfig
from alembic import command as alembic_command


def run_alembic_migrations(engine: Engine) -> None:
    backend_dir = Path(__file__).resolve().parent.parent
    cfg = AlembicConfig(str(backend_dir / "alembic.ini"))
    cfg.set_main_option("script_location", str(backend_dir / "alembic"))
    cfg.set_main_option("sqlalchemy.url", str(engine.url))
    inspector = inspect(engine)
    if "alembic_version" not in inspector.get_table_names():
        alembic_command.stamp(cfg, "head")
    alembic_command.upgrade(cfg, "head")
