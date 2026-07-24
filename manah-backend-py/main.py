"""
Manah Backend — FastAPI Application
Port of manah-backend (Node.js/Express) to Python/FastAPI.

Startup: uvicorn main:app --reload --port 3001
"""
import os
import time
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from loguru import logger
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from slowapi.util import get_remote_address

from config import get_settings
from database import init_db
from llm import get_llm_provider_label

settings = get_settings()

# ── Rate limiters ──────────────────────────────────────────────────────────────
limiter = Limiter(key_func=get_remote_address, default_limits=["100/minute"])


# ── Lifespan ───────────────────────────────────────────────────────────────────
@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("🌿 Manah Backend starting up (FastAPI)…")

    # Init SQLite (sync, one-time schema creation)
    init_db()
    logger.success("✓ Database ready")

    # Start background summarization scheduler
    from jobs.summarization import start_summarization_job
    scheduler = start_summarization_job()

    llm_label = "🧪 MOCK" if settings.USE_MOCK_LLM else f"✨ {get_llm_provider_label()}"
    logger.info(f"🤖 LLM: {llm_label}")
    logger.info(f"🔐 CORS origins: {settings.cors_allowed_origins}")
    logger.info(f"💬 Companion API (Supabase JWT): POST /api/companion/chat")
    logger.info(f"🔌 WebSocket (legacy SQLite chat): ws://localhost:{settings.PORT}/ws/chat")
    logger.success(f"🚀 Manah Backend running on http://localhost:{settings.PORT}")

    yield

    logger.info("Manah Backend shutting down…")
    scheduler.shutdown(wait=False)


# ── App factory ────────────────────────────────────────────────────────────────
app = FastAPI(
    title="Manah API",
    description="Manah AI Companion — Saathi for Indian Gen-Z. Python/FastAPI backend.",
    version="2.0.0",
    docs_url="/docs",
    redoc_url="/redoc",
    lifespan=lifespan,
)

# ── Rate limiting ──────────────────────────────────────────────────────────────
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

# ── CORS ───────────────────────────────────────────────────────────────────────
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_allowed_origins,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
    allow_headers=["Content-Type", "Authorization"],
)


# ── Security headers middleware (helmet equivalent) ───────────────────────────
@app.middleware("http")
async def security_headers(request: Request, call_next):
    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["X-XSS-Protection"] = "1; mode=block"
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    if settings.is_production:
        response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
    return response


# ── Request timing middleware ──────────────────────────────────────────────────
@app.middleware("http")
async def timing_middleware(request: Request, call_next):
    start = time.monotonic()
    response = await call_next(request)
    elapsed_ms = int((time.monotonic() - start) * 1000)
    response.headers["X-Response-Time-Ms"] = str(elapsed_ms)
    return response


# ── Global exception handler ───────────────────────────────────────────────────
@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    logger.error(f"[ERROR] Unhandled exception: {exc}", exc_info=True)
    return JSONResponse(
        status_code=500,
        content={"error": "Internal server error"},
    )


# ── Routers ────────────────────────────────────────────────────────────────────
from auth.router import router as auth_router
from chat.router import router as chat_router
from companion.router import router as companion_router
from mood.router import router as mood_router
from settings.router import router as settings_router
from user.router import router as user_router
from websocket.ws_chat import router as ws_router

app.include_router(auth_router)
app.include_router(chat_router)
app.include_router(companion_router)
app.include_router(mood_router)
app.include_router(settings_router)
app.include_router(user_router)
app.include_router(ws_router)


# ── Health check ───────────────────────────────────────────────────────────────
@app.get("/health", tags=["System"])
async def health():
    return {
        "status": "ok",
        "service": "manah-backend-py",
        "timestamp": __import__("datetime").datetime.utcnow().isoformat() + "Z",
        "version": "2.0.0",
    }


# ── Entry point ────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "main:app",
        host="0.0.0.0",
        port=settings.PORT,
        reload=not settings.is_production,
        log_level="info",
    )
