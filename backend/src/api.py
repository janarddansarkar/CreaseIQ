"""Thin FastAPI boundary (spec section 13) over runner.ask(). Run from backend/src:  uvicorn api:app --port 8000"""
from __future__ import annotations

import logging
import os
import uuid
from typing import Optional

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.concurrency import run_in_threadpool
from pydantic import BaseModel, Field

from config import STRINGS, SUPPORTED_FORMATS, SUPPORTED_LANGUAGES, settings
from graph import build_graph
from runner import ask

log = logging.getLogger("creaseiq.api")
app = FastAPI(title="CreaseIQ API", version="1.0")
app.add_middleware(CORSMiddleware, allow_origins=[o.strip() for o in os.getenv("CORS_ALLOW_ORIGINS", "http://localhost:5173").split(",")],
                   allow_methods=["*"], allow_headers=["*"])
_GRAPH = None


def graph():
    """Compile the graph once, on first use."""
    global _GRAPH
    if _GRAPH is None:
        _GRAPH = build_graph()
    return _GRAPH


class ChatRequest(BaseModel):
    conversation_id: Optional[str] = Field(None, max_length=64, pattern=r"^[A-Za-z0-9_\-]+$")
    message: str = Field(..., min_length=1, max_length=2000)
    response_language: Optional[str] = None


class Citation(BaseModel):
    chunk_id: Optional[str] = None
    source_title: Optional[str] = None
    version: Optional[str] = None
    format: Optional[str] = None
    clause_number: Optional[str] = None
    page: Optional[str] = None


class ChatResponse(BaseModel):
    request_id: str
    conversation_id: str
    status: str
    message: str
    response_language: Optional[str] = None
    format: Optional[str] = None
    clarification_question: Optional[str] = None
    citations: list[Citation] = []
    web_sources: list[dict] = []
    error: Optional[str] = None


@app.get("/api/v1/health")
def health():
    """Liveness check."""
    return {"status": "ok"}


@app.get("/api/v1/languages")
def languages():
    """Supported reply languages."""
    return {"languages": SUPPORTED_LANGUAGES}


@app.get("/api/v1/formats")
def formats():
    """Supported match formats."""
    return {"formats": list(SUPPORTED_FORMATS)}


@app.post("/api/v1/chat", response_model=ChatResponse)
async def chat(req: ChatRequest):
    """Run one turn of the agent for this conversation (the conversation id is the memory thread / user id)."""
    rid, cid = uuid.uuid4().hex[:12], req.conversation_id or uuid.uuid4().hex[:16]
    if req.response_language and req.response_language not in SUPPORTED_LANGUAGES:
        raise HTTPException(422, "Unsupported response_language")
    try:
        out = await run_in_threadpool(ask, graph(), req.message, cid, req.response_language, False)
    except Exception:
        log.exception("chat failed rid=%s", rid)
        raise HTTPException(500, f"Something went wrong. Please try again. (request {rid})")
    v = out["values"]
    cites = [Citation(chunk_id=c.get("chunk_id"), source_title=c.get("source_title"), version=c.get("version"), format=c.get("format"),
                      clause_number=c.get("clause_number"), page=str(c["printed_page_start"]) if c.get("printed_page_start") is not None else None)
             for c in v.get("citations") or []]
    return ChatResponse(request_id=rid, conversation_id=cid, status=out["status"], message=out["answer"], response_language=v.get("response_language"),
                        format=v.get("format"), clarification_question=v.get("clarification_question"), citations=cites,
                        web_sources=v.get("web_sources") or [], error="internal" if v.get("error") else None)
