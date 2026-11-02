"""ask(): stands in for the FastAPI boundary. Redacts PII, then runs the graph for one user with SQLite-backed memory."""
from __future__ import annotations

from typing import Optional

from langchain_core.messages import HumanMessage

from config import SUPPORTED_FORMATS, settings
from context import build_history, make_digest, prior_turn
from guardrails import sanitize_input
from memory import MemoryStore, get_store


def ask(graph, text: str, user_id: str, language: Optional[str] = None, show: bool = True, store: Optional[MemoryStore] = None) -> dict:
    """Redact PII from `text`, run the graph on this user's conversation (thread = user_id), and return status, answer, node path and final state.

    Memory: registers the user (evicting the oldest user when over the cap), loads their long-term profile into the run, then records the
    turn, updates the profile and prunes old checkpoints."""
    store = store or get_store()
    clean, pii = sanitize_input(text)
    store.ensure_user(user_id)
    profile = store.get_profile(user_id)
    past = store.turns(user_id)
    config = {"configurable": {"thread_id": user_id}, "recursion_limit": settings.limits.recursion_limit}
    path = []
    for chunk in graph.stream({"messages": [HumanMessage(clean)], "requested_language": language or profile["preferred_language"], "pii_found": pii,
                               "profile": profile, "history": build_history(past, profile), "prior_turn": prior_turn(past)}, config, stream_mode="updates"):
        path += list(chunk.keys())
    v = graph.get_state(config).values
    store.record_turn(user_id, clean, v["answer"], v["status"], v.get("format"), v.get("clause_number"), make_digest(v))
    if v["status"] == "answered":       # only a verified answer teaches the profile
        fmt = v.get("format") if v.get("format") in SUPPORTED_FORMATS else None
        store.update_profile(user_id, fmt=fmt, language=v.get("response_language"), topic=v.get("clause_number") or v.get("normalized_english_query", "")[:80] or None)
    store.prune_checkpoints(user_id)
    out = {"status": v["status"], "answer": v["answer"], "path": path, "values": v}
    if show:
        print("> " + clean)
        print("  path:  " + " -> ".join(path))
        print(f"  status: {v['status']}" + (f" ({v['insufficient_reason']})" if v["status"] == "insufficient_evidence" else "") + (f" | error: {v['error']}" if v.get("error") else ""))
        print("  answer: " + v["answer"].replace("\n", "\n          ") + "\n")
    return out
