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
