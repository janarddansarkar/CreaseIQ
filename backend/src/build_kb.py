"""
CreaseIQ knowledge base builder + hybrid (BM25 + semantic) retriever.

Reads every PDF in the configured docs folder, chunks it, and builds:
  * a semantic index  -> ChromaDB persistent collection (default ONNX MiniLM embeddings, no torch needed)
  * a lexical index   -> BM25 (pure python, persisted as JSON)
Queries fuse both rankings with Reciprocal Rank Fusion (RRF).

All parameters live in the [kb.*] sections of backend/config/config.toml. Override the file with --config or
the KB_CONFIG env var.

Usage (from backend/):
    .venv/bin/python src/build_kb.py build
    .venv/bin/python src/build_kb.py query "what is a free hit in T20Is?" -k 5 --mode hybrid|bm25|semantic
    .venv/bin/python src/build_kb.py --config path/to/other.toml build

Use from other code:
    from build_kb import HybridRetriever, load_config
    hits = HybridRetriever(load_config()).search("powerplay fielding restrictions", k=5)
"""
from __future__ import annotations

import argparse
import json
import math
import os
import re
import tomllib
from collections import Counter
from dataclasses import dataclass
from pathlib import Path

import chromadb
import pymupdf

ROOT = Path(__file__).resolve().parents[2]          # CreaseIQ/
DEFAULT_CONFIG = Path(__file__).resolve().parents[1] / "config" / "config.toml"


# ---------------------------------------------------------------- config
@dataclass(frozen=True)
class Config:
    docs_dir: Path
    kb_dir: Path
    chroma_dir: Path
    bm25_path: Path
    chunk_words: int
    overlap_words: int
    collection: str
    distance_metric: str
    embed_batch: int
    bm25_k1: float
    bm25_b: float
    stopwords: frozenset[str]
    default_k: int
    default_mode: str
    candidates: int
    rrf_k: int
    rerank_enabled: bool
    rerank_model: str
    rerank_candidates: int
    rerank_batch_size: int
    rerank_cache_dir: Path


def load_config(path: str | Path | None = None) -> Config:
    """Read the [kb.*] sections of config/config.toml (or `path` / $KB_CONFIG) into a validated Config."""
    path = Path(path or os.environ.get("KB_CONFIG") or DEFAULT_CONFIG)
    with path.open("rb") as f:
        raw = tomllib.load(f)["kb"]          # the [kb.*] sections of config/config.toml

    def p(rel: str) -> Path:
        """Resolve a config path: absolute paths stay as they are, relative ones resolve against the project root."""
        q = Path(rel)
        return q if q.is_absolute() else ROOT / q

    cfg = Config(
        docs_dir=p(raw["paths"]["docs_dir"]),
        kb_dir=p(raw["paths"]["kb_dir"]),
        chroma_dir=p(raw["paths"]["chroma_dir"]),
        bm25_path=p(raw["paths"]["bm25_path"]),
        chunk_words=raw["chunking"]["chunk_words"],
        overlap_words=raw["chunking"]["overlap_words"],
        collection=raw["semantic"]["collection"],
        distance_metric=raw["semantic"]["distance_metric"],
        embed_batch=raw["semantic"]["embed_batch"],
        bm25_k1=raw["bm25"]["k1"],
        bm25_b=raw["bm25"]["b"],
        stopwords=frozenset(raw["bm25"]["stopwords"]),
        default_k=raw["retrieval"]["default_k"],
        default_mode=raw["retrieval"]["default_mode"],
        candidates=raw["retrieval"]["candidates"],
        rrf_k=raw["retrieval"]["rrf_k"],
        rerank_enabled=raw["rerank"]["enabled"],
        rerank_model=raw["rerank"]["model"],
        rerank_candidates=raw["rerank"]["candidates"],
        rerank_batch_size=raw["rerank"]["batch_size"],
        rerank_cache_dir=p(raw["rerank"]["cache_dir"]),
    )
    if cfg.overlap_words >= cfg.chunk_words:
        raise ValueError("chunking.overlap_words must be smaller than chunking.chunk_words")
    return cfg


# ---------------------------------------------------------------- loading + chunking
@dataclass
class Chunk:
    id: str
    text: str
    source: str
    page: int


def format_of(source: str) -> str:
    """Match format from a PDF name/chunk id: '...T20I...' -> 'T20I', '...ODI...' -> 'ODI', else 'unknown'."""
    up = source.upper()
    return "T20I" if "T20I" in up else "ODI" if "ODI" in up else "unknown"


