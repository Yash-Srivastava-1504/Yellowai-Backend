"""
Manah Backend — OpenRouter LLM Adapter
Uses the OpenAI-compatible SDK pointed at openrouter.ai.
"""
import asyncio
from typing import AsyncIterator

from openai import AsyncOpenAI

from config import get_settings

settings = get_settings()

_default_headers = {}
if settings.OPENROUTER_HTTP_REFERER:
    _default_headers["HTTP-Referer"] = settings.OPENROUTER_HTTP_REFERER
if settings.OPENROUTER_APP_TITLE:
    _default_headers["X-Title"] = settings.OPENROUTER_APP_TITLE

# Generous limits — system prompt alone is ~800 tokens
_MAX_OUTPUT_TOKENS = 2048
_STREAM_TIMEOUT_SECS = 90   # total wall-clock time for one streaming call


class OpenRouterAdapter:
    def __init__(self):
        self._client = AsyncOpenAI(
            base_url=settings.OPENROUTER_BASE_URL,
            api_key=settings.OPENROUTER_API_KEY or "missing-key",
            default_headers=_default_headers or None,
            timeout=60.0,  # per-request HTTP timeout
        )
        self._model = settings.OPENROUTER_MODEL

    async def _with_retry(self, fn, retries: int = 3):
        for attempt in range(retries + 1):
            try:
                return await fn()
            except Exception as err:
                status = getattr(err, "status_code", None)
                is_retryable = status in (429, 503) or "ECONNRESET" in str(err)
                if not is_retryable or attempt == retries:
                    raise
                delay = (2 ** attempt) * 0.5
                print(f"[OpenRouter] Attempt {attempt + 1} failed ({status}). Retrying in {delay}s…")
                await asyncio.sleep(delay)

    async def chat(self, messages: list[dict]) -> str:
        response = await self._with_retry(
            lambda: self._client.chat.completions.create(
                model=self._model,
                messages=messages,
                max_tokens=_MAX_OUTPUT_TOKENS,
                temperature=0.75,
            )
        )
        return response.choices[0].message.content

    async def stream_chat(self, messages: list[dict]) -> AsyncIterator[str]:
        stream = await self._with_retry(
            lambda: self._client.chat.completions.create(
                model=self._model,
                messages=messages,
                max_tokens=_MAX_OUTPUT_TOKENS,
                temperature=0.75,
                stream=True,
            )
        )
        # Yield individual text deltas with a per-chunk timeout guard
        async def _iter():
            async for chunk in stream:
                delta = chunk.choices[0].delta.content
                if delta:
                    yield delta

        # Wrap the entire iteration in a wall-clock timeout
        gen = _iter()
        try:
            while True:
                try:
                    delta = await asyncio.wait_for(gen.__anext__(), timeout=_STREAM_TIMEOUT_SECS)
                    yield delta
                except StopAsyncIteration:
                    break
        finally:
            await gen.aclose()
