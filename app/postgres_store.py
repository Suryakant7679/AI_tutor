from __future__ import annotations

import json
import os
from datetime import datetime
from pathlib import Path
from typing import Any

from app.store import ConversationStore, default_long_term_memory, normalize_long_term_memory


class PostgreSQLConversationStore(ConversationStore):
    """ConversationStore implementation backed by PostgreSQL sessions and chats."""

    def __init__(self, database_url: str, memory_path: str = "data/memory.json") -> None:
        if not database_url.strip():
            raise ValueError("database_url is required")
        self.database_url = database_url
        root = Path(__file__).resolve().parents[1]
        path = Path(memory_path)
        self.path = path if path.is_absolute() else root / path
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def _connect(self):
        try:
            import psycopg
        except ImportError as exc:
            raise RuntimeError(
                'PostgreSQL storage requires psycopg. Install it with: pip install "psycopg[binary]"'
            ) from exc
        return psycopg.connect(self.database_url)

    def _load(self) -> dict[str, Any]:
        from psycopg.rows import dict_row

        with self._connect() as connection:
            with connection.cursor(row_factory=dict_row) as cursor:
                cursor.execute(
                    """
                    SELECT id, active_project, current_workspace, running_task, active_file,
                           open_files, active_tool, terminal_output, browser_results, mcp_outputs,
                           developer_instructions, user_preferences, created_at, updated_at
                    FROM sessions ORDER BY updated_at DESC
                    """
                )
                sessions = [self._session_from_row(row) for row in cursor.fetchall()]
                cursor.execute(
                    """
                    SELECT id, session_id, title, active_thread_id, threads, messages, summary,
                           compressed_message_count, recovery_state, short_term_memory,
                           created_at, updated_at
                    FROM chats ORDER BY updated_at DESC
                    """
                )
                conversations = [self._chat_from_row(row) for row in cursor.fetchall()]
        return {
            "sessions": sessions,
            "conversations": conversations,
            "long_term_memory": self._load_memory(),
        }

    def _save(self, payload: dict[str, Any]) -> None:
        from psycopg.types.json import Jsonb

        with self._connect() as connection:
            with connection.cursor() as cursor:
                for session in payload.get("sessions", []):
                    cursor.execute(
                        """
                        INSERT INTO sessions (
                            id, active_project, current_workspace, running_task, active_file,
                            open_files, active_tool, terminal_output, browser_results, mcp_outputs,
                            developer_instructions, user_preferences, created_at, updated_at
                        ) VALUES (
                            %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s
                        )
                        ON CONFLICT (id) DO UPDATE SET
                            active_project = EXCLUDED.active_project,
                            current_workspace = EXCLUDED.current_workspace,
                            running_task = EXCLUDED.running_task,
                            active_file = EXCLUDED.active_file,
                            open_files = EXCLUDED.open_files,
                            active_tool = EXCLUDED.active_tool,
                            terminal_output = EXCLUDED.terminal_output,
                            browser_results = EXCLUDED.browser_results,
                            mcp_outputs = EXCLUDED.mcp_outputs,
                            developer_instructions = EXCLUDED.developer_instructions,
                            user_preferences = EXCLUDED.user_preferences,
                            updated_at = EXCLUDED.updated_at
                        """,
                        (
                            session["id"], session.get("active_project", ""),
                            Jsonb(session.get("current_workspace", {})), session.get("running_task", ""),
                            session.get("active_file", ""), Jsonb(session.get("open_files", [])),
                            session.get("active_tool", ""), session.get("terminal_output", ""),
                            session.get("browser_results", ""), session.get("mcp_outputs", ""),
                            session.get("developer_instructions", ""), Jsonb(session.get("user_preferences", {})),
                            session.get("created_at"), session.get("updated_at"),
                        ),
                    )
                for chat in payload.get("conversations", []):
                    cursor.execute(
                        """
                        INSERT INTO chats (
                            id, session_id, title, active_thread_id, threads, messages, summary,
                            compressed_message_count, recovery_state, short_term_memory,
                            created_at, updated_at
                        ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                        ON CONFLICT (id) DO UPDATE SET
                            session_id = EXCLUDED.session_id,
                            title = EXCLUDED.title,
                            active_thread_id = EXCLUDED.active_thread_id,
                            threads = EXCLUDED.threads,
                            messages = EXCLUDED.messages,
                            summary = EXCLUDED.summary,
                            compressed_message_count = EXCLUDED.compressed_message_count,
                            recovery_state = EXCLUDED.recovery_state,
                            short_term_memory = EXCLUDED.short_term_memory,
                            updated_at = EXCLUDED.updated_at
                        """,
                        (
                            chat["id"], chat.get("session_id"), chat.get("title", "New chat"),
                            chat.get("active_thread_id", "main"), Jsonb(chat.get("threads", [])),
                            Jsonb(chat.get("messages", [])), chat.get("summary", ""),
                            chat.get("compressed_message_count", 0), Jsonb(chat.get("recovery_state", {})),
                            Jsonb(chat.get("short_term_memory", {})), chat.get("created_at"), chat.get("updated_at"),
                        ),
                    )
            connection.commit()
        self._save_memory(payload.get("long_term_memory"))

    def _load_memory(self) -> dict[str, Any]:
        if not self.path.exists():
            return default_long_term_memory()
        try:
            return normalize_long_term_memory(json.loads(self.path.read_text(encoding="utf-8")))
        except (OSError, json.JSONDecodeError):
            return default_long_term_memory()

    def _save_memory(self, memory: Any) -> None:
        self.path.write_text(json.dumps(normalize_long_term_memory(memory), indent=2), encoding="utf-8")

    @staticmethod
    def _value(value: Any) -> Any:
        return value.isoformat() if isinstance(value, datetime) else value

    @classmethod
    def _session_from_row(cls, row: dict[str, Any]) -> dict[str, Any]:
        session = {key: cls._value(value) for key, value in row.items()}
        session["id"] = str(session["id"])
        return session

    @classmethod
    def _chat_from_row(cls, row: dict[str, Any]) -> dict[str, Any]:
        chat = {key: cls._value(value) for key, value in row.items()}
        chat["id"] = str(chat["id"])
        chat["session_id"] = str(chat["session_id"]) if chat.get("session_id") else None
        return chat
