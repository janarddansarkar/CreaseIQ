import fakeredis
import numpy as np
import pytest

import cache
from cache import cache_lookup, cache_store, key_terms, term_overlap

Q = "T20I overs per bowler in an innings"
BODY = "A bowler may bowl four overs."
CITES = [{"chunk_id": "c1", "source_title": "T20I PC", "clause_number": "13.9", "printed_page_start": 23}]


# ---- pure helpers ------------------------------------------------------------------------------------------------
def test_key_terms_drops_stopwords_formats_and_plurals():
    assert key_terms("What are the overs the bowlers bowl in T20I?") == key_terms("over bowler bowl")


def test_term_overlap():
    a, b = key_terms("run out at the non-striker end"), key_terms("bowled at the stumps")
    assert term_overlap(a, a) == 1.0 and term_overlap(a, b) < 0.5 and term_overlap(frozenset(), frozenset()) == 1.0


# ---- ResponseCache (fakeredis) -----------------------------------------------------------------------------------
def test_store_then_lookup_hits_exact_and_paraphrase(fake_redis):
    fake_redis.store(Q, "T20I", "en", "scenario", None, BODY, CITES, "four overs")
    hit = fake_redis.lookup(Q, "T20I", "en", "scenario", None)
    assert hit and hit["similarity"] > 0.99 and hit["answer_body"] == BODY and hit["citations"] == CITES and hit["conclusion"] == "four overs"
    assert fake_redis.lookup("Overs per bowler in T20I innings", "T20I", "en", "scenario", None)


def test_lookup_counts_hits(fake_redis):
    key = fake_redis.store(Q, "T20I", "en", "scenario", None, BODY, CITES, "")
    fake_redis.lookup(Q, "T20I", "en", "scenario", None)
    fake_redis.lookup(Q, "T20I", "en", "scenario", None)
    assert int(fake_redis.r.hget(key, "hits")) == 2


@pytest.mark.parametrize("fmt,lang,intent", [("ODI", "en", "scenario"), ("T20I", "hi", "scenario"), ("T20I", "en", "compare")])
def test_buckets_are_isolated(fake_redis, fmt, lang, intent):
    fake_redis.store(Q, "T20I", "en", "scenario", None, BODY, CITES, "")
    assert fake_redis.lookup(Q, fmt, lang, intent, None) is None


def test_changed_decisive_fact_is_a_miss_even_if_embeddings_are_close(fake_redis):
    fake_redis.store("Is a batter out if run out at the non striker end in T20I", "T20I", "en", "scenario", None, BODY, CITES, "")
    assert fake_redis.lookup("Is a batter out if bowled at the non striker end in T20I", "T20I", "en", "scenario", None) is None


def test_unrelated_question_is_a_miss(fake_redis):
    fake_redis.store(Q, "T20I", "en", "scenario", None, BODY, CITES, "")
    assert fake_redis.lookup("What is the penalty for slow over rate", "T20I", "en", "scenario", None) is None


def test_clause_lookups_require_the_same_clause(fake_redis):
    fake_redis.store("What does clause 21.18 say", "T20I", "en", "clause_lookup", "21.18", BODY, CITES, "")
    assert fake_redis.lookup("What does clause 21.18 say", "T20I", "en", "clause_lookup", "21.18")
    assert fake_redis.lookup("What does clause 21.19 say", "T20I", "en", "clause_lookup", "21.19") is None


def test_expired_entries_are_dropped_from_the_index(fake_redis):
    key = fake_redis.store(Q, "T20I", "en", "scenario", None, BODY, CITES, "")
    fake_redis.r.delete(key)      # simulate TTL expiry of the hash
    assert fake_redis.lookup(Q, "T20I", "en", "scenario", None) is None
    assert fake_redis.r.zcard(fake_redis._idx(fake_redis.bucket("T20I", "en", "scenario"))) == 0


def test_bucket_size_cap_evicts_oldest(fake_redis, monkeypatch):
    monkeypatch.setattr(cache._C, "max_entries_per_bucket", 3)
    for i in range(5):
        fake_redis.store(f"distinct question number {i} about topic{i}", "T20I", "en", "scenario", None, BODY, CITES, "")
    assert len(fake_redis.keys()) == 3


def test_ttl_is_set_and_clear_deletes_everything(fake_redis):
    key = fake_redis.store(Q, "T20I", "en", "scenario", None, BODY, CITES, "")
    assert 0 < fake_redis.r.ttl(key) <= cache._C.ttl_seconds
    assert fake_redis.clear() >= 2 and fake_redis.keys() == []


def test_kb_version_changes_the_key_space(fake_redis):
    fake_redis.store(Q, "T20I", "en", "scenario", None, BODY, CITES, "")
    fake_redis._kb = "otherkb1"
    assert fake_redis.lookup(Q, "T20I", "en", "scenario", None) is None


def test_embedding_is_normalised(fake_redis):
    assert np.linalg.norm(fake_redis.embed("hello cricket")) == pytest.approx(1.0, abs=1e-4)


def _dead_redis():
    server = fakeredis.FakeServer()
    server.connected = False      # every command raises ConnectionError, like a stopped Redis
    return fakeredis.FakeRedis(server=server)


# ---- graph nodes -------------------------------------------------------------------------------------------------
def _state(**kw):
    return {"normalized_english_query": Q, "format": "T20I", "intent": "scenario", "response_language": "en", "clause_number": None, **kw}


def test_lookup_off_when_disabled(monkeypatch):
    monkeypatch.setattr(cache._C, "enabled", False)
    assert cache_lookup(_state()) == {"cache_status": "off"}


def test_lookup_miss_then_hit_builds_a_verified_answer(fake_redis):
    assert cache_lookup(_state()) == {"cache_status": "miss"}
    fake_redis.store(Q, "T20I", "en", "scenario", None, BODY, CITES, "four overs")
    out = cache_lookup(_state())
    assert out["cache_status"] == "hit" and out["validation_status"] == "passed"
    assert out["answer"].startswith("⚡ Cache hit") and BODY in out["answer"] and "T20I PC, clause 13.9" in out["answer"]


def test_lookup_fails_open_when_redis_is_down(monkeypatch):
    c = cache.ResponseCache()
    c._r = _dead_redis()
    monkeypatch.setattr(cache, "_CACHE", c)
    assert cache_lookup(_state()) == {"cache_status": "error"}


GOOD = dict(status="answered", validation_status="passed", answer_body=BODY, citations=CITES, cache_status="miss", analysis={"conclusion": "c"})


def test_store_saves_only_verified_answers(fake_redis):
    assert cache_store(_state(**GOOD)) == {}
    assert len(fake_redis.keys()) == 1


@pytest.mark.parametrize("override", [
    {"cache_status": "hit"}, {"cache_status": "off"}, {"cache_status": "error"}, {"status": "insufficient_evidence"},
    {"validation_status": "failed"}, {"pii_found": ["EMAIL"]}, {"answer_body": ""},
])
def test_store_skips(fake_redis, override):
    cache_store(_state(**{**GOOD, **override}))
    assert fake_redis.keys() == []


def test_store_fails_open(monkeypatch):
    c = cache.ResponseCache()
    c._r = _dead_redis()
    monkeypatch.setattr(cache, "_CACHE", c)
    assert cache_store(_state(**GOOD)) == {"cache_status": "error"}
