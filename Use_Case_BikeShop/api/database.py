"""
Database configuration using SQLModel with SQLite.

SQLite runs under 4 uvicorn workers plus the worker, so (SPEC §10):
- WAL mode lets readers carry on while one process writes;
- busy_timeout makes a second writer wait up to 5 s instead of failing with
  "database is locked";
- plain reads run outside transactions, so they always see the latest data;
- every write runs in BEGIN IMMEDIATE: it takes the write lock first, then
  reads and writes. A booking does this *before* it checks availability
  (SPEC §5.4), so nobody can slip in between the check and the insert.
  (Django's SQLite backend offers the same as transaction_mode="IMMEDIATE".)
"""
import warnings

from sqlalchemy import event, exc as sa_exc
from sqlalchemy.engine import Connection
from sqlmodel import Session, SQLModel, create_engine, select

from .config import DATA_DIR, DATABASE_URL

# SQLite stores Decimal as text/float; SQLAlchemy warns about it on every use.
warnings.filterwarnings("ignore", message=".*does not support Decimal objects natively.*", category=sa_exc.SAWarning)

engine = create_engine(DATABASE_URL, connect_args={"check_same_thread": False})


@event.listens_for(engine, "connect")
def _on_connect(dbapi_connection, _):
    # Autocommit at the driver level: we start transactions ourselves (below).
    dbapi_connection.isolation_level = None
    cursor = dbapi_connection.cursor()
    cursor.execute("PRAGMA journal_mode=WAL")
    cursor.execute("PRAGMA busy_timeout=5000")
    cursor.execute("PRAGMA foreign_keys=ON")
    cursor.close()


def _begin_immediate(connection: Connection) -> None:
    """Start BEGIN IMMEDIATE unless this connection is already in a transaction."""
    if not connection.connection.driver_connection.in_transaction:
        connection.exec_driver_sql("BEGIN IMMEDIATE")


@event.listens_for(Session, "before_flush")
def _before_flush(session, flush_context, instances):
    # The ORM is about to write: make sure that happens inside BEGIN IMMEDIATE.
    _begin_immediate(session.connection())


def start_write_transaction(db: Session) -> None:
    """
    End whatever the session was doing and take the write lock now.

    Use it at the top of a service method that reads, decides and writes
    (booking, reserving, status changes): no other writer can slip in
    between the check and the write.
    """
    db.commit()
    _begin_immediate(db.connection())


def create_tables():
    """Create all database tables."""
    SQLModel.metadata.create_all(bind=engine)


def get_db():
    """Get database session dependency."""
    with Session(engine) as session:
        yield session


def check_database() -> str:
    """Return 'ok' if the database answers, else the error (for /health)."""
    try:
        with Session(engine) as session:
            session.exec(select(1)).one()
        return "ok"
    except Exception as e:  # noqa: BLE001 - health check reports, never raises
        return f"error: {e.__class__.__name__}"


# Columns added after their table already existed in production (SPEC §4).
# create_all() only creates missing tables, so these are added by hand:
# table -> [(column, SQL type and default)]. Existing rows get the default.
ADDED_COLUMNS = {
    "analyticsevent": [("channel", "VARCHAR NOT NULL DEFAULT 'api'")],
}


def add_missing_columns():
    """
    A tiny migration: add the columns in ADDED_COLUMNS where they are missing.
    Several processes start at once (API workers, the worker), so it takes the
    write lock first, like a booking: the others wait, then find nothing to do.
    """
    with engine.connect() as connection:
        connection.exec_driver_sql("BEGIN IMMEDIATE")
        try:
            for table, columns in ADDED_COLUMNS.items():
                existing = {row[1] for row in connection.exec_driver_sql(f"PRAGMA table_info({table})")}
                for column, definition in columns:
                    if existing and column not in existing:   # existing is empty if the table doesn't exist
                        connection.exec_driver_sql(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")
                        print(f"  added column {table}.{column}", flush=True)
            connection.exec_driver_sql("COMMIT")
        except Exception:
            connection.exec_driver_sql("ROLLBACK")
            raise


def init_database():
    """Initialize the database: create missing tables, then add missing columns."""
    if DATABASE_URL.startswith("sqlite:///"):
        DATA_DIR.mkdir(parents=True, exist_ok=True)
    create_tables()
    add_missing_columns()
    print("✅ Database initialized successfully!", flush=True)
