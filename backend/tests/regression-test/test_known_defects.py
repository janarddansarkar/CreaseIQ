"""One test per defect that was found and fixed. Each recreates the failing condition, so re-introducing the bug fails the matching test.

REG-001  plural 'T20Is'/'ODIs' not recognised as a format                      (commit 031ebd3)
REG-002  earlier turns reworded a self-contained question's retrieval query     (commit be9dc7c)
REG-003  a citation copied as the whole evidence header was not resolved         (found while writing the test suites)
REG-004  the retry after a failed repair used elliptical text ("And in ODI?")    (found while verifying REG-002's safety net)
REG-005  the repair budget was not reset by the retry, so the retry could not repair
REG-006  a Redis outage must not break answers (fail-open)
REG-007  the cache served a paraphrase that changed the decisive fact
REG-008  PII questions and failed answers must never be cached
REG-009  evicting a user left that user's graph checkpoints behind
REG-010  the stream's step events must equal the executed node path
REG-011  tests must never touch the real memory database
REG-012  an off-corpus question naming a format was answered from unrelated passages (format name inflated the reranker score)
REG-013  a correct answer citing a clause printed inside a page-level passage ('13.9.1' in passage 'p23') was rejected, so the agent abstained
REG-014  the test suite shipped questions and answers to LangSmith because .env enables tracing
REG-015  plural/list clause references ('clauses 14 and 15') bypassed answer validation, so invented clauses could be cited
REG-016  web answers showed their sources twice in the UI (inline text block AND the web-sources panel)
"""
import fakeredis
import pytest

import cache
import rag
import route
import tools
from config import settings
from memory import MemoryStore
from route import UNKNOWN, detect_format
from runner import ask


# ---- REG-001 ---------------------------------------------------------------------------------------------------
@pytest.mark.parametrize("text,fmt", [
    ("What is a free hit in T20Is?", "T20I"), ("how many overs in ODIs", "ODI"), ("T20I's rules", "T20I"), ("T20Is", "T20I"),
])
def test_reg001_plural_formats_are_recognised(text, fmt):
    assert detect_format(text) == fmt


def test_reg001_plural_question_is_answered_end_to_end(agent):
    out = agent("What is a free hit in T20Is?")
    assert out["status"] == "answered" and out["values"]["format"] == "T20I"


# ---- REG-002 ---------------------------------------------------------------------------------------------------
def test_reg002_history_must_not_reword_a_self_contained_question(agent, monkeypatch):
    """Reproduces the failure with a scripted 'model' that words its search query differently when it can see history, and a retriever that only
    finds the passages for the canonical wording (exactly what mistral:7b did). Before the fix this abstained."""
    real_route = route.llm_structured

    def history_sensitive_router(task, schema, system, user):
        r = real_route(task, schema, system, user)
        if "overs" in user.lower() and "t20i" in user.lower():
            wording = "T20I overs per bowler in an innings" if "<history>" in user else "T20I bowling overs per innings"
            r = r.model_copy(update={"normalized_english_query": wording})
        return r
    monkeypatch.setattr(route, "llm_structured", history_sensitive_router)

    real_tool = rag.TOOLS["search_t20i_rules"]

    class WordingSensitiveRetriever:
        def invoke(self, args):
            hits = real_tool.invoke(args)
            if "bowling overs per innings" in args["query"].lower():
                return hits
            return [{**h, "retrieval_score": 0.02} for h in hits]       # reworded query: only weak matches come back
    monkeypatch.setitem(rag.TOOLS, "search_t20i_rules", WordingSensitiveRetriever())

    agent("What happens after a no ball in an ODI?", user="reg2")      # an earlier turn exists, so there IS history to leak
    out = agent("In T20I, how many overs can one bowler bowl in an innings?", user="reg2")
    assert out["status"] == "answered" and out["values"]["normalized_english_query"] == "T20I bowling overs per innings"


# ---- REG-003 ---------------------------------------------------------------------------------------------------
CHUNK = "ICC Men's T20I Playing Conditions|p38|c0"


@pytest.mark.parametrize("cited", [
    f"[{CHUNK} | clause 21.18 | T20I]",       # the whole evidence header, as the model sees it
    f"{CHUNK} | clause 21.18",
    CHUNK,
    "clause 21.18",
    "21.18",
])
def test_reg003_sloppy_citations_resolve_to_the_retrieved_chunk(cited):
    passage = {"chunk_id": CHUNK, "clause_number": "21.18"}
    assert rag.resolve_citation(cited, [passage]) == CHUNK


