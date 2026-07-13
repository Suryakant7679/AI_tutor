# AIOS Roadmap

This roadmap is based on the architecture in `readme.md` and the features already present in this starter app.

## Current implementation status (as of 2026-07-09)

- [x] Local chat UI with a sidebar, conversation history, and multi-chat support
- [x] Persistent conversation storage in local JSON files
- [x] Backend API for health checks, conversation management, and chat requests
- [x] Multi-provider LLM support with auto fallback across Groq, Gemini, OpenAI, and DeepSeek
- [x] Streaming responses from the backend to the frontend
- [x] Browser-based speech-to-text input with automatic submission
- [x] Browser-based text-to-speech output for assistant replies
- [x] Stable chat layout with scrollable history and message area
- [x] Regression tests for request parsing, streaming event handling, and provider selection
- [x] Verified local run flow for the current app

## Checkpoint 1: Local Chat Starter

- [x] Browser chat UI
- [x] Sidebar layout
- [x] Conversation history list
- [x] Multi-chat conversation creation
- [x] Load previous conversation messages
- [x] Persist conversations to local JSON storage
- [x] Health API endpoint
- [x] Conversation API endpoints
- [x] Chat API endpoint
- [x] Basic request validation for JSON and required messages
- [x] Basic API error handling
- [x] `.env` configuration loading
- [x] Setup documentation for running locally

## Checkpoint 2: LLM Provider Layer

- [x] Provider selection with `AIOS_PROVIDER`
- [x] Auto provider fallback
- [x] Groq provider support
- [x] Gemini provider support
- [x] OpenAI provider support
- [x] DeepSeek provider support
- [x] Per-provider model environment variables
- [x] LLM timeout and retry configuration
- [x] Formal model router interface
- [x] Task-based model selection for coding, reasoning, vision, math, research, and general chat
- [ ] Local Ollama model support
- [x] Provider usage and cost tracking

## Checkpoint 3: Streaming Engine

- [x] Streaming connection from API to frontend
- [x] Token streaming for OpenAI-compatible providers
- [x] Live frontend message updates while the model responds
- [x] Final assistant message persistence after stream completion
- [x] Streaming parser tests
- [x] Native Gemini token streaming
- [x] Live Markdown rendering during stream
- [x] Tool execution progress events
- [x] Stream cancellation from the UI
- [x] Stream recovery after interrupted connections

## Checkpoint 4: Frontend Experience

- [x] Chat UI
- [x] Sidebar
- [x] Conversation history
- [x] Multi-chat support
- [x] Streaming response UI
- [x] Markdown renderer
- [x] Code syntax highlighting
- [x] File upload
- [x] Image upload
- [x] Audio upload
- [x] PDF upload
- [x] Drag and drop uploads
- [x] Artifacts panel
- [x] Settings screen
- [x] User profile
- [x] Project workspace view
- [x] Notification center
- [x] Mobile-first UI polish

## Checkpoint 5: API Gateway

- [x] Receive chat requests
- [x] Basic request validation
- [x] Basic logging through server log output
- [x] Basic error handling
- [x] Streaming response support
- [x] Authentication
- [x] Authorization
- [x] JWT verification
- [x] Rate limiting
- [x] Structured request and response schemas
- [x] Analytics events
- [x] API versioning
- [x] Durable session creation

## Checkpoint 6: Session And Conversation Management

- [x] Conversation ID creation
- [x] Save user and assistant messages
- [x] Load previous messages
- [x] Limit LLM context to the most recent messages
- [x] Session ID management
- [x] Active project tracking
- [x] Current workspace tracking
- [x] Running task tracking
- [x] Active file tracking
- [x] Active tool tracking
- [x] Token counter
- [x] Context window size management
- [x] User preferences
- [x] Multi-thread chats
- [x] Conversation summarization
- [x] Conversation compression
- [x] Context pruning strategy
- [x] Chat recovery

## Checkpoint 7: Memory System

- [x] Short-term memory for current conversation, files, task, variables, and tool outputs
- [x] Long-term memory for user preferences, coding style, projects, commands, and learned behavior
- [x] Semantic memory with vector embeddings
- [x] Semantic search across conversations and documents
- [x] Related conversation retrieval
- [x] Similar document retrieval

## Checkpoint 8: Context Builder

