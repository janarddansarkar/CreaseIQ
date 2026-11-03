import pytest
from langchain_core.messages import HumanMessage, SystemMessage

import llm
from state import Analysis, RouteResult


def test_stub_router_classifies():
    r = llm.llm_structured("route", RouteResult, "p", "KNOWN_FACTS: \nPENDING_QUESTION: \nMESSAGE: How many overs can a bowler bowl in T20I?")
    assert r.cricket_relevance == "cricket" and "overs" in r.normalized_english_query
    n = llm.llm_structured("route", RouteResult, "p", "MESSAGE: who won the football world cup")
    assert n.cricket_relevance == "non_cricket"
    u = llm.llm_structured("route", RouteResult, "p", "MESSAGE: what is the rule")
    assert u.cricket_relevance == "unclear"


def test_stub_analysis_cites_given_evidence():
    ev = "[c1 | clause 1.1 | T20I] text one\n[c2 | clause 2.2 | T20I] text two\n[c3 | clause 3.3 | T20I] text three"
    a = llm.llm_structured("analyse", Analysis, "p", f"QUESTION: q\nFACTS: \nEVIDENCE:\n{ev}")
    assert a.cited_chunk_ids == ["c1", "c2"] and a.conclusion


def test_stub_text_tasks():
    assert llm.llm_text("reformulate", "p", "QUERY: T20I overstepping").endswith("no ball front foot popping crease")
    assert llm.llm_text("general", "p", "RESULTS:\n- A snippet | title | http://u").endswith("A snippet.")
    assert llm.llm_text("unknown", "p", "x") == ""


def test_structured_retries_then_succeeds(monkeypatch):
    calls = {"n": 0}

    class Flaky:
        def with_structured_output(self, schema, **kw):
            class R:
                def invoke(_, msgs):
                    calls["n"] += 1
                    if calls["n"] == 1:
                        raise ValueError("bad json")
                    return "ok"
            return R()
    monkeypatch.setattr(llm, "llm", Flaky())
    assert llm.llm_structured("t", RouteResult, "s", "u") == "ok" and calls["n"] == 2


def test_structured_raises_after_all_attempts(monkeypatch):
    class Dead:
        def with_structured_output(self, schema, **kw):
            class R:
                def invoke(_, msgs):
                    raise ValueError("always")
            return R()
    monkeypatch.setattr(llm, "llm", Dead())
    with pytest.raises(ValueError, match="always"):
        llm.llm_structured("t", RouteResult, "s", "u")


def test_field_parser():
    assert llm.field("A: 1\nTASK: answer\nB: 2", "TASK") == "answer" and llm.field("nothing", "TASK") == ""


def test_task_tag_is_prepended_to_the_system_prompt(monkeypatch):
    seen = {}

    class Spy:
        def invoke(self, msgs):
            seen["system"], seen["user"] = msgs[0], msgs[-1]
            from langchain_core.messages import AIMessage
            return AIMessage(content="  hi  ")
    monkeypatch.setattr(llm, "llm", Spy())
    assert llm.llm_text("answer", "SYS", "USR") == "hi"
    assert isinstance(seen["system"], SystemMessage) and seen["system"].content.startswith("TASK: answer\nSYS")
    assert isinstance(seen["user"], HumanMessage)