def test_reg003_a_header_citation_survives_validation_without_a_repair(agent, monkeypatch):
    real = rag.llm_structured

    def header_citing(task, schema, system, user):
        a = real(task, schema, system, user)
        if task == "analyse":
            ids = [line[1:line.index(" | clause")] for line in user.splitlines() if line.startswith("[") and " | clause" in line]
            a = a.model_copy(update={"cited_chunk_ids": [f"[{i} | clause 1 | T20I]" for i in ids[:2]]})
        return a
    monkeypatch.setattr(rag, "llm_structured", header_citing)
    out = agent("How many overs can one bowler bowl in T20I?")
    assert out["status"] == "answered" and "constrained_repair" not in out["path"]


# ---- REG-004 / REG-005 -----------------------------------------------------------------------------------------
def test_reg004_retry_never_searches_with_an_elliptical_follow_up():
    out = _requery({"question": "And in ODI?", "normalized_english_query": "overs per bowler ODI"}, reformulated="overs per bowler ODI one-day")
    assert out["normalized_english_query"] == "overs per bowler ODI one-day"


def test_reg005_retry_resets_the_repair_budget():
    assert _requery({"question": "How many overs can a bowler bowl in T20I?", "normalized_english_query": "x"})["repair_attempt"] == 0


def _requery(extra, reformulated="reformulated"):
    import unittest.mock as m
    base = {"retrieval_attempt": 0, "repair_attempt": 1, "input_language": "en", **extra}
    with m.patch.object(rag, "llm_text", return_value=reformulated):
        return rag.requery_original(base)


# ---- REG-006 / REG-007 / REG-008 -----------------------------------------------------------------------------------
def test_reg006_redis_outage_does_not_break_answers(agent, monkeypatch):
    server = fakeredis.FakeServer()
    server.connected = False
    c = cache.ResponseCache()
    c._r = fakeredis.FakeRedis(server=server)
    monkeypatch.setattr(cache, "_CACHE", c)
    out = agent("How many overs can one bowler bowl in T20I?")
    assert out["status"] == "answered" and out["cache_status"] == "error"


def test_reg007_a_changed_decisive_fact_is_not_served_from_the_cache(agent):
    first = agent("Is a batter out if bowled off a no ball in T20I?", user="reg7a")
    second = agent("Is a batter out if run out off a no ball in T20I?", user="reg7b")
    assert first["status"] == "answered" and second["cache_status"] == "miss"


def test_reg008_pii_and_failed_answers_are_never_cached(agent, fake_redis, monkeypatch):
    agent("What is the free hit rule in T20I? mail fan@example.com", user="reg8a")
    monkeypatch.setattr(rag, "llm_text", lambda *a, **k: "See clause 99.9.9.")
    failed = agent("How many overs can one bowler bowl in T20I?", user="reg8b")
    assert failed["status"] == "insufficient_evidence" and fake_redis.keys() == []


# ---- REG-009 ---------------------------------------------------------------------------------------------------
def test_reg009_evicting_a_user_removes_their_checkpoints_too(tmp_path):
    from graph import build_graph
    store = MemoryStore(tmp_path / "evict.sqlite", max_users=2)
    graph = build_graph(store=store)
    for user in ("old", "mid", "new"):
        ask(graph, "How many overs can one bowler bowl in T20I?", user, None, False, store=store)

    def rows(user):
        return store.conn.execute("SELECT COUNT(*) FROM checkpoints WHERE thread_id=?", (user,)).fetchone()[0]
    assert rows("old") == 0 and rows("mid") == 1 and rows("new") == 1
    assert store.turns("old") == []


# ---- REG-010 ---------------------------------------------------------------------------------------------------
def test_reg010_step_callback_reports_every_executed_node_in_order(graph, store):
    seen = []
    out = ask(graph, "How many overs can one bowler bowl in T20I?", "reg10", None, False, store=store, on_step=seen.append)
    assert seen == out["path"] and len(seen) > 8


def test_reg010_step_callback_is_optional(graph, store):
    assert ask(graph, "How many overs can one bowler bowl in T20I?", "reg10b", None, False, store=store)["status"] == "answered"


# ---- REG-011 ---------------------------------------------------------------------------------------------------
def test_reg011_the_suite_never_touches_the_real_memory_database():
    import memory
    real = memory.BACKEND.parent / "backend" / "data" / "memory.sqlite"
    assert memory.default_db_path() != real and "creaseiq-tests-" in str(memory.default_db_path())
    assert cache.get_cache().prefix == "creaseiq-test"


