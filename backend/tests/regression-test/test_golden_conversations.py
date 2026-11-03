"""Replays golden/conversations.json through the real agent. A failure here means user-visible behaviour changed."""
import json
from pathlib import Path

import pytest

from config import STRINGS

CASES = json.loads((Path(__file__).parent / "golden" / "conversations.json").read_text())["cases"]


@pytest.mark.parametrize("case", CASES, ids=[c["id"] for c in CASES])
def test_golden_conversation(case, agent, fake_web):
    user = f"golden-{case['id']}"
    for n, turn in enumerate(case["turns"], 1):
        out = agent(turn["user"], user=user, lang=turn.get("language"))
        v, e, where = out["values"], turn["expect"], f"{case['id']} turn {n} ({turn['user']!r})"
        assert out["status"] == e["status"], f"{where}: status {out['status']} != {e['status']}"
        for key, field in (("format", "format"), ("intent", "intent"), ("language", "response_language"), ("cache_status", "cache_status")):
            if key in e:
                assert v.get(field) == e[key], f"{where}: {field}={v.get(field)!r}, expected {e[key]!r}"
        if "reason" in e and e["reason"] is not None:
            assert v.get("insufficient_reason") == e["reason"], where
        cites = v.get("citations") or []
        if "citation_formats" in e:
            assert {c["format"] for c in cites} == set(e["citation_formats"]), f"{where}: citation formats"
        for clause in e.get("citation_clauses_include", []):
            assert clause in {c["clause_number"] for c in cites}, f"{where}: clause {clause} not cited"
        low = out["answer"].lower()
        for s in e.get("answer_contains", []):
            assert s.lower() in low, f"{where}: answer lacks {s!r}"
        for s in e.get("answer_not_contains", []):
            assert s.lower() not in low, f"{where}: answer has {s!r}"
        for node in e.get("path_includes", []):
            assert node in out["path"], f"{where}: path lacks {node}"
        for node in e.get("path_excludes", []):
            assert node not in out["path"], f"{where}: path has {node}"
        q = v.get("normalized_english_query", "").lower()
        for s in e.get("query_includes", []):
            assert s in q, f"{where}: query {q!r} lacks {s!r}"
        for s in e.get("query_excludes", []):
            assert s not in q, f"{where}: query {q!r} has {s!r}"
        if out["status"] == "answered" and not v.get("response_language") == "hi":
            assert STRINGS["en"]["disclaimer"] in out["answer"], f"{where}: disclaimer missing"
