"""Knowledge-base admin: upload a rulebook PDF -> staged rebuild -> smoke check -> atomic swap -> hot reload, plus the public KB info.

    POST /api/v1/admin/documents   (X-Admin-Token)  multipart: file, format, version  -> 202 {job_id}
    GET  /api/v1/admin/jobs/{id}   (X-Admin-Token)  progress of an upload
    GET  /api/v1/kb                (public)         when the knowledge base was last updated + which rulebooks it holds

A rebuild never touches the live indexes until the new ones pass a smoke check; any failure leaves the old knowledge base serving.
The rulebook of a format is REPLACED by the upload (the old PDF is archived, timestamped), because retrieval is per format.
"""
from __future__ import annotations

import gc
import hmac
import json
import logging
import os
import re
import shutil
import threading
import time
import uuid
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import chromadb
import pymupdf
from fastapi import APIRouter, BackgroundTasks, Depends, File, Form, Header, HTTPException, UploadFile

from build_kb import Config, HybridRetriever, build_knowledge_base, format_of, load_config
from config import CONFIG_FILE, SUPPORTED_FORMATS, settings

log = logging.getLogger("creaseiq.admin")
_A = settings.admin
admin_router = APIRouter(prefix="/api/v1/admin")
public_router = APIRouter(prefix="/api/v1")

_BUSY = threading.Lock()              # one rebuild at a time
_JOBS: dict[str, dict] = {}
_VERSION_OK = re.compile(r"^[\w .,()/\-]{0,64}$")


def _cfg() -> Config:
    return load_config(CONFIG_FILE)


def _pdf_name(fmt: str) -> str:
    """Canonical file name: build_kb.format_of() reads the format from the name, and the name is what citations show."""
    return f"ICC Men's {fmt} Playing Conditions.pdf"


# ---------------------------------------------------------------- manifest / public info
def _manifest_path(cfg: Config) -> Path:
    return cfg.kb_dir / _A.manifest_name


def _describe(cfg: Config) -> dict[str, dict]:
    """Per format: file name, pages and chunk count of what is indexed in `cfg`'s Chroma collection."""
    col = chromadb.PersistentClient(path=str(cfg.chroma_dir)).get_collection(cfg.collection)
    out: dict[str, dict] = {}
    for m in col.get(include=["metadatas"])["metadatas"] or []:
        d = out.setdefault(format_of(m["source"]), {"title": Path(m["source"]).stem, "pages": 0, "chunks": 0})
        d["pages"], d["chunks"] = max(d["pages"], int(m["page"])), d["chunks"] + 1
    return out


def kb_info() -> dict:
    """What the public /kb returns. Falls back to file times for a knowledge base built before the manifest existed."""
    cfg = _cfg()
    mp = _manifest_path(cfg)
    try:
        return json.loads(mp.read_text())
    except (OSError, ValueError):
        pass
    if not cfg.bm25_path.exists():
        return {"updated_at": None, "documents": []}
    updated = datetime.fromtimestamp(cfg.bm25_path.stat().st_mtime, timezone.utc).isoformat(timespec="seconds")
    docs = [{"format": f, "version": None, **d} for f, d in sorted(_describe(cfg).items())]
    return {"updated_at": updated, "documents": docs}


@public_router.get("/kb")
def kb():
    """When the knowledge base was last updated and which rulebooks it holds."""
    return kb_info()


# ---------------------------------------------------------------- auth + validation
def require_admin(x_admin_token: Optional[str] = Header(None)) -> None:
    expected = os.getenv(_A.token_env)
    if not expected:
        raise HTTPException(503, f"Admin API is disabled: set {_A.token_env} on the server")
    if not x_admin_token or not hmac.compare_digest(x_admin_token.encode(), expected.encode()):
        raise HTTPException(401, "Invalid admin token")


def validate_pdf(path: Path) -> int:
    """Reject anything that is not a real, text-bearing rulebook; returns the page count."""
    try:
        doc = pymupdf.open(path)
    except Exception:
        raise HTTPException(400, "The file is not a readable PDF")
    with doc:
        n = doc.page_count
        if n < _A.min_pages:
            raise HTTPException(400, f"The PDF has {n} pages; a playing-conditions rulebook has at least {_A.min_pages}")
        with_text = sum(1 for i in range(n) if len(doc.load_page(i).get_text("text").strip()) > 40)
    if with_text / n < _A.min_text_ratio:
        raise HTTPException(400, "The PDF has no extractable text (a scanned image?). OCR it first")
    return n


# ---------------------------------------------------------------- the rebuild
def _set(job: dict, status: str, detail: str = "") -> None:
    job.update(status=status, detail=detail)
    if status in ("done", "failed"):
        job["finished_at"] = _now()
    log.info("kb job %s: %s %s", job["id"], status, detail)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _smoke_check(staged: Config, formats: set[str]) -> None:
    """The staged indexes must open and answer a query for every format that has a rulebook."""
    r = HybridRetriever(staged)
    if r.col.count() == 0:
        raise RuntimeError("the new index is empty")
    for f in sorted(formats):
        if not r.bm25.search("how many overs bowler", 3, f) or not r._semantic("how many overs bowler", 3, f):
            raise RuntimeError(f"the new index returns nothing for {f}")


