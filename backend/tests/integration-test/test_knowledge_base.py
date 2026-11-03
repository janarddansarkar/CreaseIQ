"""The real hybrid (BM25 + semantic + rerank) knowledge base built from the ICC Playing Conditions PDFs."""
import pytest

import tools
from config import settings

SEARCH = {"ODI": "search_odi_rules", "T20I": "search_t20i_rules"}


@pytest.mark.parametrize("fmt", ["ODI", "T20I"])
def test_search_returns_only_that_formats_passages(fmt):
    hits = tools.TOOLS[SEARCH[fmt]].invoke({"query": "free hit after a no ball", "top_k": 5})
    assert hits and all(h["format"] == fmt for h in hits)


def test_passages_have_the_workflow_schema_and_sane_scores():
    hits = tools.TOOLS[SEARCH["T20I"]].invoke({"query": "number of overs per bowler", "top_k": 3})
    assert len(hits) <= 3
    for h in hits:
        assert {"chunk_id", "clause_number", "format", "text", "retrieval_score", "refers_outside", "source_title", "printed_page_start"} <= set(h)
        assert 0 <= h["retrieval_score"] <= 1 and h["text"].strip()
    scores = [h["retrieval_score"] for h in hits]
    assert scores == sorted(scores, reverse=True)


def test_relevant_query_clears_the_evidence_threshold():
    top = tools.TOOLS[SEARCH["T20I"]].invoke({"query": "How many overs can one bowler bowl in an innings?", "top_k": 3})[0]
    assert top["retrieval_score"] >= settings.retrieval.min_score
    assert "over" in top["text"].lower()


def test_top_k_is_respected_and_defaults_from_config():
    assert len(tools.TOOLS[SEARCH["ODI"]].invoke({"query": "powerplay fielding restrictions", "top_k": 2})) <= 2
    assert len(tools.TOOLS[SEARCH["ODI"]].invoke({"query": "powerplay fielding restrictions"})) <= settings.retrieval.top_k


def test_blank_query_returns_nothing():
    assert tools.TOOLS[SEARCH["ODI"]].invoke({"query": "   "}) == []


@pytest.mark.parametrize("fmt", ["ODI", "T20I"])
def test_get_clause_returns_the_free_hit_clause(fmt):
    hits = tools.get_clause.invoke({"format": fmt, "clause_number": "21.18"})
    assert hits and all(h["format"] == fmt for h in hits)
    assert any("free hit" in h["text"].lower() for h in hits)
    assert all(h["retrieval_score"] == 1.0 for h in hits)


def test_get_clause_unknown_clause_is_empty():
    assert tools.get_clause.invoke({"format": "T20I", "clause_number": "99.99.99"}) == []


def test_every_format_tool_is_registered_in_the_graph_tool_table():
    import rag
    assert set(SEARCH.values()) <= set(rag.TOOLS)
