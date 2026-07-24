"""
Manah Backend — Companion Router
POST /api/companion/chat — SSE streaming (Supabase JWT, stateless)
"""
import asyncio
import json
from typing import Annotated, Optional

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from loguru import logger
from pydantic import BaseModel, Field

from auth.middleware import SupabaseUser, get_supabase_user
from llm import get_llm_adapter
from services.crisis import HELPLINE_RESPONSE, detect_crisis
from services.prompt_builder import build_prompt_from_thread

router = APIRouter(prefix="/api/companion", tags=["Companion"])

VALID_COMPANIONS = {"didi", "bhaiya", "friend"}
VALID_LANGS = {"en", "hi", "hinglish"}
MAX_CONTENT_LEN = 8000
MAX_THREAD_MESSAGES = 10   # keep last 10 turns; avoids eating the context window
_LLM_TIMEOUT = 60          # seconds before we give up waiting for the LLM


# ── Schemas ────────────────────────────────────────────────────────────────────

class MessageItem(BaseModel):
    role: str
    content: str


class CompanionChatRequest(BaseModel):
    # Full thread mode (preferred)
    messages: Optional[list[MessageItem]] = None
    # Legacy mode
    message: Optional[str] = None
    history: Optional[list[dict]] = None
    # Common
    companion: str = "friend"
    language: str = "hinglish"


# ── Helpers ────────────────────────────────────────────────────────────────────

def _sanitize(s: str) -> str:
    return s.replace("\x00", "").strip()[:MAX_CONTENT_LEN]


def _normalize_thread(raw: list[dict]) -> list[dict]:
    out = []
    for m in raw:
        role = m.get("role")
        if role not in ("user", "assistant"):
            continue
        content = _sanitize(str(m.get("content", "")))
        if not content:
            continue
        out.append({"role": role, "content": content})
    return out[-MAX_THREAD_MESSAGES:]


def _resolve_thread(body: CompanionChatRequest) -> list[dict]:
    if body.messages:
        return _normalize_thread([m.model_dump() for m in body.messages])
    # Legacy
    out = []
    for h in (body.history or []):
        role = "user" if h.get("role") == "user" or h.get("sender") == "user" else "assistant"
        text = _sanitize(str(h.get("content", h.get("text", ""))))
        if text:
            out.append({"role": role, "content": text})
    if body.message:
        out.append({"role": "user", "content": _sanitize(body.message)})
    return _normalize_thread(out)


# ── POST /api/companion/chat ───────────────────────────────────────────────────

@router.post("/chat")
async def companion_chat_stream(
    body: CompanionChatRequest,
    supabase_user: Annotated[SupabaseUser, Depends(get_supabase_user)],
):
    """SSE streaming companion chat. Requires Supabase JWT."""
    tone = body.companion if body.companion in VALID_COMPANIONS else "friend"
    lang = body.language if body.language in VALID_LANGS else "hinglish"

    thread = _resolve_thread(body)
    if not thread or thread[-1]["role"] != "user":
        raise HTTPException(
            status_code=400,
            detail='Invalid request: send messages as a non-empty array ending with role "user".',
        )

    last_user_text = thread[-1]["content"]

    # Crisis detection
    if detect_crisis(last_user_text):
        async def crisis_gen():
            yield f"data: {json.dumps({**HELPLINE_RESPONSE, 'crisis': True})}\n\n"
            yield f"data: {json.dumps({'done': True})}\n\n"
        return StreamingResponse(
            crisis_gen(),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )

    llm_messages = build_prompt_from_thread(thread=thread, tone=tone, language=lang)
    llm = get_llm_adapter()

    async def event_gen():
        try:
            async def _stream():
                parts = []
                async for delta in llm.stream_chat(llm_messages):
                    parts.append(delta)
                    yield delta

            async for delta in _stream():
                yield f"data: {json.dumps({'delta': delta, 'done': False})}\n\n"
        except asyncio.TimeoutError:
            logger.warning("[COMPANION] LLM stream timed out after %ss", _LLM_TIMEOUT)
            yield f"data: {json.dumps({'error': 'The reply took too long. Please try again.', 'done': True})}\n\n"
            return
        except Exception as err:
            logger.error(f"[COMPANION] LLM stream error: {err}")
            yield f"data: {json.dumps({'error': 'We could not finish the reply. Please try again in a moment.', 'stream_error': True, 'done': True})}\n\n"
            return
        yield f"data: {json.dumps({'delta': '', 'done': True})}\n\n"

    return StreamingResponse(
        event_gen(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
