"""Admin API: auth, upload validation, and the staged rebuild -> swap -> reload -> manifest flow (all in a temp dir, never the real KB)."""
import json
from dataclasses import replace

import pymupdf
import pytest
from fastapi.testclient import TestClient

import api
import kb_admin
import memory
import tools
from build_kb import load_config
from config import CONFIG_FILE

TOKEN = {"X-Admin-Token": "s3cret"}
BOWLER = "A bowler may bowl a maximum of ten overs in an innings. Powerplay overs restrict the fielders outside the circle. "


def make_pdf(path, pages=6, text=BOWLER * 3):
    doc = pymupdf.open()
    for i in range(pages):
        doc.new_page().insert_textbox(pymupdf.Rect(40, 40, 550, 800), f"{i + 1}.1 {text}", fontsize=10)
    doc.save(path)
    return path


@pytest.fixture
def env(tmp_path, monkeypatch):
    """A throw-away docs/ + kb/ tree holding both formats, with the admin token set and reload_kb recorded instead of run."""
    real = load_config(CONFIG_FILE)
    docs = tmp_path / "docs"
    docs.mkdir()
    make_pdf(docs / "ICC Men's ODI Playing Conditions.pdf")
    make_pdf(docs / "ICC Men's T20I Playing Conditions.pdf")
    cfg = replace(real, docs_dir=docs, kb_dir=tmp_path / "kb", chroma_dir=tmp_path / "vector_db", bm25_path=tmp_path / "kb" / "bm25.json")
    from build_kb import build_knowledge_base
    build_knowledge_base(cfg)
    reloads = []
    monkeypatch.setattr(kb_admin, "_cfg", lambda: cfg)
    monkeypatch.setattr(tools, "reload_kb", lambda *a: reloads.append(1))
    monkeypatch.setenv("CREASEIQ_ADMIN_TOKEN", "s3cret")
    monkeypatch.setattr(memory, "_STORE", memory.MemoryStore(tmp_path / "api.sqlite"))
    monkeypatch.setattr(api, "_GRAPH", None)
    with TestClient(api.app) as c:
        yield c, cfg, reloads, tmp_path


def post(c, path, fmt="ODI", version="", headers=TOKEN):
    with open(path, "rb") as f:
        return c.post("/api/v1/admin/documents", headers=headers, data={"format": fmt, "version": version}, files={"file": ("x.pdf", f, "application/pdf")})


def test_disabled_without_token_env(env, monkeypatch):
    c, *_ = env
    monkeypatch.delenv("CREASEIQ_ADMIN_TOKEN")
    assert c.post("/api/v1/admin/documents", headers=TOKEN).status_code == 503


def test_wrong_or_missing_token(env):
    c, *_ = env
    assert c.get("/api/v1/admin/jobs/x").status_code == 401
    assert c.get("/api/v1/admin/jobs/x", headers={"X-Admin-Token": "nope"}).status_code == 401


def test_rejects_bad_uploads(env, tmp_path):
    c = env[0]
    good = make_pdf(tmp_path / "ok.pdf")
    assert post(c, good, fmt="TEST").status_code == 422                       # unknown format
    assert post(c, good, version="bad;version").status_code == 422
    txt = tmp_path / "a.pdf"; txt.write_text("not a pdf")
    assert post(c, txt).status_code == 400                                    # not a PDF
    assert post(c, make_pdf(tmp_path / "short.pdf", pages=2)).status_code == 400   # too short
    assert post(c, make_pdf(tmp_path / "blank.pdf", text=" ")).status_code == 400  # no extractable text
    assert post(c, good, headers={}).status_code in (401, 503)


def test_unknown_job_404(env):
    assert env[0].get("/api/v1/admin/jobs/nope", headers=TOKEN).status_code == 404


def test_upload_rebuilds_swaps_and_publishes_manifest(env, tmp_path):
    c, cfg, reloads, _ = env
    before = kb_admin.kb_info()
    new = make_pdf(tmp_path / "new.pdf", pages=7, text="Free hit awarded after a front foot no ball. Bowler overs maximum. ")
    r = post(c, new, fmt="odi", version="Jan 2027")
    assert r.status_code == 202
    job = c.get(f"/api/v1/admin/jobs/{r.json()['job_id']}", headers=TOKEN).json()
    assert job["status"] == "done", job
    assert reloads == [1]
    info = c.get("/api/v1/kb").json()
    assert {d["format"] for d in info["documents"]} == {"ODI", "T20I"}
    odi = next(d for d in info["documents"] if d["format"] == "ODI")
    assert odi["version"] == "Jan 2027" and odi["pages"] == 7
    assert info["updated_at"] >= (before["updated_at"] or "")
    assert (cfg.docs_dir.parent / "docs" / "archive").exists() and list((cfg.docs_dir.parent / "docs" / "archive").glob("*.pdf"))
    assert not list(cfg.kb_dir.glob(".staging-*")) and not list(cfg.kb_dir.glob(".upload-*"))   # scratch files cleaned up


def test_failed_rebuild_keeps_old_kb(env, tmp_path, monkeypatch):
    c, cfg, reloads, _ = env
    snapshot = cfg.bm25_path.read_bytes()
    monkeypatch.setattr(kb_admin, "_smoke_check", lambda *a: (_ for _ in ()).throw(RuntimeError("boom")))
    r = post(c, make_pdf(tmp_path / "new.pdf"))
    job = c.get(f"/api/v1/admin/jobs/{r.json()['job_id']}", headers=TOKEN).json()
    assert job["status"] == "failed" and "boom" in job["detail"]
    assert cfg.bm25_path.read_bytes() == snapshot and reloads == []
    assert len(list((cfg.docs_dir).glob("*.pdf"))) == 2
    assert kb_admin._BUSY.acquire(blocking=False); kb_admin._BUSY.release()   # lock released after a failure


def test_busy_returns_409(env, tmp_path):
    c = env[0]
    assert kb_admin._BUSY.acquire(blocking=False)
    try:
        assert post(c, make_pdf(tmp_path / "n.pdf")).status_code == 409
    finally:
        kb_admin._BUSY.release()


def test_kb_info_without_manifest(env):
    c, cfg, *_ = env
    info = c.get("/api/v1/kb").json()
    assert info["updated_at"] and {d["format"] for d in info["documents"]} == {"ODI", "T20I"}
