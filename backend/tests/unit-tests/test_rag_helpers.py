import pytest

import rag
from config import STRINGS, settings


def P(cid="T20I|p23|c0", clause="13.9", fmt="T20I", score=0.9, text="A bowler may bowl 4 overs.", outside=False):
    return {"chunk_id": cid, "clause_number": clause, "format": fmt, "retrieval_score": score, "text": text, "refers_outside": outside,
            "source_id": "s", "source_title": "T20I PC", "version": "", "printed_page_start": 23}


# ---- evidence helpers --------------------------------------------------------------------------------------------
def test_evidence_for_reasoning_drops_weak_passages():
    ps = [P(score=0.9), P("x", score=settings.retrieval.min_score - 0.01), P("y", score=settings.retrieval.min_score)]
    assert [p["chunk_id"] for p in rag.evidence_for_reasoning({"retrieved_rules": ps})] == ["T20I|p23|c0", "y"]


def test_numbered_evidence_format():
    assert rag.numbered_evidence([P()]) == "[T20I|p23|c0 | clause 13.9 | T20I] A bowler may bowl 4 overs."


def test_allowed_clauses_include_referenced_clauses():
    ps = [P(clause="13.9", text="as in clause 6.1. and clause 2.4,")]
    assert rag.allowed_clauses(ps) == {"13.9", "6.1", "2.4"}


def test_build_citations_adds_source_fields_only_for_known_chunks():
    cites = rag.build_citations(["T20I|p23|c0", "ghost"], [P()])
    assert cites[0]["clause_number"] == "13.9" and cites[0]["printed_page_start"] == 23
    assert cites[1] == {"chunk_id": "ghost"}


def test_render_answer_appends_sources_and_disclaimer():
    out = rag.render_answer({"response_language": "en", "format": "T20I"}, "Body.", rag.build_citations(["T20I|p23|c0"], [P()]))
    assert out.startswith("Body.") and "T20I PC, clause 13.9, p.23" in out and out.endswith(STRINGS["en"]["disclaimer"])


def test_render_answer_notes_a_remembered_format():
    out = rag.render_answer({"response_language": "en", "format": "ODI", "format_from_memory": True}, "Body.", [])
    assert "ODI" in out.split("Body.")[0]


# ---- resolve_citation --------------------------------------------------------------------------------------------
@pytest.mark.parametrize("cid,expected", [
    ("T20I|p23|c0", "T20I|p23|c0"),
    ("[T20I|p23|c0 | clause 13.9 | T20I]", "T20I|p23|c0"),
    ("[ICC Men's T20I Playing Conditions|p38|c0 | clause 21.18 | T20I]", "ICC Men's T20I Playing Conditions|p38|c0"),      # real chunk ids contain '|'
    ("ICC Men's T20I Playing Conditions|p38|c0 | clause 21.18", "ICC Men's T20I Playing Conditions|p38|c0"),
    ("clause 13.9", "T20I|p23|c0"),
    ("13.9", "T20I|p23|c0"),
    ("T20I", None),                  # bare format name is noise
    ("totally-made-up", "totally-made-up"),      # kept so validation rejects it
])
def test_resolve_citation(cid, expected):
    real = P("ICC Men's T20I Playing Conditions|p38|c0", clause="21.18")
    assert rag.resolve_citation(cid, [P(), real]) == expected


# ---- check_evidence ----------------------------------------------------------------------------------------------
def test_check_evidence_outcomes():
    ok = rag.check_evidence({"retrieved_rules": [P()], "intent": "scenario"})
    assert ok == {"evidence_status": "sufficient", "insufficient_reason": None}
    assert rag.check_evidence({"retrieved_rules": [], "intent": "scenario"})["insufficient_reason"] == "no_relevant_passage"
    assert rag.check_evidence({"retrieved_rules": [P(score=0.01)], "intent": "scenario"})["insufficient_reason"] == "weak_evidence"
    assert rag.check_evidence({"retrieved_rules": [P(outside=True)], "intent": "scenario"})["insufficient_reason"] == "outside_sources"


def test_compare_needs_strong_evidence_from_both_formats():
    one = rag.check_evidence({"retrieved_rules": [P(fmt="ODI")], "intent": "compare"})
    both = rag.check_evidence({"retrieved_rules": [P(fmt="ODI"), P("b", fmt="T20I")], "intent": "compare"})
    assert one["insufficient_reason"] == "weak_evidence" and both["evidence_status"] == "sufficient"


