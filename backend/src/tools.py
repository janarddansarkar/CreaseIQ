"""Tools: knowledge-base search per format (hybrid BM25 + semantic from build_kb.py) and web search."""
from __future__ import annotations

import os

from langchain_core.tools import StructuredTool, tool

from config import CONFIG_FILE, LEXICON, settings

from build_kb import HybridRetriever, load_config, to_passage

_KB_CFG = load_config(CONFIG_FILE)
_KB = HybridRetriever(_KB_CFG)                       # fails fast if the knowledge base has not been built
RRF_MAX = 2 / (_KB_CFG.rrf_k + 1)                    # best possible fused score (rank 1 in both indexes)


def _search(fmt: str, query: str, top_k: int | None) -> list[dict]:
    """Hybrid-search one format's Playing Conditions and return passages in the workflow schema."""
    if not query.strip():
        return []
    return [to_passage(h, RRF_MAX) for h in _KB.search(query, k=top_k or settings.retrieval.top_k, fmt=fmt)]


def _format_search_tool(fmt: str, name: str) -> StructuredTool:
    """Create the search tool for one match format."""
    def run(query: str, top_k: int | None = None) -> list[dict]:
        """Search the format's Playing Conditions for `query`."""
        return _search(fmt, query, top_k)
    return StructuredTool.from_function(run, name=name, description=f"Search ONLY the {fmt} Playing Conditions (hybrid BM25 + semantic).")


@tool
def get_clause(format: str, clause_number: str) -> list[dict]:
    """Fetch the chunk(s) of one format that contain a numbered clause, e.g. '2.14'."""
    return [to_passage(h, 1.0) for h in _KB.get_clause(format, clause_number)]


def _hit(title: str, url: str, snippet: str) -> dict:
    """One normalised result: whitespace collapsed (snippets can span lines) and the snippet cut to settings.web.max_snippet_chars."""
    return {"title": " ".join(title.split()), "url": url, "snippet": " ".join(snippet.split())[:settings.web.max_snippet_chars]}


def _ddgs_search(query: str, n: int) -> list[dict]:
    """DuckDuckGo text search via the `ddgs` package (no API key); returns [{title, url, snippet}]."""
    from ddgs import DDGS
    w = settings.web
    hits = DDGS(timeout=w.timeout_seconds).text(query, region=w.region, safesearch=w.safesearch, max_results=n)
    return [_hit(h.get("title", ""), h.get("href", ""), h.get("body", "")) for h in hits]


def _tavily_search(query: str, n: int) -> list[dict]:
    """Tavily search API (built for LLM agents); needs the key in the env var named by settings.web.tavily_key_env."""
    import httpx
    w = settings.web
    key = os.getenv(w.tavily_key_env)
    if not key:
        raise RuntimeError(f"{w.tavily_key_env} is not set")
    resp = httpx.post(w.tavily_url, headers={"Authorization": f"Bearer {key}"}, timeout=w.timeout_seconds,
                      json={"query": query, "max_results": n, "search_depth": w.tavily_depth})
    resp.raise_for_status()
    return [_hit(h.get("title", ""), h.get("url", ""), h.get("content", "")) for h in resp.json().get("results", [])]


_WEB_PROVIDERS = {"ddgs": _ddgs_search, "tavily": _tavily_search}


@tool
def web_search(web_query: str, max_results: int | None = None) -> list[dict]:
    """Web search for clearly non-cricket questions only. Provider is chosen in settings.web.provider; returns [{title, url, snippet}]."""
    if not web_query.strip():
        return []
    return _WEB_PROVIDERS[settings.web.provider](web_query, max_results or settings.web.max_results)


FORMAT_TOOLS = {fmt: _format_search_tool(fmt, name) for fmt, name in LEXICON["format_tools"].items()}
TOOLS = {t.name: t for t in (*FORMAT_TOOLS.values(), get_clause, web_search)}
TOOL_FORMAT = {name: fmt for fmt, name in LEXICON["format_tools"].items()}
