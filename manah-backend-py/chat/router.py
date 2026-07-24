"""
Manah Backend — Chat Router
POST /api/chat/session     — create session
GET  /api/chat/sessions    — list sessions
GET  /api/chat/history     — message history
POST /api/chat/message     — REST full reply (with crisis check)
GET  /api/chat/stream      — SSE streaming reply
POST /api/chat/summarize   — on-demand summarization
"""
import asyncio
import json
from typing import Annotated

import aiosqlite
from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse
from loguru import logger

from auth.middleware import CurrentUser, get_current_user
from chat import schemas
from database import get_db
from llm import get_llm_adapter
from services.crisis import HELPLINE_RESPONSE, detect_crisis
from services.memory import get_memory, run_summarization, save_memory, should_summarize
from services.prompt_builder import build_prompt, build_summarization_prompt

router = APIRouter(prefix="/api/chat", tags=["Chat"])

HISTORY_LIMIT = 5


# ── POST /api/chat/session ─────────────────────────────────────────────────────

@router.post("/session", response_model=schemas.SessionOut, status_code=201)
async def create_session(
    body: schemas.CreateSessionRequest,
    user: Annotated[CurrentUser, Depends(get_current_user)],
    db: Annotated[aiosqlite.Connection, Depends(get_db)],
):
    async with db.execute(
        "INSERT INTO sessions (user_id, title) VALUES (?, ?)",
        (user.id, body.title or "New Conversation"),
    ) as cur:
        session_id = cur.lastrowid
    await db.commit()

    async with db.execute("SELECT * FROM sessions WHERE id = ?", (session_id,)) as cur:
        row = await cur.fetchone()
    s = dict(row)
    return schemas.SessionOut(sessionId=s["id"], title=s["title"], createdAt=s["created_at"])


# ── GET /api/chat/sessions ─────────────────────────────────────────────────────

@router.get("/sessions", response_model=schemas.SessionsResponse)
async def get_sessions(
    user: Annotated[CurrentUser, Depends(get_current_user)],
    db: Annotated[aiosqlite.Connection, Depends(get_db)],
):
    async with db.execute(
        """
        SELECT s.id, s.title, s.created_at, s.last_message_at,
               (SELECT text FROM messages WHERE session_id = s.id ORDER BY created_at DESC LIMIT 1) as lastMessage
        FROM sessions s
        WHERE s.user_id = ?
        ORDER BY CASE WHEN s.last_message_at IS NULL THEN 1 ELSE 0 END,
                 s.last_message_at DESC,
                 s.created_at DESC
        LIMIT 50
        """,
        (user.id,),
    ) as cur:
        rows = await cur.fetchall()

    return schemas.SessionsResponse(
        sessions=[schemas.SessionListItem(**dict(r)) for r in rows]
    )


# ── GET /api/chat/history ──────────────────────────────────────────────────────

@router.get("/history", response_model=schemas.HistoryResponse)
async def get_history(
    user: Annotated[CurrentUser, Depends(get_current_user)],
    db: Annotated[aiosqlite.Connection, Depends(get_db)],
    sessionId: int = Query(...),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
):
    async with db.execute(
        "SELECT * FROM sessions WHERE id = ? AND user_id = ?", (sessionId, user.id)
    ) as cur:
        session = await cur.fetchone()
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

    async with db.execute(
        "SELECT id, sender, text, created_at FROM messages WHERE session_id = ? ORDER BY created_at ASC LIMIT ? OFFSET ?",
        (sessionId, limit, offset),
    ) as cur:
        rows = await cur.fetchall()

    return schemas.HistoryResponse(
        sessionId=sessionId,
        title=dict(session)["title"],
        messages=[schemas.MessageItem(**dict(r)) for r in rows],
    )


# ── POST /api/chat/message ─────────────────────────────────────────────────────

@router.post("/message", response_model=schemas.SendMessageResponse)
async def send_message(
    body: schemas.SendMessageRequest,
    user: Annotated[CurrentUser, Depends(get_current_user)],
    db: Annotated[aiosqlite.Connection, Depends(get_db)],
):
    # Verify session ownership
    async with db.execute(
        "SELECT * FROM sessions WHERE id = ? AND user_id = ?", (body.sessionId, user.id)
    ) as cur:
        session = await cur.fetchone()
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

    # Crisis detection — bypass LLM
    if detect_crisis(body.message):
        try:
            await db.execute(
                "INSERT INTO logs (user_id, action, detail) VALUES (?, 'crisis_detected', ?)",
                (user.id, json.dumps({"sessionId": body.sessionId, "messageSnippet": body.message[:50]})),
            )
            await db.commit()
        except Exception as log_err:
            logger.error(f"[CRISIS] Failed to log: {log_err}")
        return schemas.SendMessageResponse(
            reply=HELPLINE_RESPONSE["reply"], sessionId=body.sessionId
        )

    # Save user message
    await db.execute(
        "INSERT INTO messages (session_id, sender, text) VALUES (?, 'user', ?)",
        (body.sessionId, body.message),
    )
    await db.execute(
        "UPDATE sessions SET last_message_at = datetime('now') WHERE id = ?", (body.sessionId,)
    )
    await db.commit()

    # Get conversation history
    async with db.execute(
        "SELECT sender, text FROM messages WHERE session_id = ? ORDER BY created_at DESC LIMIT ?",
        (body.sessionId, HISTORY_LIMIT * 2),
    ) as cur:
        history = list(reversed([dict(r) for r in await cur.fetchall()]))

    # Get user preferences
    async with db.execute("SELECT tone, language FROM users WHERE id = ?", (user.id,)) as cur:
        user_row = dict(await cur.fetchone())
    memory = await get_memory(db, user.id)

    messages = build_prompt(
        user_message=body.message,
        history=history[:-1],
        memory_summary=memory["summary"] if memory else None,
        tone=user_row.get("tone", "friend"),
        language=user_row.get("language", "hinglish"),
    )

    llm = get_llm_adapter()
    try:
        reply = await llm.chat(messages)
    except Exception as err:
        logger.error(f"[CHAT] LLM error: {err}")
        raise HTTPException(status_code=503, detail="AI service temporarily unavailable. Please try again.")

    # Save AI reply + log
    await db.execute(
        "INSERT INTO messages (session_id, sender, text) VALUES (?, 'assistant', ?)",
        (body.sessionId, reply),
    )
    await db.execute(
        "INSERT INTO logs (user_id, action, detail) VALUES (?, 'chat', ?)",
        (user.id, json.dumps({"sessionId": body.sessionId, "messageLength": len(body.message)})),
    )
    await db.commit()

    # Trigger async summarization if needed
    if await should_summarize(db, body.sessionId):
        asyncio.ensure_future(_summarize_bg(body.sessionId, user.id))

    return schemas.SendMessageResponse(reply=reply, sessionId=body.sessionId)


