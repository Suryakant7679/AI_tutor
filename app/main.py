from __future__ import annotations

import json
import mimetypes
import os
import re
import shlex
import shutil
import subprocess
import hashlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Iterator
from urllib.parse import parse_qsl, urlparse
from uuid import uuid4
from email.parser import BytesParser
from email.policy import default

try:
    from app.config import configured_api_keys, load_env
    from app.llm import LLMError, generate_response, generate_response_stream
    from app.store import ConversationStore, utc_now
except ModuleNotFoundError:
    from config import configured_api_keys, load_env
    from llm import LLMError, generate_response, generate_response_stream
    from store import ConversationStore, utc_now


load_env()
ROOT = Path(__file__).resolve().parents[1]
WEB_ROOT = ROOT / "web"
STORE = ConversationStore(os.getenv("AIOS_DATA_FILE", "data/conversations.json"))
UPLOAD_ROOT = ROOT / os.getenv("AIOS_UPLOAD_DIR", "data/uploads")
UPLOAD_INDEX = ROOT / os.getenv("AIOS_UPLOAD_INDEX", "data/uploads.json")
VECTOR_INDEX = ROOT / os.getenv("AIOS_VECTOR_INDEX", "data/vectors.json")
MAX_UPLOAD_BYTES = int(os.getenv("AIOS_MAX_UPLOAD_BYTES", str(10 * 1024 * 1024)))
EMBEDDING_DIMENSIONS = int(os.getenv("AIOS_EMBEDDING_DIMENSIONS", "64"))
EMBEDDING_MODEL = os.getenv("AIOS_EMBEDDING_MODEL", "local-hash-v1")
RAG_TOP_K = int(os.getenv("AIOS_RAG_TOP_K", "5"))


