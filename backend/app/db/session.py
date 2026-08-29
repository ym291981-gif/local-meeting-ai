"""DBエンジン・セッション管理。"""
from __future__ import annotations

import logging
from collections.abc import Generator

from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session, sessionmaker

from app.config import get_settings
from app.db.models import Base

logger = logging.getLogger(__name__)

_settings = get_settings()

connect_args = {"check_same_thread": False} if _settings.database_url.startswith("sqlite") else {}
engine = create_engine(_settings.database_url, connect_args=connect_args)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)


def _sqlite_column_names(conn, table: str) -> set[str]:
    rows = conn.execute(text(f"PRAGMA table_info({table})")).fetchall()
    return {row[1] for row in rows}


def ensure_schema() -> None:
    """既存SQLite DBに不足カラムがあれば ALTER で追加する(Alembicなし運用向け)。"""
    if not str(engine.url).startswith("sqlite"):
        return
    with engine.begin() as conn:
        meeting_cols = _sqlite_column_names(conn, "meetings")
        if meeting_cols and "summary_mode" not in meeting_cols:
            logger.info("meetings.summary_mode カラムを追加します")
            conn.execute(
                text(
                    "ALTER TABLE meetings ADD COLUMN summary_mode VARCHAR(50) "
                    "DEFAULT 'auto'"
                )
            )

        snapshot_cols = _sqlite_column_names(conn, "minutes_snapshots")
        if snapshot_cols and "sections" not in snapshot_cols:
            logger.info("minutes_snapshots.sections カラムを追加します")
            conn.execute(text("ALTER TABLE minutes_snapshots ADD COLUMN sections JSON"))


def init_db() -> None:
    Base.metadata.create_all(bind=engine)
    ensure_schema()


def get_db() -> Generator[Session, None, None]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
