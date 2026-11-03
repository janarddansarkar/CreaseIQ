"""Web search tool plumbing (no network: providers and httpx are faked). KB-backed search tools are covered in integration-test."""
import pytest

import tools


def test_hit_normalises_whitespace_and_truncates():
    h = tools._hit("A \n  title", "http://x", "word " * 500)
    assert h["title"] == "A title" and len(h["snippet"]) <= tools.settings.web.max_snippet_chars and "\n" not in h["snippet"]


def test_web_search_dispatches_to_configured_provider(monkeypatch):
    monkeypatch.setitem(tools._WEB_PROVIDERS, tools.settings.web.provider, lambda q, n: [{"title": q, "url": "u", "snippet": str(n)}])
    out = tools.web_search.invoke({"web_query": "hello", "max_results": 2})
    assert out == [{"title": "hello", "url": "u", "snippet": "2"}]


def test_web_search_empty_query_returns_nothing(monkeypatch):
    monkeypatch.setitem(tools._WEB_PROVIDERS, tools.settings.web.provider, lambda q, n: pytest.fail("must not be called"))
    assert tools.web_search.invoke({"web_query": "   "}) == []


def test_tavily_requires_a_key(monkeypatch):
    monkeypatch.delenv(tools.settings.web.tavily_key_env, raising=False)
    with pytest.raises(RuntimeError, match="not set"):
        tools._tavily_search("q", 3)


def test_tavily_parses_results(monkeypatch):
    monkeypatch.setenv(tools.settings.web.tavily_key_env, "k")

    class Resp:
        def raise_for_status(self): pass
        def json(self): return {"results": [{"title": "T", "url": "http://u", "content": "snippet  text"}]}
    import httpx
    seen = {}
    monkeypatch.setattr(httpx, "post", lambda url, **kw: seen.update(kw) or Resp())
    assert tools._tavily_search("q", 3) == [{"title": "T", "url": "http://u", "snippet": "snippet text"}]
    assert seen["headers"]["Authorization"] == "Bearer k" and seen["json"]["max_results"] == 3


def test_tool_registry_covers_every_format():
    assert set(tools.TOOL_FORMAT.values()) == {"ODI", "T20I"}
    assert {"get_clause", "web_search"} <= set(tools.TOOLS)