# ── GET /api/chat/stream (SSE) ─────────────────────────────────────────────────

@router.get("/stream")
async def stream_message(
    user: Annotated[CurrentUser, Depends(get_current_user)],
    db: Annotated[aiosqlite.Connection, Depends(get_db)],
    sessionId: int = Query(...),
    message: str = Query(..., min_length=1),
):
    # Verify session
    async with db.execute(
        "SELECT * FROM sessions WHERE id = ? AND user_id = ?", (sessionId, user.id)
    ) as cur:
        session = await cur.fetchone()
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

    # Save user message
    await db.execute(
        "INSERT INTO messages (session_id, sender, text) VALUES (?, 'user', ?)", (sessionId, message)
    )
    await db.execute("UPDATE sessions SET last_message_at = datetime('now') WHERE id = ?", (sessionId,))
    await db.commit()

    # Gather context
    async with db.execute(
        "SELECT sender, text FROM messages WHERE session_id = ? ORDER BY created_at DESC LIMIT ?",
        (sessionId, HISTORY_LIMIT * 2),
    ) as cur:
        history = list(reversed([dict(r) for r in await cur.fetchall()]))

    async with db.execute("SELECT tone, language FROM users WHERE id = ?", (user.id,)) as cur:
        user_row = dict(await cur.fetchone())
    memory = await get_memory(db, user.id)

    llm_messages = build_prompt(
        user_message=message,
        history=history[:-1],
        memory_summary=memory["summary"] if memory else None,
        tone=user_row.get("tone", "friend"),
        language=user_row.get("language", "hinglish"),
    )

    llm = get_llm_adapter()

    async def event_gen():
        full_reply = ""
        try:
            async for delta in llm.stream_chat(llm_messages):
                full_reply += delta
                yield f"data: {json.dumps({'delta': delta, 'done': False})}\n\n"
        except Exception as err:
            logger.error(f"[CHAT/SSE] LLM error: {err}")
            yield f"data: {json.dumps({'error': 'AI service error', 'done': True})}\n\n"
            return

        yield f"data: {json.dumps({'delta': '', 'done': True})}\n\n"

        # Persist + maybe summarize (fire-and-forget via new db connection)
        if full_reply:
            asyncio.ensure_future(_save_assistant_reply(sessionId, user.id, full_reply, message))

    return StreamingResponse(
        event_gen(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


# ── POST /api/chat/summarize ───────────────────────────────────────────────────

@router.post("/summarize", response_model=schemas.SummarizeResponse)
async def summarize_session(
    body: schemas.SummarizeRequest,
    user: Annotated[CurrentUser, Depends(get_current_user)],
    db: Annotated[aiosqlite.Connection, Depends(get_db)],
):
    async with db.execute(
        "SELECT * FROM sessions WHERE id = ? AND user_id = ?", (body.sessionId, user.id)
    ) as cur:
        session = await cur.fetchone()
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

    await run_summarization(db, body.sessionId, user.id)
    memory = await get_memory(db, user.id)
    return schemas.SummarizeResponse(
        summary=memory["summary"] if memory else "No summary generated yet.",
        updatedAt=memory["updated_at"] if memory else None,
    )


# ── Background helpers ─────────────────────────────────────────────────────────

async def _summarize_bg(session_id: int, user_id: int) -> None:
    """Fire-and-forget summarization using a fresh DB connection."""
    import aiosqlite as _aiosqlite
    from database import DB_PATH
    try:
        async with _aiosqlite.connect(DB_PATH) as bg_db:
            bg_db.row_factory = _aiosqlite.Row
            await run_summarization(bg_db, session_id, user_id)
    except Exception as err:
        logger.error(f"[CHAT] Background summarization failed: {err}")


async def _save_assistant_reply(session_id: int, user_id: int, reply: str, user_message: str) -> None:
    """Save streamed reply and optionally trigger summarization."""
    import aiosqlite as _aiosqlite
    from database import DB_PATH
    try:
        async with _aiosqlite.connect(DB_PATH) as bg_db:
            bg_db.row_factory = _aiosqlite.Row
            await bg_db.execute(
                "INSERT INTO messages (session_id, sender, text) VALUES (?, 'assistant', ?)",
                (session_id, reply),
            )
            await bg_db.commit()
            if await should_summarize(bg_db, session_id):
                await run_summarization(bg_db, session_id, user_id)
    except Exception as err:
        logger.error(f"[CHAT] Failed to save streamed reply: {err}")
