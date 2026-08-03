from __future__ import annotations

import re
from html import unescape
from typing import Any
from urllib.parse import parse_qs, quote_plus, urlparse

import httpx


def _result_url(value: str) -> str:
    value = unescape(value)
    parsed = urlparse(value)
    redirected = parse_qs(parsed.query).get("uddg", []) if parsed.hostname and parsed.hostname.endswith("duckduckgo.com") else []
    return redirected[0] if redirected else value


def search_web(query: str, max_results: int = 5) -> list[dict[str, Any]]:
    query = " ".join(str(query).split())[:500]
    if not query:
        return []
    limit = max(1, min(int(max_results), 10))
    with httpx.Client(timeout=5, follow_redirects=True, headers={"User-Agent": "Mozilla/5.0 (compatible; AIOS-Research/1.0)"}) as client:
        response = client.get(f"https://html.duckduckgo.com/html/?q={quote_plus(query)}")
        response.raise_for_status()
    anchors = re.findall(r'<a[^>]+class="[^"]*result__a[^"]*"[^>]+href="([^"]+)"[^>]*>(.*?)</a>', response.text, re.I | re.S)
    snippets = re.findall(r'<(?:a|div)[^>]+class="[^"]*result__snippet[^"]*"[^>]*>(.*?)</(?:a|div)>', response.text, re.I | re.S)
    results: list[dict[str, Any]] = []
    for index, (href, title_html) in enumerate(anchors[:limit]):
        url = _result_url(href)
        if urlparse(url).scheme not in {"http", "https"}:
            continue
        title = " ".join(re.sub(r"<[^>]+>", " ", unescape(title_html)).split())
        snippet_html = snippets[index] if index < len(snippets) else ""
        snippet = " ".join(re.sub(r"<[^>]+>", " ", unescape(snippet_html)).split())
        results.append({"title": title, "url": url, "snippet": snippet})
    return results


def research_context(query: str, max_results: int = 5) -> str:
    results = search_web(query, max_results)
    if not results:
        return ""
    lines = ["Live web research results from DuckDuckGo:", "Cite claims with clickable Markdown links to these exact URLs. Never invent bare numeric citations."]
    for index, result in enumerate(results, 1):
        lines.append(f"[{index}] {result['title']}\nURL: {result['url']}\n{result['snippet']}")
    return "\n\n".join(lines)
