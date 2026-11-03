"""Load state, route the message (one structured model call), and make the routing decisions in code."""
from __future__ import annotations

import re

from langchain_core.messages import HumanMessage, RemoveMessage

from common import safe_node
from config import LEXICON, PROMPTS, settings
from context import is_followup
from language import detect_language
from llm import llm_structured
from state import RouteResult

_R = LEXICON["routing"]
_FORMAT_RES = {fmt: re.compile(p, re.I) for fmt, p in LEXICON["format_patterns"].items()}
_COMPARE = re.compile(_R["compare_pattern"], re.I)
_CLAUSE = re.compile(_R["clause_pattern"], re.I)
UNKNOWN = "unknown"


def load_or_initialize_state(state):
    """Node: reset the per-turn fields; keep the conversation facts only when this turn answers a clarification."""
    last_user = next((m.content for m in reversed(state["messages"]) if isinstance(m, HumanMessage)), "")
    follow_up = state.get("status") == "clarification_required"
    out = {"question": last_user, "is_follow_up": follow_up, "retrieval_attempt": 0, "repair_attempt": 0, "retrieved_rules": [], "retrieval_plan": [],
           "evidence_status": "pending", "insufficient_reason": None, "analysis": None, "citations": [], "answer": "", "answer_body": "",
           "validation_status": "pending", "validation_issues": [], "web_results": [], "web_sources": [], "error": None, "unsupported_reason": None,
           "status": "pending", "clarification_question": None, "blocked_reason": None, "format_from_memory": False, "memory_format": None,
           "cache_status": "off", "cache_similarity": None, "cache_query": None}
    keep = 2 * settings.memory.max_turns - 1       # short-term memory: last max_turns turns (user message + reply); -1 leaves room for this turn's reply
    old = state["messages"]
    if len(old) > keep:
        out["messages"] = [RemoveMessage(id=m.id) for m in old[: len(old) - keep] if m.id]
    if not follow_up:       # a brand-new question: forget the previous one
        out.update(original_question=last_user, clarification_count=0, scenario_facts=[], missing_facts=[], format=UNKNOWN, intent="", clause_number=None)
        if settings.memory.prefill_format:      # long-term memory: offered only when the message itself names no format (see decide_route)
            out["memory_format"] = (state.get("profile") or {}).get("preferred_format")
    return out


def detect_format(text: str) -> str:
    """Return the match format named in the text, or 'unknown' when none or both are named."""
    hits = [fmt for fmt, rx in _FORMAT_RES.items() if rx.search(text)]
    return hits[0] if len(hits) == 1 else UNKNOWN


def decide_route(r: RouteResult, state: dict, message: str, pending: str) -> dict:
    """Intent, format, scope and missing facts from the text and the model's extraction. Same code path for the stub and a real model."""
    text = f"{pending} {message}"
    clause = _CLAUSE.search(text)
    relevance = r.cricket_relevance
    if relevance != "cricket" and (detect_format(text) != UNKNOWN or clause):    # a named format or clause is cricket
        relevance = "cricket"
    fmt = detect_format(text)
    if fmt == UNKNOWN:
        fmt = state.get("format", UNKNOWN)                                       # carried over from an earlier turn
    from_memory = False
    if fmt == UNKNOWN and state.get("memory_format") and relevance == "cricket" and not _COMPARE.search(text):
        fmt, from_memory = state["memory_format"], True                          # long-term memory: the user's usual format
    unsupported = next((v for k, v in _R["unsupported_markers"].items() if k in text.lower()), None) if relevance == "cricket" else None
    if relevance != "cricket":
        intent = "general"
    elif clause:
        intent = "clause_lookup"
    elif _COMPARE.search(text):
        intent = "compare"
    else:
        intent = "scenario"
    missing = []
    if relevance == "cricket" and not unsupported and intent in ("scenario", "clause_lookup") and fmt == UNKNOWN:
        missing.append("format")
    return {"cricket_relevance": relevance, "intent": intent, "format": fmt, "format_from_memory": from_memory and intent in ("scenario", "clause_lookup"), "unsupported_reason": unsupported, "missing_facts": missing,
            "clause_number": clause.group(1).strip(_R["clause_strip_chars"]) if clause else None}


@safe_node
def understand_and_route(state):
    """Node: one structured model call extracts facts and queries; routing decisions are then made in code."""
    follow = state.get("is_follow_up", False)
    pending = state.get("original_question", "") if follow else ""
    hist = (state.get("history") or "") if (follow or is_followup(state["question"])) else ""      # history only completes elliptical follow-ups; a self-contained question must not be reworded by it
    user = "\n".join(([hist] if hist else []) + [f"KNOWN_FACTS: {' | '.join(state.get('scenario_facts', []))}", f"PENDING_QUESTION: {pending}", f"MESSAGE: {state['question']}"])
    r: RouteResult = llm_structured("route", RouteResult, PROMPTS["route"], user)
    prior = state.get("prior_turn")
    followup = bool(prior) and not follow and is_followup(state["question"])
    if followup and r.cricket_relevance == "unclear":      # an elliptical follow-up to a rules turn cannot be judged alone: it continues that topic
        r = r.model_copy(update={"cricket_relevance": "cricket"})
    d = decide_route(r, state, state["question"], pending)
    query = r.normalized_english_query or state["question"]
    if followup and d["cricket_relevance"] == "cricket":      # complete the elliptical follow-up from the last answered turn
        base = prior["q_norm"]
        if detect_format(state["question"]) != UNKNOWN:         # a different format is named: drop the old one's words from the carried query
            base = " ".join(w for w in base.split() if detect_format(w) == UNKNOWN)
        query = f"{base} {query}".strip()
        if prior.get("intent") == "clause_lookup" and prior.get("clause_no") and not d["clause_number"]:
            d.update(intent="clause_lookup", clause_number=prior["clause_no"])
    return {**d, "input_language": detect_language(state["question"]),
            "response_language": state.get("requested_language") or detect_language(state["question"]),
            "scenario_facts": list(dict.fromkeys(state.get("scenario_facts", []) + r.scenario_facts)),
            "normalized_english_query": query, "web_query": r.web_query or state["question"]}