class AIOSHandler(BaseHTTPRequestHandler):
    server_version = "AIOSStarter/0.1"

    def do_GET(self) -> None:
        parsed_url = urlparse(self.path)
        path = parsed_url.path
        if path == "/api/health":
            self.send_json(
                {
                    "status": "ok",
                    "service": "aios-starter",
                    "configured_api_keys": configured_api_keys(),
                }
            )
            return
        if path == "/api/session":
            requested_session_id = self.session_id_from_request(parsed_url.query)
            self.send_json({"session": STORE.get_or_create_session(requested_session_id)})
            return
        if path == "/api/memory":
            self.send_json({"memory": STORE.get_long_term_memory()})
            return
        if path == "/api/search":
            query = dict(parse_qsl(parsed_url.query, keep_blank_values=False))
            text_query = str(query.get("q") or "").strip()
            source_types = [item.strip() for item in str(query.get("sources") or "").split(",") if item.strip()]
            try:
                top_k = max(1, min(int(query.get("top_k", RAG_TOP_K)), 50))
            except (TypeError, ValueError):
                top_k = RAG_TOP_K
            index_conversation_history(STORE.list_conversations())
            index_long_term_memory(STORE.get_long_term_memory())
            self.send_json({"query": text_query, "results": semantic_search(text_query, top_k, source_types or None)})
            return
        if path == "/api/conversations":
            session_id = self.session_id_from_request(parsed_url.query)
            conversations = (
                STORE.list_conversations_for_session(session_id)
                if session_id
                else STORE.list_conversations()
            )
            self.send_json({"conversations": compact_conversations(conversations)})
            return
        if path.startswith("/api/conversations/") and path.endswith("/related"):
            conversation_id = path.split("/")[-2]
            try:
                conversation = STORE.get_conversation(conversation_id)
            except KeyError:
                self.send_error(404, "Conversation not found")
                return
            query_params = dict(parse_qsl(parsed_url.query, keep_blank_values=False))
            query = str(query_params.get("q") or conversation_search_text(conversation)).strip()
            conversations = STORE.list_conversations()
            index_conversation_history(conversations)
            self.send_json({
                "conversation_id": conversation_id,
                "query": query,
                "related": related_conversations(query, conversations, exclude_id=conversation_id),
            })
            return
        if path.startswith("/api/conversations/"):
            conversation_id = path.rsplit("/", 1)[-1]
            try:
                self.send_json(STORE.get_conversation(conversation_id))
            except KeyError:
                self.send_error(404, "Conversation not found")
            return
        if path == "/api/uploads":
            self.send_json({"artifacts": list_artifacts()})
            return
        if path.startswith("/api/uploads/") and path.endswith("/similar"):
            artifact_id = path.split("/")[-2]
            artifact = find_artifact(artifact_id)
            if not artifact:
                self.send_error(404, "Upload not found")
                return
            records = vector_records_for_artifact(artifact)
            upsert_vector_records(records)
            self.send_json({"artifact_id": artifact_id, "similar": similar_documents(artifact_id)})
            return
        if path.startswith("/api/uploads/") and path.endswith("/content"):
            artifact_id = path.split("/")[-2]
            self.serve_upload(artifact_id)
            return
        self.serve_static(path)

    def do_POST(self) -> None:
        path = urlparse(self.path).path
        if path == "/api/conversations":
            try:
                body = self.read_json()
            except ValueError:
                body = {}
            session_id = str(body.get("session_id") or "").strip() or self.session_id_from_request()
            session = STORE.get_or_create_session(session_id or None)
            conversation = STORE.create_conversation(session_id=session["id"])
            self.send_json(conversation, status=201)
            return
        if path.startswith("/api/conversations/") and path.endswith("/threads"):
            conversation_id = path.split("/")[-2]
            try:
                body = self.read_json()
            except ValueError:
                body = {}
            try:
                thread = STORE.create_thread(conversation_id, str(body.get("title") or "New thread"))
                self.send_json(thread, status=201)
            except KeyError:
                self.send_error(404, "Conversation not found")
            return
        if path == "/api/session":
            try:
                body = self.read_json()
            except ValueError as exc:
                self.send_json({"error": str(exc)}, status=400)
                return
            session_id = str(body.get("session_id") or "").strip() or self.session_id_from_request()
            session = STORE.get_or_create_session(session_id or None)
            session = STORE.update_session_context(
                session["id"],
                active_project=optional_text(body, "active_project"),
                current_workspace=optional_dict(body, "current_workspace"),
                running_task=optional_text(body, "running_task"),
                active_file=optional_text(body, "active_file"),
                open_files=optional_string_list(body, "open_files"),
                active_tool=optional_text(body, "active_tool"),
                terminal_output=optional_text(body, "terminal_output"),
                browser_results=optional_text(body, "browser_results"),
                mcp_outputs=optional_text(body, "mcp_outputs"),
                developer_instructions=optional_text(body, "developer_instructions"),
                user_preferences=optional_dict(body, "user_preferences"),
            )
            index_long_term_memory(STORE.get_long_term_memory())
            self.send_json({"session": session})
            return
        if path == "/api/memory":
            try:
                body = self.read_json()
            except ValueError as exc:
                self.send_json({"error": str(exc)}, status=400)
                return
            memory = STORE.update_long_term_memory(
                user_preferences=optional_dict(body, "user_preferences"),
                coding_style=optional_string_list(body, "coding_style"),
                projects=optional_project_list(body, "projects"),
                commands=optional_string_list(body, "commands"),
                learned_behavior=optional_string_list(body, "learned_behavior"),
            )
            index_long_term_memory(memory)
            self.send_json({"memory": memory})
            return
        if path == "/api/uploads":
            try:
                artifacts = self.receive_uploads()
            except ValueError as exc:
                self.send_json({"error": str(exc)}, status=400)
                return
            self.send_json({"artifacts": artifacts}, status=201)
            return
        if path == "/api/chat":
            try:
                body = self.read_json()
            except ValueError as exc:
                self.send_json({"error": str(exc)}, status=400)
                return

            message = str(body.get("message", "")).strip()
            conversation_id = body.get("conversation_id")
            thread_id = str(body.get("thread_id") or "").strip() or None
            artifact_ids = optional_string_list(body, "artifact_ids") or []
            memory_variables = optional_dict(body, "variables") or {}
            session_id = str(body.get("session_id") or "").strip() or self.session_id_from_request()
            if not message:
                self.send_error(400, "Message is required")
                return
            session = STORE.get_or_create_session(session_id or None)
            if not conversation_id:
                conversation_id = STORE.create_conversation(session_id=session["id"])["id"]
            try:
                STORE.set_recovery_state(
                    conversation_id,
                    {"status": "running", "thread_id": thread_id or "main", "updated_at": utc_now()},
                )
                user_message = STORE.add_message(conversation_id, "user", message, thread_id=thread_id)
                upsert_vector_records([vector_record_for_message(conversation_id, user_message)])
                memory = STORE.update_short_term_memory(
                    conversation_id,
                    artifact_ids=artifact_ids,
                    task=session.get("running_task", ""),
                    variables=memory_variables,
                    tool_outputs={
                        "terminal": session.get("terminal_output", ""),
                        "browser": session.get("browser_results", ""),
                        "mcp": session.get("mcp_outputs", ""),
                    },
                )
                conversation = STORE.get_conversation(conversation_id)
                thread_id = thread_id or conversation.get("active_thread_id") or "main"
                context_window_tokens = session["user_preferences"]["context_window_tokens"]
                llm_messages = conversation_messages_for_llm(
                    conversation["messages"],
                    max_tokens=context_window_tokens,
                    thread_id=thread_id,
                    summary=conversation.get("summary", ""),
                )
                llm_messages = build_context_messages(
                    session,
                    llm_messages,
                    artifact_ids=artifact_ids,
                    short_term_memory=memory,
                    long_term_memory=STORE.get_long_term_memory(),
                    max_tokens=context_window_tokens,
                )
                context_token_count = count_message_tokens(llm_messages)
                if body.get("stream"):
                    self.send_chat_stream(
                        session["id"],
                        conversation_id,
                        thread_id,
                        llm_messages,
                        context_token_count,
                        context_window_tokens,
                    )
                    return
                assistant_text, provider = generate_response(llm_messages)
                assistant_message = STORE.add_message(conversation_id, "assistant", assistant_text, thread_id=thread_id)
                upsert_vector_records([vector_record_for_message(conversation_id, assistant_message)])
                STORE.update_short_term_memory(conversation_id)
                STORE.set_recovery_state(conversation_id, {"status": "complete", "thread_id": thread_id})
                self.send_json(
                    {
                        "session_id": session["id"],
                        "conversation_id": conversation_id,
                        "thread_id": thread_id,
                        "context_token_count": context_token_count,
                        "context_window_tokens": context_window_tokens,
                        "provider": provider,
                        "message": {"role": "assistant", "content": assistant_text},
                    }
                )
            except KeyError:
                self.send_error(404, "Conversation not found")
            except LLMError as exc:
                self.send_json({"error": str(exc)}, status=502)
            return
        self.send_error(404, "Not found")

    def receive_uploads(self) -> list[dict[str, Any]]:
        raw_length = self.headers.get("Content-Length", "0").strip()
        length = int(raw_length or "0")
        if length <= 0:
            raise ValueError("No upload body received.")
        if length > MAX_UPLOAD_BYTES:
            raise ValueError(f"Upload is too large. Limit is {MAX_UPLOAD_BYTES} bytes.")

        content_type = self.headers.get("Content-Type", "")
        body = self.rfile.read(length)
        files = parse_multipart_files(content_type, body)
        if not files:
            raise ValueError("No files were uploaded.")

        UPLOAD_ROOT.mkdir(parents=True, exist_ok=True)
        artifacts = load_artifacts()
        created: list[dict[str, Any]] = []
        for item in files:
            artifact_id = str(uuid4())
            filename = safe_filename(item["filename"])
            target = UPLOAD_ROOT / f"{artifact_id}-{filename}"
            content = item["content"]
            target.write_bytes(content)
            document = document_metadata_for_upload(filename, item["content_type"], content, target)
            artifact = {
                "id": artifact_id,
                "filename": filename,
                "content_type": item["content_type"],
                "size": len(content),
                "category": artifact_category(filename, item["content_type"]),
                "path": str(target.relative_to(ROOT)),
                "preview": document["preview"],
                "document_type": document["document_type"],
                "extracted_text": document["extracted_text"],
                "cleaned_text": document["cleaned_text"],
                "chunks": document["chunks"],
                "ocr_status": document["ocr_status"],
                "ocr_error": document["ocr_error"],
                "metadata": document["metadata"],
            }
            vector_records = vector_records_for_artifact(artifact)
            artifact["metadata"]["embedding_model"] = EMBEDDING_MODEL
            artifact["metadata"]["embedding_dimensions"] = EMBEDDING_DIMENSIONS
            artifact["metadata"]["vector_count"] = len(vector_records)
            upsert_vector_records(vector_records)
            artifacts.insert(0, artifact)
            created.append(artifact)
        save_artifacts(artifacts)
        return created

    def send_chat_stream(
        self,
        session_id: str,
        conversation_id: str,
        thread_id: str,
        llm_messages: list[dict[str, str]],
        context_token_count: int,
        context_window_tokens: int,
    ) -> None:
        assistant_parts: list[str] = []
        self.send_response(200)
        self.send_header("Content-Type", "application/x-ndjson; charset=utf-8")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.end_headers()

        try:
            self.write_ndjson_event(
                {
                    "type": "meta",
                    "session_id": session_id,
                    "conversation_id": conversation_id,
                    "thread_id": thread_id,
                    "context_token_count": context_token_count,
                    "context_window_tokens": context_window_tokens,
                    "provider": "selecting",
                }
            )
            self.write_ndjson_event(
                {
                    "type": "progress",
                    "stage": "request",
                    "message": "Preparing conversation context",
                }
            )
            self.write_ndjson_event(
                {
                    "type": "progress",
                    "stage": "model",
                    "message": "Connecting to model stream",
                }
            )
            chunks, provider = generate_response_stream(llm_messages)
            self.write_ndjson_event(
                {
                    "type": "meta",
                    "session_id": session_id,
                    "conversation_id": conversation_id,
                    "thread_id": thread_id,
                    "context_token_count": context_token_count,
                    "context_window_tokens": context_window_tokens,
                    "provider": provider,
                }
            )
            self.write_ndjson_event(
                {"type": "progress", "stage": "model", "message": "Model stream connected. Waiting for first token"}
            )
            wrote_token = False
            for chunk in iter_stream_chunks(chunks, chunk_size=8):
                if not wrote_token:
                    self.write_ndjson_event(
                        {
                            "type": "progress",
                            "stage": "stream",
                            "message": "Streaming response",
                        }
                    )
                    wrote_token = True
                assistant_parts.append(chunk)
                self.write_ndjson_event({"type": "delta", "content": chunk})

            assistant_text = "".join(assistant_parts).strip()
            self.write_ndjson_event(
                {"type": "progress", "stage": "storage", "message": "Saving assistant reply"}
            )
            assistant_message = STORE.add_message(conversation_id, "assistant", assistant_text, thread_id=thread_id)
            upsert_vector_records([vector_record_for_message(conversation_id, assistant_message)])
            STORE.update_short_term_memory(conversation_id)
            STORE.set_recovery_state(conversation_id, {"status": "complete", "thread_id": thread_id})
            self.write_ndjson_event(
                {
                    "type": "done",
                    "message": {"role": "assistant", "content": assistant_text},
                }
            )
        except LLMError as exc:
            self.write_ndjson_event({"type": "error", "error": str(exc)})
        except (BrokenPipeError, ConnectionResetError):
            assistant_text = "".join(assistant_parts).strip()
            if assistant_text:
                STORE.add_message(
                    conversation_id,
                    "assistant",
                    f"{assistant_text}\n\n[Stream interrupted before completion.]",
                    thread_id=thread_id,
                )
            STORE.set_recovery_state(conversation_id, {"status": "interrupted", "thread_id": thread_id})
            return

    def serve_static(self, path: str) -> None:
        relative = "index.html" if path == "/" else path.lstrip("/")
        target = (WEB_ROOT / relative).resolve()
        if WEB_ROOT not in target.parents and target != WEB_ROOT:
            self.send_error(403, "Forbidden")
            return
        if not target.exists() or target.is_dir():
            self.send_error(404, "Not found")
            return
        content_type = mimetypes.guess_type(target.name)[0] or "application/octet-stream"
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.end_headers()
        self.wfile.write(target.read_bytes())

    def serve_upload(self, artifact_id: str) -> None:
        artifact = find_artifact(artifact_id)
        if not artifact:
            self.send_error(404, "Upload not found")
            return

        target = (ROOT / artifact["path"]).resolve()
        if UPLOAD_ROOT.resolve() not in target.parents:
            self.send_error(403, "Forbidden")
            return
        if not target.exists() or target.is_dir():
            self.send_error(404, "Upload file not found")
            return

        self.send_response(200)
        self.send_header("Content-Type", artifact["content_type"])
        self.send_header("Content-Length", str(target.stat().st_size))
        self.end_headers()
        self.wfile.write(target.read_bytes())

    def read_json(self) -> dict[str, Any]:
        raw_length = self.headers.get("Content-Length", "0").strip()
        if not raw_length:
            return {}
        try:
            length = int(raw_length)
        except ValueError as exc:
            raise ValueError("Invalid Content-Length header") from exc
        raw = self.rfile.read(length).decode("utf-8")
        return parse_json_body(raw)

    def session_id_from_request(self, query: str = "") -> str:
        for key, value in parse_qsl(query, keep_blank_values=False):
            if key == "session_id" and value.strip():
                return value.strip()
        return self.headers.get("X-AIOS-Session-Id", "").strip()

    def send_json(self, payload: dict[str, Any], status: int = 200) -> None:
        body = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def write_ndjson_event(self, payload: dict[str, Any]) -> None:
        self.wfile.write(serialize_ndjson_event(payload))
        self.wfile.flush()

    def log_message(self, format: str, *args: Any) -> None:
        print(f"[aios] {self.address_string()} - {format % args}")


