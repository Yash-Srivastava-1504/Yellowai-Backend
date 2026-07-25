"""
Manah Backend — Auth Service
Password hashing (bcrypt directly), JWT generation/verification, DB helpers.
"""
import json
from datetime import datetime, timedelta, timezone
from typing import Optional

import aiosqlite
import bcrypt as _bcrypt
from jose import JWTError, jwt

from config import get_settings

settings = get_settings()


# ── Password ───────────────────────────────────────────────────────────────────

def hash_password(plain: str) -> str:
    salt = _bcrypt.gensalt()
    return _bcrypt.hashpw(plain.encode(), salt).decode()


def verify_password(plain: str, hashed: str) -> bool:
    try:
        return _bcrypt.checkpw(plain.encode(), hashed.encode())
    except Exception:
        return False


# ── JWT ────────────────────────────────────────────────────────────────────────

def create_access_token(user_id: int, email: str) -> str:
    expire = datetime.now(timezone.utc) + timedelta(seconds=settings.JWT_EXPIRES_IN)
    payload = {"id": user_id, "email": email, "exp": expire}
    return jwt.encode(payload, settings.JWT_SECRET, algorithm="HS256")


def create_refresh_token(user_id: int) -> str:
    expire = datetime.now(timezone.utc) + timedelta(seconds=settings.JWT_REFRESH_EXPIRES_IN)
    payload = {"id": user_id, "exp": expire}
    return jwt.encode(payload, settings.JWT_REFRESH_SECRET, algorithm="HS256")


def decode_access_token(token: str) -> dict:
    """Raises JWTError on invalid/expired token."""
    return jwt.decode(token, settings.JWT_SECRET, algorithms=["HS256"])


def decode_refresh_token(token: str) -> dict:
    """Raises JWTError on invalid/expired token."""
    return jwt.decode(token, settings.JWT_REFRESH_SECRET, algorithms=["HS256"])


# ── DB helpers ─────────────────────────────────────────────────────────────────

async def get_user_by_email(db: aiosqlite.Connection, email: str) -> Optional[dict]:
    async with db.execute("SELECT * FROM users WHERE email = ?", (email.lower(),)) as cur:
        row = await cur.fetchone()
        return dict(row) if row else None


async def get_user_by_id(db: aiosqlite.Connection, user_id: int) -> Optional[dict]:
    async with db.execute(
        "SELECT id, name, email, language, tone, avatar, created_at FROM users WHERE id = ?",
        (user_id,),
    ) as cur:
        row = await cur.fetchone()
        return dict(row) if row else None


async def create_user(db: aiosqlite.Connection, email: str, password_hash: str, name: str) -> int:
    async with db.execute(
        "INSERT INTO users (email, password_hash, name) VALUES (?, ?, ?)",
        (email.lower(), password_hash, name),
    ) as cur:
        user_id = cur.lastrowid
    # Create default settings row
    await db.execute("INSERT OR IGNORE INTO user_settings (user_id) VALUES (?)", (user_id,))
    await db.commit()
    return user_id


async def store_refresh_token(db: aiosqlite.Connection, user_id: int, token: str) -> None:
    expires_at = (datetime.now(timezone.utc) + timedelta(seconds=settings.JWT_REFRESH_EXPIRES_IN)).isoformat()
    await db.execute(
        "INSERT INTO refresh_tokens (user_id, token, expires_at) VALUES (?, ?, ?)",
        (user_id, token, expires_at),
    )
    await db.commit()


async def revoke_refresh_token(db: aiosqlite.Connection, token: str) -> None:
    await db.execute("DELETE FROM refresh_tokens WHERE token = ?", (token,))
    await db.commit()


async def get_stored_refresh_token(db: aiosqlite.Connection, token: str, user_id: int) -> Optional[dict]:
    async with db.execute(
        "SELECT * FROM refresh_tokens WHERE token = ? AND user_id = ? AND expires_at > datetime('now')",
        (token, user_id),
    ) as cur:
        row = await cur.fetchone()
        return dict(row) if row else None


async def log_action(db: aiosqlite.Connection, user_id: Optional[int], action: str, detail: dict = None) -> None:
    await db.execute(
        "INSERT INTO logs (user_id, action, detail) VALUES (?, ?, ?)",
        (user_id, action, json.dumps(detail or {})),
    )
    await db.commit()