# ---- validate_final_answer ---------------------------------------------------------------------------------------
def _state(**kw):
    ps = [P()]
    body = "A bowler may bowl 4 overs under clause 13.9."
    cites = rag.build_citations(["T20I|p23|c0"], ps)
    s = {"response_language": "en", "format": "T20I", "retrieved_rules": ps, "answer_body": body, "citations": cites}
    s["answer"] = rag.render_answer(s, body, cites)
    return {**s, **kw}


def test_validation_passes_a_clean_answer():
    assert rag.validate_final_answer(_state()) == {"validation_status": "passed", "validation_issues": []}


@pytest.mark.parametrize("override,issue", [
    ({"answer_body": "  "}, "empty_answer"),
    ({"citations": []}, "no_citations"),
    ({"citations": [{"chunk_id": "ghost"}]}, "unknown_citation:ghost"),
    ({"answer_body": "See clause 99.9 for details."}, "unknown_clause:99.9"),
    ({"answer": "no disclaimer here"}, "missing_disclaimer"),
])
def test_validation_catches(override, issue):
    out = rag.validate_final_answer(_state(**override))
    assert out["validation_status"] == "failed" and issue in out["validation_issues"]


# ---- reformulate / requery_original ------------------------------------------------------------------------------
BASE = {"normalized_english_query": "T20I overs per bowler", "retrieval_attempt": 0, "repair_attempt": 1, "input_language": "en"}


def test_reformulate_uses_model_and_counts_the_attempt(monkeypatch):
    monkeypatch.setattr(rag, "llm_text", lambda *a, **k: "new query")
    assert rag.reformulate_query(BASE) == {"normalized_english_query": "new query", "retrieval_attempt": 1}


def test_reformulate_keeps_old_query_when_model_fails(monkeypatch):
    def boom(*a, **k):
        raise RuntimeError("down")
    monkeypatch.setattr(rag, "llm_text", boom)
    assert rag.reformulate_query(BASE)["normalized_english_query"] == "T20I overs per bowler"


def test_requery_uses_the_original_wording_and_resets_repairs():
    out = rag.requery_original({**BASE, "question": "  How many overs   can a bowler bowl in T20I? "})
    assert out == {"normalized_english_query": "How many overs can a bowler bowl in T20I?", "retrieval_attempt": 1, "repair_attempt": 0}


def test_requery_falls_back_to_reformulation(monkeypatch):
    monkeypatch.setattr(rag, "llm_text", lambda *a, **k: "reformulated")
    for q, lang in (("And in ODI?", "en"),                       # elliptical follow-up: raw text lacks the carried context
                    ("T20I में कितने ओवर?", "hi"),                 # not English
                    ("T20I overs per bowler", "en")):             # identical to the current query: nothing new to try
        out = rag.requery_original({**BASE, "question": q, "input_language": lang})
        assert out["normalized_english_query"] == "reformulated" and out["retrieval_attempt"] == 1 and out["repair_attempt"] == 0, q


# ---- search_query: the format name is removed from the query sent to a (format-specific) search tool ------------------------
@pytest.mark.parametrize("query,expected", [
    ("What is the strategic timeout rule in T20I?", "What is the strategic timeout rule?"),
    ("In T20I, how many overs can one bowler bowl in an innings?", "how many overs can one bowler bowl in an innings?"),
    ("How many overs in ODIs?", "How many overs?"),
    ("What is the dress code for the umpires in an T20I match?", "What is the dress code for the umpires?"),
    ("What happens in a one day international if rain stops play?", "What happens if rain stops play?"),
    ("T20I overs per bowler in an innings", "overs per bowler in an innings"),
    ("Compare the free hit rule in ODI and T20I", "Compare the free hit rule"),
    ("ODI vs T20I powerplay", "powerplay"),
    ("टी-20 में पावरप्ले", "में पावरप्ले"),
    ("What does the rule say about a free hit", "What does the rule say about a free hit"),      # nothing to remove
])
def test_search_query_removes_the_format_name(query, expected):
    assert rag.search_query(query) == expected


@pytest.mark.parametrize("query", ["T20I", "the T20I rules", "ODI", "in ODIs"])
def test_search_query_keeps_the_original_when_only_the_format_would_be_left(query):
    assert rag.search_query(query) == query


def test_search_query_does_not_touch_look_alike_words():
    assert rag.search_query("Android godis t200 runs") == "Android godis t200 runs"
