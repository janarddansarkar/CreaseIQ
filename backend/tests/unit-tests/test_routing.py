import pytest
from langchain_core.messages import AIMessage, HumanMessage

from route import UNKNOWN, decide_route, detect_format, load_or_initialize_state
from state import RouteResult


def R(relevance="cricket", **kw):
    return RouteResult(cricket_relevance=relevance, **kw)


@pytest.mark.parametrize("text,fmt", [
    ("how many overs in a T20I", "T20I"),
    ("T20 International rules", "T20I"),
    ("ODI powerplay", "ODI"),
    ("one day international", "ODI"),
    ("compare ODI and T20I", UNKNOWN),      # both named: ambiguous
    ("how many overs", UNKNOWN),
])
def test_detect_format(text, fmt):
    assert detect_format(text) == fmt


def test_scenario_with_format():
    d = decide_route(R(), {}, "Is a free hit given for a no ball in T20I?", "")
    assert (d["intent"], d["format"], d["missing_facts"], d["unsupported_reason"]) == ("scenario", "T20I", [], None)


def test_missing_format_triggers_clarification():
    d = decide_route(R(), {}, "Is a free hit given for a no ball?", "")
    assert d["format"] == UNKNOWN and d["missing_facts"] == ["format"]


def test_clause_lookup_extracts_number():
    d = decide_route(R(), {}, "What does clause 21.18. say in ODI?", "")
    assert d["intent"] == "clause_lookup" and d["clause_number"] == "21.18"


def test_compare_intent_does_not_need_a_single_format():
    d = decide_route(R(), {}, "Compare the free hit rule in ODI and T20I", "")
    assert d["intent"] == "compare" and d["missing_facts"] == []


def test_named_format_makes_an_unclear_message_cricket():
    d = decide_route(R("unclear"), {}, "what about T20I?", "")
    assert d["cricket_relevance"] == "cricket"


def test_non_cricket_is_general():
    d = decide_route(R("non_cricket"), {}, "who won the football world cup", "")
    assert d["intent"] == "general" and d["missing_facts"] == [] and d["unsupported_reason"] is None


@pytest.mark.parametrize("text,reason", [
    ("What is the follow-on rule in a Test match?", "format_not_supported"),
    ("women's T20I super over?", "format_not_supported"),
    ("IPL powerplay overs in T20I", "competition_specific"),
])
def test_unsupported_scope(text, reason):
    assert decide_route(R(), {}, text, "")["unsupported_reason"] == reason


def test_pending_question_is_combined_with_the_clarification_reply():
    d = decide_route(R(), {}, "T20I", "Is a free hit given for a no ball?")
    assert d["format"] == "T20I" and d["missing_facts"] == []


def test_format_carried_from_state():
    assert decide_route(R(), {"format": "ODI"}, "and the powerplay?", "")["format"] == "ODI"


def test_memory_format_is_used_and_flagged():
    d = decide_route(R(), {"memory_format": "ODI"}, "How many fielders in the powerplay?", "")
    assert d["format"] == "ODI" and d["format_from_memory"] is True and d["missing_facts"] == []


def test_memory_format_never_overrides_a_named_format():
    d = decide_route(R(), {"memory_format": "ODI"}, "How many overs in T20I?", "")
    assert d["format"] == "T20I" and d["format_from_memory"] is False


def test_memory_format_not_used_for_compare():
    d = decide_route(R(), {"memory_format": "ODI"}, "What is the difference between formats for free hits?", "")
    assert d["format_from_memory"] is False


# ---- load_or_initialize_state --------------------------------------------------------------------------------------
def test_new_question_resets_conversation_facts():
    out = load_or_initialize_state({"messages": [HumanMessage("T20I overs?")], "scenario_facts": ["old"], "profile": {"preferred_format": "ODI"}})
    assert out["question"] == "T20I overs?" and out["original_question"] == "T20I overs?"
    assert out["scenario_facts"] == [] and out["format"] == UNKNOWN and out["clarification_count"] == 0
    assert out["memory_format"] == "ODI" and out["is_follow_up"] is False
    assert out["retrieval_attempt"] == 0 and out["repair_attempt"] == 0 and out["cache_status"] == "off"


def test_clarification_reply_keeps_the_thread():
    out = load_or_initialize_state({"messages": [HumanMessage("free hit?"), AIMessage("which format?"), HumanMessage("T20I")], "status": "clarification_required"})
    assert out["is_follow_up"] is True and out["question"] == "T20I"
    assert "original_question" not in out and "scenario_facts" not in out      # carried over, not reset


def test_old_messages_are_trimmed_to_the_memory_window():
    msgs = [HumanMessage(f"q{i}", id=f"m{i}") for i in range(80)]
    out = load_or_initialize_state({"messages": msgs})
    assert len(out["messages"]) == 80 - 49 and all(type(m).__name__ == "RemoveMessage" for m in out["messages"])
