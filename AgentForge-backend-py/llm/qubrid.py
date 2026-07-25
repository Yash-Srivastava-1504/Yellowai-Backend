"""
Manah Backend — Qubrid LLM Adapter
Same interface as OpenRouterAdapter, pointed at Qubrid endpoint.
"""
import asyncio
from typing import AsyncIterator

from openai import AsyncOpenAI

from config import get_settings

settings = get_settings()


class QubridAdapter:
    def __init__(self):
        self._client = AsyncOpenAI(
            base_url=settings.QUBRID_BASE_URL,
            api_key=settings.QUBRID_API_KEY or "missing-key",
        )
        self._model = settings.QUBRID_MODEL

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
                print(f"[QUBRID] Attempt {attempt + 1} failed ({status}). Retrying in {delay}s…")
                await asyncio.sleep(delay)

    async def chat(self, messages: list[dict]) -> str:
        response = await self._with_retry(
            lambda: self._client.chat.completions.create(
                model=self._model,
                messages=messages,
                max_tokens=512,
                temperature=0.75,
            )
        )
        return response.choices[0].message.content

    async def stream_chat(self, messages: list[dict]) -> AsyncIterator[str]:
        stream = await self._with_retry(
            lambda: self._client.chat.completions.create(
                model=self._model,
                messages=messages,
                max_tokens=512,
                temperature=0.75,
                stream=True,
            )
        )
        async for chunk in stream:
            delta = chunk.choices[0].delta.content
            if delta:
                yield delta
