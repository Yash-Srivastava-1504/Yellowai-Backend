"""
ChatBot Platform — Minimal SQLite Database
Kept for the legacy auth module (refresh tokens, audit logs).
Primary data store is Supabase (managed via REST from the frontend and projects/chat_v2 modules).
"""
import sqlite3
from pathlib import Path
from typing import AsyncGenerator

import aiosqlite
from loguru import logger

from config import get_settings


def _resolve_db_path() -> str:
    settings = get_settings()
    db_path = settings.DB_PATH if hasattr(settings, "DB_PATH") else "./data/platform.db"
    if db_path == ":memory:":
        return ":memory:"
    resolved = Path(db_path).resolve()
    resolved.parent.mkdir(parents=True, exist_ok=True)
    return str(resolved)


DB_PATH = _resolve_db_path()

# ── Minimal schema (legacy auth only) ─────────────────────────────────────────
_SCHEMA = """
-- Audit / action logs
CREATE TABLE IF NOT EXISTS logs (
  id          INTEGER PRIMARY KEY AUTOINCREMENT,
  user_id     TEXT,
  action      TEXT    NOT NULL,
  detail      TEXT    DEFAULT '{}',
  created_at  TEXT    NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_logs_user   ON logs(user_id);
CREATE INDEX IF NOT EXISTS idx_logs_action ON logs(action);
"""


def init_db() -> None:
    """
    Synchronous DB init — called once at startup.
    Creates minimal tables (idempotent), enables WAL.
    """
    if DB_PATH == ":memory:":
        logger.info("[DB] Using in-memory SQLite (test mode)")
        return

    conn = sqlite3.connect(DB_PATH)
    try:
        conn.execute("PRAGMA journal_mode = WAL")
        conn.executescript(_SCHEMA)
        conn.commit()
        logger.info(f"[DB] SQLite initialised at {DB_PATH}")
    finally:
        conn.close()


async def get_db() -> AsyncGenerator[aiosqlite.Connection, None]:
    """FastAPI dependency: yields an async aiosqlite connection."""
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        try:
            yield db
            await db.commit()
        except Exception:
            await db.rollback()
            raise
