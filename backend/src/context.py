"""Context engineering: per-turn digests, a token-budgeted conversation history, and deterministic follow-up detection.

History is untrusted user text and is shown ONLY to the routing step (to complete elliptical follow-ups); the analyse / answer / general
prompts still receive evidence only, so rules answers never come from conversation memory.
"""
from __future__ import annotations

import re
from typing import Optional

from config import LEXICON, settings
from guardrails import check_input

_C = settings.context
_FOLLOWUP = re.compile(LEXICON["routing"]["followup_pattern"], re.I)
_USEFUL = ("answered", "answered_general", "insufficient_evidence")      # turns worth replaying; refusals and clarifications carry no context
_FENCE = "history"


def _clean(text: str, limit: int) -> str:
    """One line: collapsed whitespace, fence token neutralised, cut to `limit` characters."""
    t = " ".join(str(text or "").split()).replace(f"</{_FENCE}", "< /" + _FENCE).replace(f"<{_FENCE}", "< " + _FENCE)
    return t if len(t) <= limit else t[: limit - 1].rstrip() + "…"


def make_digest(v: dict) -> dict:
    """Compact, model-free summary of a finished turn built from the final graph state."""
    clauses = list(dict.fromkeys(c.get("clause_number") for c in v.get("citations") or [] if c.get("clause_number")))
    gist = ((v.get("analysis") or {}).get("conclusion") or "") if v.get("status") == "answered" else ""
    return {"q": _clean(v.get("question"), _C.question_chars), "q_norm": _clean(v.get("normalized_english_query"), _C.question_chars),
            "fmt": v.get("format"), "intent": v.get("intent"), "clause_no": v.get("clause_number"), "clauses": clauses,
            "gist": _clean(gist, _C.gist_chars), "status": v.get("status")}


def usable(turns: list[dict]) -> list[dict]:
    """Turns safe and useful to replay: a useful status, a digest, and a question that still passes the input guard."""
    return [t for t in turns if t["status"] in _USEFUL and t.get("digest") and not check_input(t["question"])]


def prior_turn(turns: list[dict]) -> Optional[dict]:
    """Digest of the most recent answered cricket-rules turn (what a follow-up refers to), or None."""
    for t in reversed(usable(turns)):
        if t["status"] == "answered" and t["digest"].get("intent") in ("scenario", "clause_lookup", "compare") and t["digest"].get("q_norm"):
            return t["digest"]
    return None


def is_followup(message: str) -> bool:
    """True for an elliptical message that only makes sense with the previous turn ('What about T20I?', 'Does that apply to wides?')."""
    return bool(_FOLLOWUP.search(message.strip()))


def _approx_tokens(text: str) -> int:
    """Cheap token estimate (about 4 characters per token)."""
    return (len(text) + 3) // 4


def _rich(age: int, d: dict) -> str:
    """Detailed line for a recent turn."""
    cl = f"; cl. {', '.join(d['clauses'])}" if d.get("clauses") else ""
    gist = f"; gist: {d['gist']}" if d.get("gist") else ""
    return f"-{age} [{d.get('fmt') or '?'}|{d.get('intent') or '?'}] Q: {d['q']} -> {d['status']}{cl}{gist}"


def _short(age: int, d: dict) -> str:
    """One-liner for an older turn."""
    q = " ".join(d["q"].split()[: _C.old_question_words])
    cl = f" ({', '.join(d['clauses'][:2])})" if d.get("clauses") else ""
    return f"-{age} [{d.get('fmt') or '?'}] Q: {q} -> {d['status']}{cl}"


def build_history(turns: list[dict], profile: dict) -> str:
    """Fenced HISTORY block: profile line, older turns as one-liners, the last `recent_turns` in detail, within max_history_tokens.
    Over budget, the oldest one-liners are dropped first (with an omitted count), then gists are cut. Empty string when there is nothing to show."""
    ts = usable(turns)
    head = []
    if profile.get("preferred_format") or profile.get("topics"):
        head.append(f"profile: usual format {profile.get('preferred_format') or '?'}; recent topics: {_clean('; '.join(profile.get('topics') or []), 200)}")
    if not ts and not head:
        return ""
    n, k = len(ts), _C.recent_turns
    older = [_short(n - i, t["digest"]) for i, t in enumerate(ts[: max(0, n - k)])]
    recent = [_rich(n - i, t["digest"]) for i, t in enumerate(ts[max(0, n - k):], start=max(0, n - k))]

    def render(older_lines, omitted, rec):
        """Join the pieces into the fenced block."""
        note = [f"({omitted} earlier turns omitted)"] if omitted else []
        return f"<{_FENCE}>\n" + "\n".join(head + note + older_lines + rec) + f"\n</{_FENCE}>"

    omitted, text = 0, render(older, 0, recent)
    while _approx_tokens(text) > _C.max_history_tokens and older:
        older.pop(0)
        omitted += 1
        text = render(older, omitted, recent)
    if _approx_tokens(text) > _C.max_history_tokens:        # still too big: keep only the newest turns in short form
        recent = [_short(n - i, t["digest"]) for i, t in enumerate(ts[max(0, n - k):], start=max(0, n - k))]
        text = render(older, omitted, recent)
    return text
