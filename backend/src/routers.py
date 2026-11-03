"""Routers (the diamonds of the architecture diagram)."""
from __future__ import annotations

from typing import Literal

from langgraph.graph import END

from config import settings

_L = settings.limits


def route_after_route(state) -> Literal["handle_error", "general_qa_gate", "clarification_gate", "scope_gate"]:
    """After routing: error, non-cricket, unclear or cricket."""
    if state.get("error"):
        return "handle_error"
    return {"non_cricket": "general_qa_gate", "unclear": "clarification_gate"}.get(state["cricket_relevance"], "scope_gate")


def route_general_qa(state) -> Literal["web_search", "handle_non_cricket"]:
    """Web search when general Q&A is enabled, otherwise the 'switched off' reply."""
    return "web_search" if settings.features.general_qa_enabled else "handle_non_cricket"


def route_scope(state) -> Literal["handle_unsupported", "context_gate"]:
    """Unsupported format or competition goes to handle_unsupported; supported goes on."""
    return "handle_unsupported" if state.get("unsupported_reason") else "context_gate"


def route_context(state) -> Literal["clarification_gate", "cache_lookup"]:
    """Missing decisive facts go to clarification; otherwise the response cache is checked before retrieval starts."""
    return "clarification_gate" if state.get("missing_facts") else "cache_lookup"


def route_after_cache(state) -> Literal["save_final_state", "retrieve_rules"]:
    """A cache hit is already a verified answer and is saved directly; a miss (or cache error) continues to retrieval."""
    return "save_final_state" if state.get("cache_status") == "hit" else "retrieve_rules"


def route_clarification(state) -> Literal["ask_clarification", "handle_insufficient_evidence"]:
    """Ask for clarification while the cap allows it, otherwise abstain."""
    return "handle_insufficient_evidence" if state.get("clarification_count", 0) >= _L.max_clarifications else "ask_clarification"


def route_after_evidence(state) -> Literal["analyse_scenario", "reformulate_query", "handle_insufficient_evidence"]:
    """Analyse when evidence is sufficient; retry once with a reformulated query; otherwise abstain."""
    if state["evidence_status"] == "sufficient":
        return "analyse_scenario"
    if state.get("insufficient_reason") == "outside_sources":      # a better query cannot add provisions the corpus does not contain
        return "handle_insufficient_evidence"
    return "reformulate_query" if state.get("retrieval_attempt", 0) < _L.max_retrieval_retries else "handle_insufficient_evidence"


def route_after_input_guard(state) -> Literal["handle_unsupported", "understand_and_route"]:
    """Stop with a refusal when the input guard blocked the message."""
    return "handle_unsupported" if state.get("blocked_reason") else "understand_and_route"


def route_after_validation(state) -> Literal["handle_error", "output_guard", "constrained_repair", "requery_original", "handle_insufficient_evidence"]:
    """Error, then output guard when valid, then the single repair, then one retrieval retry from the original wording, then abstain."""
    if state.get("error"):
        return "handle_error"
    if state["validation_status"] == "passed":
        return "output_guard"
    if state.get("repair_attempt", 0) < _L.max_repairs:
        return "constrained_repair"
    return "requery_original" if state.get("retrieval_attempt", 0) < _L.max_retrieval_retries else "handle_insufficient_evidence"


def route_after_output(state) -> Literal["save_final_state", "constrained_repair", "handle_unsupported"]:
    """A rejected reply reuses the single repair attempt; if that is spent, refuse with a safe fixed message."""
    if state["validation_status"] == "passed":
        return "save_final_state"
    return "constrained_repair" if state.get("repair_attempt", 0) < _L.max_repairs else "handle_unsupported"


def continue_or_error(next_node: str):
    """Build a router that goes to handle_error when the state has an error, otherwise to `next_node`."""
    def route(state):
        """Return the next node name."""
        return "handle_error" if state.get("error") else next_node
    return route


def end_or_error(state):
    """Router for nodes that end the graph: handle_error on error, otherwise END."""
    return "handle_error" if state.get("error") else END
