"""Redis semantic response cache: a similar, already-answered question is served from Redis ("cache hit") instead of re-running retrieval + the LLM.

Entries are plain Redis hashes (no Redis modules needed); the stored query embedding is compared in code (numpy) within a small bucket:
kb_version | format | language | intent. Only verified answers are stored. Redis being down never breaks the agent (fail-open).

CLI:  python src/cache.py stats | list | clear
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
import sys
import time
from typing import Optional

import numpy as np

from common import S
import re

from config import CONFIG_FILE, LEXICON, settings

_C = settings.cache
log = logging.getLogger("creaseiq.cache")
_IGNORE = set(LEXICON["cache"]["ignore_words"])


def _stopwords() -> frozenset:
    """The knowledge base's BM25 stopword list (a, the, is, in, ...)."""
    from build_kb import load_config
    return load_config(CONFIG_FILE).stopwords


_STOP: Optional[frozenset] = None


def key_terms(text: str) -> frozenset:
    """Content words of a question: lower-cased, plural 's' stripped, stopwords / generic question words / format names removed."""
    global _STOP
    _STOP = _STOP if _STOP is not None else _stopwords()
    out = set()
    for w in re.findall(r"\w+", text.lower()):
        w = w[:-1] if len(w) > 3 and w.endswith("s") else w
        if w not in _IGNORE and w not in _STOP:
            out.add(w)
    return frozenset(out)


def term_overlap(a: frozenset, b: frozenset) -> float:
    """Jaccard overlap of two key-term sets (1.0 when both are empty)."""
    return len(a & b) / len(a | b) if (a | b) else 1.0


class ResponseCache:
    """Similarity cache over Redis. Lazy: nothing connects until the first lookup/store."""

    def __init__(self) -> None:
        """Read the settings; the Redis client, the embedder and the knowledge-base version are created on first use."""
        self.prefix = os.environ.get("CREASEIQ_CACHE_PREFIX") or _C.prefix
        self._r = None
        self._ef = None
        self._kb: Optional[str] = None

    # ---- plumbing --------------------------------------------------------------------------------------------
    @property
    def r(self):
        """The Redis client (short timeouts so a dead server fails fast)."""
        if self._r is None:
            import redis
            self._r = redis.Redis.from_url(os.environ.get(_C.url_env, _C.url_default), socket_connect_timeout=_C.connect_timeout, socket_timeout=_C.connect_timeout * 4)
        return self._r

    def embed(self, text: str) -> np.ndarray:
        """L2-normalised MiniLM embedding (Chroma's default ONNX model, already used by the knowledge base)."""
        if self._ef is None:
            from chromadb.utils.embedding_functions import DefaultEmbeddingFunction
            self._ef = DefaultEmbeddingFunction()
        v = np.asarray(self._ef([text])[0], dtype=np.float32)
        return v / (np.linalg.norm(v) or 1.0)

    @property
    def kb_version(self) -> str:
        """Fingerprint of the built knowledge base: rebuilding it changes the key space, so old answers are never served."""
        if self._kb is None:
            from build_kb import load_config
            p = load_config(CONFIG_FILE).bm25_path
            st = p.stat() if p.exists() else None
            self._kb = hashlib.sha1(f"{st.st_size}:{int(st.st_mtime)}".encode()).hexdigest()[:8] if st else "nokb"
        return self._kb

    def bucket(self, fmt: str, lang: str, intent: str) -> str:
        """Entries are only compared within the same knowledge-base version, format, language and intent."""
        return f"{self.kb_version}:{fmt}:{lang}:{intent}"

    def _idx(self, bucket: str) -> str:
        """Key of the sorted set that lists a bucket's entries (score = creation time)."""
        return f"{self.prefix}:idx:{bucket}"

    # ---- lookup / store ----------------------------------------------------------------------------------------
    def lookup(self, query: str, fmt: str, lang: str, intent: str, clause: Optional[str]) -> Optional[dict]:
        """Best entry in the bucket with cosine >= similarity (and the same clause for clause lookups), or None."""
        bucket = self.bucket(fmt, lang, intent)
        ids = [i.decode() for i in self.r.zrange(self._idx(bucket), 0, -1)]
        if not ids:
            return None
        keys = [f"{self.prefix}:cache:{bucket}:{i}" for i in ids]
        pipe = self.r.pipeline()
        for k in keys:
            pipe.hmget(k, "embedding", "clause", "query")
        rows = pipe.execute()
        live = [(k, emb, cl, q) for k, (emb, cl, q) in zip(keys, rows) if emb is not None]
        stale = [i for i, (emb, _, _) in zip(ids, rows) if emb is None]
        if stale:
            self.r.zrem(self._idx(bucket), *stale)       # expired by TTL
        if clause:
            live = [t for t in live if (t[2] or b"").decode() == clause]
        if not live:
            return None
        sims = np.vstack([np.frombuffer(e, dtype=np.float32) for _, e, _, _ in live]) @ self.embed(query)
        terms = key_terms(query)
        best = next((int(i) for i in np.argsort(-sims)                     # best cosine first; it must ALSO share the key terms
                     if float(sims[i]) >= _C.similarity and term_overlap(terms, key_terms(live[i][3].decode())) >= _C.min_term_overlap), None)
        if best is None:
            return None
        key = live[best][0]
        h = {k.decode(): v for k, v in self.r.hgetall(key).items() if k != b"embedding"}
        self.r.hincrby(key, "hits", 1)
        return {"similarity": round(float(sims[best]), 3), "query": h["query"].decode(), "answer_body": h["answer_body"].decode(),
                "citations": json.loads(h["citations"]), "conclusion": h.get("conclusion", b"").decode(), "key": key}

    def store(self, query: str, fmt: str, lang: str, intent: str, clause: Optional[str], answer_body: str, citations: list, conclusion: str) -> str:
        """Save a verified answer (TTL applies) and keep the bucket within max_entries_per_bucket by dropping the oldest entries."""
        bucket = self.bucket(fmt, lang, intent)
        eid = hashlib.sha1(f"{query}|{clause}".encode()).hexdigest()[:16]
        key = f"{self.prefix}:cache:{bucket}:{eid}"
        now = time.time()
        pipe = self.r.pipeline()
        pipe.hset(key, mapping={"query": query, "embedding": self.embed(query).tobytes(), "answer_body": answer_body, "citations": json.dumps(citations),
                                "conclusion": conclusion, "clause": clause or "", "format": fmt, "language": lang, "intent": intent,
                                "created": now, "hits": 0})
        pipe.expire(key, _C.ttl_seconds)
        pipe.zadd(self._idx(bucket), {eid: now})
        pipe.expire(self._idx(bucket), _C.ttl_seconds)
        pipe.execute()
        extra = self.r.zcard(self._idx(bucket)) - _C.max_entries_per_bucket
        if extra > 0:
            old = [i for i, _ in self.r.zpopmin(self._idx(bucket), extra)]
            self.r.delete(*[f"{self.prefix}:cache:{bucket}:{i.decode()}" for i in old])
        return key

    # ---- admin -----------------------------------------------------------------------------------------------
    def keys(self) -> list[str]:
        """All cache entry keys under the prefix."""
        return sorted(k.decode() for k in self.r.scan_iter(match=f"{self.prefix}:cache:*", count=200))

    def clear(self) -> int:
        """Delete every key under the prefix; returns how many."""
        ks = [k for k in self.r.scan_iter(match=f"{self.prefix}:*", count=200)]
        return self.r.delete(*ks) if ks else 0


