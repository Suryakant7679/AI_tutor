# AIOS Tutor

AIOS Tutor is a local AI chat workspace with a browser UI, persistent conversations, streaming model responses, speech controls, and multi-provider LLM support.

The project is currently a clean starter version of a larger AIOS architecture. It is intentionally small, dependency-light, and easy to run locally while future checkpoints add memory, RAG, tools, agents, and deployment infrastructure.

## Highlights

- Local browser chat UI with sidebar conversation history
- Multi-chat support with local JSON persistence
- Streaming assistant responses over NDJSON
- Live Markdown rendering while responses stream
- Stream cancellation and interrupted-stream recovery
- Browser speech-to-text input and text-to-speech output
- Provider fallback across Groq, Gemini, OpenAI, and DeepSeek
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
| `AIOS_DATA_FILE` | Conversation storage path. Defaults to `data/conversations.json`. |
| `AIOS_PROVIDER` | Provider mode: `auto`, `groq`, `gemini`, `openai`, or `deepseek`. |
| `AIOS_DEFAULT_MODEL` | Optional model override used when provider-specific values are blank. |
| `AIOS_TEMPERATURE` | Model temperature. |
| `AIOS_LLM_TIMEOUT` | Provider request timeout in seconds. |
| `AIOS_LLM_RETRIES` | Retry count for non-streaming calls. |

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
    llm.py           provider calls, fallback, streaming parsers
    main.py          HTTP server, API routes, static file serving
    store.py         local JSON conversation storage
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
| `GET` | `/api/conversations` | Lists saved conversations. |
| `POST` | `/api/conversations` | Creates a new conversation. |
| `GET` | `/api/conversations/{id}` | Loads one conversation and its messages. |
| `POST` | `/api/chat` | Sends a user message and returns a normal or streaming assistant reply. |

Streaming chat responses use newline-delimited JSON events:

```json
{"type":"meta","conversation_id":"...","provider":"gemini"}
{"type":"progress","stage":"model","message":"Model stream connected"}
{"type":"delta","content":"Hello"}
{"type":"done","message":{"role":"assistant","content":"Hello"}}
```

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