_LEAD_CLAUSE = re.compile(r"^\s*(\d+(?:\.\d+)+)\b")


def tokenize(text: str, stopwords: frozenset[str]) -> list[str]:
    """Lowercase alnum tokens, stopwords removed. Keeps things like '12.3.1' and 'drs' intact."""
    toks = re.findall(r"[a-z0-9]+(?:\.[a-z0-9]+)*", text.lower())
    return [t for t in toks if t not in stopwords]


def load_pdf_pages(path: Path) -> list[tuple[int, str]]:
    """Return [(page_number, cleaned_text)] for every non-empty page of a PDF (page numbers start at 1)."""
    pages = []
    with pymupdf.open(path) as doc:
        for i in range(doc.page_count):
            text = re.sub(r"[ \t]+", " ", str(doc.load_page(i).get_text("text"))).strip()
            if text:
                pages.append((i + 1, text))
    return pages


def chunk_page(text: str, cfg: Config) -> list[str]:
    """Sliding word window with overlap."""
    words = text.split()
    if len(words) <= cfg.chunk_words:
        return [" ".join(words)]
    chunks, step = [], cfg.chunk_words - cfg.overlap_words
    for start in range(0, len(words), step):
        chunks.append(" ".join(words[start:start + cfg.chunk_words]))
        if start + cfg.chunk_words >= len(words):
            break
    return chunks


def build_chunks(cfg: Config) -> list[Chunk]:
    """Read every PDF in cfg.docs_dir and split it into overlapping Chunks, printing a per-file chunk count."""
    pdfs = sorted(cfg.docs_dir.glob("*.pdf"))
    if not pdfs:
        raise SystemExit(f"No PDFs found in {cfg.docs_dir}")
    chunks: list[Chunk] = []
    for pdf in pdfs:
        n_before = len(chunks)
        for page_no, text in load_pdf_pages(pdf):
            for j, piece in enumerate(chunk_page(text, cfg)):
                chunks.append(Chunk(f"{pdf.stem}|p{page_no}|c{j}", piece, pdf.name, page_no))
        print(f"  {pdf.name}: {len(chunks) - n_before} chunks")
    return chunks


# ---------------------------------------------------------------- BM25
class BM25:
    """Okapi BM25 with an inverted index (pure python, JSON-serialisable)."""

    def __init__(self, cfg: Config, ids: list[str], doc_lens: list[int],
                 postings: dict[str, list[tuple[int, int]]]):
        """Store the corpus statistics and postings of a built index."""
        self.cfg, self.ids, self.doc_lens, self.postings = cfg, ids, doc_lens, postings
        self.avgdl = sum(doc_lens) / max(len(doc_lens), 1)

    @classmethod
    def build(cls, cfg: Config, chunks: list[Chunk]) -> "BM25":
        """Build the inverted index (term -> [(chunk_index, term_frequency)]) over all chunks."""
        postings: dict[str, list[tuple[int, int]]] = {}
        lens = []
        for idx, c in enumerate(chunks):
            tf = Counter(tokenize(c.text, cfg.stopwords))
            lens.append(sum(tf.values()))
            for term, freq in tf.items():
                postings.setdefault(term, []).append((idx, freq))
        return cls(cfg, [c.id for c in chunks], lens, postings)

    def search(self, query: str, k: int, fmt: str | None = None) -> list[tuple[str, float]]:
        """Score chunks with Okapi BM25 and return the top-k [(chunk_id, score)]; fmt restricts results to one match format."""
        n, k1, b = len(self.ids), self.cfg.bm25_k1, self.cfg.bm25_b
        scores: dict[int, float] = {}
        for term in set(tokenize(query, self.cfg.stopwords)):
            plist = self.postings.get(term)
            if not plist:
                continue
            idf = math.log(1 + (n - len(plist) + 0.5) / (len(plist) + 0.5))
            for idx, freq in plist:
                if fmt and format_of(self.ids[idx]) != fmt:
                    continue
                denom = freq + k1 * (1 - b + b * self.doc_lens[idx] / self.avgdl)
                scores[idx] = scores.get(idx, 0.0) + idf * freq * (k1 + 1) / denom
        top = sorted(scores.items(), key=lambda kv: kv[1], reverse=True)[:k]
        return [(self.ids[i], s) for i, s in top]

    def save(self, path: Path) -> None:
        """Write the index to `path` as JSON."""
        path.write_text(json.dumps({"ids": self.ids, "doc_lens": self.doc_lens, "postings": self.postings}))

    @classmethod
    def load(cls, cfg: Config, path: Path) -> "BM25":
        """Load an index previously written by save()."""
        d = json.loads(path.read_text())
        return cls(cfg, d["ids"], d["doc_lens"], {t: [tuple(p) for p in pl] for t, pl in d["postings"].items()})


