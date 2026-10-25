# AwaazAI

AwaazAI is a platform for building and talking to **voice AI agents** in English, Hindi and Hinglish. Users sign up, configure agents, and the agent's voice pipeline (speech-to-text → LLM → text-to-speech) streams replies back in real time.

The project is split into three independent services:

| Folder | Role | Stack | Default port |
|---|---|---|---|
| [`Frontend/`](Frontend) | Web app: landing page, auth, dashboard, agent studio, voice testing | React 19 · Vite · React Router | 5173 |
| [`Backend/`](Backend) | Platform API: auth, users, agent configuration, database, rate limiting, bridge to VoiceAgent | FastAPI · SQLAlchemy 2 · Alembic · PostgreSQL · PyJWT + bcrypt | 8000 |
| [`VoiceAgent/`](VoiceAgent) | AI execution: conversation sessions, Gemini LLM, Deepgram STT, Deepgram / Sarvam TTS, streaming | FastAPI · google-genai · websockets · httpx | 8001 |

The Backend contains no AI engine; all STT / LLM / TTS logic lives in VoiceAgent. The services share no code.

```
Browser (Frontend :5173)
   │  REST + JWT                         WebSocket / SSE (voice)
   ▼                                          ▼
Backend :8000  ── status check ──►  VoiceAgent :8001 ──► Gemini · Deepgram · Sarvam
   │
   ▼
PostgreSQL (schema: awaazai)
```

## Features

- **Auth:** register / login with bcrypt-hashed passwords and JWT bearer tokens
- **Agent management:** create, list, update and delete your own agents (other users' agents return `404`)
- **Streaming chat:** Gemini replies streamed over Server-Sent Events (`POST /chat/stream`)
- **Live transcription:** Deepgram speech-to-text over WebSocket (`WS /stt/stream`)
- **Streaming speech:** text-to-speech via Deepgram Aura or Sarvam Bulbul, switchable with `TTS_PROVIDER`
- **Full voice turn:** text or raw PCM16 audio in, spoken reply out, over one socket (`WS /voice/stream`)
- **Multilingual:** English, Hindi and Hinglish, switchable per turn
- **Hardening:** rate limiting on auth endpoints, security headers, request IDs, consistent error format, concurrency limits and timeouts

## Project status

| Area | Status |
|---|---|
| Backend (auth, agents, health, migrations, tests) | Working |
| VoiceAgent phases 1–3 (chat, streaming chat, STT, TTS) | Done |
| VoiceAgent phase 4 (`WS /voice/stream` pipeline) | Step 1 done; barge-in and multi-turn sockets not started |
| Backend ↔ Frontend ↔ VoiceAgent integration, service-to-service auth | Not complete |

See [`VoiceAgent/README.md`](VoiceAgent/README.md) for the detailed phase table.

## Prerequisites

- Python 3.12+
- Node.js 20+ and npm
- PostgreSQL (local, or a hosted one such as Neon or Supabase)
- API keys for the VoiceAgent: **Gemini**, **Deepgram**, and optionally **Sarvam**

## Getting started

Run each service in its own terminal. Examples use Windows PowerShell.

### 1. Backend

```powershell
cd Backend
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements-dev.txt

Copy-Item .env.example .env
# set JWT_SECRET (generate with the command below) and your database settings
python -c "import secrets; print(secrets.token_urlsafe(48))"

alembic upgrade head
uvicorn app.main:app --reload --port 8000
```

API docs: http://localhost:8000/docs

### 2. VoiceAgent

```powershell
cd VoiceAgent
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements-dev.txt

Copy-Item .env.example .env
# add GEMINI_API_KEY (and DEEPGRAM_API_KEY / SARVAM_API_KEY for speech)

uvicorn app.main:app --host 127.0.0.1 --port 8001 --reload
```

API docs: http://localhost:8001/docs. Use a single worker, since sessions are held in memory.

### 3. Frontend

```powershell
cd Frontend
npm install
npm run dev
```

Open http://localhost:5173.

## Testing

```powershell
# Backend (in-memory SQLite, no .env or keys needed)
cd Backend; python -m pytest

# VoiceAgent (fully offline, all provider calls mocked)
cd VoiceAgent; python -m pytest

# Frontend (unit + UI tests) and lint
cd Frontend; npm test; npm run lint
```

## API overview

Backend (`/api/v1`):

| Method | Path | Auth | Purpose |
|---|---|---|---|
| GET | `/health`, `/ready` | – | Liveness / readiness |
| POST | `/auth/register` | – | Create account |
| POST | `/auth/login` | – | Get bearer token |
| GET | `/users/me` | ✔ | Current user |
| POST, GET | `/agents` | ✔ | Create / list your agents |
| GET, PATCH, DELETE | `/agents/{id}` | ✔ | Read / update / delete an agent |
| GET | `/voice-agent/status` | ✔ | Is VoiceAgent reachable? |

VoiceAgent: `GET /health`, `POST /chat`, `POST /chat/stream`, `WS /stt/stream`, `POST /tts/stream`, `WS /voice/stream`.

Full details, request examples and configuration tables are in [`Backend/README.md`](Backend/README.md) and [`VoiceAgent/README.md`](VoiceAgent/README.md).

## Configuration and secrets

Each service has a `.env.example`. Copy it to `.env` and fill it in. `.env` files are git-ignored: **never commit API keys, database passwords or `JWT_SECRET`.** In production the Backend refuses to start without a `JWT_SECRET` or with `CORS_ORIGINS=*`.

## Repository layout

```
AwaazAI/
├── Backend/       FastAPI platform API, Alembic migrations, tests
├── Frontend/      React + Vite web app
├── VoiceAgent/    Gemini / Deepgram / Sarvam voice pipeline service
├── prompt/        Prompt files used while building the project
└── video/         Demo videos (git-ignored)
```

## License

No license has been specified yet. Add a `LICENSE` file before accepting outside contributions.
