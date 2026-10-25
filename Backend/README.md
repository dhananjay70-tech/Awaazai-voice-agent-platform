# AwaazAI Backend

Platform backend for AwaazAI: authentication, agent configuration APIs, and the integration boundary to the separate `VoiceAgent/` service. **It contains no AI engine** (STT, LLM, TTS, RAG, LangGraph all live in `VoiceAgent/`).

**Stack:** FastAPI · Uvicorn · Pydantic Settings · SQLAlchemy 2 · Alembic · PostgreSQL (psycopg 3) · PyJWT + bcrypt · HTTPX · Pytest

## Setup (Windows PowerShell)

```powershell
cd C:\Users\niran\Desktop\AwaazAI\Backend

python -m venv .venv
.\.venv\Scripts\Activate.ps1          # if blocked: Set-ExecutionPolicy -Scope CurrentUser RemoteSigned
python -m pip install -r requirements-dev.txt

Copy-Item .env.example .env
# generate a JWT secret and paste it into .env as JWT_SECRET=...
python -c "import secrets; print(secrets.token_urlsafe(48))"
```

## Run the tests

Tests use an in-memory SQLite database and a fake JWT secret. They need no PostgreSQL, no `.env` and no API keys.

```powershell
python -m pytest
```

## PostgreSQL

The server starts without a database (`/ready` then reports `database: not_configured` and database endpoints return 503). To use PostgreSQL:

**Local install:** install PostgreSQL, then in `psql`:

```sql
CREATE USER awaazai WITH PASSWORD 'choose-a-password';
CREATE DATABASE awaazai OWNER awaazai;
```

**Hosted (Neon, Supabase, Render, ...):** copy the connection string they give you.

Then set in `.env` either one URL or the separate parts:

```
DATABASE_URL=postgresql://awaazai:choose-a-password@localhost:5432/awaazai
# or POSTGRES_HOST / POSTGRES_PORT / POSTGRES_USER / POSTGRES_PASSWORD / POSTGRES_DB
```

### Schema isolation

All AwaazAI tables, and Alembic's `alembic_version` table, live in a dedicated PostgreSQL schema named **`awaazai`**, so the app can share a database (e.g. a Supabase project) with other projects without touching their `public` tables. The first migration runs `CREATE SCHEMA IF NOT EXISTS awaazai`. Downgrading drops AwaazAI's tables but leaves the empty schema in place. The database user needs `CREATE` privilege on the database for the first migration.

### Migrations

The app **never creates tables on startup**; Alembic does.

```powershell
alembic upgrade head                              # apply all migrations
alembic current                                   # show applied revision
alembic revision --autogenerate -m "describe change"   # after editing models, then review the file
alembic downgrade -1                              # undo the last migration
alembic upgrade head --sql                        # print the SQL instead of running it
```

## Run the server

```powershell
uvicorn app.main:app --reload --port 8000
```

Interactive docs: http://localhost:8000/docs (`/docs`, `/redoc` and `/openapi.json` are **disabled when `ENVIRONMENT=production`**).

## Configuration (`.env`)

