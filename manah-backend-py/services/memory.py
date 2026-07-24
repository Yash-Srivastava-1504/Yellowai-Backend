"""
Manah Backend — Memory Service
Conversation summarization: get, save, check, run.
"""
import json
from typing import Optional

import aiosqlite
from loguru import logger


async def get_memory(db: aiosqlite.Connection, user_id: int) -> Optional[dict]:
    """Get the latest memory summary for a user."""
    async with db.execute(
        "SELECT summary, updated_at FROM memory WHERE user_id = ? ORDER BY updated_at DESC LIMIT 1",
        (user_id,),
    ) as cur:
        row = await cur.fetchone()
        return dict(row) if row else None


async def save_memory(db: aiosqlite.Connection, user_id: int, summary: str, session_id: Optional[int] = None) -> None:
    """Upsert a memory summary for a user (one summary per user)."""
    async with db.execute("SELECT id FROM memory WHERE user_id = ?", (user_id,)) as cur:
        existing = await cur.fetchone()

    if existing:
        await db.execute(
            "UPDATE memory SET summary = ?, session_id = ?, updated_at = datetime('now') WHERE user_id = ?",
            (summary, session_id, user_id),
        )
    else:
        await db.execute(
            "INSERT INTO memory (user_id, session_id, summary) VALUES (?, ?, ?)",
            (user_id, session_id, summary),
        )
    await db.commit()


MESSAGES_PER_SUMMARY = 5


async def should_summarize(db: aiosqlite.Connection, session_id: int) -> bool:
    """Returns True if a session has >= MESSAGES_PER_SUMMARY new user messages since last summary."""
    async with db.execute(
        """
        SELECT COUNT(*) as count FROM messages
        WHERE session_id = ?
          AND sender = 'user'
          AND created_at > COALESCE(
            (SELECT updated_at FROM memory WHERE session_id = ? ORDER BY updated_at DESC LIMIT 1),
            '1970-01-01'
          )
        """,
        (session_id, session_id),
    ) as cur:
        row = await cur.fetchone()
        return (row["count"] if row else 0) >= MESSAGES_PER_SUMMARY


async def run_summarization(db: aiosqlite.Connection, session_id: int, user_id: int) -> None:
    """Fetch recent messages, call LLM, store result in memory table."""
    from llm import get_llm_adapter
    from services.prompt_builder import build_summarization_prompt

    async with db.execute(
        "SELECT sender, text FROM messages WHERE session_id = ? ORDER BY created_at DESC LIMIT 20",
        (session_id,),
    ) as cur:
        rows = await cur.fetchall()

    messages = list(reversed([dict(r) for r in rows]))
    if len(messages) < 2:
        return

    logger.info(f"[MEMORY] Summarising session {session_id} for user {user_id}")
    try:
        llm = get_llm_adapter()
        prompt = build_summarization_prompt(messages)
        summary = await llm.chat(prompt)
        await save_memory(db, user_id, summary.strip(), session_id)
        logger.info(f"[MEMORY] Summary saved for user {user_id}: '{summary[:80]}…'")
    except Exception as err:
        logger.error(f"[MEMORY] Summarisation failed: {err}")


async def get_sessions_needing_summary(db: aiosqlite.Connection) -> list[dict]:
    """Return sessions with >= MESSAGES_PER_SUMMARY unsummarised user messages."""
    async with db.execute(
        """
        SELECT s.id as sessionId, s.user_id as userId, COUNT(m.id) as userMsgCount
        FROM sessions s
        JOIN messages m ON m.session_id = s.id AND m.sender = 'user'
        WHERE m.created_at > COALESCE(
          (SELECT updated_at FROM memory WHERE user_id = s.user_id ORDER BY updated_at DESC LIMIT 1),
          '1970-01-01'
        )
        GROUP BY s.id
        HAVING userMsgCount >= ?
        """,
        (MESSAGES_PER_SUMMARY,),
    ) as cur:
        rows = await cur.fetchall()
        return [dict(r) for r in rows]
