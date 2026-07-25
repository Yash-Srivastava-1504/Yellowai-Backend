"""
ChatBot Platform — Chat v2 Router
POST /api/chat/stream — project-scoped SSE streaming chat.

Flow:
  1. Verify Supabase JWT → user_id
  2. Fetch project from Supabase (verify ownership)
  3. Fetch active system prompt for the project
  4. Build LLM message array: [system, ...thread]
  5. Stream deltas back via SSE (same protocol as original companion endpoint)
"""
import json
from typing import Annotated

import httpx
from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import StreamingResponse
from loguru import logger

from auth.middleware import SupabaseUser, get_supabase_user
from chat_v2.schemas import ChatRequest
from config import get_settings
from llm import get_llm_adapter
from services.prompt_builder import build_project_prompt

router = APIRouter(prefix="/api/chat", tags=["Chat"])

settings = get_settings()

MAX_THREAD_MESSAGES = 20  # keep last 20 turns; prevent context window overflow
MAX_CONTENT_LEN = 8000    # per-message character cap


# ── Supabase REST helpers (shared pattern with projects/router.py) ─────────────

def _supabase_headers() -> dict:
    key = settings.SUPABASE_SERVICE_ROLE_KEY or settings.SUPABASE_SECRET_KEY or ""
    if not key:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Server is missing Supabase service key configuration.",
        )
    return {
        "apikey": key,
        "Authorization": f"Bearer {key}",
        "Content-Type": "application/json",
    }


def _rest_url(path: str) -> str:
    base = (settings.SUPABASE_URL or "").rstrip("/")
    return f"{base}/rest/v1/{path}"


async def _fetch_project_prompt(project_id: str, user_id: str) -> str:
    """
    Verify that the project belongs to this user and return the active prompt content.
    Returns empty string if no prompt has been set (the LLM will still work without a system prompt).
    """
    async with httpx.AsyncClient() as client:
        # Verify project ownership
        proj_resp = await client.get(
            _rest_url("projects"),
            headers=_supabase_headers(),
            params={"id": f"eq.{project_id}", "select": "id,user_id,name"},
            timeout=8.0,
        )

    if proj_resp.status_code >= 400:
        logger.error(f"[Chat] Project fetch failed: {proj_resp.status_code} {proj_resp.text}")
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail="Could not load project.")

    projects = proj_resp.json()
    if not projects:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Project not found.")

    project = projects[0]
    if project["user_id"] != user_id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Access denied.")

    # Fetch active prompt
    async with httpx.AsyncClient() as client:
        prompt_resp = await client.get(
            _rest_url("prompts"),
            headers=_supabase_headers(),
            params={
                "project_id": f"eq.{project_id}",
                "is_active": "eq.true",
                "order": "created_at.desc",
                "limit": "1",
                "select": "content",
            },
            timeout=8.0,
        )

    if prompt_resp.status_code >= 400:
        logger.error(f"[Chat] Prompt fetch failed: {prompt_resp.status_code} {prompt_resp.text}")
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail="Could not load project prompt.")

    prompts = prompt_resp.json()
    return prompts[0]["content"] if prompts else ""


def _sanitize(s: str) -> str:
    return s.replace("\x00", "").strip()[:MAX_CONTENT_LEN]


def _normalize_thread(messages: list[dict]) -> list[dict]:
    out = []
    for m in messages:
        role = m.get("role")
        if role not in ("user", "assistant"):
            continue
        content = _sanitize(str(m.get("content", "")))
        if content:
            out.append({"role": role, "content": content})
    return out[-MAX_THREAD_MESSAGES:]


# ── POST /api/chat/stream ──────────────────────────────────────────────────────

@router.post("/stream")
async def stream_chat(
    body: ChatRequest,
    user: Annotated[SupabaseUser, Depends(get_supabase_user)],
):
    """
    SSE streaming chat endpoint. Requires Supabase JWT.
    The client sends the full thread; this endpoint is stateless (history stored in Supabase by the frontend).
    """
    thread = _normalize_thread([m.model_dump() for m in body.messages])
    if not thread or thread[-1]["role"] != "user":
        raise HTTPException(
            status_code=400,
            detail='Invalid request: messages must be a non-empty array ending with role "user".',
        )

    # Load project + active prompt (verifies ownership)
    system_prompt = await _fetch_project_prompt(body.project_id, user.id)

    # Build the LLM message array
    llm_messages = build_project_prompt(system_prompt=system_prompt, thread=thread)

    llm = get_llm_adapter()

    async def event_gen():
        try:
            async for delta in llm.stream_chat(llm_messages):
                yield f"data: {json.dumps({'delta': delta, 'done': False})}\n\n"
        except TimeoutError:
            logger.warning("[Chat/SSE] LLM stream timed out")
            yield f"data: {json.dumps({'error': 'The reply took too long. Please try again.', 'done': True})}\n\n"
            return
        except Exception as err:
            logger.error(f"[Chat/SSE] LLM stream error: {err}")
            yield f"data: {json.dumps({'error': 'AI service error. Please try again.', 'done': True})}\n\n"
            return
        yield f"data: {json.dumps({'delta': '', 'done': True})}\n\n"

    return StreamingResponse(
        event_gen(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
