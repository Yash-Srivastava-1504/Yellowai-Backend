"""
Manah Backend — Mock LLM Adapter
Returns fixed responses for testing without calling any real API.
"""
from typing import AsyncIterator

MOCK_REPLY = "Hey yaar, main samajh sakta hoon. Bata mujhe, kya chal raha hai? 💙"
MOCK_SUMMARY = "User shared some personal thoughts. Saathi listened with warmth."


class MockAdapter:
    async def chat(self, messages: list[dict]) -> str:
        # Check if it's a summarization prompt
        system = messages[0].get("content", "") if messages else ""
        if "memory summariser" in system.lower():
            return MOCK_SUMMARY
        return MOCK_REPLY

    async def stream_chat(self, messages: list[dict]) -> AsyncIterator[str]:
        words = MOCK_REPLY.split()
        import asyncio
        for word in words:
            yield word + " "
            await asyncio.sleep(0.05)
