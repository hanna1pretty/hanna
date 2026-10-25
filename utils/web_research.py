import asyncio
import html
import ipaddress
import json
import logging
import re
import socket
from dataclasses import dataclass
from html.parser import HTMLParser
from urllib.parse import parse_qs, quote_plus, unquote, urljoin, urlparse

import aiohttp

from config import (
    WEB_FETCH_MAX_BYTES, WEB_FETCH_TIMEOUT, WEB_SEARCH_API_KEY,
    WEB_SEARCH_ENDPOINT, WEB_SEARCH_RESULTS,
)

logger = logging.getLogger(__name__)


@dataclass
class WebSource:
    title: str
    url: str
    snippet: str = ""
    content: str = ""


class _DuckParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.results: list[dict] = []
        self.current: dict | None = None
        self.capture = None

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        classes = attrs.get("class", "")
        if tag == "a" and "result__a" in classes:
            self.current = {"title": "", "url": attrs.get("href", ""), "snippet": ""}
            self.capture = "title"
        elif self.current and "result__snippet" in classes:
            self.capture = "snippet"

    def handle_data(self, data):
        if self.current and self.capture:
            self.current[self.capture] += data

    def handle_endtag(self, tag):
        if self.current and tag == "a" and self.capture == "title":
            self.results.append(self.current)
            self.current = None
            self.capture = None


class _TextParser(HTMLParser):
    SKIP = {"script", "style", "noscript", "svg", "nav", "header", "footer", "form"}

    def __init__(self):
        super().__init__()
        self.depth = 0
        self.parts: list[str] = []

    def handle_starttag(self, tag, attrs):
        if tag in self.SKIP:
            self.depth += 1
        elif not self.depth and tag in {"p", "div", "article", "section", "h1", "h2", "h3", "li", "br"}:
            self.parts.append("\n")

    def handle_endtag(self, tag):
        if tag in self.SKIP and self.depth:
            self.depth -= 1
        elif not self.depth and tag in {"p", "div", "article", "section", "h1", "h2", "h3", "li"}:
            self.parts.append("\n")

    def handle_data(self, data):
        if not self.depth:
            self.parts.append(data)


def _clean_text(value: str, limit: int = 9000) -> str:
    value = html.unescape(value or "")
    value = re.sub(r"\s+", " ", value).strip()
    return value[:limit]


def _safe_public_url(url: str) -> str:
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise ValueError("Only public HTTP(S) URLs are allowed")
    host = parsed.hostname.rstrip(".").lower()
    if host in {"localhost", "metadata.google.internal", "metadata.amazonaws.com"}:
        raise ValueError("Internal host is not allowed")
    try:
        addresses = socket.getaddrinfo(host, parsed.port or (443 if parsed.scheme == "https" else 80), type=socket.SOCK_STREAM)
    except socket.gaierror as exc:
        raise ValueError("Host could not be resolved") from exc
    for address in addresses:
        ip = ipaddress.ip_address(address[4][0])
        if not ip.is_global:
            raise ValueError("Private or non-public address is not allowed")
    return url


async def _request_text(session, url: str, headers: dict | None = None, redirects: int = 0) -> tuple[str, str]:
    if redirects > 3:
        raise ValueError("Too many redirects")
    url = _safe_public_url(url)
    async with session.get(url, headers=headers or {}, allow_redirects=False) as response:
        if 300 <= response.status < 400 and response.headers.get("Location"):
            next_url = urljoin(url, response.headers["Location"])
            return await _request_text(session, next_url, headers, redirects + 1)
        if response.status != 200:
            raise RuntimeError(f"HTTP {response.status}")
        chunks = []
        received = 0
        async for chunk in response.content.iter_chunked(16384):
            received += len(chunk)
            if received > WEB_FETCH_MAX_BYTES:
                break
            chunks.append(chunk)
        return b"".join(chunks).decode(response.charset or "utf-8", errors="replace"), response.headers.get("Content-Type", "")


