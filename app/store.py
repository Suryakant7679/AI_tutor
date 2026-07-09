from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4


class ConversationStore:
    def __init__(self, path: str = "data/conversations.json") -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def list_conversations(self) -> list[dict[str, Any]]:
        return self._load()["conversations"]

    def create_conversation(self, title: str = "New chat") -> dict[str, Any]:
        payload = self._load()
        conversation = {
            "id": str(uuid4()),
            "title": title,
            "created_at": utc_now(),
            "updated_at": utc_now(),
            "messages": [],
        }
        payload["conversations"].insert(0, conversation)
        self._save(payload)
        return conversation

    def add_message(self, conversation_id: str, role: str, content: str) -> dict[str, Any]:
        payload = self._load()
        conversation = self._find(payload, conversation_id)
        message = {
            "id": str(uuid4()),
            "role": role,
            "content": content,
            "created_at": utc_now(),
        }
        conversation["messages"].append(message)
        conversation["updated_at"] = utc_now()
        if conversation["title"] == "New chat" and role == "user":
            conversation["title"] = content[:48] or "New chat"
        self._save(payload)
        return message

    def get_conversation(self, conversation_id: str) -> dict[str, Any]:
        payload = self._load()
        return self._find(payload, conversation_id)

    def _load(self) -> dict[str, Any]:
        if not self.path.exists():
            return {"conversations": []}
        with self.path.open("r", encoding="utf-8") as handle:
            return json.load(handle)

    def _save(self, payload: dict[str, Any]) -> None:
        with self.path.open("w", encoding="utf-8") as handle:
            json.dump(payload, handle, indent=2)

    @staticmethod
    def _find(payload: dict[str, Any], conversation_id: str) -> dict[str, Any]:
        for conversation in payload["conversations"]:
            if conversation["id"] == conversation_id:
                return conversation
        raise KeyError(f"Conversation not found: {conversation_id}")


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()
