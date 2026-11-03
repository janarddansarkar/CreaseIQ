"""Shared test setup. Runs BEFORE any project module is imported, because config.py / llm.py / tools.py read their settings at import time.

Default run (deterministic, offline): the rule-based StubLLM, a throw-away SQLite memory DB, a throw-away cache prefix, and an in-memory fake Redis.
RUN_LIVE=1: the real Ollama model from backend/.env is used instead (only the `live` tests are meant for that mode).
"""
from __future__ import annotations

import os
import re
import sys
import tempfile
from pathlib import Path

import pytest

BACKEND = Path(__file__).resolve().parents[1]      # backend/ (this file lives in backend/tests/)
LIVE = os.environ.get("RUN_LIVE") == "1"

_TMP = Path(tempfile.mkdtemp(prefix="creaseiq-tests-"))
_cfg = (BACKEND / "config" / "config.toml").read_text()
_cfg = re.sub(r"^(use_stub\s*=\s*)\w+", r"\g<1>" + ("false" if LIVE else "true"), _cfg, count=1, flags=re.M)
(_TMP / "config.toml").write_text(_cfg)
os.environ["CREASEIQ_CONFIG"] = str(_TMP / "config.toml")
os.environ["CREASEIQ_MEMORY_DB"] = str(_TMP / "memory.sqlite")
os.environ["CREASEIQ_CACHE_PREFIX"] = "creaseiq-test"
for _var in ("LANGSMITH_TRACING", "LANGCHAIN_TRACING_V2", "LANGSMITH_TRACING_V2"):      # tests must never ship questions/answers to LangSmith (.env enables tracing for the app)
    os.environ[_var] = "false"
sys.path.insert(0, str(BACKEND / "src"))


def pytest_collection_modifyitems(config, items):
    """`live` tests only run with RUN_LIVE=1; in live mode only they run (the other tests assume the stub model)."""
    for item in items:
        is_live = "live" in item.keywords
        if is_live and not LIVE:
            item.add_marker(pytest.mark.skip(reason="live test: set RUN_LIVE=1 (needs Ollama)"))
        if LIVE and not is_live:
            item.add_marker(pytest.mark.skip(reason="stub-model test skipped in RUN_LIVE mode"))


@pytest.fixture
def store(tmp_path):
    """A fresh SQLite memory store (own file) per test."""
    from memory import MemoryStore
    s = MemoryStore(tmp_path / "memory.sqlite")
    yield s
    s.conn.close()


@pytest.fixture
def fake_redis(monkeypatch):
    """Every test gets an empty in-memory Redis behind the process-wide response cache (so no real Redis is needed and nothing leaks between tests)."""
    import fakeredis
    import cache
    c = cache.ResponseCache()
    c._r = fakeredis.FakeRedis(server=fakeredis.FakeServer())
    monkeypatch.setattr(cache, "_CACHE", c)
    return c


@pytest.fixture(autouse=True)
def _isolated_cache(request, monkeypatch):
    """Autouse: every test gets its own empty fake Redis."""
    request.getfixturevalue("fake_redis")


@pytest.fixture
def graph(store):
    """A freshly compiled agent graph on the test's own memory store."""
    from graph import build_graph
    return build_graph(store=store)


class Agent:
    """Callable wrapper: agent("question", user="u1", lang=None) -> runner.ask() result dict, on the test's own graph + memory store."""

    def __init__(self, graph, store):
        self.graph, self.store = graph, store

    def __call__(self, text, user="u1", lang=None):
        from runner import ask
        return ask(self.graph, text, user, lang, False, store=self.store)


@pytest.fixture
def agent(graph, store):
    return Agent(graph, store)


@pytest.fixture
def fake_web(monkeypatch):
    """Deterministic web-search provider (no network). Returns the list of queries it was called with."""
    import tools
    calls: list[str] = []

    def provider(q, n):
        calls.append(q)
        return [{"title": "FIFA World Cup", "url": "https://example.org/wc", "snippet": "The FIFA World Cup is an international football competition."}]
    monkeypatch.setitem(tools._WEB_PROVIDERS, tools.settings.web.provider, provider)
    return calls