_CACHE: Optional[ResponseCache] = None


def get_cache() -> ResponseCache:
    """The process-wide cache."""
    global _CACHE
    if _CACHE is None:
        _CACHE = ResponseCache()
    return _CACHE


# ---- graph nodes -----------------------------------------------------------------------------------------------
def cache_lookup(state):
    """Node: serve a similar, already-answered question from Redis. A miss or any Redis error falls through to normal retrieval."""
    if not _C.enabled:
        return {"cache_status": "off"}
    try:
        lang = state.get("response_language") or settings.language.default
        hit = get_cache().lookup(state["normalized_english_query"], state["format"], lang, state["intent"], state.get("clause_number"))
    except Exception as e:      # fail-open: the cache must never break an answer
        log.warning("cache lookup failed: %s: %s", type(e).__name__, e)
        return {"cache_status": "error"}
    if not hit:
        return {"cache_status": "miss"}
    from rag import render_answer
    label = S(state, "cache_hit_label").format(q=hit["query"], sim=f"{hit['similarity']:.2f}")
    return {"cache_status": "hit", "cache_similarity": hit["similarity"], "cache_query": hit["query"], "answer_body": hit["answer_body"],
            "citations": hit["citations"], "analysis": {"conclusion": hit["conclusion"], "requirements": [], "fact_mapping": [], "uncertainty": "", "cited_chunk_ids": []},
            "validation_status": "passed", "answer": f"{label}\n\n{render_answer({**state, 'answer_body': hit['answer_body']}, hit['answer_body'], hit['citations'])}"}


def cache_store(state):
    """Node: after a verified answer (validation + output guard passed, no PII, not itself a cache hit), save it in Redis."""
    if not _C.enabled or state.get("cache_status") in ("hit", "off", "error") or state.get("status") != "answered" \
            or state.get("validation_status") != "passed" or state.get("pii_found") or not state.get("answer_body"):
        return {}
    try:
        lang = state.get("response_language") or settings.language.default
        get_cache().store(state["normalized_english_query"], state["format"], lang, state["intent"], state.get("clause_number"), state["answer_body"],
                          state.get("citations", []), (state.get("analysis") or {}).get("conclusion", ""))
        return {}
    except Exception as e:
        log.warning("cache store failed: %s: %s", type(e).__name__, e)
        return {"cache_status": "error"}


def _cli() -> None:
    """python src/cache.py stats | list | clear"""
    cmd = sys.argv[1] if len(sys.argv) > 1 else "stats"
    c = get_cache()
    if cmd == "clear":
        print(f"deleted {c.clear()} keys")
        return
    ks = c.keys()
    if cmd == "list":
        for k in ks:
            h = c.r.hmget(k, "query", "hits")
            print(f"{k}  ttl={c.r.ttl(k)}s  hits={(h[1] or b'0').decode()}  query={(h[0] or b'').decode()!r}")
    else:
        print(f"redis {c.r.ping() and 'OK'} | prefix {c.prefix} | kb_version {c.kb_version} | entries {len(ks)}")


if __name__ == "__main__":
    _cli()
