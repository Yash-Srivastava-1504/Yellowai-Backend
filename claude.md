# Manah - Mindful Muse

An AI-powered mental health companion designed to provide accessible emotional support through personalized chat.

## Architecture

Manah uses a modern decoupled architecture:

1. **Frontend (`manah-mindful-muse`)**
   - React + Vite + TypeScript
   - Tailwind CSS & Shadcn UI
   - Manages state, routing, chat UI, and client-side Supabase interactions.
   - All user data and authentication state is directly tied to the Supabase client here.

2. **Backend (`manah-backend-py`)**
   - FastAPI (Python)
   - Serves as a stateless proxy to handle Server-Sent Events (SSE) for LLM streaming.
   - Verifies Supabase JWTs directly against the Supabase JWKS endpoint.
   - Abstracts API keys and prompt management so the frontend never sees them.

3. **Database & Auth (Supabase)**
   - Hosted PostgreSQL + Row Level Security (RLS)
   - Tables: `profiles`, `mood_entries`, `conversations`, `messages`
   - Handles user signups, sign-ins, and secure session management.

4. **LLM Provider**
   - Configured via OpenRouter (or Qubrid) to run Gemini models.
   - Streams responses chunk-by-chunk to the frontend via the FastAPI proxy.

## Setup Instructions

### 1. Database (Supabase)
Run the SQL migration files located in `manah-mindful-muse/supabase/` in your Supabase project's SQL Editor to create the necessary tables and RLS policies.

### 2. Backend
```bash
cd manah-backend-py
python -m venv .venv
# Activate venv: .\.venv\Scripts\Activate.ps1 (Windows) or source .venv/bin/activate (Mac/Linux)
pip install -r requirements.txt
```
Copy `.env.example` to `.env` and fill in your Supabase and LLM API credentials. **Never commit the `.env` file to version control.**
```bash
uvicorn main:app --reload --port 3001
```

### 3. Frontend
```bash
cd manah-mindful-muse
npm install
```
Copy `.env.example` to `.env` and fill in your `VITE_SUPABASE_URL` and `VITE_SUPABASE_ANON_KEY`. Point `VITE_API_URL` to `http://localhost:3001`.
```bash
npm run dev
```

## Security and Best Practices
- The root and both subdirectories have `.gitignore` files configured to prevent `.env` from being pushed.
- The Node.js legacy backend has been entirely removed and replaced with the FastAPI implementation for better performance and maintainability.
