from __future__ import annotations

import json
import mimetypes
import os
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Iterator
from urllib.parse import parse_qsl, urlparse

try:
    from app.config import configured_api_keys, load_env
    from app.llm import LLMError, generate_response, generate_response_stream
    from app.store import ConversationStore
except ModuleNotFoundError:
    from config import configured_api_keys, load_env
    from llm import LLMError, generate_response, generate_response_stream
    from store import ConversationStore


load_env()
ROOT = Path(__file__).resolve().parents[1]
WEB_ROOT = ROOT / "web"
STORE = ConversationStore(os.getenv("AIOS_DATA_FILE", "data/conversations.json"))


class AIOSHandler(BaseHTTPRequestHandler):
    server_version = "AIOSStarter/0.1"

    def do_GET(self) -> None:
        path = urlparse(self.path).path
        if path == "/api/health":
            self.send_json(
                {
                    "status": "ok",
                    "service": "aios-starter",
                    "configured_api_keys": configured_api_keys(),
                }
            )
            return
        if path == "/api/conversations":
            self.send_json({"conversations": compact_conversations(STORE.list_conversations())})
            return
        if path.startswith("/api/conversations/"):
            conversation_id = path.rsplit("/", 1)[-1]
            try:
                self.send_json(STORE.get_conversation(conversation_id))
            except KeyError:
                self.send_error(404, "Conversation not found")
            return
        self.serve_static(path)

    def do_POST(self) -> None:
        path = urlparse(self.path).path
        if path == "/api/conversations":
            conversation = STORE.create_conversation()
            self.send_json(conversation, status=201)
            return
        if path == "/api/chat":
            try:
                body = self.read_json()
            except ValueError as exc:
                self.send_json({"error": str(exc)}, status=400)
                return

            message = str(body.get("message", "")).strip()
            conversation_id = body.get("conversation_id")
            if not message:
                self.send_error(400, "Message is required")
                return
            if not conversation_id:
                conversation_id = STORE.create_conversation()["id"]
            try:
                STORE.add_message(conversation_id, "user", message)
                conversation = STORE.get_conversation(conversation_id)
                llm_messages = conversation_messages_for_llm(conversation["messages"])
                if body.get("stream"):
                    self.send_chat_stream(conversation_id, llm_messages)
                    return
                assistant_text, provider = generate_response(llm_messages)
                STORE.add_message(conversation_id, "assistant", assistant_text)
                self.send_json(
                    {
                        "conversation_id": conversation_id,
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

    def send_chat_stream(
        self, conversation_id: str, llm_messages: list[dict[str, str]]
    ) -> None:
        try:
            chunks, provider = generate_response_stream(llm_messages)
        except LLMError as exc:
            self.send_json({"error": str(exc)}, status=502)
            return

        assistant_parts: list[str] = []
        self.send_response(200)
        self.send_header("Content-Type", "application/x-ndjson; charset=utf-8")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.end_headers()

        try:
            self.write_ndjson_event(
                {"type": "meta", "conversation_id": conversation_id, "provider": provider}
            )
            self.write_ndjson_event(
                {"type": "progress", "stage": "model", "message": "Model stream connected"}
            )
            for chunk in iter_stream_chunks(chunks, chunk_size=8):
                assistant_parts.append(chunk)
                self.write_ndjson_event({"type": "delta", "content": chunk})

            assistant_text = "".join(assistant_parts).strip()
            self.write_ndjson_event(
                {"type": "progress", "stage": "storage", "message": "Saving assistant reply"}
            )
            STORE.add_message(conversation_id, "assistant", assistant_text)
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
                )
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
            "title": item["title"],
            "created_at": item["created_at"],
            "updated_at": item["updated_at"],
            "message_count": len(item["messages"]),
        }
        for item in conversations
    ]


def conversation_messages_for_llm(messages: list[dict[str, Any]]) -> list[dict[str, str]]:
    return [
        {"role": item["role"], "content": item["content"]}
        for item in messages[-20:]
        if item["role"] in {"user", "assistant"}
    ]


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
