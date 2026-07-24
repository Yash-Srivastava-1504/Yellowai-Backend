# Manah Backend — FastAPI (Python)
# claude.md: Complete Project Documentation

## Table of Contents
1. [Project Overview](#1-project-overview)
2. [Architecture Diagram](#2-architecture-diagram)
3. [Technology Stack](#3-technology-stack)
4. [Directory Structure](#4-directory-structure)
5. [Module Deep-Dives](#5-module-deep-dives)
6. [API Reference](#6-api-reference)
7. [WebSocket Protocol](#7-websocket-protocol)
8. [Environment Variables](#8-environment-variables)
9. [Running the Project](#9-running-the-project)
10. [Key Design Decisions](#10-key-design-decisions)
11. [Known Gotchas](#11-known-gotchas)

---

## 1. Project Overview

**Manah** is an AI companion app for Indian Gen-Z. The AI persona is called **Saathi** — a warm, emotionally intelligent friend that listens without judgment.

This directory (`manah-backend-py/`) is a **Python/FastAPI** rewrite of the original Node.js/Express backend (`manah-backend/`). Both expose the **same REST API surface and WebSocket protocol**, so the existing React frontend (`manah-mindful-muse/`) works unchanged.

### Key Capabilities

| Feature | Details |
|---|---|
| **AI Persona** | Saathi — friend, didi (elder sister), or bhaiya (elder brother) |
| **Language** | Hinglish (default), English, Hindi |
| **Auth** | JWT (custom, SQLite) for chat; Supabase JWT (RS256/HS256) for companion |
| **Chat** | Sessions + message history + SSE streaming + WebSocket |
| **Companion** | Stateless SSE endpoint (Supabase JWT); full thread or legacy mode |
| **Mood** | Daily mood logging (0–4 scale) + date-range queries |
| **Memory** | Conversation summarization (background cron + on-demand) |
| **Crisis Detection** | Keyword matching → Indian helplines response (bypasses LLM) |
| **LLM** | OpenRouter / Qubrid / Mock (all OpenAI-compatible SDK) |
| **Database** | SQLite (built-in, WAL mode) via `aiosqlite` |

---

## 2. Architecture Diagram

```
Browser / React Frontend (manah-mindful-muse, port 5173)
    |
    ├── HTTP REST → FastAPI (main.py, port 3001)
    │       |
    │       ├── POST /api/auth/*        → auth/router.py
    │       ├── POST /api/chat/*        → chat/router.py
    │       ├── POST /api/companion/chat → companion/router.py (SSE)
    │       ├── POST/GET /api/mood      → mood/router.py
    │       ├── GET/PUT /api/settings   → settings/router.py
    │       ├── GET/PUT /api/user/me    → user/router.py
    │       └── GET /health
    │
    └── WebSocket ws:///ws/chat         → websocket/ws_chat.py
                |
                ├── Crisis check        → services/crisis.py
                ├── Prompt builder      → services/prompt_builder.py
                ├── LLM streaming       → llm/ (openrouter | qubrid | mock)
                └── Memory              → services/memory.py

Background (APScheduler, every 10 min):
    jobs/summarization.py → services/memory.run_summarization()

External Services:
    OpenRouter API  ← llm/openrouter.py  (if OPENROUTER_API_KEY set)
    Qubrid API      ← llm/qubrid.py      (fallback)
    Supabase JWKS   ← auth/middleware.py (for companion RS256 JWT)
    SQLite file     ← database.py        (./data/manah.db)
```

---

## 3. Technology Stack

| Layer | Technology | Details |
|---|---|---|
| Web Framework | FastAPI 0.110+ + Uvicorn | Async, OpenAPI docs at /docs |
| Database | SQLite via `aiosqlite` 0.20+ | WAL mode, FK ON, same schema as Node version |
| Auth (legacy) | `python-jose` + `passlib[bcrypt]` | HS256 JWT, bcrypt password hashing |
| Auth (companion) | `python-jose` + `httpx` JWKS fetch | Supabase RS256/ES256/HS256 JWT |
| LLM | `openai` SDK (OpenAI-compat) | Works with OpenRouter, Qubrid, mock |
| SSE | FastAPI `StreamingResponse` | `text/event-stream` |
| WebSocket | FastAPI built-in `WebSocket` | No extra library needed |
| Rate Limiting | `slowapi` | 100 req/min global |
| Scheduler | `apscheduler` 3.10+ | `AsyncIOScheduler`, cron `*/10 * * * *` |
| Config | `pydantic-settings` | Typed env vars, `.env` file support |
| CORS | FastAPI `CORSMiddleware` | Configurable via `CORS_ORIGINS` / `FRONTEND_URL` |

---

## 4. Directory Structure

```
manah-backend-py/
├── main.py                    # App factory, lifespan, middleware, router registration
├── config.py                  # pydantic-settings Settings class
├── database.py                # SQLite init + async aiosqlite get_db() dependency
├── requirements.txt
├── .env.example
│
├── auth/
│   ├── router.py              # POST /api/auth/signup, login, refresh, logout
│   ├── schemas.py             # Pydantic request/response models
│   ├── service.py             # hash, JWT, DB helpers
│   └── middleware.py          # get_current_user(), get_supabase_user() Depends()
│
├── chat/
│   ├── router.py              # POST /session, GET /sessions, GET /history, POST /message, GET /stream, POST /summarize
│   └── schemas.py
│
├── companion/
│   └── router.py              # POST /api/companion/chat (SSE, Supabase JWT)
│
├── mood/
│   └── router.py              # POST /api/mood, GET /api/mood
│
├── settings/
│   └── router.py              # GET /api/settings, PUT /api/settings
│
├── user/
│   └── router.py              # GET /api/user/me, PUT /api/user/me, DELETE /api/user/account
│
├── llm/
│   ├── __init__.py            # get_llm_adapter() factory
│   ├── openrouter.py          # OpenAI-compat → openrouter.ai
│   ├── qubrid.py              # OpenAI-compat → platform.qubrid.com
│   └── mock.py                # Fixed responses for testing
│
├── services/
│   ├── crisis.py              # detect_crisis() + HELPLINE_RESPONSE
│   ├── memory.py              # get_memory, save_memory, should_summarize, run_summarization
│   └── prompt_builder.py      # BASE_SYSTEM_PROMPT, PERSONA_PROMPTS, build_prompt(), etc.
│
├── jobs/
│   └── summarization.py       # APScheduler cron every 10 min
│
└── websocket/
    └── ws_chat.py             # /ws/chat WebSocket endpoint
```

---

## 5. Module Deep-Dives

### 5.1 `auth/middleware.py` — JWT Dependencies

Two FastAPI `Depends()` factories:

- **`get_current_user()`** — Verifies JWT from `Authorization: Bearer <token>` header or `accessToken` cookie. Returns `CurrentUser(id, email)`. Used by all legacy SQLite auth routes (chat, mood, settings, user).

- **`get_supabase_user()`** — Verifies Supabase Auth JWT:
  - **HS256**: Uses `SUPABASE_JWT_SECRET` env var (legacy projects)
  - **RS256/ES256**: Fetches JWKS from `{iss}/.well-known/jwks.json` (current Supabase projects — no secret required)
  
  Returns `SupabaseUser(id: str uuid, email: Optional[str])`. Used by companion router only.

### 5.2 `services/prompt_builder.py` — Saathi Prompt Engine

Three exported functions:

| Function | Used By | Description |
|---|---|---|
| `build_prompt()` | chat/router.py, websocket/ws_chat.py | Legacy chat: history[] + message → messages array |
| `build_prompt_from_thread()` | companion/router.py | Full thread mode: [{role, content}] → messages array |
| `build_summarization_prompt()` | services/memory.py | Memory summarization prompt |

System prompt layers: `BASE_SYSTEM_PROMPT` → `PERSONA_PROMPTS[tone]` → language instruction → optional memory injection.

### 5.3 `services/crisis.py` — Crisis Detection

`detect_crisis(message)` checks 14 English crisis keywords (case-insensitive substring match). If triggered:
- REST route returns `HELPLINE_RESPONSE` JSON (3 Indian helplines)
- WebSocket sends `HELPLINE_RESPONSE` frame
- Companion SSE yields `HELPLINE_RESPONSE` event + `done: true`

**Bypasses the LLM entirely** — a critical safety feature.

### 5.4 `services/memory.py` — Conversation Memory

Summarization is triggered when a session accumulates ≥ 5 new user messages since the last summary (`MESSAGES_PER_SUMMARY = 5`). The summary is stored in the `memory` table (one row per user, upserted).

Background flow: LLM receives last 20 messages → `build_summarization_prompt()` → LLM response → stored in DB. On next chat request, memory is injected into the system prompt.

### 5.5 `llm/__init__.py` — Adapter Selection

```
USE_MOCK_LLM=true          → MockAdapter (tests)
OPENROUTER_API_KEY=<valid> → OpenRouterAdapter
(default)                  → QubridAdapter
```

All adapters expose: `async chat(messages) -> str` and `async stream_chat(messages) -> AsyncIterator[str]`.

Retry policy: 3 attempts with exponential backoff (0.5s, 1s, 2s) on HTTP 429 or 503.

### 5.6 `database.py` — SQLite Layer

`init_db()` — synchronous one-time init called at startup:
- Creates `./data/` directory if needed
- Opens SQLite, sets WAL mode + FK enforcement
- Executes all `CREATE TABLE IF NOT EXISTS` (8 tables)

`get_db()` — async FastAPI `Depends()`:
- Opens an `aiosqlite.Connection` per request
- Sets `row_factory = aiosqlite.Row` for dict-like access
- Auto-commits on success, rollbacks on exception

---

## 6. API Reference

### Auth

| Method | Path | Auth | Description |
|---|---|---|---|
| POST | `/api/auth/signup` | — | Register new user |
| POST | `/api/auth/login` | — | Login with email + password |
| POST | `/api/auth/refresh` | — | Get new access token via refresh token |
| POST | `/api/auth/logout` | — | Revoke refresh token |

### Chat (requires Bearer JWT)

| Method | Path | Description |
|---|---|---|
| POST | `/api/chat/session` | Create new session |
| GET | `/api/chat/sessions` | List user sessions |
| GET | `/api/chat/history?sessionId=X` | Message history |
| POST | `/api/chat/message` | Send message (full reply, crisis check) |
| GET | `/api/chat/stream?sessionId=X&message=Y` | SSE streaming reply |
| POST | `/api/chat/summarize` | On-demand summarization |

### Companion (requires Supabase Bearer JWT)

| Method | Path | Description |
|---|---|---|
| POST | `/api/companion/chat` | SSE streaming, stateless, full thread or legacy mode |

**Body (preferred):**
```json
{
  "messages": [{"role": "user", "content": "..."}, ...],
  "companion": "friend",
  "language": "hinglish"
}
```

### Mood (requires Bearer JWT)

| Method | Path | Description |
|---|---|---|
| POST | `/api/mood` | Log mood (upsert, one per day) |
| GET | `/api/mood` | Last 30 days (or `?start=YYYY-MM-DD&end=YYYY-MM-DD`) |

### Settings + User (requires Bearer JWT)

| Method | Path | Description |
|---|---|---|
| GET | `/api/settings` | Get user settings |
| PUT | `/api/settings` | Update settings |
| GET | `/api/user/me` | Get profile |
| PUT | `/api/user/me` | Update profile |
| DELETE | `/api/user/account` | Delete account (cascade) |

### System

| Method | Path | Description |
|---|---|---|
| GET | `/health` | Health check |
| GET | `/docs` | OpenAPI Swagger UI |
| GET | `/redoc` | ReDoc UI |

---

## 7. WebSocket Protocol

**Endpoint**: `ws://localhost:3001/ws/chat`

**Auth**: JWT via `?token=<jwt>` query param OR `accessToken` cookie.

**Message format** (JSON frames):

```
CLIENT → SERVER:
  { "sessionId": 42, "message": "Haan yaar..." }

SERVER → CLIENT (streaming):
  { "delta": "...", "done": false }   (chunk)
  { "delta": "", "done": true }       (final frame)

SERVER → CLIENT (error):
  { "error": "..." }

SERVER → CLIENT (crisis):
  { "crisis": true, "reply": "...", "helplines": [...] }
```

---

## 8. Environment Variables

| Variable | Default | Description |
|---|---|---|
| `PORT` | 3001 | Server port |
| `NODE_ENV` | development | production = secure cookies + HSTS |
| `SUPABASE_JWT_SECRET` | — | HS256 Supabase secret (legacy projects only) |
| `JWT_SECRET` | — | **Required** — access token signing key |
| `JWT_REFRESH_SECRET` | — | **Required** — refresh token signing key |
| `JWT_EXPIRES_IN` | 3600 | Access token TTL (seconds) |
| `JWT_REFRESH_EXPIRES_IN` | 2592000 | Refresh token TTL (seconds, 30 days) |
| `DB_PATH` | ./data/manah.db | SQLite file path |
| `OPENROUTER_API_KEY` | — | OpenRouter key (activates OpenRouter adapter) |
| `OPENROUTER_MODEL` | google/gemini-2.5-flash | Model name |
| `OPENROUTER_BASE_URL` | https://openrouter.ai/api/v1 | API base URL |
| `QUBRID_API_KEY` | — | Qubrid key (fallback adapter) |
| `QUBRID_MODEL` | google/gemini-2.5-flash | Model name |
| `USE_MOCK_LLM` | false | true = use mock adapter (for tests) |
| `FRONTEND_URL` | http://localhost:5173 | Single CORS origin |
| `CORS_ORIGINS` | — | Comma-separated list (overrides FRONTEND_URL) |

---

## 9. Running the Project

```powershell
# 1. Navigate to the Python backend
cd manah-backend-py

# 2. Create and activate virtual environment
python -m venv .venv
.\.venv\Scripts\Activate.ps1

# 3. Install dependencies
pip install -r requirements.txt

# 4. Copy and fill env vars
copy .env.example .env
# Edit .env: set JWT_SECRET, JWT_REFRESH_SECRET, and LLM keys

# 5. Start the server
uvicorn main:app --reload --port 3001

# Or directly:
python main.py
```

**API docs**: http://localhost:3001/docs

**Start the frontend** (separate terminal):
```powershell
cd manah-mindful-muse
npm run dev
```

---

## 10. Key Design Decisions

### Why FastAPI over Flask?
FastAPI provides native async support, automatic OpenAPI docs, Pydantic v2 validation, and WebSocket support out of the box — all needed for streaming, WebSocket, and type-safe API development.

### Why `aiosqlite` over SQLAlchemy?
The Node.js backend used raw SQL (`node:sqlite`). `aiosqlite` provides the same raw SQL approach but async. SQLAlchemy ORM would add significant complexity for no gain in a simple single-DB app.

### Why APScheduler over `asyncio.create_task` loop?
APScheduler handles crash recovery, scheduling edge cases, and provides a clean API. Using `create_task` with `asyncio.sleep` is fragile if the task throws.

### Why keep the same SQLite schema?
The existing frontend and the Node backend share the same SQLite DB. Keeping the identical schema means zero migration needed when switching backends.

### Why `asyncio.ensure_future` for background tasks?
Summarization should not block the HTTP response. FastAPI's `BackgroundTasks` is scoped to the request lifecycle, but we need the DB connection to outlive the request for `_save_assistant_reply` (SSE streaming case). `ensure_future` with a fresh connection is the correct pattern here.

---

## 11. Known Gotchas

### `aiosqlite.Row` field access
`aiosqlite.Row` objects support both dict-style `row["field"]` and index-style access. **Always** call `dict(row)` before passing to Pydantic models to avoid validation errors.

### SSE streaming + DB connection lifecycle
The SSE `event_gen()` generator function outlives the FastAPI request handling. The `get_db()` dependency connection is **not** available inside `event_gen()`. Use `asyncio.ensure_future(_save_assistant_reply(...))` with a fresh `aiosqlite.connect(DB_PATH)` for post-stream persistence.

### Supabase JWKS caching
`auth/middleware.py` fetches JWKS on every Supabase JWT verification. For production, cache the JWKS response (e.g., `httpx` with response caching or `cachetools`).

### First startup — no `data/` directory
`database.py` creates `./data/` automatically. If running from a different CWD, set `DB_PATH` in `.env` to an absolute path.

### Mock adapter for CI/testing
Set `USE_MOCK_LLM=true` in your test `.env` to avoid API calls in tests. The mock adapter returns a fixed Hinglish reply and summary string.

### Rate limiter uses in-memory store
`slowapi` uses an in-memory counter by default. For multi-worker deployments, configure a Redis backend.
