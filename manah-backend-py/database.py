"""
Manah Backend — SQLite Database
Synchronous init (WAL + FK + schema), async session dependency for FastAPI.
"""
import os
import sqlite3
from contextlib import asynccontextmanager
from pathlib import Path
from typing import AsyncGenerator

import aiosqlite
from loguru import logger

from config import get_settings

# ── Path resolution ────────────────────────────────────────────────────────────

def _resolve_db_path() -> str:
    settings = get_settings()
    db_path = settings.DB_PATH
    if db_path == ":memory:":
        return ":memory:"
    resolved = Path(db_path).resolve()
    resolved.parent.mkdir(parents=True, exist_ok=True)
    return str(resolved)


DB_PATH = _resolve_db_path()

# ── Schema ─────────────────────────────────────────────────────────────────────

_SCHEMA = """
-- Users table
CREATE TABLE IF NOT EXISTS users (
  id            INTEGER PRIMARY KEY AUTOINCREMENT,
  email         TEXT    UNIQUE NOT NULL,
  password_hash TEXT    NOT NULL,
  name          TEXT    NOT NULL DEFAULT 'User',
  language      TEXT    NOT NULL DEFAULT 'hinglish',
  tone          TEXT    NOT NULL DEFAULT 'friend',
  avatar        TEXT    NOT NULL DEFAULT '🙂',
  created_at    TEXT    NOT NULL DEFAULT (datetime('now')),
  last_login    TEXT
);
CREATE INDEX IF NOT EXISTS idx_users_email ON users(email);

-- Sessions table
CREATE TABLE IF NOT EXISTS sessions (
  id               INTEGER PRIMARY KEY AUTOINCREMENT,
  user_id          INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  title            TEXT    NOT NULL DEFAULT 'New Conversation',
  created_at       TEXT    NOT NULL DEFAULT (datetime('now')),
  last_message_at  TEXT
);
CREATE INDEX IF NOT EXISTS idx_sessions_user ON sessions(user_id);

-- Messages table
CREATE TABLE IF NOT EXISTS messages (
  id          INTEGER PRIMARY KEY AUTOINCREMENT,
  session_id  INTEGER NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
  sender      TEXT    NOT NULL CHECK(sender IN ('user','assistant')),
  text        TEXT    NOT NULL,
  created_at  TEXT    NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_messages_session ON messages(session_id);

-- Memory (conversation summaries)
CREATE TABLE IF NOT EXISTS memory (
  id          INTEGER PRIMARY KEY AUTOINCREMENT,
  user_id     INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  session_id  INTEGER REFERENCES sessions(id) ON DELETE CASCADE,
  summary     TEXT    NOT NULL,
  updated_at  TEXT    NOT NULL DEFAULT (datetime('now')),
  expires_at  TEXT
);
CREATE INDEX IF NOT EXISTS idx_memory_user ON memory(user_id);

-- Moods table
CREATE TABLE IF NOT EXISTS moods (
  id          INTEGER PRIMARY KEY AUTOINCREMENT,
  user_id     INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  date        TEXT    NOT NULL,
  level       INTEGER NOT NULL CHECK(level BETWEEN 0 AND 4),
  note        TEXT,
  tags        TEXT    DEFAULT '[]'
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_moods_user_date ON moods(user_id, date);

-- Per-user settings
CREATE TABLE IF NOT EXISTS user_settings (
  user_id       INTEGER PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
  theme         TEXT    NOT NULL DEFAULT 'light',
  notifications INTEGER NOT NULL DEFAULT 1,
  notif_time    TEXT    NOT NULL DEFAULT 'evening',
  companion     TEXT    NOT NULL DEFAULT 'friend',
  anonymous     INTEGER NOT NULL DEFAULT 0,
  weekly_report INTEGER NOT NULL DEFAULT 1
);

-- Audit / action logs
CREATE TABLE IF NOT EXISTS logs (
  id          INTEGER PRIMARY KEY AUTOINCREMENT,
  user_id     INTEGER REFERENCES users(id) ON DELETE SET NULL,
  action      TEXT    NOT NULL,
  detail      TEXT    DEFAULT '{}',
  created_at  TEXT    NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_logs_user   ON logs(user_id);
CREATE INDEX IF NOT EXISTS idx_logs_action ON logs(action);

-- Refresh token store
CREATE TABLE IF NOT EXISTS refresh_tokens (
  id          INTEGER PRIMARY KEY AUTOINCREMENT,
  user_id     INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  token       TEXT    UNIQUE NOT NULL,
  expires_at  TEXT    NOT NULL,
  created_at  TEXT    NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_refresh_user ON refresh_tokens(user_id);
"""


def init_db() -> None:
    """
    Synchronous DB init — called once at startup.
    Creates tables (idempotent), enables WAL + FK.
    """
    if DB_PATH == ":memory:":
        logger.info("[DB] Using in-memory SQLite (test mode)")
        return  # aiosqlite handles :memory: per-connection — skip sync init

    conn = sqlite3.connect(DB_PATH)
    try:
        conn.execute("PRAGMA journal_mode = WAL")
        conn.execute("PRAGMA foreign_keys = ON")
        conn.executescript(_SCHEMA)
        conn.commit()
        logger.info(f"[DB] SQLite initialised at {DB_PATH}")
    finally:
        conn.close()


# ── Async dependency ───────────────────────────────────────────────────────────

async def get_db() -> AsyncGenerator[aiosqlite.Connection, None]:
    """
    FastAPI dependency: yields an async aiosqlite connection.
    Row factory set to sqlite3.Row for dict-like access.
    """
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        await db.execute("PRAGMA foreign_keys = ON")
        try:
            yield db
            await db.commit()
        except Exception:
            await db.rollback()
            raise