def compact_conversations(conversations: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        {
            "id": item["id"],
            "session_id": item.get("session_id"),
            "title": item["title"],
            "created_at": item["created_at"],
            "updated_at": item["updated_at"],
            "message_count": len(item["messages"]),
        }
        for item in conversations
    ]


def conversation_messages_for_llm(
    messages: list[dict[str, Any]],
    max_tokens: int = 4000,
    thread_id: str | None = None,
    summary: str = "",
) -> list[dict[str, str]]:
    selected: list[dict[str, str]] = []
    token_count = 0
    for item in reversed(messages):
        if item["role"] not in {"user", "assistant"}:
            continue
        if thread_id and item.get("thread_id") != thread_id:
            continue
        message = {"role": item["role"], "content": item["content"]}
        message_tokens = count_message_tokens([message])
        if selected and token_count + message_tokens > max_tokens:
            break
        selected.append(message)
        token_count += message_tokens
    selected = list(reversed(selected))
    if summary:
        summary_message = {
            "role": "system",
            "content": f"Conversation summary for compressed older context: {summary}",
        }
        if count_message_tokens([summary_message, *selected]) <= max_tokens:
            selected.insert(0, summary_message)
    return selected


def build_context_messages(
    session: dict[str, Any],
    messages: list[dict[str, str]],
    artifact_ids: list[str] | None = None,
    short_term_memory: dict[str, Any] | None = None,
    long_term_memory: dict[str, Any] | None = None,
    max_tokens: int = 4000,
) -> list[dict[str, str]]:
    base_messages = fit_messages_to_token_window(messages, max_tokens)
    retrieval_query = latest_user_message(base_messages)
    memory = short_term_memory or {}
    remembered_artifacts = memory.get("artifact_ids", []) if isinstance(memory, dict) else []
    effective_artifact_ids = list(dict.fromkeys([*(artifact_ids or []), *remembered_artifacts]))
    sections = remove_duplicate_context_sections(
        rank_context_sections(
            context_sections(session, effective_artifact_ids, retrieval_query, memory, long_term_memory or {})
        )
    )
    selected_sections: list[str] = []
    for section in sections:
        text = section["text"]
        candidate = selected_sections + [text]
        candidate_message = context_message_from_sections(candidate)
        if count_message_tokens([candidate_message, *base_messages]) <= max_tokens:
            selected_sections.append(text)
            continue

        remaining = max_tokens - count_message_tokens([context_message_from_sections(selected_sections), *base_messages])
        compressed = compress_context_text(text, max(80, remaining))
        if compressed == text:
            continue
        candidate_message = context_message_from_sections(selected_sections + [compressed])
        if count_message_tokens([candidate_message, *base_messages]) <= max_tokens:
            selected_sections.append(compressed)

    if not selected_sections:
        return base_messages
    return fit_messages_to_token_window([context_message_from_sections(selected_sections), *base_messages], max_tokens)


