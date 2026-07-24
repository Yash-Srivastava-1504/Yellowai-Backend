"""
Manah Backend — Configuration
All environment variables loaded via pydantic-settings.
"""
from functools import lru_cache
from typing import Optional

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # ── Server ─────────────────────────────────────────────────────────────────
    PORT: int = 3001
    NODE_ENV: str = "development"

    # ── Supabase JWT ───────────────────────────────────────────────────────────
    SUPABASE_URL: Optional[str] = None
    SUPABASE_PUBLISHABLE_KEY: Optional[str] = None
    SUPABASE_SECRET_KEY: Optional[str] = None
    SUPABASE_JWKS_URL: Optional[str] = None   # explicit override; auto-derived from URL if absent
    SUPABASE_JWT_SECRET: Optional[str] = None  # only for legacy HS256 projects

    # ── JWT (legacy SQLite auth + WebSocket) ──────────────────────────────────
    JWT_SECRET: str = "change_this_to_a_long_random_secret"
    JWT_REFRESH_SECRET: str = "change_this_too_separate_secret"
    JWT_EXPIRES_IN: int = 3600          # seconds (1 hour)
    JWT_REFRESH_EXPIRES_IN: int = 2592000  # seconds (30 days)

    # ── Database ───────────────────────────────────────────────────────────────
    DB_PATH: str = "./data/manah.db"

    # ── OpenRouter ─────────────────────────────────────────────────────────────
    OPENROUTER_API_KEY: Optional[str] = None
    OPENROUTER_BASE_URL: str = "https://openrouter.ai/api/v1"
    OPENROUTER_MODEL: str = "google/gemini-2.5-flash"
    OPENROUTER_HTTP_REFERER: str = "http://localhost:5173"
    OPENROUTER_APP_TITLE: str = "Manah"

    # ── Qubrid ─────────────────────────────────────────────────────────────────
    QUBRID_API_KEY: Optional[str] = None
    QUBRID_BASE_URL: str = "https://platform.qubrid.com/v1"
    QUBRID_MODEL: str = "google/gemini-2.5-flash"

    # ── LLM ────────────────────────────────────────────────────────────────────
    USE_MOCK_LLM: bool = False

    # ── CORS ───────────────────────────────────────────────────────────────────
    FRONTEND_URL: str = "http://localhost:5173"
    CORS_ORIGINS: Optional[str] = None  # comma-separated override

    @property
    def cors_allowed_origins(self) -> list[str]:
        if self.CORS_ORIGINS:
            return [o.strip() for o in self.CORS_ORIGINS.split(",") if o.strip()]
        defaults = {
            "http://localhost:5173",
            "http://localhost:8080",
            "http://127.0.0.1:5173",
            "http://127.0.0.1:8080",
        }
        if self.FRONTEND_URL:
            defaults.add(self.FRONTEND_URL.strip())
        return list(defaults)

    @property
    def is_production(self) -> bool:
        return self.NODE_ENV == "production"

    @property
    def openrouter_active(self) -> bool:
        key = (self.OPENROUTER_API_KEY or "").strip()
        return bool(key) and not key.startswith("your_") and key != "missing-key"


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
