# AgentForge — Architecture

## Entity Diagram

```text
                              ┌─────────────┐
                              │ auth.users  │  (Supabase Auth)
                              └──────┬──────┘
                                     │ 1:1
                                     ▼
                              ┌─────────────┐
                              │  profiles   │  (display_name, theme)
                              └──────┬──────┘
                                     │ 1:N
                                     ▼
                              ┌─────────────┐
                              │  projects   │  (id, name, desc)
                              └──────┬──────┘
                                     │ 1:N
        ┌────────────────────────────┼────────────────────────────┐
        ▼                            ▼                            ▼
 ┌─────────────┐              ┌─────────────┐              ┌─────────────┐
 │   prompts   │              │conversations│              │project_files│
 │ (versioned) │              │project_id FK│              │project_id FK│
 │  is_active  │              └──────┬──────┘              └─────────────┘
 └─────────────┘                     │ 1:N
                                     ▼
                              ┌─────────────┐
                              │  messages   │
                              │role, content│
                              └─────────────┘
```

**Relationships:**
- A `User` owns many `Projects`.
- A `Project` has many `Prompts` (version history). At most one has `is_active = true`.
- A `Project` has many `Project_Files` (knowledge base documents stored in Supabase Storage).
- A `Project` has many `Conversations` (one per chat session, currently one active thread per project).
- A `Conversation` has many `Messages` (role: `user` | `assistant`, content, timestamp).

---

## Non-Functional Requirements

### Scalability
**Decision: Stateless backend + Supabase managed database.**

The FastAPI backend is fully stateless — no in-memory session state, no sticky sessions. All persistent state lives in Supabase (PostgreSQL). This means the backend can be horizontally scaled behind a load balancer without coordination. Each request validates the Supabase JWT independently (JWKS keys are cached in-process for 5 minutes to reduce external calls). The LLM adapter is also stateless — each request opens a new streaming connection to OpenRouter.

### Security
**Decision: Supabase Row Level Security (RLS) as the primary access control layer.**

Every table — `projects`, `prompts`, `conversations`, `messages` — has RLS policies that scope reads and writes strictly through `auth.uid() = user_id` (or through a JOIN to `projects.user_id` for nested tables). This means even if application-level checks were bypassed, the database would refuse to return or modify another user's data. The backend additionally validates Supabase JWTs on every request using `get_supabase_user()` (JWT signature verification via JWKS or shared secret), rejecting expired or malformed tokens with HTTP 401 before any database access.

### Extensibility
**Decision: Prompt versioning and Modular Knowledge Base.**

Rather than storing one system prompt per project and overwriting it, each prompt update inserts a new `prompts` row and deactivates previous ones. This means prompt history is always preserved. Additionally, we implemented a custom Knowledge Base (File Upload) system using Supabase Storage and `PyPDF2` on the backend, rather than relying on OpenAI's expensive Files API. This fulfills the assignment's "Good to have" requirement securely at $0 cost, and the `build_project_prompt()` function elegantly combines the system prompt with extracted file text before hitting the LLM.

### Performance
**Decision: Server-Sent Events (SSE) for streaming LLM responses.**

Rather than waiting for the full LLM response before returning it to the client, the backend streams token deltas as SSE events (`data: {"delta": "...", "done": false}`). The client renders tokens as they arrive, achieving a perceived latency of ~300–800ms to first token vs. 5–15s for a full response. The `OpenRouterAdapter` already includes a `_with_retry` mechanism with exponential backoff for 429 (rate limit) and 503 (service unavailable) errors, and a 90-second wall-clock timeout guard on the stream iteration.

### Reliability
**Decision: Retry/backoff in the LLM adapter + rate limiting at the API gateway level.**

The `OpenRouterAdapter._with_retry()` method retries up to 3 times with exponential backoff (0.5s, 1s, 2s) on retryable HTTP errors (429, 503, ECONNRESET). Non-retryable errors (400, 401, 404) are propagated immediately. At the API level, `slowapi` enforces a 100 requests/minute limit per IP address, protecting the backend from abuse. Global exception handling in `main.py` catches any unhandled exception and returns a structured `{"error": "Internal server error"}` JSON response with a 500 status, avoiding stack trace leakage to clients.

---

## Data Flow: Chat Request

```text
 Client (React)
   │
   │  POST /api/chat/stream
   │  Authorization: Bearer <supabase_jwt>
   │  Body: { project_id, messages: [{role, content}] }
   │
   ▼
 FastAPI (chat_v2/router.py)
   │
   ├─ get_supabase_user()  ──> verify JWT (JWKS/HS256)
   │
   ├─ _fetch_project_prompt(project_id, user_id)
   │    ├─ Supabase REST: verify project.user_id == auth user
   │    └─ Supabase REST: fetch active prompt content
   │
   ├─ _fetch_project_files(project_id)
   │    └─ Supabase REST: fetch extracted text from all project files
   │
   ├─ build_project_prompt(system_prompt, thread, project_files)
   │    └─ [{role:system, content:prompt+files}, ...messages]
   │
   ├─ llm.stream_chat(messages)  ──>  OpenRouter API (Gemini)
   │
   └─ StreamingResponse (SSE)
        │
        └─ yield "data: {delta, done}" per token
             │
             ▼
        Client renders tokens live
        Saves final reply to Supabase (messages table)
```

---

## Security Boundary

```text
 ┌────────────────────────────────────────────┐
 │                  Browser                   │
 │  • Supabase anon key (public — safe)       │
 │  • VITE_SUPABASE_URL (public — safe)       │
 │  • Supabase Auth session / JWT             │
 │  • Never sees OpenRouter API key           │
 └─────────────────────┬──────────────────────┘
                       │ HTTPS + Bearer JWT
                       ▼
 ┌────────────────────────────────────────────┐
 │               FastAPI Backend              │
 │  • Holds OPENROUTER_API_KEY (server-only)  │
 │  • Holds SUPABASE_SERVICE_ROLE_KEY         │
 │  • Validates JWT before every request      │
 │  • Proxies LLM calls — key never exposed   │
 └─────────────────────┬──────────────────────┘
                       │
             ┌─────────┴─────────┐
             ▼                   ▼
      OpenRouter API     Supabase REST API
      (LLM provider)    (service role key)
```
