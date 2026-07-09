from __future__ import annotations

import json
import mimetypes
import os
import re
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
    from app.store import ConversationStore
except ModuleNotFoundError:
    from config import configured_api_keys, load_env
    from llm import LLMError, generate_response, generate_response_stream
    from store import ConversationStore


load_env()
ROOT = Path(__file__).resolve().parents[1]
WEB_ROOT = ROOT / "web"
STORE = ConversationStore(os.getenv("AIOS_DATA_FILE", "data/conversations.json"))
UPLOAD_ROOT = ROOT / os.getenv("AIOS_UPLOAD_DIR", "data/uploads")
UPLOAD_INDEX = ROOT / os.getenv("AIOS_UPLOAD_INDEX", "data/uploads.json")
MAX_UPLOAD_BYTES = int(os.getenv("AIOS_MAX_UPLOAD_BYTES", str(10 * 1024 * 1024)))


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
        if path == "/api/uploads":
            self.send_json({"artifacts": list_artifacts()})
            return
        if path.startswith("/api/uploads/") and path.endswith("/content"):
            artifact_id = path.split("/")[-2]
            self.serve_upload(artifact_id)
            return
        self.serve_static(path)

    def do_POST(self) -> None:
        path = urlparse(self.path).path
        if path == "/api/conversations":
            conversation = STORE.create_conversation()
            self.send_json(conversation, status=201)
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
            artifact = {
                "id": artifact_id,
                "filename": filename,
                "content_type": item["content_type"],
                "size": len(content),
                "category": artifact_category(filename, item["content_type"]),
                "path": str(target.relative_to(ROOT)),
                "preview": preview_text(filename, item["content_type"], content),
            }
            artifacts.insert(0, artifact)
            created.append(artifact)
        save_artifacts(artifacts)
        return created

    def send_chat_stream(
        self, conversation_id: str, llm_messages: list[dict[str, str]]
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
                    "conversation_id": conversation_id,
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
                {"type": "meta", "conversation_id": conversation_id, "provider": provider}
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
    return "file"


def preview_text(filename: str, content_type: str, content: bytes, limit: int = 4000) -> str:
    if artifact_category(filename, content_type) != "file":
        return ""
    try:
        return content[:limit].decode("utf-8", errors="replace")
    except UnicodeDecodeError:
        return ""


def load_artifacts() -> list[dict[str, Any]]:
    if not UPLOAD_INDEX.exists():
        return []
    with UPLOAD_INDEX.open("r", encoding="utf-8") as handle:
        payload = json.load(handle)
    return payload.get("artifacts", [])


def save_artifacts(artifacts: list[dict[str, Any]]) -> None:
    UPLOAD_INDEX.parent.mkdir(parents=True, exist_ok=True)
    with UPLOAD_INDEX.open("w", encoding="utf-8") as handle:
        json.dump({"artifacts": artifacts}, handle, indent=2)


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
