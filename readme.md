# AI Tutor

AI Tutor is a deployed, multi-user chatbot for conversational learning, document Q&A, and mathematical explanations. It provides authenticated chat, streaming responses, PDF/text extraction, retrieval-backed context, and rendered LaTeX equations.

## Live application

- Frontend: https://ai-tutor-eta-ochre.vercel.app
- Backend: https://ai-tutor-backend-gc7m.onrender.com
- Health check: https://ai-tutor-eta-ochre.vercel.app/api/v1/health

The current production stack is:

| Component | Service |
| --- | --- |
| Static frontend | Vercel |
| Python backend | Render (Docker) |
| Relational database | Supabase PostgreSQL |
| Shared state and rate limiting | Upstash Redis |
| Vector database | Qdrant Cloud |
| AI providers | Gemini, Groq, OpenAI, or DeepSeek |

## Current features

- Email registration and Bearer-token authentication
- User-scoped conversations and chat history
- Streaming assistant responses with cancellation and recovery
- PDF and text uploads with extracted document context
- Hidden attachment context: extracted PDF text is not displayed as the user's prompt
- Retrieval-backed document and conversation context through Qdrant
- Mathematical answers rendered with KaTeX/LaTeX
- Markdown, syntax-highlighted code, speech input, and text-to-speech
- Multiple AI providers with automatic fallback and task-aware routing
- Redis-backed sessions, caching, rate limits, and stream state
- PostgreSQL migrations and durable user/chat storage
- Health, usage, search, planning, orchestration, and observability APIs

## How deployment works

```text
Browser
   |
   v
Vercel (web/)
   |  /api/* proxy
   v
Render (Docker/Python)
   |---- Supabase PostgreSQL
   |---- Upstash Redis
   |---- Qdrant Cloud
   `---- Configured AI provider
```

Vercel deploys the `web/` directory. Its `vercel.json` forwards API requests to the Render backend. Render builds the root `Dockerfile`, starts `python -m app.main`, and applies PostgreSQL migrations during startup.

## Local development

Requirements:

- Python 3.12+
- Node.js only for the optional JavaScript syntax check
- At least one supported AI provider key

Clone and configure the project:

```powershell
git clone https://github.com/Suryakant7679/AI_tutor.git
cd AI_tutor
Copy-Item .env.example .env
python -m pip install -r requirements.txt
```

Add at least one provider key to `.env`:

```dotenv
AIOS_PROVIDER=auto
GROQ_API_KEY=your_key
GEMINI_API_KEY=
OPENAI_API_KEY=
DEEPSEEK_API_KEY=
```

Start the application:

```powershell
python -m app.main
```

Open http://127.0.0.1:8000. The local health endpoint is http://127.0.0.1:8000/api/v1/health.

## Production environment variables

Add production secrets in **Render ? Web Service ? Environment**. Do not commit real credentials to GitHub.

Required infrastructure values:

```dotenv
AIOS_HOST=0.0.0.0
AIOS_STORAGE_BACKEND=postgres
AIOS_VECTOR_BACKEND=qdrant
AIOS_AUTH_REQUIRED=true

DATABASE_URL=postgresql://USER:URL_ENCODED_PASSWORD@SUPABASE_POOLER_HOST:5432/postgres?sslmode=require
REDIS_URL=rediss://default:PASSWORD@UPSTASH_HOST:6379
QDRANT_URL=https://YOUR_QDRANT_CLUSTER
QDRANT_API_KEY=your_qdrant_api_key
QDRANT_COLLECTION=aios_embeddings

AIOS_JWT_SECRET=generate_at_least_32_random_bytes
AIOS_ADMIN_EMAILS=your_email@example.com
```

Configure at least one model provider:

```dotenv
AIOS_PROVIDER=gemini
GEMINI_API_KEY=your_gemini_key
AIOS_GEMINI_MODEL=gemini-2.5-flash

# Optional fallback
GROQ_API_KEY=your_groq_key
AIOS_GROQ_MODEL=openai/gpt-oss-20b
```

Important connection formats:

- Supabase: use the Session Pooler URI and append `?sslmode=require`. URL-encode reserved characters in the password.
- Upstash: use the Redis TLS URI beginning with `rediss://`, not the REST URL and not the complete `redis-cli` command.
- Qdrant: use the HTTPS cluster URL and its API key.

A complete safe template is available in `.env.render.example`.

## Vercel configuration

Create a Vercel project from this repository using:

| Setting | Value |
| --- | --- |
| Framework preset | Other |
| Root directory | `web` |
| Build command | Leave empty |
| Output directory | Leave empty |

The API proxy is already configured in `web/vercel.json`.

## Render configuration

Create a Render Web Service from this repository using:

| Setting | Value |
| --- | --- |
| Branch | `main` |
| Runtime | Docker |
| Root directory | Leave empty |
| Instance | Free, when available |
| Health check path | `/api/v1/health` |

Add the environment variables above, then deploy. New commits to `main` automatically trigger Vercel and Render deployments.

## API overview

All routes use the `/api/v1` prefix. Authentication-protected requests require:

```http
Authorization: Bearer YOUR_ACCESS_TOKEN
```

| Method | Route | Purpose |
| --- | --- | --- |
| `GET` | `/api/v1/health` | Service, provider, and Redis status |
| `POST` | `/api/v1/auth/register` | Create an account |
| `POST` | `/api/v1/auth/login` | Sign in and receive a token |
| `GET` | `/api/v1/auth/me` | Return the authenticated user |
| `GET/POST` | `/api/v1/conversations` | List or create conversations |
| `POST` | `/api/v1/chat` | Send a normal or streaming chat request |
| `GET/POST` | `/api/v1/uploads` | List or upload artifacts |
| `GET` | `/api/v1/conversations/search` | Search conversation history |
| `GET` | `/api/v1/observability` | Runtime health and metrics |
| `GET` | `/api/v1/usage` | Provider token and cost estimates |

## Testing

Run the complete suite:

```powershell
python -m pytest -q
```

Check frontend JavaScript syntax:

```powershell
node --check web/app.js
```

Current verified result: **215 tests passed**.

## Project structure

```text
app/             Python backend, authentication, storage, LLM routing, RAG, and agents
web/             Static frontend and Vercel proxy configuration
migrations/      PostgreSQL schema migrations
tests/           Automated backend and frontend regression tests
docs/            Deployment documentation
Dockerfile       Render production image
.env.example     Local configuration template
.env.render.example  Render-safe variable template
```

## Free-tier considerations

- Render may sleep after inactivity, so the first request can take longer.
- Render's local filesystem is ephemeral; durable accounts and chats belong in Supabase.
- Uploaded files may disappear after a Render restart, while their durable metadata depends on configured storage.
- Each cloud service and AI provider has its own free quota and rate limits.
- This setup is intended for light usage by roughly 100?200 registered users, not 100?200 simultaneous AI requests.

## Security

- Never commit `.env`, database passwords, Redis credentials, JWT secrets, or provider API keys.
- Rotate any credential that has been posted publicly.
- Keep write-capable MCP and execution tools disabled on the public deployment unless they are explicitly secured.
- Use long, random production values for `AIOS_JWT_SECRET`.

## License

No license has been declared. All rights remain with the repository owner unless a license is added later.
