# Free public deployment

> Deployment status: **PENDING**. Repository preparation is complete, but no Vercel, Koyeb, Supabase, Upstash, Qdrant, or model-provider deployment has been created yet.

## Details to collect before deployment

Keep these values in a password manager or the provider dashboards; never commit them:

- `DATABASE_URL`: Supabase Session pooler PostgreSQL URI
- `REDIS_URL`: Upstash TLS URI beginning with `rediss://`
- `QDRANT_URL` and `QDRANT_API_KEY`: Qdrant Cloud cluster credentials
- One model credential: `GROQ_API_KEY`, `GEMINI_API_KEY`, or `OPENAI_API_KEY`
- `AIOS_ADMIN_EMAILS`: your administrator email address
- `AIOS_JWT_SECRET`: a new random secret of at least 32 bytes
- Koyeb public hostname: available only after backend deployment
- Vercel public hostname: available only after frontend deployment

## Pending checklist

- [x] Prepare a single-service Koyeb Docker image
- [x] Add automatic PostgreSQL migrations
- [x] Add a safe production environment template
- [x] Add Vercel API proxy configuration
- [x] Validate application tests and configuration
- [ ] Create Supabase, Upstash, and Qdrant free projects
- [ ] Create the model-provider API key
- [ ] Deploy the Koyeb backend and verify `/api/health`
- [ ] Replace the Koyeb placeholder in `web/vercel.json`
- [ ] Deploy the Vercel frontend
- [ ] Complete private-browser and small-group testing
This setup targets 100–200 registered users with light traffic, not 100–200 simultaneous users.

## Services

- Vercel: static `web/` frontend
- Koyeb: one Web Service using `Dockerfile.koyeb`
- Supabase: PostgreSQL
- Upstash: Redis
- Qdrant Cloud: vectors
- Groq or Gemini: model API

Separate workers are omitted because Koyeb Free cannot run Worker Services. Normal chat, authentication, PostgreSQL conversation storage, Redis rate limiting, streaming, and vector access run in the web service. Deferred background jobs do not run.

## Create the managed services

Create free Supabase, Upstash Redis, and Qdrant Cloud projects, preferably in nearby regions. Copy the Supabase Session pooler PostgreSQL URI, the Upstash `rediss://` URI, and the Qdrant HTTPS URL and API key.

## Push the repository

Push the project to GitHub or another Koyeb/Vercel-supported Git provider. Never commit `.env`, `.env.production`, passwords, or API keys.

## Deploy Koyeb

Create a Koyeb Web Service from the repository:

- Builder: Dockerfile
- Dockerfile: `Dockerfile.koyeb`
- Instance: Free
- Port: `8000`
- Health path: `/api/health`

Copy the values from `.env.free-tier.example` into Koyeb Environment Variables. Generate the JWT secret locally with:

```powershell
python -c "import secrets; print(secrets.token_urlsafe(48))"
```

The container automatically runs PostgreSQL migrations before starting. After it becomes healthy, copy its `https://...koyeb.app` address and test `/api/health`.

## Deploy Vercel

In `web/vercel.json`, replace `https://REPLACE-WITH-YOUR-KOYEB-HOST.koyeb.app` with the exact Koyeb address without a trailing slash. Commit and push it.

Create a Vercel project with:

- Root directory: `web`
- Framework preset: Other
- Build command: empty
- Output directory: `.`

Deploy, open the Vercel URL in a private window, register, log in, send a message, reload, and confirm the conversation remains.

## Limitations

- Koyeb sleeps after inactivity, causing a cold start.
- Uploads and other files under `data/` are temporary and disappear on redeployment.
- Supabase, Upstash, Qdrant, and the AI provider each impose free quotas.
- Invite a small test group before publishing broadly.