# ---- REG-012 ---------------------------------------------------------------------------------------------------
@pytest.mark.parametrize("question", [
    "What is the strategic timeout rule in T20I?",      # scored 0.26 (> min_score 0.2) with the format name, 0.00 without
    "What is the dress code for the umpires in an ODI match?",      # scored up to 0.94
])
def test_reg012_naming_the_format_must_not_turn_an_off_corpus_question_into_evidence(agent, question):
    out = agent(question)
    assert out["status"] == "insufficient_evidence" and out["values"]["insufficient_reason"] == "weak_evidence"


def test_reg012_the_format_name_does_not_reach_the_reranker():
    q = "What is the dress code for the umpires in an T20I match?"      # not in the corpus; the raw query scored 0.89 purely because of the format name
    t = tools.TOOLS["search_t20i_rules"]
    with_name = t.invoke({"query": q, "top_k": 3})[0]["retrieval_score"]
    without = t.invoke({"query": rag.search_query(q), "top_k": 3})[0]["retrieval_score"]
    assert with_name >= settings.retrieval.min_score > without      # documents the bug: the raw query cleared the evidence bar, the cleaned one does not


# ---- REG-013 ---------------------------------------------------------------------------------------------------
def _validate_against_real_passages(body):
    passages = tools.TOOLS["search_t20i_rules"].invoke({"query": "how many overs can one bowler bowl in an innings", "top_k": 3})
    cites = rag.build_citations([passages[0]["chunk_id"]], passages)
    state = {"response_language": "en", "format": "T20I", "retrieved_rules": passages, "answer_body": body, "citations": cites}
    state["answer"] = rag.render_answer(state, body, cites)
    return passages, rag.validate_final_answer(state)


def test_reg013_a_clause_printed_in_the_real_retrieved_page_is_grounded():
    passages, out = _validate_against_real_passages("Under clause 13.9.1 no bowler may bowl more than four overs in an innings.")
    assert passages[0]["clause_number"] == "p23" and "13.9.1" in passages[0]["text"]      # the exact case that failed: page label, clause in the text
    assert out == {"validation_status": "passed", "validation_issues": []}


def test_reg013_an_invented_clause_is_still_rejected_against_the_real_passages():
    _, out = _validate_against_real_passages("Under clause 13.9.99 no bowler may bowl more than four overs in an innings.")
    assert out["validation_status"] == "failed" and "unknown_clause:13.9.99" in out["validation_issues"]


# ---- REG-014 ---------------------------------------------------------------------------------------------------
def test_reg014_tests_never_send_traces_to_langsmith():
    import os
    from langsmith.utils import tracing_is_enabled
    assert os.environ["LANGSMITH_TRACING"] == "false" and not tracing_is_enabled()


# ---- REG-015 ---------------------------------------------------------------------------------------------------
def test_reg015_the_exact_answer_that_slipped_through_in_the_ui_is_now_rejected():
    body = ("In T20I a bowler can bowl a maximum of four overs in an innings (clause 13.9.1). The follow-on and declaration are not allowed "
            "in T20I cricket (clauses 14 and 15). The overs can be adjusted (clauses 13.7.1.1-13.7.1.4).")
    passages = tools.TOOLS["search_t20i_rules"].invoke({"query": "how many overs can one bowler bowl in an innings", "top_k": 3})
    cites = rag.build_citations([passages[0]["chunk_id"]], passages)
    state = {"response_language": "en", "format": "T20I", "retrieved_rules": passages, "answer_body": body, "citations": cites}
    state["answer"] = rag.render_answer(state, body, cites)
    out = rag.validate_final_answer(state)
    assert out["validation_status"] == "failed"
    assert {"unknown_clause:14", "unknown_clause:15"} <= set(out["validation_issues"])


def test_reg015_singular_references_still_work_and_prose_numbers_are_not_clauses():
    assert rag.referenced_clauses("under clause 13.9.1 and 4 overs, with clauses 13.9.2 and 13.9.3") == ["13.9.1", "13.9.2", "13.9.3"]


# ---- REG-016 ---------------------------------------------------------------------------------------------------
def test_reg016_web_answer_layout_the_ui_relies_on(agent, fake_web):
    out = agent("Who won the football world cup?")
    parts = out["answer"].split("\n\n")
    assert out["status"] == "answered_general" and len(parts) >= 3
    assert parts[-2].startswith("Sources:") and parts[-1].startswith("General answer from web search")
    assert out["values"]["web_sources"]      # the structured list the UI renders instead of the text block