- [x] Include recent conversation history in the LLM prompt
- [x] Include system prompt in model calls
- [x] Include uploaded files
- [x] Include current project context
- [x] Include open files
- [x] Include terminal output
- [x] Include git status
- [x] Include browser results
- [x] Include MCP outputs
- [x] Include running task state
- [x] Include developer instructions
- [x] Include user preferences
- [x] Rank context
- [x] Compress context
- [x] Remove duplicate context
- [x] Fit context into target model window

## Checkpoint 9: Planning And Agent Orchestration

- [x] Planner agent
- [x] Task classification
- [x] Complexity analysis
- [x] Subtask generation
- [x] Tool requirement detection
- [x] Dependency estimation
- [x] LangGraph orchestrator
- [x] Decision node routing
- [x] Memory agent
- [x] RAG agent
- [x] Browser agent
- [x] Coding agent
- [x] Terminal agent
- [x] Filesystem agent
- [x] Vision agent
- [x] Database agent
- [x] Tool agent
- [x] Reflection agent
- [x] Reviewer agent
- [x] Retry failed tasks
- [x] Merge agent results into final output

## Checkpoint 10: MCP And Tool Router

- [x] MCP router
- [x] Tool request classification
- [x] Filesystem MCP
- [x] Python MCP
- [x] Terminal MCP
- [x] Browser MCP
- [x] Git MCP
- [x] GitHub MCP
- [x] Docker MCP
- [x] Kubernetes MCP
- [x] PostgreSQL MCP
- [x] SQLite MCP
- [x] Redis MCP
- [x] Cloud provider MCP integrations
- [x] Communication and productivity MCP integrations
- [x] REST API MCP
- [x] OCR MCP
- [x] Image processing MCP
- [x] Custom MCP server support

## Checkpoint 11: RAG Pipeline

- [x] Document upload
- [x] OCR for scanned files
- [x] Text cleaning
- [x] Chunking
- [x] Metadata extraction
- [x] Embedding generation
- [x] Vector database storage
- [x] Hybrid retrieval
- [x] Re-ranking
- [x] Top K selection
- [x] Citation generation
- [x] Retrieved context injection into chat

## Checkpoint 12: Response Validation

- [x] Markdown validation
- [x] JSON validation
- [x] Code validation
- [x] Hallucination checks
- [x] Tool output verification
- [x] Missing information checks
- [x] Citation checks
- [x] Safety checks
- [x] Grammar checks
- [x] Formatting checks

## Checkpoint 13: Data Layer

- [x] Local JSON conversation storage
- [x] PostgreSQL users table
- [x] PostgreSQL chats table
- [x] PostgreSQL sessions table
- [x] PostgreSQL projects table
- [x] PostgreSQL files table
- [x] PostgreSQL settings table
- [x] PostgreSQL API keys table
- [x] PostgreSQL logs table
- [x] PostgreSQL analytics table
- [x] Redis active sessions
- [x] Redis cache
- [x] Redis streaming state
- [x] Redis queue state
- [x] Redis temporary memory
- [x] Redis rate limits
- [x] Qdrant document embeddings
- [x] Qdrant memory embeddings
- [x] Qdrant code embeddings
- [x] Qdrant conversation embeddings
- [x] Local uploaded file storage
- [x] Local artifact storage

## Checkpoint 14: Background Workers

- [x] PDF processing worker
- [x] OCR worker
- [x] Embedding generation worker
- [x] Memory compression worker
- [x] Conversation summary worker
- [x] Git monitoring worker
- [x] File monitoring worker
- [x] Cache cleanup worker
- [x] Analytics worker
- [x] Health check worker
- [x] Scheduled jobs
- [x] Email notifications
- [x] Backup worker
- [x] Vector index update worker

## Checkpoint 15: Observability

- [x] Basic local server logs
- [x] Token usage monitoring
- [x] API latency monitoring
- [x] Model performance monitoring
- [x] Tool success rate monitoring
- [x] Error tracking
- [x] User analytics
- [x] Memory usage monitoring
- [x] GPU usage monitoring
- [x] CPU usage monitoring
- [x] Queue status monitoring
- [x] Cost tracking
- [x] System health dashboard

## Checkpoint 16: Deployment

- [x] Docker container for frontend/backend
- [x] Docker Compose for PostgreSQL, Redis, Qdrant, workers, scheduler, and monitoring
- [x] Nginx reverse proxy
- [x] HTTPS setup
- [ ] Cloudflare Tunnel (pending: add `TUNNEL_TOKEN` and activate the tunnel)
- [x] Production environment configuration
- [x] Backup and restore process
