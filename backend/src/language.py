"""Script / language detection."""
from __future__ import annotations

from config import settings

_DEVA_LO, _DEVA_HI = settings.guardrails.devanagari_range


def is_devanagari(ch: str) -> bool:
    """True if the character lies in the Devanagari Unicode range."""
    return _DEVA_LO <= ord(ch) <= _DEVA_HI


def script_stats(text: str) -> dict:
    """Letter counts and Latin / Devanagari / other-script ratios of a text."""
    letters = [ord(c) for c in text if c.isalpha()]
    d = max(len(letters), 1)
    latin = sum(o <= settings.guardrails.latin_max_codepoint for o in letters)
    deva = sum(_DEVA_LO <= o <= _DEVA_HI for o in letters)
    return {"letters": len(letters), "latin": latin / d, "devanagari": deva / d, "other": 1 - (latin + deva) / d, "deva_count": deva}


def detect_language(text: str) -> str:
    """Return 'hi' when enough letters are Devanagari, otherwise the default language."""
    s = script_stats(text)
    return "hi" if s["letters"] and s["devanagari"] >= settings.language.min_devanagari_ratio else settings.language.default
