"""Small helpers shared by the nodes."""
from __future__ import annotations

import functools

from langchain_core.messages import AIMessage

from config import SUPPORTED_LANGUAGES, STRINGS, settings


def safe_node(fn):
    """An exception is recorded in state['error']; the router then sends the graph to handle_error."""
    @functools.wraps(fn)
    def wrapper(state):
        """Run the node; on any exception return {'error': ...} so the router can send the graph to handle_error."""
        try:
            return fn(state)
        except Exception as e:
            return {"error": f"{fn.__name__}: {type(e).__name__}: {e}"}
    return wrapper


def S(state, key: str) -> str:
    """Fixed message in the response language."""
    lang = state.get("response_language") or settings.language.default
    return STRINGS[lang if lang in SUPPORTED_LANGUAGES else settings.language.default][key]


def reply(state, status: str, text: str, **extra) -> dict:
    """Build a terminal node update: status, answer text and the assistant message appended to the conversation."""
    return {"status": status, "answer": text, "messages": [AIMessage(text)], **extra}
