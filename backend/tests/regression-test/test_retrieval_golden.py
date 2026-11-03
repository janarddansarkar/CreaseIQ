"""Retrieval recall baseline on the real knowledge base. A failure means a re-ingest, chunking, BM25, embedding or reranker change moved results."""
import json
from pathlib import Path

import pytest

import tools
from config import settings

G = json.loads((Path(__file__).parent / "golden" / "retrieval.json").read_text())
TOOL = {"T20I": "search_t20i_rules", "ODI": "search_odi_rules"}


def top(case, k=3):
    return tools.TOOLS[TOOL[case["format"]]].invoke({"query": case["query"], "top_k": k})


@pytest.mark.parametrize("case", G["recall"], ids=[f"{c['format']}-{c['query'][:35]}" for c in G["recall"]])
def test_expected_passage_is_retrieved(case):
    hits = top(case)
    window = hits[: case["within"]]
    assert any(case["phrase"] in h["text"] for h in window), f"{case['phrase']!r} not in top {case['within']}: {[h['clause_number'] for h in hits]}"
    assert all(h["format"] == case["format"] for h in hits)
    assert hits[0]["retrieval_score"] >= settings.retrieval.min_score, "best passage would not count as evidence"
    if "clause_top1" in case:
        assert hits[0]["clause_number"] == case["clause_top1"]


@pytest.mark.parametrize("case", G["abstain"], ids=[c["query"][:35] for c in G["abstain"]])
def test_out_of_corpus_queries_stay_below_the_evidence_threshold(case):
    assert all(h["retrieval_score"] < settings.retrieval.min_score for h in top(case)), "off-corpus query now looks like evidence: the agent would answer instead of abstaining"
