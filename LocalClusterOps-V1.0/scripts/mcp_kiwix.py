#!/usr/bin/env python3
"""MCP server exposing local Kiwix search tools to LibreChat agents.

Default endpoint: http://127.0.0.1:8080
Override with KIWIX_MCP_ENDPOINT if needed.
"""
from __future__ import annotations

import json
import os
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from html.parser import HTMLParser

from mcp.server.fastmcp import FastMCP

DEFAULT_ENDPOINT = os.environ.get("KIWIX_MCP_ENDPOINT", "http://127.0.0.1:8080").rstrip("/")
TIMEOUT = 5
FASTMCP_HOST = os.environ.get("FASTMCP_HOST", "127.0.0.1")
FASTMCP_PORT = int(os.environ.get("FASTMCP_PORT", "8000"))

mcp = FastMCP("kiwix", host=FASTMCP_HOST, port=FASTMCP_PORT)


def _endpoint(value: str | None = None) -> str:
    return (value or DEFAULT_ENDPOINT).rstrip("/")


def _fetch(url: str, timeout: int = TIMEOUT) -> bytes:
    with urllib.request.urlopen(url, timeout=timeout) as response:
        return response.read()


class _SearchResultParser(HTMLParser):
    """Parse Kiwix HTML search results into a compact list."""

    def __init__(self, base_url: str):
        super().__init__()
        self._base = base_url
        self._in_result = False
        self._in_title = False
        self._in_snippet = False
        self._current: dict[str, str] = {}
        self.results: list[dict[str, str]] = []

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        css_class = attrs.get("class", "")
        if "result" in css_class and tag in ("div", "article", "li"):
            self._in_result = True
            self._current = {}
        if self._in_result and tag == "a" and "href" in attrs:
            href = attrs["href"]
            if not href.startswith("http"):
                href = self._base + href
            self._current["url"] = href
            self._in_title = True
        if self._in_result and "snippet" in css_class:
            self._in_snippet = True

    def handle_data(self, data):
        text = data.strip()
        if not text:
            return
        if self._in_title:
            self._current["title"] = text
            self._in_title = False
        elif self._in_snippet:
            self._current.setdefault("snippet", "")
            self._current["snippet"] += text

    def handle_endtag(self, tag):
        if self._in_result and tag in ("div", "article", "li"):
            if self._current.get("url"):
                self.results.append(self._current)
            self._current = {}
            self._in_result = False
            self._in_snippet = False


def _suggest_fallback(query: str, book_id: str, endpoint: str, count: int) -> list[dict[str, str]]:
    params = urllib.parse.urlencode({"term": query, "count": str(count)})
    url = f"{endpoint}/{book_id}/suggest?{params}"
    data = json.loads(_fetch(url).decode("utf-8", errors="replace"))
    results = []
    for item in data:
        title = item.get("label") or item.get("value", "")
        path = item.get("url", f"/{book_id}/A/{urllib.parse.quote(title)}")
        if not path.startswith("http"):
            path = endpoint + path
        results.append({"title": title, "url": path, "snippet": ""})
    return results


@mcp.tool()
def kiwix_status(endpoint: str | None = None) -> str:
    """Check whether the Kiwix server is reachable and return basic status JSON."""
    ep = _endpoint(endpoint)
    try:
        _fetch(ep, timeout=3)
        payload = {"ok": True, "endpoint": ep}
    except Exception as exc:
        payload = {"ok": False, "endpoint": ep, "error": str(exc)}
    return json.dumps(payload, indent=2)


@mcp.tool()
def kiwix_list_books(endpoint: str | None = None) -> str:
    """List all books currently served by the local Kiwix instance."""
    ep = _endpoint(endpoint)
    try:
        raw = _fetch(f"{ep}/catalog/v2/entries").decode("utf-8", errors="replace")
        ns = {"atom": "http://www.w3.org/2005/Atom"}
        root = ET.fromstring(raw)
        books = []
        for entry in root.findall("atom:entry", ns):
            title_el = entry.find("atom:title", ns)
            id_el = entry.find("atom:id", ns)
            link_el = entry.find("atom:link[@type='text/html']", ns)
            if title_el is None:
                continue
            book_id = ""
            if link_el is not None:
                href = link_el.get("href", "")
                book_id = href.strip("/").split("/")[0]
            elif id_el is not None and id_el.text:
                book_id = id_el.text.strip().split("/")[-1]
            books.append({"id": book_id, "title": title_el.text or book_id})
        return json.dumps({"endpoint": ep, "books": books}, indent=2)
    except Exception as exc:
        return json.dumps({"endpoint": ep, "error": str(exc), "books": []}, indent=2)


@mcp.tool()
def kiwix_search(
    query: str,
    book_id: str = "",
    count: int = 5,
    endpoint: str | None = None,
) -> str:
    """Search the local Kiwix server and return compact JSON results."""
    ep = _endpoint(endpoint)
    params = {"pattern": query, "count": str(count)}
    if book_id:
        params["books"] = book_id
    url = f"{ep}/search?{urllib.parse.urlencode(params)}"
    try:
        html = _fetch(url).decode("utf-8", errors="replace")
        parser = _SearchResultParser(ep)
        parser.feed(html)
        results = parser.results
        if not results and book_id:
            results = _suggest_fallback(query, book_id, ep, count)
        return json.dumps(
            {
                "endpoint": ep,
                "query": query,
                "book_id": book_id,
                "count": len(results),
                "results": results,
            },
            indent=2,
        )
    except Exception as exc:
        return json.dumps(
            {"endpoint": ep, "query": query, "book_id": book_id, "error": str(exc), "results": []},
            indent=2,
        )


if __name__ == "__main__":
    transport = os.environ.get("KIWIX_MCP_TRANSPORT", "stdio").strip() or "stdio"
    mount_path = os.environ.get("KIWIX_MCP_MOUNT_PATH")
    mcp.run(transport=transport, mount_path=mount_path)
