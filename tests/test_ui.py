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

    def test_recent_chat_history_is_scrollable_and_rows_do_not_overlap(self) -> None:
        stylesheet = (ROOT / "web" / "styles.css").read_text(encoding="utf-8")
        javascript = (ROOT / "web" / "app.js").read_text(encoding="utf-8")
        self.assertIn("#conversation-list .secondary", stylesheet)
        self.assertIn("#conversation-list .conversation-item", stylesheet)
        self.assertIn("flex: 0 0 36px", stylesheet)
        self.assertIn("text-overflow: ellipsis", stylesheet)
        self.assertIn("overflow-y: auto", stylesheet)
        self.assertIn("button.title = title", javascript)
        self.assertIn('button.classList.toggle("active"', javascript)
        self.assertIn('data-action="rename"', javascript)
        self.assertIn('data-action="delete"', javascript)
        self.assertIn('method: "PATCH"', javascript)
        self.assertIn('method: "DELETE"', javascript)
    def test_browser_start_opens_a_blank_new_chat(self) -> None:
        javascript = (ROOT / "web" / "app.js").read_text(encoding="utf-8")
        boot = javascript.split("async function boot()", 1)[1].split("\n}\n\nboot();", 1)[0]
        self.assertIn("setActiveConversation(null)", boot)
        self.assertIn('setActiveThread("main")', boot)
        self.assertIn('messages.innerHTML = ""', boot)
        self.assertNotIn("openConversation(activeConversationId)", boot)
    def test_sidebar_profile_footer_is_removed(self) -> None:
        html = (ROOT / "web" / "index.html").read_text(encoding="utf-8")
        self.assertNotIn("sidebar-footer", html)
        self.assertNotIn("<strong>Surya</strong>", html)

if __name__ == "__main__":
    unittest.main()
