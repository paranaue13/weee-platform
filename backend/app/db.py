from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker, DeclarativeBase
from .config import settings

connect_args = {"check_same_thread": False} if settings.database_url.startswith("sqlite") else {}
engine = create_engine(settings.database_url, pool_pre_ping=True, connect_args=connect_args)
if settings.database_url.startswith("sqlite"):
    @event.listens_for(engine, "connect")
    def _sqlite_pragmas(dbapi_conn, _record):
        # WAL: οι αναγνώστες (π.χ. το προγραμματισμένο αντίγραφο ασφαλείας) δεν μπλοκάρουν τους εγγραφείς και αντίστροφα.
        # busy_timeout: αναμονή έως 30" πριν το «database is locked». Το αντίγραφο γίνεται με το online backup API (σωστό και με WAL).
        cur = dbapi_conn.cursor()
        try:
            cur.execute("PRAGMA busy_timeout=30000")
            cur.execute("PRAGMA journal_mode=WAL")
            cur.execute("PRAGMA synchronous=NORMAL")
        except Exception:
            pass
        finally:
            cur.close()

SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)

class Base(DeclarativeBase):
    pass

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
