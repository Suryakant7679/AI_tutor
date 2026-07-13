# AIOS Starter Setup

This is the first working skeleton for the AIOS project.

## Run

Add your API keys to `.env` first:

```text
AIOS_PROVIDER=auto
AIOS_DEFAULT_MODEL=
OPENAI_API_KEY=your_key_here
ANTHROPIC_API_KEY=
GROQ_API_KEY=
DEEPSEEK_API_KEY=
GEMINI_API_KEY=
```

Leave providers blank if you are not using them yet.

`AIOS_PROVIDER=auto` chooses the first available key in this order: Groq, Gemini, OpenAI, DeepSeek. You can force one with `AIOS_PROVIDER=groq`, `gemini`, `openai`, or `deepseek`.

The app reloads `.env` on startup and lets the file override old terminal environment values. After changing an API key, restart the server.

Provider-specific model settings are supported:

```text
AIOS_GROQ_MODEL=llama-3.1-8b-instant
AIOS_GEMINI_MODEL=gemini-3.5-flash
AIOS_OPENAI_MODEL=gpt-4o-mini
AIOS_DEEPSEEK_MODEL=deepseek-chat
```

If one provider rejects a request, auto mode tries the next configured provider. For example, if Groq returns a provider/CDN `403`, the app can continue with Gemini when `GEMINI_API_KEY` is present. To skip Groq entirely, set:

```text
AIOS_PROVIDER=gemini
```

If you see `[WinError 10054] An existing connection was forcibly closed by the remote host`, the provider or network closed the connection before returning an API response. Keep `AIOS_PROVIDER=auto` so the app retries and then falls back to another configured provider.

If Gemini returns `models/gemini-1.5-flash is not found`, remove the old `AIOS_GEMINI_MODEL=gemini-1.5-flash` setting or change it to `AIOS_GEMINI_MODEL=gemini-3.5-flash`. The app also tries a few current Gemini fallback model names when Gemini is enabled.

```powershell
python app/main.py
```

Open:

```text
http://127.0.0.1:8000
```

Health check:

```text
http://127.0.0.1:8000/api/health
```

## Current Features

- Simple chat UI.
- Local JSON conversation storage.
- Conversation list and reload.
- Dependency-free Python backend.
- Local `.env` loading for API keys.
- Real LLM calls through OpenAI-compatible providers or Gemini.

## Next Development Step

Add file upload and RAG now that the real model calls and streaming responses are in place.

## PostgreSQL schema

Create a PostgreSQL role and database, then put its connection URL in `.env`:

```text
DATABASE_URL=postgresql://aios:your_password@127.0.0.1:5432/aios
```

Install the database driver and apply all versioned migrations:

```powershell
python -m pip install -r requirements.txt
python -m app.migrate
```

The migrations create `users`, `sessions`, `chats`, `projects`, `files`,
`settings`, `api_keys`, `logs`, and `analytics`, their indexes and foreign keys, automatic
`updated_at` triggers, and a `schema_migrations` ledger. API keys must be
encrypted by the application before their ciphertext is stored in
`api_keys.encrypted_secret`; plaintext secrets must never be inserted.
The migration is safe to run again. When `DATABASE_URL` is configured and
`AIOS_STORAGE_BACKEND=auto` (the default), sessions and chats use PostgreSQL.
Use `AIOS_STORAGE_BACKEND=json` only when you explicitly want local JSON.

## Redis ephemeral state

Start Redis locally with Docker and configure the connection:

```powershell
docker run --name aios-redis -p 6379:6379 -d redis:7-alpine
```

```text
REDIS_URL=redis://127.0.0.1:6379/0
```

Install dependencies with `python -m pip install -r requirements.txt`, then
restart the app. Redis stores TTL-backed active sessions, cache entries,
stream recovery state, and queue job state. PostgreSQL remains authoritative;
the app degrades gracefully when Redis is unavailable.

Temporary conversation memory expires after `AIOS_REDIS_MEMORY_TTL` seconds.
Chat requests use an atomic fixed-window rate limit configured by
`AIOS_CHAT_RATE_LIMIT` requests per `AIOS_CHAT_RATE_WINDOW` seconds. When Redis
is unavailable, rate limiting fails open so local development remains usable.

## Qdrant vector storage

Start Qdrant with a persistent Docker volume:

```powershell
docker run --name aios-qdrant -p 6333:6333 -p 6334:6334 -v aios-qdrant-data:/qdrant/storage -d qdrant/qdrant:latest
```

Configure `QDRANT_URL=http://127.0.0.1:6333` and run
`python -m app.import_vectors_to_qdrant` once. Index the current repository with
`python -m app.index_workspace_code`. The `aios_embeddings` collection
stores document, memory, code, and conversation points in one collection with
filterable `source_type` payloads. Uploaded bytes remain under `data/uploads`
and artifact metadata remains in `data/uploads.json`.

Import existing local sessions and conversations once before starting the app:

```powershell
python -m app.import_json_store
```
