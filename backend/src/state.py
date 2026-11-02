"""State and structured-output schemas."""
from __future__ import annotations

from typing import Annotated, Literal, Optional, TypedDict

from langgraph.graph.message import add_messages
from pydantic import BaseModel, Field


class RouteResult(BaseModel):
    """What the MODEL extracts from the message. Decisions (intent, format, scope, missing facts, language) are made in code."""
    cricket_relevance: Literal["cricket", "non_cricket", "unclear"]
    scenario_facts: list[str] = Field(default_factory=list)
    normalized_english_query: str = ""
    web_query: str = ""


class Analysis(BaseModel):
    """Evidence-linked reasoning. Citations are chunk ids drawn from the retrieved passages only."""
    requirements: list[str] = Field(default_factory=list)
    fact_mapping: list[str] = Field(default_factory=list)
    conclusion: str
    uncertainty: str = ""
    cited_chunk_ids: list[str] = Field(default_factory=list)


class CreaseState(TypedDict, total=False):
    messages: Annotated[list, add_messages]        # redacted conversation history
    question: str                                   # current (redacted) user message
    original_question: str                         # the question that started the current clarification thread
    is_follow_up: bool                              # this turn answers a clarification
    requested_language: Optional[str]               # optional caller override: en | hi
    input_language: str
    response_language: str
    cricket_relevance: str                          # cricket | non_cricket | unclear
    intent: str                                     # scenario | clause_lookup | compare | general
    format: str                                     # ODI | T20I | unknown
    clause_number: Optional[str]
    competition: Optional[str]
    match_date: Optional[str]
    scenario_facts: list[str]
    missing_facts: list[str]                        # keys of STRINGS "fact_<key>"
    clarification_question: Optional[str]
    clarification_count: int                        # cap: limits.max_clarifications
    normalized_english_query: str
    web_query: str
    retrieval_attempt: int                          # cap: limits.max_retrieval_retries
    retrieval_plan: list[dict]                      # [{tool, args}] chosen by retrieve_rules, run by retrieval_tools
    retrieved_rules: list[dict]
    evidence_status: str                            # pending | sufficient | insufficient
    insufficient_reason: Optional[str]              # no_relevant_passage | weak_evidence | outside_sources | clarification_limit
    analysis: Optional[dict]
    citations: list[dict]
    answer_body: str
    answer: str
    repair_attempt: int                             # cap: limits.max_repairs
    validation_status: str                          # pending | passed | failed
    validation_issues: list[str]
    web_results: list[dict]
    web_sources: list[dict]
    status: str                                     # answered | answered_general | clarification_required | unsupported |
                                                    # insufficient_evidence | out_of_scope | error
    unsupported_reason: Optional[str]
    error: Optional[str]
    pii_found: list[str]
    profile: dict                                   # long-term memory of the user: preferred_format, preferred_language, topics
    memory_format: Optional[str]                    # remembered format offered to this turn when the message names none
    format_from_memory: bool                        # the remembered format was actually used (the answer says so)
    history: str                                    # fenced digest of the user's recent turns (routing step only)
    prior_turn: Optional[dict]                      # digest of the last answered rules turn, for resolving follow-ups
    cache_status: str                               # hit | miss | off | error
    cache_similarity: Optional[float]
    cache_query: Optional[str]                      # the earlier question a cache hit was served for
    blocked_reason: Optional[str]                   # why input_guard / output_guard stopped the turn (internal; never shown to users)
