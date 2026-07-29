# Live deployment

Status: **LIVE**

## Public endpoints

- Frontend: https://ai-tutor-eta-ochre.vercel.app
- Render backend: https://ai-tutor-backend-gc7m.onrender.com
- Proxied health check: https://ai-tutor-eta-ochre.vercel.app/api/health
- Source: https://github.com/Suryakant7679/AI_tutor/tree/main

## Architecture

- Vercel serves the static `web/` directory.
- `web/vercel.json` proxies `/api/*` to Render.
- Render builds the root `Dockerfile` and runs the Python HTTP service.
- Supabase Session Pooler provides PostgreSQL on port 5432 with SSL.
- Qdrant Cloud stores vectors.
- Upstash Redis provides shared ephemeral state when its `rediss://` URI is valid.
- Gemini is the primary model provider; Groq can remain configured as fallback.

## Render environment

Copy the keys from `.env.render.example` into Render Environment settings. Keep
all values secret. The critical managed-service values are:

```text
DATABASE_URL=postgresql://...pooler.supabase.com:5432/postgres?sslmode=require
REDIS_URL=rediss://...
QDRANT_URL=https://...
QDRANT_API_KEY=...
GEMINI_API_KEY=...
AIOS_ADMIN_EMAILS=...
AIOS_JWT_SECRET=...
```

The application runs database migrations during startup. An invalid Redis URL
no longer prevents startup, but health reports `redis: unavailable` and shared
rate limiting/stream state falls back to the single Render process.

## Verification

```text
GET https://ai-tutor-backend-gc7m.onrender.com/api/health
GET https://ai-tutor-eta-ochre.vercel.app/api/health
```

Both should return HTTP 200. An invalid login should return HTTP 401, confirming
that Vercel proxying, Render, and Supabase queries are working.

## Free-tier behavior

- Render sleeps after inactivity and can take about a minute to wake.
- Render local files and uploads are ephemeral.
- Vercel, Render, Supabase, Qdrant, Upstash, and model providers enforce their
  own free quotas.
- This configuration targets light use by roughly 100-200 registered users, not
  100-200 simultaneous chats.
