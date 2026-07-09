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
- [ ] Formal model router interface
- [ ] Task-based model selection for coding, reasoning, vision, math, research, and general chat
- [ ] Local Ollama model support
- [ ] Provider usage and cost tracking

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
- [ ] Authentication
- [ ] Authorization
- [ ] JWT verification
- [ ] Rate limiting
- [ ] Structured request and response schemas
- [ ] Analytics events
- [ ] API versioning
- [ ] Durable session creation

## Checkpoint 6: Session And Conversation Management

- [x] Conversation ID creation
- [x] Save user and assistant messages
- [x] Load previous messages
- [x] Limit LLM context to the most recent messages
- [ ] Session ID management
- [ ] Active project tracking
- [ ] Current workspace tracking
- [ ] Running task tracking
- [ ] Active file tracking
- [ ] Active tool tracking
- [ ] Token counter
- [ ] Context window size management
- [ ] User preferences
- [ ] Multi-thread chats
- [ ] Conversation summarization
- [ ] Conversation compression
- [ ] Context pruning strategy
- [ ] Chat recovery

## Checkpoint 7: Memory System

- [ ] Short-term memory for current conversation, files, task, variables, and tool outputs
- [ ] Long-term memory for user preferences, coding style, projects, commands, and learned behavior
- [ ] Semantic memory with vector embeddings
- [ ] Semantic search across conversations and documents
- [ ] Related conversation retrieval
- [ ] Similar document retrieval

## Checkpoint 8: Context Builder

- [x] Include recent conversation history in the LLM prompt
- [x] Include system prompt in model calls
- [ ] Include uploaded files
- [ ] Include current project context
- [ ] Include open files
- [ ] Include terminal output
- [ ] Include git status
- [ ] Include browser results
- [ ] Include MCP outputs
- [ ] Include running task state
- [ ] Include developer instructions
- [ ] Include user preferences
- [ ] Rank context
- [ ] Compress context
- [ ] Remove duplicate context
- [ ] Fit context into target model window

## Checkpoint 9: Planning And Agent Orchestration

- [ ] Planner agent
- [ ] Task classification
- [ ] Complexity analysis
- [ ] Subtask generation
- [ ] Tool requirement detection
- [ ] Dependency estimation
- [ ] LangGraph orchestrator
- [ ] Decision node routing
- [ ] Memory agent
- [ ] RAG agent
- [ ] Browser agent
- [ ] Coding agent
- [ ] Terminal agent
- [ ] Filesystem agent
- [ ] Vision agent
- [ ] Database agent
- [ ] Tool agent
- [ ] Reflection agent
- [ ] Reviewer agent
- [ ] Retry failed tasks
- [ ] Merge agent results into final output

## Checkpoint 10: MCP And Tool Router

- [ ] MCP router
- [ ] Tool request classification
- [ ] Filesystem MCP
- [ ] Python MCP
- [ ] Terminal MCP
- [ ] Browser MCP
- [ ] Git MCP
- [ ] GitHub MCP
- [ ] Docker MCP
- [ ] Kubernetes MCP
- [ ] PostgreSQL MCP
- [ ] SQLite MCP
- [ ] Redis MCP
- [ ] Cloud provider MCP integrations
- [ ] Communication and productivity MCP integrations
- [ ] REST API MCP
- [ ] OCR MCP
- [ ] Image processing MCP
- [ ] Custom MCP server support

## Checkpoint 11: RAG Pipeline

- [ ] Document upload
- [ ] OCR for scanned files
- [ ] Text cleaning
- [ ] Chunking
- [ ] Metadata extraction
- [ ] Embedding generation
- [ ] Vector database storage
- [ ] Hybrid retrieval
- [ ] Re-ranking
- [ ] Top K selection
- [ ] Citation generation
- [ ] Retrieved context injection into chat

## Checkpoint 12: Response Validation

- [ ] Markdown validation
- [ ] JSON validation
- [ ] Code validation
- [ ] Hallucination checks
- [ ] Tool output verification
- [ ] Missing information checks
- [ ] Citation checks
- [ ] Safety checks
- [ ] Grammar checks
- [ ] Formatting checks

## Checkpoint 13: Data Layer

- [x] Local JSON conversation storage
- [ ] PostgreSQL users table
- [ ] PostgreSQL chats table
- [ ] PostgreSQL sessions table
- [ ] PostgreSQL projects table
- [ ] PostgreSQL files table
- [ ] PostgreSQL settings table
- [ ] PostgreSQL API keys table
- [ ] PostgreSQL logs table
- [ ] PostgreSQL analytics table
- [ ] Redis active sessions
- [ ] Redis cache
- [ ] Redis streaming state
- [ ] Redis queue state
- [ ] Redis temporary memory
- [ ] Redis rate limits
- [ ] Qdrant document embeddings
- [ ] Qdrant memory embeddings
- [ ] Qdrant code embeddings
- [ ] Qdrant conversation embeddings
- [ ] Local uploaded file storage
- [ ] Local artifact storage

## Checkpoint 14: Background Workers

- [ ] PDF processing worker
- [ ] OCR worker
- [ ] Embedding generation worker
- [ ] Memory compression worker
- [ ] Conversation summary worker
- [ ] Git monitoring worker
- [ ] File monitoring worker
- [ ] Cache cleanup worker
- [ ] Analytics worker
- [ ] Health check worker
- [ ] Scheduled jobs
- [ ] Email notifications
- [ ] Backup worker
- [ ] Vector index update worker

## Checkpoint 15: Observability

- [x] Basic local server logs
- [ ] Token usage monitoring
- [ ] API latency monitoring
- [ ] Model performance monitoring
- [ ] Tool success rate monitoring
- [ ] Error tracking
- [ ] User analytics
- [ ] Memory usage monitoring
- [ ] GPU usage monitoring
- [ ] CPU usage monitoring
- [ ] Queue status monitoring
- [ ] Cost tracking
- [ ] System health dashboard

## Checkpoint 16: Deployment

- [ ] Docker container for frontend/backend
- [ ] Docker Compose for PostgreSQL, Redis, Qdrant, workers, scheduler, and monitoring
- [ ] Nginx reverse proxy
- [ ] HTTPS setup
- [ ] Cloudflare Tunnel or custom domain
- [ ] Production environment configuration
- [ ] Backup and restore process
