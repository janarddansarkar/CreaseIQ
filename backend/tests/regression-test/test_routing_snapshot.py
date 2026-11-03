"""Snapshot of the deterministic routing decisions (format, intent, scope, missing facts) for a broad set of phrasings."""
import pytest

from route import UNKNOWN, decide_route, detect_format
from state import RouteResult

CRICKET = RouteResult(cricket_relevance="cricket")

# text -> (format, intent, unsupported_reason, missing_facts). Unsupported requests skip the missing-format question on purpose.
SNAPSHOT = [
    ("How many overs can a bowler bowl in T20I?",            ("T20I", "scenario", None, [])),
    ("How many overs can a bowler bowl in T20Is?",           ("T20I", "scenario", None, [])),
    ("t20 powerplay rules",                                  ("T20I", "scenario", None, [])),
    ("Twenty20 super over",                                  ("T20I", "scenario", None, [])),
    ("twenty-20 rules",                                      ("T20I", "scenario", None, [])),
    ("टी-20 में पावरप्ले",                                      ("T20I", "scenario", None, [])),
    ("How many overs can a bowler bowl in an ODI?",          ("ODI", "scenario", None, [])),
    ("ODIs powerplay",                                       ("ODI", "scenario", None, [])),
    ("one day international fielding",                       ("ODI", "scenario", None, [])),
    ("one-day match rules",                                  ("ODI", "scenario", None, [])),
    ("वनडे में कितने ओवर",                                      ("ODI", "scenario", None, [])),
    ("What happens after a no ball?",                        (UNKNOWN, "scenario", None, ["format"])),
    ("What does clause 21.18 say in T20I?",                  ("T20I", "clause_lookup", None, [])),
    ("clause 2.6.3 ODI",                                     ("ODI", "clause_lookup", None, [])),
    ("What does clause 21.18 say?",                          (UNKNOWN, "clause_lookup", None, ["format"])),
    ("Compare the free hit rule in ODI and T20I",            (UNKNOWN, "compare", None, [])),
    ("ODI vs T20I powerplay",                                (UNKNOWN, "compare", None, [])),
    ("difference between ODI and T20I free hit",             (UNKNOWN, "compare", None, [])),
    ("What is the follow-on rule in a Test match?",          (UNKNOWN, "scenario", "format_not_supported", [])),
    ("test cricket DRS",                                     (UNKNOWN, "scenario", "format_not_supported", [])),
    ("women's T20I super over",                              ("T20I", "scenario", "format_not_supported", [])),
    ("IPL powerplay in T20I",                                ("T20I", "scenario", "competition_specific", [])),
    ("Big Bash free hit T20I",                               ("T20I", "scenario", "competition_specific", [])),
]


@pytest.mark.parametrize("text,expected", SNAPSHOT, ids=[t[:40] for t, _ in SNAPSHOT])
def test_route_decision(text, expected):
    d = decide_route(CRICKET, {}, text, "")
    assert (d["format"], d["intent"], d["unsupported_reason"], d["missing_facts"]) == expected


@pytest.mark.parametrize("text", ["compare ODI and T20I", "ODI or T20I?", "both T20I and one-day rules"])
def test_two_formats_named_is_ambiguous_not_a_guess(text):
    assert detect_format(text) == UNKNOWN


@pytest.mark.parametrize("text", ["Android phone", "godis", "t200 runs", "model T20X"])
def test_look_alikes_are_not_formats(text):
    assert detect_format(text) == UNKNOWN