| Variable | Default | Notes |
|---|---|---|
| `ENVIRONMENT` | `development` | `development`, `test` or `production`. Production **refuses to start** without `JWT_SECRET` or with `CORS_ORIGINS=*`. |
| `JWT_SECRET` | *(none)* | Required for register/login. Min 32 chars. No default on purpose. Without it those endpoints return 503. |
| `ACCESS_TOKEN_EXPIRE_MINUTES` | `30` | |
| `DATABASE_URL` or `POSTGRES_*` | *(none)* | See above. |
| `CORS_ORIGINS` | Vite dev server | Comma-separated. |
| `LOG_LEVEL` | `INFO` | |
| `VOICE_AGENT_BASE_URL` | *(none)* | Leave empty until VoiceAgent exists. |
| `VOICE_AGENT_TIMEOUT_SECONDS` | `5` | |
| `RATE_LIMIT_ENABLED` | `true` | See [Rate limiting](#rate-limiting). |
| `TRUSTED_PROXY_COUNT` | `0` | Number of reverse proxies **you control** in front of the app. `0` ignores `X-Forwarded-For`. |
| `RATE_LIMIT_REGISTER_MAX` / `_WINDOW_SECONDS` | `10` / `3600` | Register attempts per client IP. |
| `RATE_LIMIT_LOGIN_IP_MAX` / `_WINDOW_SECONDS` | `20` / `300` | Login attempts per client IP. |
| `RATE_LIMIT_LOGIN_EMAIL_MAX` / `_WINDOW_SECONDS` | `10` / `900` | Login attempts per email, from any IP. |
| `DB_POOL_SIZE` / `DB_MAX_OVERFLOW` | `5` / `5` | Connections per worker process = sum of both. Hosted poolers cap total clients (Supabase session mode: **15 for the whole project**, shared with your other apps), so keep this small and multiply by your worker count. |

`.env` is git-ignored. Never commit it.

## Endpoints

| Method | Path | Auth | Purpose |
|---|---|---|---|
| GET | `/` | – | App info |
| GET | `/health` | – | **Liveness**: process is up (checks nothing else) |
| GET | `/ready` | – | **Readiness**: database + JWT config; `503` if not ready |
| POST | `/api/v1/auth/register` | – | Create account (`201`, `409` if email exists, `429` if rate limited) |
| POST | `/api/v1/auth/login` | – | Returns a bearer token (`401` bad credentials, `429` if rate limited) |
| GET | `/api/v1/users/me` | ✔ | Current user |
| POST | `/api/v1/agents` | ✔ | Create agent |
| GET | `/api/v1/agents?limit=50&offset=0` | ✔ | List **your** agents |
| GET | `/api/v1/agents/{id}` | ✔ | Get one of your agents |
| PATCH | `/api/v1/agents/{id}` | ✔ | Partial update |
| DELETE | `/api/v1/agents/{id}` | ✔ | Delete (`204`) |
| GET | `/api/v1/voice-agent/status` | ✔ | Is VoiceAgent reachable? Always `200`; body says `ok` / `not_configured` / `unavailable` / `timeout` |

Errors always look like `{"error": {"code": "...", "message": "...", "details": ..., "request_id": "..."}}`. Another user's agent returns `404`, not `403`, so IDs cannot be probed.

## Example requests (PowerShell)

```powershell
$api = "http://localhost:8000/api/v1"

# register
Invoke-RestMethod -Method Post "$api/auth/register" -ContentType "application/json" `
  -Body '{"email":"me@example.com","password":"a-long-password","full_name":"Me"}'

# login -> token
$token = (Invoke-RestMethod -Method Post "$api/auth/login" -ContentType "application/json" `
  -Body '{"email":"me@example.com","password":"a-long-password"}').access_token
$h = @{ Authorization = "Bearer $token" }

# current user
Invoke-RestMethod "$api/users/me" -Headers $h

# create / list / get / update / delete an agent
$agent = Invoke-RestMethod -Method Post "$api/agents" -Headers $h -ContentType "application/json" -Body '{
  "name":"Support Bot","system_prompt":"You are a helpful support agent.",
  "language":"hi-IN","voice_config":{"provider":"example","voice_id":"v1","speed":1.1}}'
Invoke-RestMethod "$api/agents" -Headers $h
Invoke-RestMethod "$api/agents/$($agent.id)" -Headers $h
Invoke-RestMethod -Method Patch "$api/agents/$($agent.id)" -Headers $h -ContentType "application/json" -Body '{"is_active":false}'
Invoke-RestMethod -Method Delete "$api/agents/$($agent.id)" -Headers $h
```

## Architecture

```
app/
  main.py            create_app(): middleware, CORS, routers, lifespan
  core/              config (env settings), security (bcrypt + JWT), errors (+ handlers), logging
  db/                Base, Database (lazy engine, per-request session, readiness check)
  models/            User, Agent (SQLAlchemy 2.0 typed models)
  schemas/           Pydantic request/response models
  api/
    dependencies.py  settings, db session, get_current_user
    routes/          health, auth, users, agents, voice_agent
  services/
    voice_agent_client.py   async HTTPX client to the VoiceAgent service
alembic/             migrations
tests/               pytest suite
```

Design notes:

- **Sessions** are synchronous (one per request, rolled back on error). Routes call `commit()` explicitly. FastAPI runs sync routes in a thread pool, so this stays simple without blocking the event loop. Only the VoiceAgent client is async.
- **Passwords**: bcrypt (max 72 bytes, validated). Login does one bcrypt check even for unknown emails and returns the same error for both failure cases.
- **JWT**: HS256 only, with `sub`, `iat`, `exp` required. The algorithm is never read from the token.
- **Agent `voice_config`** rejects unknown keys, so provider API keys cannot be stored or returned.
- **Security headers** on every response, including errors: `X-Content-Type-Options`, `X-Frame-Options: DENY`, `Referrer-Policy`, `Permissions-Policy` and a strict `Content-Security-Policy` (not applied to Swagger UI in development). API responses are `Cache-Control: no-store`. `Strict-Transport-Security` is sent only in production; serve the API over HTTPS there.
- **Safe error logging**: the engine uses `hide_parameters=True`, and database errors are logged by type only (never the SQL text or values), so emails and password hashes cannot reach logs. Other unexpected errors are logged with a traceback and the request ID; responses never include details.
- **Request IDs** are generated server-side, logged, returned in `X-Request-ID` and in error bodies.

## Rate limiting

`POST /auth/register` and `POST /auth/login` are throttled to slow down brute-force and credential-stuffing attacks.

| Rule | Key | Default |
|---|---|---|
| Register | client IP | 10 per hour |
| Login | client IP | 20 per 5 minutes |
| Login | email address (any IP) | 10 per 15 minutes |

Every attempt counts, including correct passwords, so a guess cannot be "free". When a limit is exceeded the API returns **429** with a `Retry-After` header (seconds) and the standard error body:

```json
{"error": {"code": "rate_limited", "message": "Too many requests. Please try again later.",
           "details": {"retry_after_seconds": 897}, "request_id": "..."}}
```

**How it works.** Counters live in PostgreSQL (`awaazai.rate_limits`, created by migration `0002`), updated with one atomic `INSERT ... ON CONFLICT DO UPDATE`, so all workers and server instances share the same counts without Redis. Keys are HMAC hashes, so no raw IPs or emails are stored. Counters are committed independently, so a failed request still counts. Expired rows are cleaned up opportunistically. IPv6 clients are grouped by /64. The limiter depends on the database (as register/login already do); when it is down those endpoints return 503. Server clocks should be roughly in sync (NTP).

### Deployment behind a reverse proxy (required reading)

Behind a proxy or load balancer, the TCP peer is the proxy, not the user. Without configuration **all users would share one budget** (or, if you trusted headers blindly, anyone could forge a fresh identity per request). Configure both pieces:

1. **Tell the app how many proxies you control:** `TRUSTED_PROXY_COUNT=N`. The client address is then taken from `X-Forwarded-For` counting N entries from the right, i.e. the address your own outermost proxy observed. Anything a client prepends is ignored. Only set this when the app is reachable **exclusively** through exactly N proxies you control (firewall the app port); otherwise a client can talk to the app directly and forge the header. With `0` (default) the header is never read.
2. **Start uvicorn with `--no-proxy-headers`**, and never set `FORWARDED_ALLOW_IPS=*`, so that only the logic above interprets `X-Forwarded-For`:

```powershell
uvicorn app.main:app --host 0.0.0.0 --port 8000 --workers 2 --no-proxy-headers
```

Your proxy must **append** to `X-Forwarded-For` (nginx: `proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;`; most managed platforms already do). Example: a platform with one proxy layer -> `TRUSTED_PROXY_COUNT=1`; CDN in front of a load balancer -> `2`.

Run `--workers` x (`DB_POOL_SIZE` + `DB_MAX_OVERFLOW`) below your database's connection limit.

This limiter is an application-level safety net. A proxy/CDN-level limit (nginx `limit_req`, Cloudflare rules) in front of it is still a good idea and complements it.

## Known limitations

- **Rate limiting covers register and login only**, and uses fixed windows (a burst straddling a window boundary can reach up to 2x the limit). Other endpoints are not limited; add a proxy-level limit if you need that.
- **No refresh tokens / logout.** Access tokens are valid until they expire (default 30 min).
- **VoiceAgent integration is a stub.** `VoiceAgent/` has no documented API yet. The client calls an *assumed* `GET /health` (marked `TODO` in `voice_agent_client.py`). Add real methods once that service defines them.
- **The automated suite runs on SQLite.** PostgreSQL-specific behaviour (migrations, the rate-limiter's atomic upsert under concurrency) was verified by hand against a live Supabase database, but is not covered by CI. Re-run `alembic upgrade head` and a few requests against your own database after deploying.

## Troubleshooting

| Symptom | Fix |
|---|---|
| `503 database_unavailable: Database is not configured` | Set `DATABASE_URL` or `POSTGRES_*` in `.env`, then `alembic upgrade head`. |
| `503 auth_not_configured` | Set `JWT_SECRET` (32+ chars) in `.env`. |
| `/ready` says `database: unavailable` | PostgreSQL is not running / wrong host, port or credentials. Check the log (credentials are never logged). |
| App exits with a `ValidationError` on startup | Read the message: short `JWT_SECRET`, or production without a secret / with `CORS_ORIGINS=*`. |
| `relation "users" does not exist` | You have not run `alembic upgrade head`. |
| Browser CORS error | Add the frontend's exact origin (scheme + host + port) to `CORS_ORIGINS`. |
| `Activate.ps1 cannot be loaded` | `Set-ExecutionPolicy -Scope CurrentUser RemoteSigned` |