def rebuild(job: dict, upload: Path, fmt: str, version: str, reload) -> None:
    """Stage -> build -> smoke check -> swap -> reload (roll back if the reload fails) -> archive old PDF -> manifest. Holds _BUSY."""
    cfg = _cfg()
    stage = cfg.kb_dir / f".staging-{job['id']}"
    swapped: list[tuple[Path, Path]] = []                 # (live, backup) pairs to undo if the reload fails
    try:
        _set(job, "building", "copying documents")
        sdocs = stage / "docs"
        sdocs.mkdir(parents=True)
        for p in cfg.docs_dir.glob("*.pdf"):
            if format_of(p.name) != fmt:
                shutil.copy2(p, sdocs / p.name)
        shutil.copy2(upload, sdocs / _pdf_name(fmt))
        staged = replace(cfg, docs_dir=sdocs, chroma_dir=stage / "vector_db", bm25_path=stage / "bm25.json")
        _set(job, "building", "chunking and embedding (this takes a minute)")
        build_knowledge_base(staged)

        _set(job, "checking", "smoke-testing the new index")
        formats = {format_of(p.name) for p in sdocs.glob("*.pdf")} & set(SUPPORTED_FORMATS)
        _smoke_check(staged, formats)
        described = _describe(staged)
        try:
            prev = {d["format"]: d for d in json.loads(_manifest_path(cfg).read_text())["documents"]}
        except (OSError, ValueError, KeyError):
            prev = {}
        docs = [{"format": f, "version": version if f == fmt else (prev.get(f) or {}).get("version"), **d} for f, d in sorted(described.items())]
        manifest = {"updated_at": _now(), "documents": docs}
        gc.collect()                           # let the staged Chroma/BM25 handles go before the directory moves

        _set(job, "swapping", "switching to the new index")
        old_chroma, old_bm25 = stage / "old_vector_db", stage / "old_bm25.json"
        if cfg.chroma_dir.exists():
            os.replace(cfg.chroma_dir, old_chroma); swapped.append((cfg.chroma_dir, old_chroma))
        os.replace(stage / "vector_db", cfg.chroma_dir)
        if cfg.bm25_path.exists():
            shutil.copy2(cfg.bm25_path, old_bm25)
        os.replace(stage / "bm25.json", cfg.bm25_path)
        try:
            reload()
        except Exception:
            log.exception("reload failed; rolling back")
            shutil.rmtree(cfg.chroma_dir, ignore_errors=True)
            for live, backup in swapped:
                os.replace(backup, live)
            if old_bm25.exists():
                os.replace(old_bm25, cfg.bm25_path)
            reload()
            raise RuntimeError("the new index failed to load; the previous knowledge base is still serving")

        # committed: archive the replaced PDF, install the new one, publish the manifest
        arch_dir = cfg.docs_dir.parent / _A.archive_dir
        for p in list(cfg.docs_dir.glob("*.pdf")):
            if format_of(p.name) == fmt:
                arch_dir.mkdir(parents=True, exist_ok=True)
                shutil.move(p, arch_dir / f"{p.stem}.{time.strftime('%Y%m%d-%H%M%S')}.pdf")
        shutil.copy2(upload, cfg.docs_dir / _pdf_name(fmt))
        _manifest_path(cfg).write_text(json.dumps(manifest, indent=2))
        job["manifest"] = manifest
        _set(job, "done", f"{fmt} rulebook replaced; {sum(d['chunks'] for d in docs)} chunks indexed")
    except Exception as e:
        log.exception("kb rebuild failed")
        _set(job, "failed", str(e) or e.__class__.__name__)
    finally:
        shutil.rmtree(stage, ignore_errors=True)
        upload.unlink(missing_ok=True)
        _BUSY.release()


# ---------------------------------------------------------------- endpoints
@admin_router.post("/documents", status_code=202, dependencies=[Depends(require_admin)])
async def upload_document(background: BackgroundTasks, file: UploadFile = File(...), format: str = Form(...), version: str = Form("")):
    """Upload a replacement rulebook for one format. Returns at once; poll /admin/jobs/{job_id}."""
    fmt = format.strip().upper()
    if fmt not in SUPPORTED_FORMATS:
        raise HTTPException(422, f"format must be one of {list(SUPPORTED_FORMATS)}")
    if not _VERSION_OK.match(version.strip()):
        raise HTTPException(422, "version may only contain letters, digits and . , ( ) / - and be at most 64 characters")
    data = await file.read(_A.max_upload_mb * 1024 * 1024 + 1)
    if len(data) > _A.max_upload_mb * 1024 * 1024:
        raise HTTPException(413, f"The file is larger than {_A.max_upload_mb} MB")
    if not data.startswith(b"%PDF-"):
        raise HTTPException(400, "The file is not a PDF")
    cfg = _cfg()
    cfg.kb_dir.mkdir(parents=True, exist_ok=True)
    job_id = uuid.uuid4().hex[:12]
    tmp = cfg.kb_dir / f".upload-{job_id}.pdf"
    tmp.write_bytes(data)
    try:
        validate_pdf(tmp)
        if not _BUSY.acquire(blocking=False):
            raise HTTPException(409, "A knowledge-base update is already running")
    except HTTPException:
        tmp.unlink(missing_ok=True)
        raise
    job = {"id": job_id, "status": "queued", "detail": "", "format": fmt, "version": version.strip() or None, "started_at": _now()}
    _JOBS[job_id] = job
    for old in list(_JOBS)[:-_A.jobs_kept]:
        _JOBS.pop(old, None)
    import tools
    background.add_task(rebuild, job, tmp, fmt, version.strip(), tools.reload_kb)
    return {"job_id": job_id, "status": "queued"}


@admin_router.get("/jobs/{job_id}", dependencies=[Depends(require_admin)])
def job_status(job_id: str):
    job = _JOBS.get(job_id)
    if not job:
        raise HTTPException(404, "Unknown job (jobs are kept in memory and are lost on restart)")
    return {k: v for k, v in job.items() if k != "manifest"}
