# AgentForge — Multi-User AI Agent Platform

AgentForge is a full-stack chatbot platform where users can create their own custom AI agents, give each one a system prompt that defines its behavior, and chat with it via a real-time streaming interface.

Built as a take-home assignment for an AI Intern role. Adapted from an existing working codebase.

---

## Features

- **Authentication** — Email/password registration and login via [Supabase Auth](https://supabase.com/auth). JWTs issued by Supabase are validated on the backend using JWKS (RS256) or a shared secret (HS256).
- **Project/Agent Management** — Create, edit, and delete AI agents. Each agent has a name, description, and system prompt.
- **Knowledge Base (File Uploads)** — Upload PDF, TXT, or CSV files to an agent. The backend parses the files and injects the extracted text into the agent's context, providing a $0 alternative to the OpenAI Files API.
- **System Prompts** — Each agent has a versioned prompt history. The backend always loads the most recent active prompt as the LLM's system message.
- **Streaming Chat** — Responses stream token-by-token via Server-Sent Events (SSE). The conversation history is persisted in Supabase and loaded on every page visit.
- **Row Level Security** — All Supabase tables enforce RLS policies so users can never access each other's agents, prompts, or conversations.
- **Rate Limiting** — `slowapi` limits requests at 100/minute per IP.
- **Security Headers** — `X-Content-Type-Options`, `X-Frame-Options`, HSTS in production.

---

## Tech Stack

| Layer | Technology |
|---|---|
| Frontend | React 18, TypeScript, Vite, Tailwind CSS, Shadcn UI |
| Backend | Python 3.11+, FastAPI, Uvicorn |
| AI / LLM | Google Gemini 2.5 Flash via [OpenRouter](https://openrouter.ai) |
| Auth / DB | [Supabase](https://supabase.com) (PostgreSQL + Auth) |
| Streaming | Server-Sent Events (SSE) via `sse-starlette` / `StreamingResponse` |
| Rate Limiting | `slowapi` |

---

## Project Structure

```
Frontend-Yellowai/manah-mindful-muse/     # React frontend
  src/
    pages/
      LandingPage.tsx       # Marketing / home page
      AuthPage.tsx          # Login / register
      ProjectsPage.tsx      # "My Agents" dashboard
      CreateEditProjectPage.tsx  # Create/edit agent form
      ChatPage.tsx          # Project-scoped streaming chat
      SettingsPage.tsx      # Account settings
    components/
      DashboardLayout.tsx   # Sidebar + nav
      AuthRoutes.tsx        # Protected route wrapper
    lib/
      supabase.ts           # Supabase client init
      chatApi.ts            # SSE streaming client
      userData.ts           # Supabase data helpers (projects, prompts, conversations)
      database.types.ts     # TypeScript types for DB rows
    contexts/
      AuthContext.tsx       # Auth state + Supabase session
  supabase/
    setup.sql                         # Base schema (profiles, auth trigger)
    projects-prompts-migration.sql    # projects, prompts, conversations.project_id
    project-files-migration.sql       # New: project_files table and storage bucket

Backend-Yellowai/Manah_AI_Companion/manah-backend-py/     # FastAPI backend
  main.py           # App factory, routers, middleware
  config.py         # Settings via pydantic-settings
  auth/
    middleware.py   # Supabase JWT verification (JWKS RS256 + HS256 fallback)
    router.py       # Legacy auth endpoints (kept)
  projects/
    router.py       # CRUD for projects + prompts (Supabase service role)
    schemas.py      # Pydantic models
  chat_v2/
    router.py       # POST /api/chat/stream — project-scoped SSE chat
    schemas.py      # ChatRequest schema
  llm/
    openrouter.py   # OpenRouter adapter (OpenAI SDK + retry/backoff)
    qubrid.py       # Qubrid fallback adapter
    mock.py         # Mock adapter for testing
  services/
    prompt_builder.py  # build_project_prompt() — injects system prompt
```

---

## Setup & Run

### Prerequisites

- Node.js 18+ and npm
- Python 3.11+
- A [Supabase](https://supabase.com) project
- An [OpenRouter](https://openrouter.ai) API key

### 1. Supabase: Run Migrations

In your Supabase project → SQL Editor, run these in order:

1. `supabase/setup.sql` — creates `profiles` table and auth trigger
2. `supabase/projects-prompts-migration.sql` — creates `projects`, `prompts`, adds `project_id` to `conversations`
3. `supabase/project-files-migration.sql` — creates `project_files` table and Supabase Storage bucket

### 2. Backend Setup

```bash
cd Backend-Yellowai/Manah_AI_Companion/manah-backend-py

# Install dependencies
pip install -r requirements.txt

# Configure environment
cp .env.example .env
# Fill in: SUPABASE_URL, SUPABASE_JWT_SECRET, SUPABASE_SERVICE_ROLE_KEY, OPENROUTER_API_KEY

# Run the server
uvicorn main:app --reload --port 3001
```

The API will be available at `http://localhost:3001`.  
Swagger docs: `http://localhost:3001/docs`

### 3. Frontend Setup

```bash
cd Frontend-Yellowai/manah-mindful-muse

# Install dependencies
npm install

# Configure environment
cp .env.example .env
# Fill in: VITE_SUPABASE_URL, VITE_SUPABASE_ANON_KEY, VITE_API_URL=http://localhost:3001

# Run the dev server
npm run dev
```

The app will be available at `http://localhost:5173`.

---

## Environment Variables

### Backend (`.env`)

| Variable | Required | Description |
|---|---|---|
| `PORT` | No | Server port (default: 3001) |
| `SUPABASE_URL` | Yes | Your Supabase project URL |
| `SUPABASE_JWT_SECRET` | Conditional | JWT secret for HS256 projects |
| `SUPABASE_SERVICE_ROLE_KEY` | Yes | Service role key for server-side DB access |
| `OPENROUTER_API_KEY` | Yes | OpenRouter API key |
| `OPENROUTER_MODEL` | No | Model ID (default: `google/gemini-2.5-flash`) |
| `FRONTEND_URL` | No | Allowed CORS origin |
| `USE_MOCK_LLM` | No | `true` to skip LLM calls (testing) |

### Frontend (`.env`)

| Variable | Required | Description |
|---|---|---|
| `VITE_SUPABASE_URL` | Yes | Your Supabase project URL |
| `VITE_SUPABASE_ANON_KEY` | Yes | Supabase `anon` public key |
| `VITE_API_URL` | Yes | Backend URL (e.g. `http://localhost:3001`) |

---

## API Endpoints

| Method | Path | Description |
|---|---|---|
| `GET` | `/health` | Health check |
| `GET` | `/api/projects` | List user's agents |
| `POST` | `/api/projects` | Create a new agent |
| `GET` | `/api/projects/{id}` | Get agent detail + active prompt |
| `PUT` | `/api/projects/{id}` | Update agent name/description |
| `DELETE` | `/api/projects/{id}` | Delete agent (cascades) |
| `POST` | `/api/projects/{id}/prompt` | Set/update active system prompt |
| `POST` | `/api/projects/{id}/files` | Upload a file to agent's knowledge base |
| `GET` | `/api/projects/{id}/files` | List uploaded files |
| `DELETE` | `/api/projects/{id}/files/{file_id}` | Delete a file |
| `POST` | `/api/chat/stream` | SSE streaming chat (project-scoped) |

All endpoints except `/health` require `Authorization: Bearer <supabase_jwt>`.

---

## Authentication Design

Authentication uses **Supabase Auth** (managed auth) — a deliberate choice:

- Users register/log in via Supabase Auth in the frontend. No custom auth server needed.
- The backend validates Supabase-issued JWTs: RS256 tokens via JWKS endpoint (auto-derived from the issuer URL), with HS256 fallback for legacy projects.
- The JWKS response is cached for 5 minutes to avoid repeated external requests.
- Row Level Security in PostgreSQL is the primary access-control layer — no auth logic leaks into application code.

---

## Architecture

See [`ARCHITECTURE.md`](./ARCHITECTURE.md) for the entity diagram and NFR decisions.
