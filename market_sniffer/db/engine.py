from __future__ import annotations

from pathlib import Path

from sqlalchemy import Engine, create_engine, event, text
from sqlalchemy.orm import Session, sessionmaker


def make_sqlite_url(db_path: Path | str) -> str:
    path = Path(db_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    return f"sqlite:///{path}"


def create_db_engine(db_path: Path | str) -> Engine:
    engine = create_engine(make_sqlite_url(db_path), future=True)

    @event.listens_for(engine, "connect")
    def _set_sqlite_pragmas(dbapi_connection, _connection_record):  # type: ignore[no-untyped-def]
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.execute("PRAGMA busy_timeout=5000")
        cursor.close()

    return engine


def session_factory(engine: Engine) -> sessionmaker[Session]:
    return sessionmaker(bind=engine, expire_on_commit=False, future=True)


def assert_sqlite_pragmas(engine: Engine) -> dict[str, str | int]:
    with engine.connect() as conn:
        return {
            "foreign_keys": conn.execute(text("PRAGMA foreign_keys")).scalar_one(),
            "journal_mode": conn.execute(text("PRAGMA journal_mode")).scalar_one(),
            "busy_timeout": conn.execute(text("PRAGMA busy_timeout")).scalar_one(),
        }
