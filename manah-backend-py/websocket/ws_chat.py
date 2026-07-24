"""
Manah Backend — WebSocket Chat Handler
ws://localhost:3001/ws/chat

Auth: JWT from ?token= query param OR accessToken cookie.
Protocol:
  CLIENT → SERVER: { "sessionId": 42, "message": "..." }
  SERVER → CLIENT: { "delta": "...", "done": false }   (streaming chunks)
  SERVER → CLIENT: { "delta": "", "done": true }       (final frame)
  SERVER → CLIENT: { "error": "..." }                  (on error)
  SERVER → CLIENT: { "crisis": true, "reply": "...", "helplines": [...] }
"""
import asyncio
import json
from typing import Optional

import aiosqlite
from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from loguru import logger

from auth.service import decode_access_token
from database import DB_PATH
from llm import get_llm_adapter
from services.crisis import HELPLINE_RESPONSE, detect_crisis
from services.memory import get_memory, run_summarization, should_summarize
from services.prompt_builder import build_prompt

router = APIRouter(tags=["WebSocket"])

HISTORY_LIMIT = 5


def _extract_token(websocket: WebSocket) -> Optional[str]:
    """Extract JWT from ?token= query param or accessToken cookie."""
    token = websocket.query_params.get("token")
    if token:
        return token
    # Try cookie
    cookies = websocket.cookies
    return cookies.get("accessToken")


@router.websocket("/ws/chat")
async def websocket_chat(websocket: WebSocket):
    # ── Auth ──────────────────────────────────────────────────────────────────
    token = _extract_token(websocket)
    if not token:
        await websocket.close(code=1008, reason="Authentication required")
        return

    try:
        payload = decode_access_token(token)
        user_id = payload["id"]
        user_email = payload["email"]
    except Exception:
        await websocket.close(code=1008, reason="Invalid or expired token")
        return

    await websocket.accept()
    logger.info(f"[WS] User {user_id} connected")

    try:
        while True:
            raw = await websocket.receive_text()

            # Parse message
            try:
                data = json.loads(raw)
            except json.JSONDecodeError:
                await websocket.send_text(json.dumps({"error": "Invalid JSON"}))
                continue

            session_id = data.get("sessionId")
            message = data.get("message")

            if not session_id or not message:
                await websocket.send_text(json.dumps({"error": "sessionId and message are required"}))
                continue

            async with aiosqlite.connect(DB_PATH) as db:
                db.row_factory = aiosqlite.Row

                # Verify session ownership
                async with db.execute(
                    "SELECT * FROM sessions WHERE id = ? AND user_id = ?", (session_id, user_id)
                ) as cur:
                    session = await cur.fetchone()

                if not session:
                    await websocket.send_text(json.dumps({"error": "Session not found or access denied"}))
                    continue

                # Crisis detection
                if detect_crisis(message):
                    try:
                        await db.execute(
                            "INSERT INTO logs (user_id, action, detail) VALUES (?, 'crisis_detected', ?)",
                            (user_id, json.dumps({"sessionId": session_id, "messageSnippet": message[:50]})),
                        )
                        await db.commit()
                    except Exception as log_err:
                        logger.error(f"[WS] Crisis log error: {log_err}")
                    await websocket.send_text(json.dumps(HELPLINE_RESPONSE))
                    continue

                # Save user message
                await db.execute(
                    "INSERT INTO messages (session_id, sender, text) VALUES (?, 'user', ?)",
                    (session_id, message),
                )
                await db.execute(
                    "UPDATE sessions SET last_message_at = datetime('now') WHERE id = ?", (session_id,)
                )
                await db.commit()

                # Fetch history + user prefs
                async with db.execute(
                    "SELECT sender, text FROM messages WHERE session_id = ? ORDER BY created_at DESC LIMIT ?",
                    (session_id, HISTORY_LIMIT * 2),
                ) as cur:
                    history = list(reversed([dict(r) for r in await cur.fetchall()]))

                async with db.execute("SELECT tone, language FROM users WHERE id = ?", (user_id,)) as cur:
                    user_row = dict(await cur.fetchone())

                memory = await get_memory(db, user_id)

                llm_messages = build_prompt(
                    user_message=message,
                    history=history[:-1],
                    memory_summary=memory["summary"] if memory else None,
                    tone=user_row.get("tone", "friend"),
                    language=user_row.get("language", "hinglish"),
                )

                # Stream from LLM
                llm = get_llm_adapter()
                full_reply = ""

                try:
                    async for delta in llm.stream_chat(llm_messages):
                        full_reply += delta
                        await websocket.send_text(json.dumps({"delta": delta, "done": False}))
                except Exception as err:
                    logger.error(f"[WS] LLM stream error: {err}")
                    await websocket.send_text(
                        json.dumps({"error": "AI service temporarily unavailable", "done": True})
                    )
                    continue

                await websocket.send_text(json.dumps({"delta": "", "done": True}))

                # Save reply + log + maybe summarize
                if full_reply:
                    await db.execute(
                        "INSERT INTO messages (session_id, sender, text) VALUES (?, 'assistant', ?)",
                        (session_id, full_reply),
                    )
                    await db.execute(
                        "INSERT INTO logs (user_id, action, detail) VALUES (?, 'chat_ws', ?)",
                        (user_id, json.dumps({"sessionId": session_id, "messageLength": len(message)})),
                    )
                    await db.commit()

                    if await should_summarize(db, session_id):
                        asyncio.ensure_future(
                            _summarize_bg(session_id, user_id)
                        )

    except WebSocketDisconnect:
        logger.info(f"[WS] User {user_id} disconnected")
    except Exception as err:
        logger.error(f"[WS] Connection error for user {user_id}: {err}")


async def _summarize_bg(session_id: int, user_id: int) -> None:
    try:
        async with aiosqlite.connect(DB_PATH) as bg_db:
            bg_db.row_factory = aiosqlite.Row
            await run_summarization(bg_db, session_id, user_id)
    except Exception as err:
        logger.error(f"[WS] Background summarization failed: {err}")