# ---------------------------------------------------------------- build
def build_knowledge_base(cfg: Config) -> None:
    """Rebuild both indexes (BM25 JSON and ChromaDB collection) from scratch so they stay in sync."""
    print(f"Reading PDFs from {cfg.docs_dir}")
    chunks = build_chunks(cfg)
    cfg.kb_dir.mkdir(parents=True, exist_ok=True)

    print("Building BM25 index...")
    BM25.build(cfg, chunks).save(cfg.bm25_path)

    print("Embedding into ChromaDB (first run downloads the ~80MB ONNX MiniLM model)...")
    client = chromadb.PersistentClient(path=str(cfg.chroma_dir))
    try:
        client.delete_collection(cfg.collection)      # full rebuild keeps both indexes in sync
    except Exception:
        pass
    col = client.create_collection(cfg.collection, metadata={"hnsw:space": cfg.distance_metric})
    for i in range(0, len(chunks), cfg.embed_batch):
        part = chunks[i:i + cfg.embed_batch]
        col.add(
            ids=[c.id for c in part],
            documents=[c.text for c in part],
            metadatas=[{"source": c.source, "page": c.page} for c in part],
        )
    print(f"Done: {len(chunks)} chunks -> {cfg.kb_dir}")


# ---------------------------------------------------------------- retrieval
class Reranker:
    """Cross-encoder (fastembed, ONNX) that scores (query, passage) pairs jointly. Loaded lazily on first use."""

    def __init__(self, cfg: Config) -> None:
        """Remember the model settings; the model itself is loaded on the first rerank call."""
        self.cfg, self._model = cfg, None

    def scores(self, query: str, texts: list[str]) -> list[float]:
        """Relevance probability in 0..1 (sigmoid of the cross-encoder logit) for each text, in input order."""
        if self._model is None:
            from fastembed.rerank.cross_encoder import TextCrossEncoder
            self._model = TextCrossEncoder(model_name=self.cfg.rerank_model, cache_dir=str(self.cfg.rerank_cache_dir))
        logits = self._model.rerank(query, texts, batch_size=self.cfg.rerank_batch_size)
        return [1.0 / (1.0 + math.exp(-x)) for x in logits]


