"""Loads every setting from backend/config/config.toml. No tunable value is hard-coded in the other modules.

    settings   [settings.*]  (SimpleNamespace: settings.limits.max_repairs)
    LEXICON    [lexicon.*]   (dict: word lists, patterns, mock data)
    PROMPTS    [prompts]     (dict: system prompts / templates)
    STRINGS    [strings.*]   (dict: fixed user-facing messages per language)
    [kb.*] is read by build_kb.load_config.
"""
from __future__ import annotations

import os
import tomllib
from pathlib import Path
from types import SimpleNamespace

from dotenv import load_dotenv

BACKEND = Path(__file__).resolve().parents[1]
CONFIG_FILE = Path(os.environ.get("CREASEIQ_CONFIG") or BACKEND / "config" / "config.toml")


with CONFIG_FILE.open("rb") as _f:
    _RAW = tomllib.load(_f)


def _ns(d: dict) -> SimpleNamespace:
    """Recursively turn a dict into a SimpleNamespace so settings can be read as attributes."""
    return SimpleNamespace(**{k: _ns(v) if isinstance(v, dict) else v for k, v in d.items()})


settings = _ns(_RAW["settings"])
LEXICON = _RAW["lexicon"]
PROMPTS = _RAW["prompts"]
STRINGS = _RAW["strings"]

load_dotenv(BACKEND / settings.paths.env_file)
load_dotenv()

SUPPORTED_FORMATS = tuple(LEXICON["format_tools"])
SUPPORTED_LANGUAGES = LEXICON["languages"]