def context_sections(
    session: dict[str, Any], artifact_ids: list[str], retrieval_query: str = "",
    short_term_memory: dict[str, Any] | None = None,
    long_term_memory: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    return [
        {"name": "developer_instructions", "priority": 100, "text": developer_instructions_context_text(session)},
        {"name": "project", "priority": 95, "text": project_context_text(session)},
        {"name": "running_task", "priority": 92, "text": running_task_state_context_text(session)},
        {"name": "short_term_memory", "priority": 90, "text": short_term_memory_context_text(short_term_memory or {})},
        {"name": "long_term_memory", "priority": 89, "text": long_term_memory_context_text(long_term_memory or {})},
        {"name": "user_preferences", "priority": 88, "text": user_preferences_context_text(session)},
        {"name": "retrieved_context", "priority": 86, "text": retrieved_context_text(retrieval_query)},
        {"name": "uploaded_files", "priority": 82, "text": uploaded_files_context_text(artifact_ids)},
        {"name": "open_files", "priority": 80, "text": open_files_context_text(session)},
        {"name": "git_status", "priority": 72, "text": git_status_context_text()},
        {"name": "terminal_output", "priority": 65, "text": terminal_output_context_text(session)},
        {"name": "mcp_outputs", "priority": 62, "text": mcp_outputs_context_text(session)},
        {"name": "browser_results", "priority": 60, "text": browser_results_context_text(session)},
    ]


def short_term_memory_context_text(memory: dict[str, Any]) -> str:
    task = str(memory.get("task") or "").strip()
    variables = memory.get("variables") if isinstance(memory.get("variables"), dict) else {}
    tool_outputs = memory.get("tool_outputs") if isinstance(memory.get("tool_outputs"), dict) else {}
    lines = [f"Current task: {task}" if task else ""]
    if variables:
        lines.append("Working variables: " + json.dumps(variables, ensure_ascii=False, default=str))
    for name, output in tool_outputs.items():
        value = str(output).strip()
        if value:
            lines.append(f"Recent {name} output: {value[-2000:]}")
    rendered = [line for line in lines if line]
    return "Short-term conversation memory:\n" + "\n".join(rendered) if rendered else ""


def long_term_memory_context_text(memory: dict[str, Any]) -> str:
    sections: list[str] = []
    preferences = memory.get("user_preferences")
    if isinstance(preferences, dict) and preferences:
        sections.append("User preferences: " + json.dumps(preferences, ensure_ascii=False, default=str))
    for key, label in (
        ("coding_style", "Coding style"),
        ("projects", "Known projects"),
        ("commands", "Frequently used commands"),
        ("learned_behavior", "Learned behavior"),
    ):
        values = memory.get(key)
        if isinstance(values, list) and values:
            sections.append(f"{label}: " + json.dumps(values[-20:], ensure_ascii=False, default=str))
    return "Long-term user memory:\n" + "\n".join(sections) if sections else ""


def rank_context_sections(sections: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return sorted(
        [section for section in sections if str(section.get("text", "")).strip()],
        key=lambda item: (-int(item.get("priority", 0)), str(item.get("name", ""))),
    )


def remove_duplicate_context_sections(sections: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen: set[str] = set()
    unique: list[dict[str, Any]] = []
    for section in sections:
        key = re.sub(r"\s+", " ", str(section.get("text", "")).strip().lower())
        if not key or key in seen:
            continue
        seen.add(key)
        unique.append(section)
    return unique


def compress_context_text(text: str, max_tokens: int) -> str:
    if estimate_tokens(text) <= max_tokens:
        return text
    max_chars = max(240, max_tokens * 4)
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    compressed = "\n".join(lines[:12])
    if len(compressed) > max_chars:
        compressed = compressed[:max_chars].rsplit(" ", 1)[0]
    return f"{compressed}\n[Context compressed to fit the model window.]"


def context_message_from_sections(sections: list[str]) -> dict[str, str]:
    context = "\n\n".join(section for section in sections if section.strip())
    return {"role": "system", "content": f"Context builder:\n{context}"}


def latest_user_message(messages: list[dict[str, str]]) -> str:
    for message in reversed(messages):
        if message.get("role") == "user":
            return str(message.get("content") or "").strip()
    return ""


def fit_messages_to_token_window(messages: list[dict[str, str]], max_tokens: int) -> list[dict[str, str]]:
    fitted = list(messages)
    while len(fitted) > 1 and count_message_tokens(fitted) > max_tokens:
        remove_at = 1 if fitted[0].get("role") == "system" else 0
        fitted.pop(remove_at)
    if fitted and count_message_tokens(fitted) > max_tokens:
        latest = fitted[-1]
        fitted[-1] = {
            **latest,
            "content": compress_context_text(latest.get("content", ""), max_tokens),
        }
    return fitted


def project_context_text(session: dict[str, Any]) -> str:
    workspace = session.get("current_workspace") or {}
    lines = [
        ("Active project", session.get("active_project")),
        ("Workspace", " - ".join(str(workspace.get(key, "")).strip() for key in ("name", "focus") if str(workspace.get(key, "")).strip())),
        ("Running task", session.get("running_task")),
        ("Active tool", session.get("active_tool")),
    ]
    rendered = [f"{label}: {value}" for label, value in lines if value]
    return "Current project context:\n" + "\n".join(rendered) if rendered else ""


def uploaded_files_context_text(artifact_ids: list[str]) -> str:
    if not artifact_ids:
        return ""
    artifacts = [
        artifact
        for artifact in list_artifacts()
        if artifact.get("id") in set(artifact_ids)
    ]
    if not artifacts:
        return ""
    lines = ["Uploaded files:"]
    for artifact in artifacts[:8]:
        preview = str(artifact.get("cleaned_text") or artifact.get("extracted_text") or artifact.get("preview") or "").strip()
        preview_text_value = f"\nExtracted text:\n{preview[:1600]}" if preview else ""
        ocr_status = str(artifact.get("ocr_status") or "").strip()
        ocr_text = f", ocr={ocr_status}" if ocr_status else ""
        ocr_error = str(artifact.get("ocr_error") or "").strip()
        metadata = artifact.get("metadata") if isinstance(artifact.get("metadata"), dict) else {}
        chunk_count = metadata.get("chunk_count") or len(artifact.get("chunks") or [])
        chunk_text = f", chunks={chunk_count}" if chunk_count else ""
        extraction_note = ""
        if not preview:
            extraction_note = "\nExtraction note: No text was extracted from this attachment. If it is an image or scanned document, OCR or vision support is required to summarize its visual content."
        elif ocr_error:
            extraction_note = f"\nExtraction note: {ocr_error[:400]}"
        lines.append(
            f"- {artifact.get('filename')} ({artifact.get('category')}, {format_bytes(int(artifact.get('size', 0)))}{ocr_text}{chunk_text}){preview_text_value}{extraction_note}"
        )
    return "\n".join(lines)


def open_files_context_text(session: dict[str, Any]) -> str:
    paths = []
    active_file = str(session.get("active_file") or "").strip()
    if active_file:
        paths.append(active_file)
    paths.extend(str(item).strip() for item in session.get("open_files", []) if str(item).strip())
    unique_paths = list(dict.fromkeys(paths))[:8]
    if not unique_paths:
        return ""
    snippets = []
    for path in unique_paths:
        snippet = read_workspace_file_snippet(path)
        if snippet:
            snippets.append(snippet)
    return "Open files:\n" + "\n\n".join(snippets) if snippets else ""


def terminal_output_context_text(session: dict[str, Any]) -> str:
    output = str(session.get("terminal_output") or "").strip()
    if not output:
        return ""
    return f"Recent terminal output:\n{output[-4000:]}"


def git_status_context_text() -> str:
    try:
        result = subprocess.run(
            ["git", "status", "--short", "--branch"],
            cwd=ROOT,
            capture_output=True,
            text=True,
            timeout=3,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return ""
    output = (result.stdout or result.stderr or "").strip()
    if not output:
        return "Git status:\nClean working tree."
    return f"Git status:\n{output[:4000]}"


def browser_results_context_text(session: dict[str, Any]) -> str:
    results = str(session.get("browser_results") or "").strip()
    if not results:
        return ""
    return f"Browser results:\n{results[-4000:]}"


def mcp_outputs_context_text(session: dict[str, Any]) -> str:
    outputs = str(session.get("mcp_outputs") or "").strip()
    if not outputs:
        return ""
    return f"MCP outputs:\n{outputs[-4000:]}"


def running_task_state_context_text(session: dict[str, Any]) -> str:
    task = str(session.get("running_task") or "").strip()
    active_file = str(session.get("active_file") or "").strip()
    active_tool = str(session.get("active_tool") or "").strip()
    parts = [
        f"Task: {task}" if task else "",
        f"Active file: {active_file}" if active_file else "",
        f"Active tool: {active_tool}" if active_tool else "",
    ]
    rendered = [item for item in parts if item]
    return "Running task state:\n" + "\n".join(rendered) if rendered else ""


def developer_instructions_context_text(session: dict[str, Any]) -> str:
    instructions = str(session.get("developer_instructions") or "").strip()
    if not instructions:
        return ""
    return f"Developer instructions:\n{instructions[-4000:]}"


def user_preferences_context_text(session: dict[str, Any]) -> str:
    preferences = session.get("user_preferences") or {}
    if not preferences:
        return ""
    lines = [
        f"Provider mode: {preferences.get('provider_mode', 'auto')}",
        f"Compact mode: {bool(preferences.get('compact_mode', False))}",
        f"Context window tokens: {preferences.get('context_window_tokens', 4000)}",
    ]
    return "User preferences:\n" + "\n".join(lines)


def read_workspace_file_snippet(path_value: str, limit: int = 4000) -> str:
    target = (ROOT / path_value).resolve()
    if target != ROOT and ROOT not in target.parents:
        return ""
    if not target.exists() or not target.is_file():
        return ""
    try:
        content = target.read_text(encoding="utf-8", errors="replace")[:limit]
    except OSError:
        return ""
    relative = target.relative_to(ROOT)
    return f"{relative}:\n{content}"


def count_message_tokens(messages: list[dict[str, str]]) -> int:
    return sum(
        estimate_tokens(item.get("role", ""))
        + estimate_tokens(item.get("content", ""))
        + 4
        for item in messages
    )


def estimate_tokens(text: str) -> int:
    if not text:
        return 0
    pieces = re.findall(r"\w+|[^\w\s]", text, flags=re.UNICODE)
    return max(1, int(len(pieces) * 1.3))


def parse_json_body(raw: str) -> dict[str, Any]:
    if not raw or not raw.strip():
        return {}

    cleaned = raw.lstrip("\ufeff").strip()
    if not cleaned:
        return {}

    if cleaned.startswith("{") or cleaned.startswith("["):
        try:
            payload = json.loads(cleaned)
        except json.JSONDecodeError as exc:
            raise ValueError(f"Invalid JSON body: {exc}") from exc
        if not isinstance(payload, dict):
            raise ValueError("JSON body must be an object")
        return payload

    if "=" in cleaned:
        return dict(parse_qsl(cleaned, keep_blank_values=True))

    raise ValueError(f"Invalid JSON body: {cleaned}")


def optional_text(payload: dict[str, Any], key: str) -> str | None:
    if key not in payload:
        return None
    return str(payload.get(key) or "").strip()


def optional_dict(payload: dict[str, Any], key: str) -> dict[str, Any] | None:
    value = payload.get(key)
    return value if isinstance(value, dict) else None


def optional_string_list(payload: dict[str, Any], key: str) -> list[str] | None:
    value = payload.get(key)
    if not isinstance(value, list):
        return None
    return [str(item).strip() for item in value if str(item).strip()]


def optional_project_list(payload: dict[str, Any], key: str) -> list[dict[str, Any] | str] | None:
    value = payload.get(key)
    if not isinstance(value, list):
        return None
    return [item for item in value if isinstance(item, (dict, str))]


def format_bytes(bytes_value: int) -> str:
    if bytes_value < 1024:
        return f"{bytes_value} B"
    if bytes_value < 1024 * 1024:
        return f"{bytes_value / 1024:.1f} KB"
    return f"{bytes_value / (1024 * 1024):.1f} MB"


def parse_multipart_files(content_type: str, body: bytes) -> list[dict[str, Any]]:
    if "multipart/form-data" not in content_type:
        raise ValueError("Uploads must use multipart/form-data.")

    message = BytesParser(policy=default).parsebytes(
        f"Content-Type: {content_type}\r\nMIME-Version: 1.0\r\n\r\n".encode("utf-8") + body
    )
    files: list[dict[str, Any]] = []
    for part in message.iter_parts():
        filename = part.get_filename()
        if not filename:
            continue
        content = part.get_payload(decode=True) or b""
        files.append(
            {
                "filename": filename,
                "content_type": part.get_content_type() or "application/octet-stream",
                "content": content,
            }
        )
    return files


def safe_filename(filename: str) -> str:
    cleaned = Path(filename).name.strip() or "upload"
    cleaned = re.sub(r"[^A-Za-z0-9._ -]+", "-", cleaned)
    return cleaned[:120] or "upload"


def artifact_category(filename: str, content_type: str) -> str:
    lowered = filename.lower()
    if content_type.startswith("image/"):
        return "image"
    if content_type.startswith("audio/"):
        return "audio"
    if content_type == "application/pdf" or lowered.endswith(".pdf"):
        return "pdf"
    if content_type.startswith("text/") or lowered.endswith((".txt", ".md", ".json", ".csv", ".py", ".js", ".html", ".css")):
        return "file"
    if lowered.endswith((".doc", ".docx", ".rtf", ".odt")):
        return "document"
    return "file"


def preview_text(filename: str, content_type: str, content: bytes, limit: int = 4000) -> str:
    if artifact_category(filename, content_type) != "file":
        return ""
    try:
        return content[:limit].decode("utf-8", errors="replace")
    except UnicodeDecodeError:
        return ""


def document_metadata_for_upload(
    filename: str,
    content_type: str,
    content: bytes,
    path: Path,
    limit: int = 12000,
) -> dict[str, Any]:
    category = artifact_category(filename, content_type)
    document_type = document_type_for_upload(filename, content_type, category)
    extracted_text = ""
    ocr_status = "not_required"
    ocr_error = ""

    if category == "file":
        extracted_text = decode_text_content(content, limit=limit)
    elif category == "image":
        extracted_text, ocr_status, ocr_error = ocr_image_file(path)
    elif category == "pdf":
        extracted_text, text_error = extract_pdf_text_file(path)
        if not extracted_text:
            extracted_text = extract_pdf_text_pymupdf(path, limit=limit)
        if not extracted_text:
            extracted_text = usable_extracted_text(extract_pdf_text_basic(content, limit=limit))
        if extracted_text:
            ocr_status = "not_required"
        else:
            extracted_text, ocr_status, ocr_error = ocr_pdf_file(path)
            if text_error and not ocr_error:
                ocr_error = text_error
    elif category == "document":
        ocr_status = "unsupported"
        ocr_error = "Binary office documents are stored, but text extraction is not available yet."

    cleaned_text = clean_extracted_text(extracted_text)[:limit]
    chunks = chunk_document_text(cleaned_text)
    return {
        "document_type": document_type,
        "extracted_text": cleaned_text,
        "cleaned_text": cleaned_text,
        "preview": cleaned_text[:4000],
        "chunks": chunks,
        "ocr_status": ocr_status,
        "ocr_error": ocr_error,
        "metadata": extract_document_metadata(
            filename=filename,
            content_type=content_type,
            content=content,
            category=category,
            document_type=document_type,
            cleaned_text=cleaned_text,
            chunks=chunks,
            ocr_status=ocr_status,
        ),
    }


def document_type_for_upload(filename: str, content_type: str, category: str) -> str:
    lowered = filename.lower()
    if category == "pdf":
        return "pdf"
    if category == "image":
        return "scanned_image"
    if category == "document":
        return Path(lowered).suffix.lstrip(".") or "document"
    if content_type.startswith("text/") or lowered.endswith((".txt", ".md", ".csv")):
        return "text"
    if lowered.endswith((".json", ".py", ".js", ".html", ".css")):
        return "code"
    return category


def decode_text_content(content: bytes, limit: int = 12000) -> str:
    try:
        return content[:limit].decode("utf-8", errors="replace")
    except UnicodeDecodeError:
        return ""


def clean_extracted_text(text: str) -> str:
    text = text.replace("\x00", " ").replace("\f", "\n")
    text = "".join(char if char == "\n" or char == "\t" or ord(char) >= 32 else " " for char in text)
    text = re.sub(r"(?<=\w)-\n(?=\w)", "", text)
    text = re.sub(r"[^\S\n]+", " ", text)
    text = re.sub(r" *\n *", "\n", text)
    text = re.sub(r"([A-Za-z0-9])\s+([,.;:!?])", r"\1\2", text)
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def usable_extracted_text(text: str, min_letters_ratio: float = 0.45, min_length: int = 12) -> str:
    text = clean_extracted_text(text)
    if len(text) < min_length:
        return ""
    visible = [char for char in text if not char.isspace()]
    if not visible:
        return ""
    letters = sum(1 for char in visible if char.isalpha())
    controls = sum(1 for char in text if ord(char) < 32 and char not in "\n\t")
    replacement_chars = text.count("\ufffd")
    if controls or replacement_chars:
        return ""
    if letters / len(visible) < min_letters_ratio:
        return ""
    readable = sum(1 for char in visible if char.isascii() and (char.isalnum() or char in ".,;:!?()[]{}+-_/|@#%&*'\"=<>"))
    if readable / len(visible) < 0.55:
        return ""
    return text


def chunk_document_text(
    text: str,
    chunk_size: int = 1200,
    overlap: int = 160,
) -> list[dict[str, Any]]:
    text = clean_extracted_text(text)
    if not text:
        return []

    chunk_size = max(200, chunk_size)
    overlap = max(0, min(overlap, chunk_size // 2))
    chunks: list[dict[str, Any]] = []
    start = 0
    text_length = len(text)
    while start < text_length:
        end = min(start + chunk_size, text_length)
        if end < text_length:
            boundary = max(text.rfind("\n\n", start, end), text.rfind(". ", start, end), text.rfind("\n", start, end))
            if boundary > start + chunk_size // 2:
                end = boundary + 1
        chunk_text_value = text[start:end].strip()
        if chunk_text_value:
            chunk_index = len(chunks) + 1
            chunks.append(
                {
                    "id": f"chunk-{chunk_index:04d}",
                    "index": chunk_index - 1,
                    "text": chunk_text_value,
                    "start_char": start,
                    "end_char": end,
                    "char_count": len(chunk_text_value),
                    "word_count": len(re.findall(r"\w+", chunk_text_value)),
                }
            )
        if end >= text_length:
            break
        start = max(end - overlap, start + 1)
    return chunks


def extract_document_metadata(
    filename: str,
    content_type: str,
    content: bytes,
    category: str,
    document_type: str,
    cleaned_text: str,
    chunks: list[dict[str, Any]],
    ocr_status: str,
) -> dict[str, Any]:
    extension = Path(filename).suffix.lower()
    words = re.findall(r"\w+", cleaned_text)
    return {
        "filename": filename,
        "extension": extension,
        "content_type": content_type,
        "category": category,
        "document_type": document_type,
        "byte_size": len(content),
        "sha256": hashlib.sha256(content).hexdigest(),
        "text_length": len(cleaned_text),
        "word_count": len(words),
        "line_count": len(cleaned_text.splitlines()) if cleaned_text else 0,
        "chunk_count": len(chunks),
        "average_chunk_words": round(sum(chunk["word_count"] for chunk in chunks) / len(chunks), 2) if chunks else 0,
        "ocr_status": ocr_status,
        "scanned_candidate": category in {"image", "pdf"} and not cleaned_text,
        "processed_at": utc_now(),
    }


def generate_embedding(text: str, dimensions: int = EMBEDDING_DIMENSIONS) -> list[float]:
    dimensions = max(8, dimensions)
    vector = [0.0] * dimensions
    tokens = re.findall(r"[A-Za-z0-9_]+", text.lower())
    if not tokens:
        return vector

    for token in tokens:
        digest = hashlib.sha256(token.encode("utf-8")).digest()
        bucket = int.from_bytes(digest[:4], "big") % dimensions
        sign = 1.0 if digest[4] % 2 == 0 else -1.0
        vector[bucket] += sign

    magnitude = sum(value * value for value in vector) ** 0.5
    if not magnitude:
        return vector
    return [round(value / magnitude, 6) for value in vector]


def vector_records_for_artifact(artifact: dict[str, Any]) -> list[dict[str, Any]]:
    chunks = artifact.get("chunks") if isinstance(artifact.get("chunks"), list) else []
    records: list[dict[str, Any]] = []
    for chunk in chunks:
        text = str(chunk.get("text") or "").strip()
        if not text:
            continue
        chunk_id = str(chunk.get("id") or f"chunk-{int(chunk.get('index', 0)) + 1:04d}")
        record_id = f"{artifact['id']}:{chunk_id}"
        records.append(
            {
                "id": record_id,
                "source_type": "document",
                "artifact_id": artifact["id"],
                "chunk_id": chunk_id,
                "chunk_index": int(chunk.get("index", len(records))),
                "filename": artifact.get("filename", ""),
                "document_type": artifact.get("document_type", ""),
                "text": text,
                "embedding": generate_embedding(text),
                "embedding_model": EMBEDDING_MODEL,
                "embedding_dimensions": EMBEDDING_DIMENSIONS,
                "metadata": {
                    "category": artifact.get("category", ""),
                    "content_type": artifact.get("content_type", ""),
                    "start_char": chunk.get("start_char", 0),
                    "end_char": chunk.get("end_char", 0),
                    "word_count": chunk.get("word_count", 0),
                    "source_path": artifact.get("path", ""),
                },
                "created_at": utc_now(),
            }
        )
    return records


def vector_record_for_message(conversation_id: str, message: dict[str, Any]) -> dict[str, Any]:
    text = str(message.get("content") or "").strip()
    message_id = str(message.get("id") or uuid4())
    return {
        "id": f"conversation:{conversation_id}:{message_id}",
        "source_type": "conversation",
        "source_id": conversation_id,
        "conversation_id": conversation_id,
        "message_id": message_id,
        "filename": f"conversation-{conversation_id[:8]}",
        "document_type": "conversation",
        "text": text,
        "embedding": generate_embedding(text),
        "embedding_model": EMBEDDING_MODEL,
        "embedding_dimensions": EMBEDDING_DIMENSIONS,
        "metadata": {
            "role": str(message.get("role") or ""),
            "thread_id": str(message.get("thread_id") or "main"),
            "created_at": str(message.get("created_at") or utc_now()),
        },
        "created_at": utc_now(),
    }


def index_conversation_history(conversations: list[dict[str, Any]]) -> None:
    records = [
        vector_record_for_message(str(conversation.get("id") or "unknown"), message)
        for conversation in conversations
        for message in conversation.get("messages", [])
        if message.get("role") in {"user", "assistant"} and str(message.get("content") or "").strip()
    ]
    upsert_vector_records(records)


def vector_records_for_long_term_memory(memory: dict[str, Any]) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    fields = ("coding_style", "projects", "commands", "learned_behavior")
    for field in fields:
        values = memory.get(field) if isinstance(memory.get(field), list) else []
        for index, value in enumerate(values):
            text = json.dumps(value, ensure_ascii=False, default=str) if isinstance(value, dict) else str(value)
            if not text.strip():
                continue
            digest = hashlib.sha256(f"{field}:{text}".encode("utf-8")).hexdigest()[:16]
            records.append({
                "id": f"memory:{field}:{digest}", "source_type": "memory", "source_id": field,
                "filename": "long-term-memory", "document_type": field, "text": text,
                "embedding": generate_embedding(text), "embedding_model": EMBEDDING_MODEL,
                "embedding_dimensions": EMBEDDING_DIMENSIONS,
                "metadata": {"memory_field": field, "item_index": index}, "created_at": utc_now(),
            })
    preferences = memory.get("user_preferences")
    if isinstance(preferences, dict) and preferences:
        text = json.dumps(preferences, ensure_ascii=False, default=str)
        records.append({
            "id": "memory:user_preferences", "source_type": "memory", "source_id": "user_preferences",
            "filename": "long-term-memory", "document_type": "user_preferences", "text": text,
            "embedding": generate_embedding(text), "embedding_model": EMBEDDING_MODEL,
            "embedding_dimensions": EMBEDDING_DIMENSIONS,
            "metadata": {"memory_field": "user_preferences"}, "created_at": utc_now(),
        })
    return records


def index_long_term_memory(memory: dict[str, Any]) -> None:
    replace_vector_source("memory", vector_records_for_long_term_memory(memory))


def load_vector_records() -> list[dict[str, Any]]:
    if not VECTOR_INDEX.exists():
        return []
    with VECTOR_INDEX.open("r", encoding="utf-8") as handle:
        payload = json.load(handle)
    return payload.get("records", [])


def save_vector_records(records: list[dict[str, Any]]) -> None:
    VECTOR_INDEX.parent.mkdir(parents=True, exist_ok=True)
    with VECTOR_INDEX.open("w", encoding="utf-8") as handle:
        json.dump(
            {
                "embedding_model": EMBEDDING_MODEL,
                "embedding_dimensions": EMBEDDING_DIMENSIONS,
                "record_count": len(records),
                "updated_at": utc_now(),
                "records": records,
            },
            handle,
            indent=2,
        )


def upsert_vector_records(records: list[dict[str, Any]]) -> None:
    if not records:
        return
    existing = load_vector_records()
    replacement_ids = {record["id"] for record in records}
    artifact_ids = {record.get("artifact_id") for record in records if record.get("artifact_id")}
    retained = [
        record
        for record in existing
        if record.get("id") not in replacement_ids and record.get("artifact_id") not in artifact_ids
    ]
    save_vector_records([*records, *retained])


def replace_vector_source(source_type: str, records: list[dict[str, Any]]) -> None:
    retained = [record for record in load_vector_records() if record.get("source_type", "document") != source_type]
    save_vector_records([*records, *retained])


def semantic_search(
    query: str, top_k: int = 8, source_types: list[str] | None = None,
) -> list[dict[str, Any]]:
    return hybrid_retrieve(query, top_k=top_k, source_types=source_types)


def conversation_search_text(conversation: dict[str, Any], limit: int = 8000) -> str:
    summary = str(conversation.get("summary") or "").strip()
    recent = [
        str(message.get("content") or "").strip()
        for message in conversation.get("messages", [])
        if message.get("role") in {"user", "assistant"} and str(message.get("content") or "").strip()
    ][-12:]
    return clean_extracted_text("\n".join([summary, *recent]))[-limit:]


def related_conversations(
    query: str,
    conversations: list[dict[str, Any]],
    exclude_id: str | None = None,
    top_k: int = 5,
) -> list[dict[str, Any]]:
    if not query.strip():
        return []
    lookup = {str(item.get("id")): item for item in conversations}
    message_results = semantic_search(query, top_k=max(top_k * 8, 20), source_types=["conversation"])
    grouped: dict[str, dict[str, Any]] = {}
    for result in message_results:
        conversation_id = str(result.get("conversation_id") or result.get("source_id") or "")
        if not conversation_id or conversation_id == exclude_id or conversation_id not in lookup:
            continue
        score = float((result.get("scores") or {}).get("rerank", 0.0))
        current = grouped.get(conversation_id)
        if current is None or score > current["score"]:
            conversation = lookup[conversation_id]
            grouped[conversation_id] = {
                "conversation_id": conversation_id,
                "title": conversation.get("title", "New chat"),
                "score": round(score, 6),
                "matching_message_id": result.get("message_id"),
                "snippet": str(result.get("text") or "")[:500],
                "updated_at": conversation.get("updated_at", ""),
            }
    return sorted(grouped.values(), key=lambda item: item["score"], reverse=True)[:max(1, top_k)]


def similar_documents(artifact_id: str, top_k: int = 5) -> list[dict[str, Any]]:
    records = load_vector_records()
    target = [record for record in records if record.get("artifact_id") == artifact_id]
    if not target:
        return []
    artifacts = {str(item.get("id")): item for item in list_artifacts()}
    grouped: dict[str, list[tuple[float, dict[str, Any], dict[str, Any]]]] = {}
    for candidate in records:
        candidate_id = str(candidate.get("artifact_id") or "")
        if not candidate_id or candidate_id == artifact_id:
            continue
        similarities = [
            cosine_similarity(source.get("embedding") or [], candidate.get("embedding") or [])
            for source in target
        ]
        if similarities:
            best = max(similarities)
            source = target[similarities.index(best)]
            grouped.setdefault(candidate_id, []).append((best, source, candidate))

    results: list[dict[str, Any]] = []
    for candidate_id, matches in grouped.items():
        strongest = sorted(matches, key=lambda item: item[0], reverse=True)[:3]
        score = sum(item[0] for item in strongest) / len(strongest)
        artifact = artifacts.get(candidate_id, {})
        results.append({
            "artifact_id": candidate_id,
            "filename": artifact.get("filename") or strongest[0][2].get("filename", ""),
            "document_type": artifact.get("document_type") or strongest[0][2].get("document_type", ""),
            "score": round(score, 6),
            "matching_chunks": [
                {
                    "source_chunk_id": item[1].get("chunk_id"),
                    "candidate_chunk_id": item[2].get("chunk_id"),
                    "score": round(item[0], 6),
                    "snippet": str(item[2].get("text") or "")[:400],
                }
                for item in strongest
            ],
        })
    return sorted(results, key=lambda item: item["score"], reverse=True)[:max(1, top_k)]


def hybrid_retrieve(query: str, top_k: int = 8, source_types: list[str] | None = None) -> list[dict[str, Any]]:
    query = clean_extracted_text(query)
    if not query:
        return []

    query_embedding = generate_embedding(query)
    query_terms = token_set(query)
    allowed_sources = {item.strip().lower() for item in (source_types or []) if item.strip()}
    candidates: list[dict[str, Any]] = []
    for record in load_vector_records():
        source_type = str(record.get("source_type") or "document").lower()
        if allowed_sources and source_type not in allowed_sources:
            continue
        text = str(record.get("text") or "")
        metadata_text = " ".join(
            str(value)
            for value in [
                record.get("filename", ""),
                record.get("document_type", ""),
                (record.get("metadata") or {}).get("category", ""),
                (record.get("metadata") or {}).get("content_type", ""),
                source_type,
            ]
        )
        vector_score = cosine_similarity(query_embedding, record.get("embedding") or [])
        keyword_score_value = keyword_overlap_score(query_terms, token_set(f"{text} {metadata_text}"))
        hybrid_score = (0.68 * vector_score) + (0.32 * keyword_score_value)
        enriched = {
            **record,
            "scores": {
                "vector": round(vector_score, 6),
                "keyword": round(keyword_score_value, 6),
                "hybrid": round(hybrid_score, 6),
            },
        }
        candidates.append(enriched)

    candidates.sort(key=lambda item: item["scores"]["hybrid"], reverse=True)
    reranked = rerank_results(query, candidates[: max(top_k * 4, top_k)])
    return select_top_k(reranked, top_k=top_k)


def select_top_k(results: list[dict[str, Any]], top_k: int = RAG_TOP_K) -> list[dict[str, Any]]:
    top_k = max(1, top_k)
    return sorted(
        results,
        key=lambda item: float((item.get("scores") or {}).get("rerank", (item.get("scores") or {}).get("hybrid", 0.0))),
        reverse=True,
    )[:top_k]


def rerank_results(query: str, results: list[dict[str, Any]]) -> list[dict[str, Any]]:
    query_text = query.lower().strip()
    query_terms = token_set(query)
    reranked: list[dict[str, Any]] = []
    for index, result in enumerate(results):
        text = str(result.get("text") or "")
        filename = str(result.get("filename") or "")
        document_type = str(result.get("document_type") or "")
        exact_phrase_bonus = 0.18 if query_text and query_text in text.lower() else 0.0
        title_bonus = 0.08 if query_terms & token_set(filename) else 0.0
        type_bonus = 0.04 if query_terms & token_set(document_type) else 0.0
        early_rank_bonus = max(0.0, 0.03 - (index * 0.002))
        base_score = float((result.get("scores") or {}).get("hybrid", 0.0))
        rerank_score = base_score + exact_phrase_bonus + title_bonus + type_bonus + early_rank_bonus
        updated = {
            **result,
            "scores": {
                **(result.get("scores") or {}),
                "rerank": round(rerank_score, 6),
            },
        }
        reranked.append(updated)
    reranked.sort(key=lambda item: item["scores"]["rerank"], reverse=True)
    return reranked


def citation_for_result(result: dict[str, Any], index: int) -> str:
    metadata = result.get("metadata") if isinstance(result.get("metadata"), dict) else {}
    source_type = str(result.get("source_type") or "document")
    filename = str(result.get("filename") or source_type)
    chunk_id = str(result.get("chunk_id") or f"chunk-{index:04d}")
    start_char = metadata.get("start_char")
    end_char = metadata.get("end_char")
    location = f", chars {start_char}-{end_char}" if start_char is not None and end_char is not None else ""
    source_label = "" if source_type == "document" else f"{source_type}: "
    return f"[{index}] {source_label}{filename}, {chunk_id}{location}"


def add_citations_to_results(results: list[dict[str, Any]]) -> list[dict[str, Any]]:
    cited: list[dict[str, Any]] = []
    for index, result in enumerate(results, start=1):
        cited.append({**result, "citation": citation_for_result(result, index)})
    return cited


def retrieved_context_text(query: str, top_k: int = RAG_TOP_K) -> str:
    if not query.strip():
        return ""
    results = add_citations_to_results(hybrid_retrieve(query, top_k=top_k))
    if not results:
        return ""
    lines = [
        "Retrieved document context and semantic memory from conversations and learned behavior:",
        "Use these results when relevant. Cite sources with the bracketed citation labels.",
    ]
    for result in results:
        scores = result.get("scores") or {}
        score = scores.get("rerank", scores.get("hybrid", 0))
        text = str(result.get("text") or "").strip()
        if len(text) > 1200:
            text = text[:1200].rsplit(" ", 1)[0] + "..."
        lines.append(f"{result['citation']} score={score}\n{text}")
    return "\n\n".join(lines)


def cosine_similarity(left: list[float], right: list[float]) -> float:
    if not left or not right:
        return 0.0
    length = min(len(left), len(right))
    dot = sum(float(left[index]) * float(right[index]) for index in range(length))
    left_magnitude = sum(float(value) * float(value) for value in left[:length]) ** 0.5
    right_magnitude = sum(float(value) * float(value) for value in right[:length]) ** 0.5
    if not left_magnitude or not right_magnitude:
        return 0.0
    return dot / (left_magnitude * right_magnitude)


def keyword_overlap_score(query_terms: set[str], document_terms: set[str]) -> float:
    if not query_terms or not document_terms:
        return 0.0
    return len(query_terms & document_terms) / len(query_terms)


def token_set(text: str) -> set[str]:
    return set(re.findall(r"[A-Za-z0-9_]+", text.lower()))


def extract_pdf_text_basic(content: bytes, limit: int = 12000) -> str:
    raw = content[: max(limit * 4, 20000)].decode("latin-1", errors="ignore")
    matches = re.findall(r"\(([^()]{3,})\)", raw)
    text = " ".join(unescape_pdf_text(item) for item in matches)
    text = usable_extracted_text(text)
    if len(text) < 12:
        return ""
    return text[:limit]


def extract_pdf_text_pymupdf(path: Path, limit: int = 12000) -> str:
    try:
        import fitz  # type: ignore[import-not-found]
    except ImportError:
        return ""
    try:
        with fitz.open(path) as document:
            text = "\n".join(page.get_text() for page in document)
    except Exception:
        return ""
    return usable_extracted_text(text)[:limit]


def extract_pdf_text_file(path: Path) -> tuple[str, str]:
    configured = os.getenv("AIOS_PDF_TEXT_COMMAND", "").strip()
    command: list[str] = []
    if configured:
        command = command_from_template(configured, path)
    else:
        pdftotext = shutil.which("pdftotext")
        if pdftotext:
            command = [pdftotext, "-layout", str(path), "-"]
    if not command:
        return "", "Install Poppler pdftotext or set AIOS_PDF_TEXT_COMMAND to extract embedded PDF text."

    timeout = int(os.getenv("AIOS_PDF_TEXT_TIMEOUT", "25"))
    try:
        completed = subprocess.run(
            command,
            capture_output=True,
            check=False,
            text=True,
            timeout=timeout,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        return "", str(exc)
    if completed.returncode != 0:
        error = clean_extracted_text(completed.stderr) or f"PDF text command exited with {completed.returncode}."
        return "", error
    text = usable_extracted_text(completed.stdout)
    return text, ""


def unescape_pdf_text(value: str) -> str:
    return (
        value.replace(r"\(", "(")
        .replace(r"\)", ")")
        .replace(r"\\", "\\")
        .replace(r"\n", "\n")
        .replace(r"\r", "\n")
        .replace(r"\t", "\t")
    )


def ocr_image_file(path: Path) -> tuple[str, str, str]:
    command = ocr_command_for_path(path)
    if not command:
        return "", "unavailable", "Install Tesseract or set AIOS_OCR_COMMAND to enable OCR."
    return run_ocr_command(command)


def ocr_pdf_file(path: Path) -> tuple[str, str, str]:
    configured = os.getenv("AIOS_PDF_OCR_COMMAND") or os.getenv("AIOS_OCR_COMMAND")
    if not configured:
        return "", "unavailable", "Scanned PDF OCR requires AIOS_PDF_OCR_COMMAND or AIOS_OCR_COMMAND."
    return run_ocr_command(command_from_template(configured, path))


def ocr_command_for_path(path: Path) -> list[str]:
    configured = os.getenv("AIOS_OCR_COMMAND", "").strip()
    if configured:
        return command_from_template(configured, path)
    tesseract = shutil.which("tesseract")
    if not tesseract:
        return []
    return [tesseract, str(path), "stdout"]


def command_from_template(template: str, path: Path) -> list[str]:
    parts = shlex.split(template)
    if not parts:
        return []
    resolved_path = str(path)
    if any("{file}" in part for part in parts):
        return [part.replace("{file}", resolved_path) for part in parts]
    return [*parts, resolved_path]


def run_ocr_command(command: list[str]) -> tuple[str, str, str]:
    if not command:
        return "", "unavailable", "No OCR command is configured."
    timeout = int(os.getenv("AIOS_OCR_TIMEOUT", "25"))
    try:
        completed = subprocess.run(
            command,
            capture_output=True,
            check=False,
            text=True,
            timeout=timeout,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        return "", "failed", str(exc)
    text = clean_extracted_text(completed.stdout)
    if completed.returncode != 0:
        error = clean_extracted_text(completed.stderr) or f"OCR command exited with {completed.returncode}."
        return text, "failed", error
    if not text:
        return "", "completed", ""
    return text, "completed", ""


def load_artifacts() -> list[dict[str, Any]]:
    if not UPLOAD_INDEX.exists():
        return []
    with UPLOAD_INDEX.open("r", encoding="utf-8") as handle:
        payload = json.load(handle)
    artifacts = payload.get("artifacts", [])
    migrated: list[dict[str, Any]] = []
    changed = False
    for artifact in artifacts:
        upgraded, was_changed = upgrade_artifact_record(artifact)
        migrated.append(upgraded)
        changed = changed or was_changed
    if changed:
        save_artifacts(migrated)
    return migrated


def save_artifacts(artifacts: list[dict[str, Any]]) -> None:
    UPLOAD_INDEX.parent.mkdir(parents=True, exist_ok=True)
    with UPLOAD_INDEX.open("w", encoding="utf-8") as handle:
        json.dump({"artifacts": artifacts}, handle, indent=2)


def upgrade_artifact_record(artifact: dict[str, Any]) -> tuple[dict[str, Any], bool]:
    required_keys = {"document_type", "cleaned_text", "chunks", "ocr_status", "metadata"}
    category = str(artifact.get("category") or "")
    current_text = str(artifact.get("cleaned_text") or artifact.get("extracted_text") or artifact.get("preview") or "")
    has_bad_pdf_text = category == "pdf" and bool(current_text) and not usable_extracted_text(current_text)
    if required_keys.issubset(artifact.keys()) and not has_bad_pdf_text:
        return artifact, False

    path_value = str(artifact.get("path") or "").strip()
    if not path_value:
        return artifact, False
    path = safe_artifact_path(path_value)
    if not path or not path.exists() or not path.is_file():
        return artifact, False

    try:
        content = path.read_bytes()
    except OSError:
        return artifact, False

    filename = str(artifact.get("filename") or path.name)
    content_type = str(artifact.get("content_type") or mimetypes.guess_type(filename)[0] or "application/octet-stream")
    document = document_metadata_for_upload(filename, content_type, content, path)
    upgraded = {
        **artifact,
        "content_type": content_type,
        "size": int(artifact.get("size") or len(content)),
        "category": artifact.get("category") or artifact_category(filename, content_type),
        "preview": document["preview"],
        "document_type": document["document_type"],
        "extracted_text": document["extracted_text"],
        "cleaned_text": document["cleaned_text"],
        "chunks": document["chunks"],
        "ocr_status": document["ocr_status"],
        "ocr_error": document["ocr_error"],
        "metadata": document["metadata"],
    }
    vector_records = vector_records_for_artifact(upgraded) if upgraded.get("id") else []
    upgraded["metadata"]["embedding_model"] = EMBEDDING_MODEL
    upgraded["metadata"]["embedding_dimensions"] = EMBEDDING_DIMENSIONS
    upgraded["metadata"]["vector_count"] = len(vector_records)
    upsert_vector_records(vector_records)
    return upgraded, True


def safe_artifact_path(path_value: str) -> Path | None:
    candidate = (ROOT / path_value).resolve()
    try:
        candidate.relative_to(ROOT)
    except ValueError:
        return None
    return candidate


def list_artifacts() -> list[dict[str, Any]]:
    return load_artifacts()


def find_artifact(artifact_id: str) -> dict[str, Any] | None:
    for artifact in load_artifacts():
        if artifact["id"] == artifact_id:
            return artifact
    return None


def serialize_ndjson_event(payload: dict[str, Any]) -> bytes:
    return (json.dumps(payload) + "\n").encode("utf-8")


def iter_stream_chunks(chunks: Iterator[str] | list[str], chunk_size: int = 8) -> Iterator[str]:
    buffer = ""
    for chunk in chunks:
        if not chunk:
            continue
        buffer += chunk
        while len(buffer) >= chunk_size:
            yield buffer[:chunk_size]
            buffer = buffer[chunk_size:]
    if buffer:
        yield buffer


def main() -> None:
    host = os.getenv("AIOS_HOST", "127.0.0.1")
    port = int(os.getenv("AIOS_PORT", "8000"))
    server = ThreadingHTTPServer((host, port), AIOSHandler)
    print(f"AIOS starter running at http://{host}:{port}")
    server.serve_forever()


if __name__ == "__main__":
    main()
