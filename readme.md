# AI Tutor

AI Tutor is a local AI chat workspace with a browser UI, persistent conversations, streaming model responses, speech controls, and multi-provider LLM support.

The project is currently a clean starter version of a larger AIOS architecture. It is intentionally small, dependency-light, and easy to run locally while future checkpoints add memory, RAG, tools, agents, and deployment infrastructure.

## Highlights

- Local browser chat UI with sidebar conversation history
- Multi-chat support with local JSON persistence
- Streaming assistant responses over NDJSON
- Live Markdown rendering while responses stream
- Stream cancellation and interrupted-stream recovery
- Browser speech-to-text input and text-to-speech output
- Provider fallback across Groq, Gemini, OpenAI, and DeepSeek
- Task-aware model routing for coding, reasoning, vision, math, research, and general chat
- Local provider usage and configurable cost estimation at `/api/usage`
- Qdrant storage for document, memory, code, and conversation embeddings
- Dependency-free Python backend using the standard library
- Regression tests for parsing, streaming, and provider behavior

## Quick Start

Clone the repo and enter the project:

```powershell
git clone https://github.com/Suryakant7679/AI_tutor.git
cd AI_tutor
```

Create your local environment file:

```powershell
Copy-Item .env.example .env
```

Add at least one API key to `.env`:

```text
AIOS_PROVIDER=auto
GROQ_API_KEY=your_key_here
GEMINI_API_KEY=
OPENAI_API_KEY=
DEEPSEEK_API_KEY=
```

Run the app:

```powershell
python app/main.py
```

Open the chat UI:

```text
http://127.0.0.1:8000
```

Health check:

```text
http://127.0.0.1:8000/api/health
```

## Configuration

The app loads `.env` on startup. Restart the server after changing provider keys or model names.

| Variable | Purpose |
| --- | --- |
| `AIOS_HOST` | Local host for the server. Defaults to `127.0.0.1`. |
| `AIOS_PORT` | Local port for the server. Defaults to `8000`. |
| `AIOS_DATA_FILE` | Legacy/local JSON conversation path. |
| `AIOS_STORAGE_BACKEND` | `auto`, `postgres`, or `json`; auto selects PostgreSQL when configured. |
| `DATABASE_URL` | PostgreSQL connection URL for runtime session/chat storage. |
| `AIOS_AUTH_REQUIRED` | Require a valid Bearer JWT for protected API routes. Defaults to `false` for local compatibility. |
| `AIOS_JWT_SECRET` | Production JWT signing secret; must contain at least 32 bytes. Blank uses a durable local secret. |
| `AIOS_JWT_TTL` | Access-token lifetime in seconds. Defaults to `3600`. |
| `AIOS_ADMIN_EMAILS` | Comma-separated emails granted the admin role at registration. |
| `AIOS_API_RATE_LIMIT` | Maximum gateway requests per rate window and identity. Defaults to `120`. |
| `AIOS_API_RATE_WINDOW` | Gateway rate-limit window in seconds. Defaults to `60`. |
| `AIOS_GATEWAY_DATA_FILE` | Durable local users, JWT secret, and analytics file. With PostgreSQL, only the generated JWT secret remains local. |
| `AIOS_PROVIDER` | Provider mode: `auto`, `groq`, `gemini`, `openai`, or `deepseek`. |
| `AIOS_DEFAULT_MODEL` | Optional model override used when provider-specific values are blank. |
| `AIOS_TEMPERATURE` | Model temperature. |
| `AIOS_LLM_TIMEOUT` | Provider request timeout in seconds. |
| `AIOS_LLM_RETRIES` | Retry count for non-streaming calls. |
| `AIOS_USAGE_FILE` | JSON usage ledger. Defaults to `data/llm_usage.json`. |
| `AIOS_OBSERVABILITY_FILE` | Durable model, tool, worker, and error event ledger. |
| `AIOS_OBSERVABILITY_MAX_EVENTS` | Maximum retained observability events. Defaults to `10000`. |
| `AIOS_ENABLED_VALIDATORS` | Optional comma-separated allowlist of response validator class names. All validators run by default. |
| `AIOS_DISABLED_VALIDATORS` | Optional comma-separated response validator class names to disable. |

Task routes can override the global provider/model with variables such as
`AIOS_CODING_PROVIDER` and `AIOS_CODING_GROQ_MODEL`. The same pattern applies
to `REASONING`, `VISION`, `MATH`, `RESEARCH`, and `GENERAL`. Cost estimates use
`AIOS_<PROVIDER>_INPUT_COST_PER_MILLION` and
`AIOS_<PROVIDER>_OUTPUT_COST_PER_MILLION`; rates default to zero until configured.

Provider-specific model variables:

