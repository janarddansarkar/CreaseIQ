"""ask(): stands in for the FastAPI boundary. Redacts PII, then runs the graph on a thread_id (the conversation id)."""
from __future__ import annotations

from typing import Optional

from langchain_core.messages import HumanMessage

from config import settings
from guardrails import sanitize_input


def ask(graph, text: str, thread_id: str, language: Optional[str] = None, show: bool = True) -> dict:
    """Redact PII from `text`, run the graph on the conversation `thread_id`, and return status, answer, node path and final state."""
    clean, pii = sanitize_input(text)
    config = {"configurable": {"thread_id": thread_id}, "recursion_limit": settings.limits.recursion_limit}
    path = []
    for chunk in graph.stream({"messages": [HumanMessage(clean)], "requested_language": language, "pii_found": pii}, config, stream_mode="updates"):
        path += list(chunk.keys())
    v = graph.get_state(config).values
    out = {"status": v["status"], "answer": v["answer"], "path": path, "values": v}
    if show:
        print("> " + clean)
        print("  path:  " + " -> ".join(path))
        print(f"  status: {v['status']}" + (f" ({v['insufficient_reason']})" if v["status"] == "insufficient_evidence" else "") + (f" | error: {v['error']}" if v.get("error") else ""))
        print("  answer: " + v["answer"].replace("\n", "\n          ") + "\n")
    return out
