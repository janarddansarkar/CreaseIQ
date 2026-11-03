import pytest

from language import detect_language, is_devanagari, script_stats


@pytest.mark.parametrize("text,lang", [
    ("In T20I how many overs can a bowler bowl?", "en"),
    ("T20I में एक गेंदबाज़ कितने ओवर फेंक सकता है?", "hi"),
    ("", "en"),
    ("12345 ???", "en"),
])
def test_detect_language(text, lang):
    assert detect_language(text) == lang


def test_script_stats_ratios():
    s = script_stats("abc नमस्ते")
    assert s["letters"] > 0 and 0 < s["latin"] < 1 and 0 < s["devanagari"] < 1
    assert s["other"] == pytest.approx(0, abs=1e-9)
    assert script_stats("")["letters"] == 0


def test_other_script_ratio():
    assert script_stats("これは日本語です")["other"] > 0.9


def test_is_devanagari():
    assert is_devanagari("क") and not is_devanagari("k")
