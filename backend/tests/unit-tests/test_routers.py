import pytest
from langgraph.graph import END

import routers as r


def test_route_after_route():
    assert r.route_after_route({"error": "x", "cricket_relevance": "cricket"}) == "handle_error"
    assert r.route_after_route({"cricket_relevance": "non_cricket"}) == "general_qa_gate"
    assert r.route_after_route({"cricket_relevance": "unclear"}) == "clarification_gate"
    assert r.route_after_route({"cricket_relevance": "cricket"}) == "scope_gate"


def test_general_qa_switch(monkeypatch):
    monkeypatch.setattr(r.settings.features, "general_qa_enabled", True)
    assert r.route_general_qa({}) == "web_search"
    monkeypatch.setattr(r.settings.features, "general_qa_enabled", False)
    assert r.route_general_qa({}) == "handle_non_cricket"


def test_route_scope_and_context():
    assert r.route_scope({"unsupported_reason": "format_not_supported"}) == "handle_unsupported"
    assert r.route_scope({}) == "context_gate"
    assert r.route_context({"missing_facts": ["format"]}) == "clarification_gate"
    assert r.route_context({"missing_facts": []}) == "cache_lookup"


def test_route_after_cache():
    assert r.route_after_cache({"cache_status": "hit"}) == "save_final_state"
    for s in ("miss", "off", "error"):
        assert r.route_after_cache({"cache_status": s}) == "retrieve_rules"


def test_clarification_cap():
    cap = r._L.max_clarifications
    assert r.route_clarification({"clarification_count": cap - 1}) == "ask_clarification"
    assert r.route_clarification({"clarification_count": cap}) == "handle_insufficient_evidence"


def test_route_after_evidence():
    assert r.route_after_evidence({"evidence_status": "sufficient"}) == "analyse_scenario"
    assert r.route_after_evidence({"evidence_status": "insufficient", "retrieval_attempt": 0}) == "reformulate_query"
    assert r.route_after_evidence({"evidence_status": "insufficient", "retrieval_attempt": 1}) == "handle_insufficient_evidence"
    assert r.route_after_evidence({"evidence_status": "insufficient", "insufficient_reason": "outside_sources", "retrieval_attempt": 0}) == "handle_insufficient_evidence"


def test_input_guard_router():
    assert r.route_after_input_guard({"blocked_reason": "input:policy"}) == "handle_unsupported"
    assert r.route_after_input_guard({"blocked_reason": None}) == "understand_and_route"


class TestAfterValidation:
    base = {"validation_status": "failed", "repair_attempt": 0, "retrieval_attempt": 0}

    def test_error_wins(self):
        assert r.route_after_validation({**self.base, "error": "x"}) == "handle_error"

    def test_passed_goes_to_output_guard(self):
        assert r.route_after_validation({**self.base, "validation_status": "passed"}) == "output_guard"

    def test_failed_first_gets_the_repair(self):
        assert r.route_after_validation(self.base) == "constrained_repair"

    def test_repair_spent_gets_one_requery(self):
        assert r.route_after_validation({**self.base, "repair_attempt": 1}) == "requery_original"

    def test_everything_spent_abstains(self):
        assert r.route_after_validation({**self.base, "repair_attempt": 1, "retrieval_attempt": 1}) == "handle_insufficient_evidence"


def test_route_after_output():
    assert r.route_after_output({"validation_status": "passed"}) == "save_final_state"
    assert r.route_after_output({"validation_status": "failed", "repair_attempt": 0}) == "constrained_repair"
    assert r.route_after_output({"validation_status": "failed", "repair_attempt": 1}) == "handle_unsupported"


def test_continue_or_error_and_end_or_error():
    nxt = r.continue_or_error("n")
    assert nxt({}) == "n" and nxt({"error": "x"}) == "handle_error"
    assert r.end_or_error({}) == END and r.end_or_error({"error": "x"}) == "handle_error"
