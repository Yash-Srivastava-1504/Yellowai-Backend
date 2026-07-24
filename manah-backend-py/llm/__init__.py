"""
Manah Backend — LLM Adapters
Factory: returns Mock | OpenRouter | Qubrid based on environment.
"""
from config import get_settings


def get_llm_adapter():
    settings = get_settings()
    if settings.USE_MOCK_LLM:
        from llm.mock import MockAdapter
        return MockAdapter()
    if settings.openrouter_active:
        from llm.openrouter import OpenRouterAdapter
        return OpenRouterAdapter()
    from llm.qubrid import QubridAdapter
    return QubridAdapter()


def get_llm_provider_label() -> str:
    settings = get_settings()
    if settings.USE_MOCK_LLM:
        return "mock"
    if settings.openrouter_active:
        return f"openrouter:{settings.OPENROUTER_MODEL}"
    return f"qubrid:{settings.QUBRID_MODEL}"
