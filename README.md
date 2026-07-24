# Manah - Mindful Muse 🪷

Manah (Mindful Muse) is an AI-powered mental health companion app designed to provide accessible, judgment-free emotional support through personalized chat. Built with a focus on privacy and empathy, Manah allows users to log their daily moods and converse with distinct AI personas to navigate stress and anxiety.

![Manah Banner](https://via.placeholder.com/800x200.png?text=Manah+-+Mindful+Muse)

## ✨ Features

- **Personalized AI Personas:** Chat with different companions (e.g., a supportive "friend", a protective "bhaiya", or a caring "didi") depending on your emotional needs.
- **Multilingual Support:** Supports English, Hindi, and Hinglish for natural, comfortable conversations.
- **Mood Tracking:** Log your daily moods and visualize your emotional well-being over time.
- **Crisis Detection:** Built-in safeguards that detect severe distress and provide immediate helpline resources.
- **Secure & Private:** Powered by Supabase Auth and Row Level Security (RLS) to ensure all conversations and mood logs remain strictly private.

## 🏗️ Architecture

Manah uses a decoupled, modern tech stack:

- **Frontend:** React, Vite, TypeScript, Tailwind CSS, and Shadcn UI.
- **Backend API:** FastAPI (Python) acting as a secure proxy to stream LLM responses (Server-Sent Events) without exposing API keys to the client.
- **Database & Auth:** Supabase (PostgreSQL).
- **AI Models:** Google Gemini models routed via OpenRouter (or Qubrid).

---

## 🚀 Getting Started

Follow these steps to run Manah locally on your machine.

### 1. Database Setup (Supabase)
1. Create a new project on [Supabase](https://supabase.com/).
2. Open the **SQL Editor** in your Supabase dashboard.
3. Copy and run the contents of `manah-mindful-muse/supabase/setup.sql`. This will create all necessary tables (`profiles`, `mood_entries`, `conversations`, `messages`) and apply the required Row Level Security (RLS) policies.

### 2. Backend Setup (FastAPI)
The backend securely handles the AI API keys and streams the LLM responses.

```bash
# Navigate to the backend directory
cd manah-backend-py

# Create a virtual environment
python -m venv .venv

# Activate the virtual environment
# On Windows:
.\.venv\Scripts\Activate.ps1
# On Mac/Linux:
source .venv/bin/activate

# Install dependencies
pip install -r requirements.txt
```

**Environment Variables:**
Create a `.env` file in `manah-backend-py` (you can copy `.env.example`) and fill in:
- `SUPABASE_URL` and `SUPABASE_PUBLISHABLE_KEY`
- `SUPABASE_SECRET_KEY` (Service role key for secure verification)
- `OPENROUTER_API_KEY` (Your OpenRouter API key)

**Run the Server:**
```bash
uvicorn main:app --reload --port 3001
```

### 3. Frontend Setup (React / Vite)
```bash
# Navigate to the frontend directory
cd manah-mindful-muse

# Install dependencies
npm install
```

**Environment Variables:**
Create a `.env` file in `manah-mindful-muse` and add your Supabase credentials and the local API URL:
```env
VITE_SUPABASE_URL=your_supabase_url
VITE_SUPABASE_ANON_KEY=your_supabase_anon_key
VITE_API_URL=http://localhost:3001
```

**Run the App:**
```bash
npm run dev
```
The app will be available at `http://localhost:5173`.

---

## 🔒 Security Notes
- The `.env` files are explicitly ignored in `.gitignore` to prevent leaking API keys.
- The React frontend strictly communicates with Supabase using the Anonymous Key (respecting RLS) and the FastAPI backend using standard Bearer tokens.
- The FastAPI backend validates all Supabase JWTs before streaming AI responses.

## 📄 License
This project is open-source and available under the MIT License.
