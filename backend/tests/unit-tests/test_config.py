"""config.toml sanity: everything the code looks up must exist, in every supported language."""
from config import LEXICON, PROMPTS, STRINGS, SUPPORTED_FORMATS, SUPPORTED_LANGUAGES, settings


def test_supported_formats_and_languages():
    assert set(SUPPORTED_FORMATS) == {"ODI", "T20I"}
    assert {"en", "hi"} <= set(SUPPORTED_LANGUAGES)


def test_every_language_has_the_same_message_keys():
    base = set(STRINGS["en"])
    for lang in SUPPORTED_LANGUAGES:
        assert set(STRINGS[lang]) == base, f"{lang} strings differ from en: {set(STRINGS[lang]) ^ base}"


def test_strings_needed_by_the_nodes_exist():
    for key in ("disclaimer", "sources", "error", "rephrase", "ask_fact", "fact_format", "non_cricket_off", "no_web", "web_label",
                "cache_hit_label", "memory_format_note", "unsupported_output_blocked", "insufficient_weak_evidence",
                "insufficient_no_relevant_passage", "insufficient_outside_sources", "insufficient_clarification_limit"):
        for lang in SUPPORTED_LANGUAGES:
            assert STRINGS[lang].get(key), f"missing strings.{lang}.{key}"


def test_unsupported_reasons_all_have_messages():
    reasons = set(LEXICON["routing"]["unsupported_markers"].values()) | {"empty", "too_long", "script", "policy", "output_blocked", "other"}
    for lang in SUPPORTED_LANGUAGES:
        for r in reasons:
            assert f"unsupported_{r}" in STRINGS[lang], f"missing unsupported_{r} in {lang}"


def test_required_prompts_exist():
    for name in ("route", "analyse", "answer", "general", "reformulate", "repair_extra"):
        assert PROMPTS[name].strip()


def test_limits_are_sane():
    L = settings.limits
    assert L.max_repairs >= 1 and L.max_retrieval_retries >= 1 and L.max_clarifications >= 1
    assert 0 < settings.retrieval.min_score < 1
    assert settings.memory.max_users == 25 and settings.memory.max_turns == 25


def test_tests_run_on_the_stub_model():
    """Guards against accidentally running the offline suite against a real model."""
    assert settings.llm.use_stub is True