```text
AIOS_GROQ_MODEL=llama-3.1-8b-instant
AIOS_GEMINI_MODEL=gemini-2.0-flash
AIOS_OPENAI_MODEL=gpt-4o-mini
AIOS_DEEPSEEK_MODEL=deepseek-chat
```

When `AIOS_PROVIDER=auto`, AIOS tries configured providers in this order:

```text
Groq -> Gemini -> OpenAI -> DeepSeek
```

## Project Structure

```text
AI_tutor/
  app/
    config.py        .env loading and configured key detection
    gateway.py       authentication, JWT, authorization, schemas, rate policy, and analytics
    llm.py           provider calls, fallback, streaming parsers
    validation.py    ordered response validation, repair, retry, and validator plugins
    main.py          HTTP server, API routes, static file serving
    migrate.py       versioned PostgreSQL migration runner
    store.py         local JSON conversation storage
  migrations/
    001_create_users_chats_sessions.sql
    002_create_projects_files_settings_api_keys.sql
    003_create_logs_analytics.sql
  data/
    .gitkeep         keeps the data folder in Git
  docs/
    plan.md          checkpoint roadmap
  tests/
    test_main.py     regression tests
  web/
    index.html       chat layout
    app.js           frontend chat, streaming, voice, Markdown
    styles.css       responsive UI styles
  .env.example       safe environment template
  SETUP.md           extra local setup notes
```

## API Overview

| Method | Route | Description |
| --- | --- | --- |
| `GET` | `/api/health` | Returns server status and configured API key names. |
| `POST` | `/api/v1/auth/register` | Registers a user, creates a durable session, and returns a Bearer JWT. |
| `POST` | `/api/v1/auth/login` | Verifies credentials, creates a durable session, and returns a Bearer JWT. |
| `GET` | `/api/v1/auth/me` | Returns the authenticated user and token session. |
| `GET` | `/api/v1/analytics` | Returns gateway events for an authenticated administrator. |
| `GET` | `/api/conversations` | Lists saved conversations. |
| `GET` | `/api/usage` | Returns accumulated provider token and cost estimates. |
| `GET` | `/api/observability` | Returns the system health and metrics dashboard payload. |
| `POST` | `/api/conversations` | Creates a new conversation. |
| `GET` | `/api/conversations/{id}` | Loads one conversation and its messages. |
| `POST` | `/api/chat` | Sends a user message and returns a normal or streaming assistant reply. |
| `POST` | `/api/plan` | Classifies an objective and returns complexity, subtasks, dependencies, tools, and success criteria. |
| `POST` | `/api/orchestrate` | Plans, routes, and executes supported specialist agents through LangGraph. |

All API routes are available under the stable `/api/v1` prefix. Legacy `/api`
paths remain aliases for version 1. API responses include `X-Request-Id`,
`X-API-Version`, and rate-limit headers. Set `AIOS_AUTH_REQUIRED=true` to make
Bearer authentication mandatory for every protected route. Authenticated
sessions and conversations are owner-scoped, and invalid requests return a
structured `{error: {code, message, details}, request_id}` response.
When PostgreSQL storage is selected, identities and analytics use the existing
`users` and `analytics` tables; JSON storage uses the local gateway file.

Streaming chat responses use newline-delimited JSON events:

```json
{"type":"meta","conversation_id":"...","provider":"gemini"}
{"type":"progress","stage":"model","message":"Model stream connected"}
{"type":"delta","content":"Hello"}
{"type":"done","message":{"role":"assistant","content":"Hello"}}
```

## Deployment

A production Compose stack is included for PostgreSQL, Redis, Qdrant, API/UI,
workers, scheduler, monitoring, Nginx HTTPS, and optional Cloudflare Tunnel.
Start by copying `.env.production.example` to the Git-ignored
`.env.production`, generating or installing TLS certificates, then run:

```powershell
$env:AIOS_ENV_FILE=".env.production"
docker compose --env-file .env.production up -d --build
```

Use `scripts/backup.ps1` and `scripts/restore.ps1` for PostgreSQL plus
application-data disaster recovery. See `SETUP.md` for certificate, tunnel,
security, validation, and recovery details.
## Testing

Run the Python test suite:

```powershell
python -m unittest discover -s tests
```

Optional frontend syntax check:

```powershell
node --check web/app.js
```

## Roadmap

The active roadmap lives in [docs/plan.md](docs/plan.md).

Current completed checkpoints:

- Checkpoint 1: Local Chat Starter
- Checkpoint 2: LLM Provider Layer
- Checkpoint 3: Streaming Engine

Next major areas:

- Frontend uploads and syntax highlighting
- Session and workspace tracking
- Memory and semantic search
- RAG pipeline
- Tool routing and agent orchestration
- Deployment with Docker, databases, and monitoring

## Notes

- `.env` is ignored by Git so API keys stay local.
- `data/*.json` is ignored by Git so private chat history stays local.
- This is a local development app, not a production-secured service yet.
