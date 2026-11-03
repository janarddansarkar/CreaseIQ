"""Failure paths of the graph: bounded repair, the requery safety net, abstention and error handling. The model is scripted per test."""
import pytest

import rag
from config import STRINGS, settings

GOOD = "A bowler may bowl a maximum of four overs in an innings."
BAD = "See clause 99.9.9 for the answer."          # cites a clause that was never retrieved -> validation fails
Q = "How many overs can one bowler bowl in T20I?"


def script(monkeypatch, bodies):
    """Make the answer-writing model return `bodies` in order (the last one repeats). Returns the list of calls made."""
    calls = []

    def fake_text(task, system, user):
        calls.append(task)
        return bodies[min(len(calls) - 1, len(bodies) - 1)]
    monkeypatch.setattr(rag, "llm_text", fake_text)
    return calls


def count(path, node):
    return path.count(node)


def test_one_bad_draft_is_fixed_by_the_single_repair(agent, monkeypatch):
    script(monkeypatch, [BAD, GOOD])
    out = agent(Q)
    assert out["status"] == "answered" and GOOD in out["answer"]
    assert count(out["path"], "constrained_repair") == 1 and "requery_original" not in out["path"]
    assert out["values"]["repair_attempt"] == 1


def test_failed_repair_triggers_one_requery_from_the_original_wording_then_succeeds(agent, monkeypatch):
    script(monkeypatch, [BAD, BAD, GOOD])         # draft bad, repair bad, answer after re-retrieval good
    out = agent(Q)
    v = out["values"]
    assert out["status"] == "answered" and GOOD in out["answer"]
    assert count(out["path"], "requery_original") == 1 and count(out["path"], "retrieve_rules") == 2
    assert v["retrieval_attempt"] == 1 and v["repair_attempt"] == 0         # the repair budget is reset for the new evidence
    assert v["normalized_english_query"] == Q                                 # the user's own wording was used for the retry


def test_everything_failing_abstains_and_is_bounded(agent, monkeypatch):
    calls = script(monkeypatch, [BAD])
    out = agent(Q)
    assert out["status"] == "insufficient_evidence" and out["answer"] in set(STRINGS["en"].values())
    assert count(out["path"], "requery_original") == settings.limits.max_retrieval_retries
    assert count(out["path"], "constrained_repair") <= settings.limits.max_repairs * (1 + settings.limits.max_retrieval_retries)
    assert len(calls) <= 8                                                     # no runaway loop
    assert out["path"][-1] == "handle_insufficient_evidence"


def test_failed_answers_are_never_cached(agent, monkeypatch, fake_redis):
    script(monkeypatch, [BAD])
    agent(Q)
    assert fake_redis.keys() == []


def test_followup_requery_uses_reformulation_not_the_elliptical_text(agent, monkeypatch):
    agent(Q, user="r1")                                                         # establishes the prior turn
    script(monkeypatch, [BAD, BAD, GOOD, GOOD])
    out = agent("And in ODI?", user="r1")
    assert out["status"] == "answered" and "requery_original" in out["path"]
    assert out["values"]["normalized_english_query"] != "And in ODI?"


def test_authority_claims_in_a_draft_are_blocked_then_repaired(agent, monkeypatch):
    script(monkeypatch, ["This is a binding decision: four overs.", GOOD])
    out = agent(Q)
    assert out["status"] == "answered" and "binding" not in out["answer"].lower() and "output_guard" in out["path"]
    assert count(out["path"], "constrained_repair") == 1


def test_a_draft_that_leaks_a_secret_is_never_returned(agent, monkeypatch):
    script(monkeypatch, ["The key is sk-abcdefghijklmnop1234."])
    out = agent(Q)
    assert "sk-abcdefghij" not in out["answer"]
    assert out["status"] in ("insufficient_evidence", "unsupported")


def test_weak_evidence_retries_once_then_abstains(agent, monkeypatch):
    class Empty:
        calls = 0

        def invoke(self, args):
            Empty.calls += 1
            return []
    monkeypatch.setitem(rag.TOOLS, "search_t20i_rules", Empty())
    out = agent("How many overs can one bowler bowl in T20I?")
    assert out["status"] == "insufficient_evidence" and out["values"]["insufficient_reason"] == "no_relevant_passage"
    assert count(out["path"], "reformulate_query") == 1 and Empty.calls == 2
    assert "analyse_scenario" not in out["path"]


def test_evidence_that_only_points_outside_the_corpus_skips_the_retry(agent, monkeypatch):
    passage = {"chunk_id": "x|p1|c0", "clause_number": "1.1", "format": "T20I", "retrieval_score": 0.9, "text": "See the ICC Code of Conduct.",
               "refers_outside": True, "source_id": "s", "source_title": "t", "version": "", "printed_page_start": 1}

    class Outside:
        def invoke(self, args):
            return [passage]
    monkeypatch.setitem(rag.TOOLS, "search_t20i_rules", Outside())
    out = agent(Q)
    assert out["status"] == "insufficient_evidence" and out["values"]["insufficient_reason"] == "outside_sources"
    assert "reformulate_query" not in out["path"]


def test_a_crashing_model_call_ends_in_the_generic_error_not_a_stack_trace(agent, monkeypatch):
    def boom(*a, **k):
        raise RuntimeError("secret-internal-detail 10.1.2.3")
    monkeypatch.setattr(rag, "llm_structured", boom)
    out = agent(Q)
    assert out["status"] == "error" and out["answer"] == STRINGS["en"]["error"] and out["path"][-1] == "handle_error"
    assert "10.1.2.3" not in out["answer"]


def test_routing_model_failure_is_handled(agent, monkeypatch):
    import route

    def boom(*a, **k):
        raise ValueError("bad json from model")
    monkeypatch.setattr(route, "llm_structured", boom)
    out = agent(Q)
    assert out["status"] == "error" and "retrieve_rules" not in out["path"]


def test_retrieval_format_leak_is_caught_by_the_release_gate(agent, monkeypatch):
    leak = {"chunk_id": "o|p1|c0", "clause_number": "1", "format": "ODI", "retrieval_score": 0.9, "text": "x", "refers_outside": False,
            "source_id": "s", "source_title": "t", "version": "", "printed_page_start": 1}

    class Leaky:
        def invoke(self, args):
            return [leak]
    monkeypatch.setitem(rag.TOOLS, "search_t20i_rules", Leaky())
    out = agent(Q)
    assert out["status"] == "error"        # an ODI passage returned from the T20I tool must never reach an answer
