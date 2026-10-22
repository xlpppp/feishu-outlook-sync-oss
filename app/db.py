"""SQLAlchemy engine / session helpers."""

from __future__ import annotations

import logging
from contextlib import contextmanager
from typing import Generator, Iterator

from sqlalchemy import create_engine, event, text
from sqlalchemy.orm import Session, declarative_base, sessionmaker

from .config import get_settings

log = logging.getLogger("db")

Base = declarative_base()

_engine = None
_SessionLocal = None


def get_engine():
    global _engine, _SessionLocal
    if _engine is None:
        url = get_settings().database_url
        connect_args = {}
        if url.startswith("sqlite"):
            connect_args["check_same_thread"] = False
        _engine = create_engine(url, connect_args=connect_args, future=True)

        if url.startswith("sqlite"):

            @event.listens_for(_engine, "connect")
            def _set_sqlite_pragma(dbapi_conn, _):
                cursor = dbapi_conn.cursor()
                cursor.execute("PRAGMA foreign_keys=ON")
                cursor.close()

        _SessionLocal = sessionmaker(
            bind=_engine, autoflush=False, autocommit=False, future=True
        )
    return _engine


def _table_columns(conn, table: str) -> set[str]:
    """Return column names for a table (SQLite PRAGMA / information_schema fallback)."""
    url = str(conn.engine.url)
    if url.startswith("sqlite"):
        rows = conn.execute(text(f"PRAGMA table_info({table})")).fetchall()
        # PRAGMA table_info: cid, name, type, notnull, dflt_value, pk
        return {r[1] for r in rows}
    # Generic: try information_schema
    try:
        rows = conn.execute(
            text(
                "SELECT column_name FROM information_schema.columns "
                "WHERE table_name = :t"
            ),
            {"t": table},
        ).fetchall()
        return {r[0] for r in rows}
    except Exception:
        return set()


def _index_names(conn, table: str) -> set[str]:
    url = str(conn.engine.url)
    if url.startswith("sqlite"):
        rows = conn.execute(text(f"PRAGMA index_list({table})")).fetchall()
        # seq, name, unique, origin, partial
        return {r[1] for r in rows}
    return set()


def migrate_schema(engine) -> None:
    """Alembic-less additive migrations for existing SQLite DBs."""
    with engine.begin() as conn:
        cols_users = _table_columns(conn, "users")
        if cols_users and "sync_direction" not in cols_users:
            log.info("ALTER TABLE users ADD COLUMN sync_direction")
            conn.execute(
                text(
                    "ALTER TABLE users ADD COLUMN sync_direction "
                    "VARCHAR(64) NOT NULL DEFAULT 'feishu_to_outlook'"
                )
            )

        cols_map = _table_columns(conn, "event_mappings")
        if cols_map and "direction" not in cols_map:
            log.info("ALTER TABLE event_mappings ADD COLUMN direction")
            conn.execute(
                text(
                    "ALTER TABLE event_mappings ADD COLUMN direction "
                    "VARCHAR(8) NOT NULL DEFAULT 'f2o'"
                )
            )

        # Unique index on (user_id, outlook_event_id) if missing
        if cols_map:
            indexes = _index_names(conn, "event_mappings")
            if "uq_mapping_user_outlook_event" not in indexes and (
                "ix_uq_mapping_user_outlook_event" not in indexes
            ):
                try:
                    conn.execute(
                        text(
                            "CREATE UNIQUE INDEX IF NOT EXISTS "
                            "uq_mapping_user_outlook_event "
                            "ON event_mappings (user_id, outlook_event_id)"
                        )
                    )
                    log.info("Created unique index uq_mapping_user_outlook_event")
                except Exception as e:
                    log.warning(
                        "Could not create uq_mapping_user_outlook_event: %s", e
                    )

            if "ix_mapping_user_direction" not in indexes:
                try:
                    conn.execute(
                        text(
                            "CREATE INDEX IF NOT EXISTS ix_mapping_user_direction "
                            "ON event_mappings (user_id, direction)"
                        )
                    )
                except Exception as e:
                    log.warning("Could not create ix_mapping_user_direction: %s", e)


def init_db() -> None:
    from . import models  # noqa: F401

    engine = get_engine()
    Base.metadata.create_all(bind=engine)
    migrate_schema(engine)


def get_session_factory() -> sessionmaker:
    get_engine()
    assert _SessionLocal is not None
    return _SessionLocal


@contextmanager
def session_scope() -> Iterator[Session]:
    factory = get_session_factory()
    session = factory()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def get_db() -> Generator[Session, None, None]:
    """FastAPI dependency."""
    factory = get_session_factory()
    session = factory()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