async def _brave_search(session, query: str) -> list[WebSource]:
    headers = {
        "Accept": "application/json",
        "Accept-Encoding": "gzip",
        "X-Subscription-Token": WEB_SEARCH_API_KEY,
    }
    params = {"q": query, "count": str(WEB_SEARCH_RESULTS), "safesearch": "moderate"}
    async with session.get(WEB_SEARCH_ENDPOINT, headers=headers, params=params) as response:
        if response.status != 200:
            raise RuntimeError(f"Brave Search HTTP {response.status}")
        data = await response.json(content_type=None)
    return [
        WebSource(
            title=_clean_text(item.get("title", "Untitled"), 240),
            url=item.get("url", ""),
            snippet=_clean_text(item.get("description", ""), 800),
        )
        for item in (data.get("web", {}).get("results", []) or [])
        if item.get("url")
    ][:WEB_SEARCH_RESULTS]


async def _duckduckgo_search(session, query: str) -> list[WebSource]:
    url = f"https://html.duckduckgo.com/html/?q={quote_plus(query)}"
    body, _ = await _request_text(session, url, {"User-Agent": "HannaAI/1.0 web-research"})
    parser = _DuckParser()
    parser.feed(body)
    sources = []
    for item in parser.results[:WEB_SEARCH_RESULTS]:
        raw_url = html.unescape(item["url"])
        parsed = urlparse(raw_url)
        if parsed.path.startswith("/l/"):
            raw_url = parse_qs(parsed.query).get("uddg", [raw_url])[0]
        sources.append(WebSource(_clean_text(item["title"], 240), raw_url, _clean_text(item["snippet"], 800)))
    return [source for source in sources if source.url.startswith(("http://", "https://"))]


async def search_web(query: str) -> list[WebSource]:
    timeout = aiohttp.ClientTimeout(total=WEB_FETCH_TIMEOUT)
    async with aiohttp.ClientSession(timeout=timeout) as session:
        if WEB_SEARCH_API_KEY:
            try:
                return await _brave_search(session, query)
            except Exception:
                logger.warning("Brave Search failed; using DuckDuckGo fallback", exc_info=True)
        return await _duckduckgo_search(session, query)


async def research_web(query: str) -> list[WebSource]:
    sources = await search_web(query)
    if not sources:
        return []
    timeout = aiohttp.ClientTimeout(total=WEB_FETCH_TIMEOUT)
    connector = aiohttp.TCPConnector(limit=WEB_SEARCH_RESULTS)
    async with aiohttp.ClientSession(timeout=timeout, connector=connector) as session:
        async def enrich(source: WebSource) -> WebSource:
            try:
                body, content_type = await _request_text(session, source.url, {"User-Agent": "HannaAI/1.0 web-research"})
                if "html" in content_type.lower() or "" in content_type:
                    parser = _TextParser()
                    parser.feed(body)
                    source.content = _clean_text(" ".join(parser.parts), 9000)
                else:
                    source.content = _clean_text(body, 9000)
            except Exception as error:
                logger.info("Could not fetch %s: %s", source.url, error)
                source.content = source.snippet
            return source
        return await asyncio.gather(*(enrich(source) for source in sources))


def build_context(sources: list[WebSource]) -> str:
    blocks = []
    remaining = 24000
    for index, source in enumerate(sources, 1):
        content = (source.content or source.snippet)[:max(0, remaining)]
        blocks.append(
            f"SOURCE {index}\nTITLE: {source.title}\nURL: {source.url}\n"
            f"CONTENT: {content}"
        )
        remaining -= len(content)
        if remaining <= 0:
            break
    return "\n\n---\n\n".join(blocks)


def source_markdown(sources: list[WebSource]) -> str:
    return "\n\n<b>SUMBER</b>\n" + "\n".join(
        f"{index}. <a href=\"{html.escape(source.url, quote=True)}\">{html.escape(source.title or source.url)}</a>"
        for index, source in enumerate(sources, 1)
    )


def is_web_request(text: str) -> bool:
    return bool(re.match(
        r"^\s*(?:cari(?:\s+di\s+internet)?|search|telusuri|riset|research|cek\s+(?:berita|internet)|web)\b",
        text or "", re.IGNORECASE,
    ))


def extract_web_query(text: str) -> str:
    query = re.sub(
        r"^\s*(?:cari(?:\s+di\s+internet)?|search|telusuri|riset|research|cek\s+(?:berita|internet)|web)\s*[:,-]?\s*",
        "", text or "", flags=re.IGNORECASE,
    ).strip()
    return query or text.strip()