class HybridRetriever:
    def __init__(self, cfg: Config | None = None) -> None:
        """Load the BM25 index and open the Chroma collection; exits with a hint if the knowledge base is not built."""
        self.cfg = cfg or load_config()
        if not self.cfg.bm25_path.exists():
            raise SystemExit("Knowledge base not built. Run: python src/build_kb.py build")
        self.bm25 = BM25.load(self.cfg, self.cfg.bm25_path)
        client = chromadb.PersistentClient(path=str(self.cfg.chroma_dir))
        self.col = client.get_collection(self.cfg.collection)
        self._source_names: list[str] | None = None
        self.reranker = Reranker(self.cfg) if self.cfg.rerank_enabled else None

    def _sources(self, fmt: str | None) -> list[str] | None:
        """Names of the indexed PDFs belonging to match format `fmt` (cached); None when no format filter is requested."""
        if not fmt:
            return None
        if self._source_names is None:
            self._source_names = sorted({m["source"] for m in (self.col.get(include=["metadatas"])["metadatas"] or [])})
        return [n for n in self._source_names if format_of(n) == fmt]

    def _semantic(self, query: str, k: int, fmt: str | None = None) -> list[tuple[str, float]]:
        """Semantic search in Chroma, optionally limited to one format; returns [(chunk_id, similarity)] with similarity = 1 - distance."""
        where = {"source": {"$in": self._sources(fmt)}} if fmt else None
        r = self.col.query(query_texts=[query], n_results=k, where=where)
        dists = (r.get("distances") or [[]])[0]
        return [(i, 1 - d) for i, d in zip(r["ids"][0], dists)]    # similarity = 1 - distance

    def search(self, query: str, k: int | None = None, mode: str | None = None, fmt: str | None = None) -> list[dict]:
        """fmt='ODI'|'T20I' restricts BOTH indexes to that format's PDFs (no cross-format leakage)."""
        k = k or self.cfg.default_k
        mode = mode or self.cfg.default_mode
        rerank = self.reranker is not None and mode == "hybrid"       # the single-index debug modes are never reranked
        if mode == "bm25":
            ranked = {"bm25": self.bm25.search(query, k, fmt)}
        elif mode == "semantic":
            ranked = {"semantic": self._semantic(query, k, fmt)}
        else:
            n = self.cfg.candidates
            ranked = {"bm25": self.bm25.search(query, n, fmt), "semantic": self._semantic(query, n, fmt)}

        fused: dict[str, float] = {}
        detail: dict[str, dict] = {}
        for name, results in ranked.items():
            for rank, (cid, raw) in enumerate(results, start=1):
                fused[cid] = fused.get(cid, 0.0) + 1.0 / (self.cfg.rrf_k + rank)
                detail.setdefault(cid, {})[name] = {"rank": rank, "score": round(raw, 4)}

        top_ids = sorted(fused, key=lambda cid: fused[cid], reverse=True)[:max(k, self.cfg.rerank_candidates) if rerank else k]
        got = self.col.get(ids=top_ids)
        by_id = {
            i: (doc, meta)
            for i, doc, meta in zip(got["ids"], got["documents"] or [], got["metadatas"] or [])
        }
        hits = [
            {"id": cid, "score": round(fused[cid], 5), "source": by_id[cid][1]["source"],
             "page": by_id[cid][1]["page"], "text": by_id[cid][0], "signals": detail[cid]}
            for cid in top_ids
        ]
        if rerank and hits:       # stage 2: the cross-encoder re-orders the RRF candidates and gives an absolute relevance score
            for h, r in zip(hits, self.reranker.scores(query, [h["text"] for h in hits])):
                h["rerank_score"] = round(r, 4)
            hits.sort(key=lambda h: h["rerank_score"], reverse=True)
        return hits[:k]


    def get_clause(self, fmt: str, clause_number: str) -> list[dict]:
        """Chunks of one format whose text has a line starting with this clause number (e.g. '12.3.1')."""
        names = self._sources(fmt) or []
        got = self.col.get(where={"source": {"$in": names}}) if names else {"ids": [], "documents": [], "metadatas": []}
        pat = re.compile(rf"(?m)^\s*{re.escape(clause_number.strip('.'))}(?![\d])\b")
        return [{"id": i, "score": 1.0, "source": m["source"], "page": m["page"], "text": d, "signals": {}}
                for i, d, m in zip(got["ids"], got["documents"] or [], got["metadatas"] or []) if pat.search(d)]


def to_passage(hit: dict, top_score: float) -> dict:
    """Hit -> the workflow's passage schema. Only provenance the PDFs really give us is filled in."""
    m = _LEAD_CLAUSE.match(hit["text"])
    return {"chunk_id": hit["id"], "text": hit["text"], "format": format_of(hit["source"]),
            "source_id": Path(hit["source"]).stem, "source_title": Path(hit["source"]).stem, "version": "", "effective_from": "",
            "publisher": "ICC", "clause_number": m.group(1) if m else f"p{hit['page']}", "clause_title": "",
            "page_start": hit["page"], "page_end": hit["page"], "printed_page_start": hit["page"],
            "refers_outside": False, "signals": hit["signals"],
            # reranked hits carry an absolute relevance (cross-encoder probability); otherwise the RRF score relative to the best possible
            "retrieval_score": round(hit["rerank_score"] if "rerank_score" in hit else min(1.0, hit["score"] / top_score), 2)}


# ---------------------------------------------------------------- CLI
def main() -> None:
    """Command-line entry point: `build` the knowledge base or `query` it."""
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--config", help="path to a TOML config (default: config/config.toml or $KB_CONFIG)")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("build", help="(re)build the knowledge base from the docs folder")
    q = sub.add_parser("query", help="search the knowledge base")
    q.add_argument("text")
    q.add_argument("-k", type=int, default=None, help="results to return (default from config)")
    q.add_argument("--mode", choices=["hybrid", "bm25", "semantic"], default=None)
    args = ap.parse_args()

    cfg = load_config(args.config)
    if args.cmd == "build":
        build_knowledge_base(cfg)
    else:
        for h in HybridRetriever(cfg).search(args.text, k=args.k, mode=args.mode):
            rr = f" rerank={h['rerank_score']}" if "rerank_score" in h else ""
            print(f"\n[{h['score']}{rr}] {h['source']} p.{h['page']}  {h['signals']}\n{h['text'][:500]}...")


if __name__ == "__main__":
    main()
