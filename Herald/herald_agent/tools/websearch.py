from __future__ import annotations

import json
import ssl
import urllib.error
import urllib.parse
import urllib.request
from html.parser import HTMLParser
from typing import Any

from herald_agent.config import config_int
from herald_agent.errors import AgentError
from herald_agent.runtime import Runtime
from herald_agent.tools.common import ensure_tool_enabled
from herald_agent.utils import truncate


class DuckDuckGoHTMLParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.results: list[dict[str, str]] = []
        self._in_link = False
        self._current_href = ""
        self._current_text: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attrs_dict = dict(attrs)
        classes = attrs_dict.get("class", "")
        if tag == "a" and "result__a" in classes:
            self._in_link = True
            self._current_href = attrs_dict.get("href", "") or ""
            self._current_text = []

    def handle_data(self, data: str) -> None:
        if self._in_link:
            self._current_text.append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag == "a" and self._in_link:
            title = " ".join("".join(self._current_text).split())
            if title and self._current_href:
                self.results.append({"title": title, "url": clean_duckduckgo_url(self._current_href)})
            self._in_link = False


def clean_duckduckgo_url(url: str) -> str:
    parsed = urllib.parse.urlparse(url)
    query = urllib.parse.parse_qs(parsed.query)
    if "uddg" in query and query["uddg"]:
        return query["uddg"][0]
    return url


def web_search(runtime: Runtime, query: str, limit: int = 5) -> str:
    ensure_tool_enabled(runtime.config, "websearch")
    web = runtime.config.get("tools", {}).get("websearch", {})
    provider = web.get("provider", "duckduckgo_html")
    limit = max(1, min(int(limit), config_int(runtime.config, "tools", "websearch", "max_results", default=8)))

    if provider == "brave":
        return brave_search(query, limit, web)
    if provider == "serper":
        return serper_search(query, limit, web)
    if provider == "duckduckgo_html":
        return duckduckgo_html_search(query, limit, web)
    raise AgentError(f"Unsupported websearch provider: {provider}")


def brave_search(query: str, limit: int, web: dict[str, Any]) -> str:
    token = web.get("api_token", "")
    if not token or token.startswith("PUT_"):
        raise AgentError("Brave Search token is not configured.")
    api_url = web.get("api_url", "https://api.search.brave.com/res/v1/web/search")
    url = api_url + "?" + urllib.parse.urlencode({"q": query, "count": limit})
    request = urllib.request.Request(
        url,
        headers={
            "Accept": "application/json",
            "X-Subscription-Token": token,
            "User-Agent": "herald-cli-agent/1.0",
        },
    )
    return json.dumps(fetch_search_json(request, web, "web", "results", limit), ensure_ascii=False, indent=2)


def serper_search(query: str, limit: int, web: dict[str, Any]) -> str:
    token = web.get("api_token", "")
    if not token or token.startswith("PUT_"):
        raise AgentError("Serper token is not configured.")
    api_url = web.get("api_url", "https://google.serper.dev/search")
    payload = json.dumps({"q": query, "num": limit}).encode("utf-8")
    request = urllib.request.Request(
        api_url,
        data=payload,
        headers={
            "Content-Type": "application/json",
            "X-API-KEY": token,
            "User-Agent": "herald-cli-agent/1.0",
        },
        method="POST",
    )
    items = fetch_search_json(request, web, "organic", None, limit)
    return json.dumps(items, ensure_ascii=False, indent=2)


def fetch_search_json(
    request: urllib.request.Request,
    web: dict[str, Any],
    top_key: str,
    nested_key: str | None,
    limit: int,
) -> list[dict[str, str]]:
    timeout = int(web.get("timeout_seconds", 20))
    try:
        with open_search_url(request, web, timeout) as response:
            data = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        raise AgentError(f"Search HTTP {exc.code}: {truncate(body, 1000)}") from exc
    except urllib.error.URLError as exc:
        raise AgentError(search_error_message(exc)) from exc

    raw_items: Any = data.get(top_key, {})
    if nested_key:
        raw_items = raw_items.get(nested_key, [])
    if not isinstance(raw_items, list):
        raw_items = []

    results = []
    for item in raw_items[:limit]:
        results.append(
            {
                "title": str(item.get("title", "")),
                "url": str(item.get("url") or item.get("link") or ""),
                "snippet": str(item.get("description") or item.get("snippet") or ""),
            }
        )
    return results


def duckduckgo_html_search(query: str, limit: int, web: dict[str, Any]) -> str:
    api_url = web.get("api_url", "https://html.duckduckgo.com/html/")
    url = api_url + "?" + urllib.parse.urlencode({"q": query})
    request = urllib.request.Request(
        url,
        headers={"User-Agent": "Mozilla/5.0 herald-cli-agent/1.0"},
    )
    timeout = int(web.get("timeout_seconds", 20))
    try:
        with open_search_url(request, web, timeout) as response:
            html = response.read().decode("utf-8", errors="replace")
    except urllib.error.URLError as exc:
        raise AgentError(search_error_message(exc)) from exc

    parser = DuckDuckGoHTMLParser()
    parser.feed(html)
    return json.dumps(parser.results[:limit], ensure_ascii=False, indent=2)


def open_search_url(request: urllib.request.Request, web: dict[str, Any], timeout: int):
    context = build_ssl_context(web)
    try:
        return urllib.request.urlopen(request, timeout=timeout, context=context)
    except urllib.error.URLError as exc:
        if is_certificate_error(exc) and web.get("insecure_ssl_fallback", False):
            insecure_context = ssl._create_unverified_context()
            return urllib.request.urlopen(request, timeout=timeout, context=insecure_context)
        raise


def build_ssl_context(web: dict[str, Any]) -> ssl.SSLContext | None:
    if not web.get("verify_ssl", True):
        return ssl._create_unverified_context()
    try:
        import certifi  # type: ignore

        return ssl.create_default_context(cafile=certifi.where())
    except Exception:
        return ssl.create_default_context()


def is_certificate_error(exc: urllib.error.URLError) -> bool:
    reason = getattr(exc, "reason", None)
    if isinstance(reason, ssl.SSLCertVerificationError):
        return True
    text = str(exc).lower()
    return "certificate_verify_failed" in text or "ssl: certificate" in text


def search_error_message(exc: urllib.error.URLError) -> str:
    if is_certificate_error(exc):
        return (
            "Search request failed: SSL certificate verification failed. "
            "Set tools.websearch.insecure_ssl_fallback=true or tools.websearch.verify_ssl=false in agent_config.json."
        )
    return f"Search request failed: {exc}"
