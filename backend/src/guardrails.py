"""Phase 1 guardrails (deterministic, no LLM calls): sanitize_input (FastAPI stand-in), input_guard, output checks, output_guard."""
from __future__ import annotations

import os
import re
import unicodedata
from typing import Optional

from config import LEXICON, PROMPTS, settings
from language import detect_language, script_stats

_G = LEXICON["guardrails"]
_CFG = settings.guardrails
_TOXIC_RES = [re.compile(r"(?<!\w)(?:" + "|".join(re.escape(t) for t in ts) + r")(?!\w)", re.I) for ts in (_G["toxic_en"], _G["toxic_hi"]) if ts]
_INJECTION = [re.compile(p, re.I) for p in _G["injection_patterns"]]
_AUTHORITY = [re.compile(p, re.I) for p in _G["authority_patterns"]]
_KEYS = [re.compile(p) for p in _G["key_patterns"]]
_PII = [(kind, re.compile(rx)) for kind, rx in _G["pii"]]


def has_toxic(text: str) -> bool:
    """True if the text contains a term from the toxic-word lists."""
    return any(r.search(text) for r in _TOXIC_RES)


def check_input(text: str) -> Optional[str]:
    """Deterministic input checks on already-sanitised text. Returns a block reason (maps to a STRINGS key) or None."""
    if not text.strip():
        return "empty"
    if len(text) > settings.limits.max_input_chars:
        return "too_long"
    s = script_stats(text)
    if s["letters"] and s["other"] > _CFG.max_other_script_ratio:
        return "script"
    if any(p.search(text) for p in _INJECTION) or has_toxic(text):
        return "policy"
    return None


def _ngrams(s: str) -> set:
    """Set of word n-grams of a text (n = guardrails.prompt_leak_ngram_words), used to detect prompt leakage."""
    n, w = _CFG.prompt_leak_ngram_words, re.findall(r"\w+", s.lower())
    return {" ".join(w[i:i + n]) for i in range(len(w) - n + 1)}


_PROMPT_NGRAMS = set().union(*(_ngrams(p) for p in PROMPTS.values()))       # every system prompt is protected


def leaks_secrets_or_prompts(text: str) -> bool:
    """True if the text contains an API-key pattern, a secret from the environment, or a long overlap with any system prompt."""
    if any(p.search(text) for p in _KEYS):
        return True
    for var in _CFG.secret_env_vars:
        v = os.getenv(var)
        if v and len(v) >= _CFG.min_secret_length and v in text:
            return True
    return bool(_ngrams(text) & _PROMPT_NGRAMS)


def check_output(state, body: str, answer: str) -> list[str]:
    """body = the model-written part; answer = body + the code-built Sources line and disclaimer.
    Authority and language checks use the body only (the fixed disclaimer says 'not an official ruling')."""
    codes = []
    if has_toxic(answer):
        codes.append("toxic")
    if leaks_secrets_or_prompts(answer):
        codes.append("leak")
    if len(answer) > settings.limits.max_output_chars:
        codes.append("too_long")
    if any(p.search(body) for p in _AUTHORITY):
        codes.append("authority")
    lang, st = state.get("response_language") or settings.language.default, script_stats(body)
    if (lang == "en" and st["devanagari"] > _CFG.wrong_language_deva_ratio) or (lang == "hi" and st["letters"] >= _CFG.hindi_min_letters and st["deva_count"] == 0):
        codes.append("wrong_language")
    return codes


def sanitize_input(text: str):
    """Stand-in for the FastAPI redaction service: contact/identifier PII only; cricket names are left alone."""
    keep = set(_G["keep_control_chars"])
    text = unicodedata.normalize("NFKC", str(text))[: settings.limits.max_input_chars * settings.limits.input_cut_multiplier]
    text = "".join(ch for ch in text if ch in keep or unicodedata.category(ch)[0] != "C").strip()
    found = []
    for kind, rx in _PII:
        n = [0]

        def sub(m, kind=kind, n=n):
            """Replace one PII match with a numbered placeholder such as [EMAIL_1]."""
            n[0] += 1
            return f"[{kind}_{n[0]}]"
        text, count = rx.subn(sub, text)
        if count:
            found.append(kind)
    return text, found


# ---- nodes -----------------------------------------------------------------------------------------------------
def input_guard(state):
    """Node: refuse empty, too long, wrong-script, injection or abusive messages before any LLM call."""
    reason = check_input(state["question"])
    if not reason:
        return {"blocked_reason": None}
    return {"blocked_reason": f"input:{reason}", "unsupported_reason": reason,
            "response_language": state.get("requested_language") or detect_language(state["question"])}


def output_guard(state):
    """Node: check the drafted answer; on failure mark validation failed so the single repair attempt (or a safe refusal) is used."""
    codes = check_output(state, state.get("answer_body", ""), state.get("answer", ""))
    if not codes:
        return {"blocked_reason": None, "unsupported_reason": None}
    return {"validation_status": "failed", "validation_issues": [f"output:{c}" for c in codes],
            "blocked_reason": "output:" + ",".join(codes), "unsupported_reason": "output_blocked"}
