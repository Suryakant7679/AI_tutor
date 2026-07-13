from __future__ import annotations

import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class ChatInterfaceTests(unittest.TestCase):
    def test_requested_navigation_and_quick_actions_are_removed(self) -> None:
        html = (ROOT / "web" / "index.html").read_text(encoding="utf-8")
        for removed in ("Library", "Projects", "Create an image", "Write or edit", "Look something up", "sidebar-toggle"):
            self.assertNotIn(removed, html)

    def test_semantic_chat_search_ui_is_connected(self) -> None:
        html = (ROOT / "web" / "index.html").read_text(encoding="utf-8")
        javascript = (ROOT / "web" / "app.js").read_text(encoding="utf-8")
        self.assertIn('id="search-chats"', html)
        self.assertIn('id="chat-search-dialog"', html)
        self.assertIn("/api/v1/conversations/search", javascript)
        self.assertIn("renderChatSearchResults", javascript)


if __name__ == "__main__":
    unittest.main()