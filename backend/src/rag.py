"""RAG nodes: retrieve_rules -> retrieval_tools -> check_evidence -> (reformulate_query) -> analyse -> answer -> validate -> repair."""
from __future__ import annotations

import re
from typing import Optional

from langchain_core.messages import AIMessage

from common import S, safe_node
from config import LEXICON, PROMPTS, SUPPORTED_FORMATS, settings
from llm import llm_structured, llm_text
from state import Analysis
from tools import TOOL_FORMAT, TOOLS

_CLAUSE_REF = re.compile(LEXICON["routing"]["clause_ref_pattern"], re.I)
_REF_STRIP = LEXICON["routing"]["answer_ref_strip_chars"]
_CITATION_FIELDS = ("source_id", "source_title", "version", "format", "clause_number", "printed_page_start")


# ---- evidence formatting ---------------------------------------------------------------------------------------
def numbered_evidence(passages: list[dict]) -> str:
    """Format passages as '[chunk_id | clause N | format] text' lines for the model."""
    return "\n".join(f"[{p['chunk_id']} | clause {p['clause_number']} | {p['format']}] {p['text']}" for p in passages)


def evidence_for_reasoning(state):
    """Passages whose retrieval_score reaches retrieval.min_score; only these are given to the model."""
    return [p for p in state["retrieved_rules"] if p["retrieval_score"] >= settings.retrieval.min_score]


def allowed_clauses(passages: list[dict]) -> set[str]:
    """Clause numbers an answer may mention (lower-case): those of the retrieved passages plus clauses their text refers to ('as in clause 6.1')."""
    allowed = {p["clause_number"].lower() for p in passages}
    for p in passages:
        allowed |= {m.rstrip(_REF_STRIP).lower() for m in _CLAUSE_REF.findall(p["text"])}
    return allowed


def build_citations(chunk_ids: list[str], passages: list[dict]) -> list[dict]:
    """Build citation records (chunk id plus source, clause and page) for the cited chunk ids."""
    by_id = {p["chunk_id"]: p for p in passages}
    return [{"chunk_id": cid, **({k: by_id[cid][k] for k in _CITATION_FIELDS} if cid in by_id else {})} for cid in chunk_ids]


def render_answer(state, body: str, citations: list[dict]) -> str:
    """Append the Sources line and the disclaimer to the answer body."""
    src = "; ".join(f"{c.get('source_title', '?')}, clause {c.get('clause_number', '?')}, p.{c.get('printed_page_start', '?')}" for c in citations)
    return f"{body}\n\n{S(state, 'sources')}: {src}\n\n{S(state, 'disclaimer')}"


# ---- retrieval -------------------------------------------------------------------------------------------------
@safe_node
def retrieve_rules(state):
    """Deterministic tool selection from the resolved format; the model never chooses between formats."""
    names = LEXICON["format_tools"]
    q, fmt, intent, k = state["normalized_english_query"], state.get("format"), state.get("intent"), settings.retrieval.top_k
    if intent == "compare":
        plan = [{"tool": names[f], "args": {"query": q, "top_k": k}} for f in SUPPORTED_FORMATS]
    elif intent == "clause_lookup":
        plan = [{"tool": "get_clause", "args": {"format": fmt, "clause_number": state["clause_number"]}}]
    elif fmt in names:
        plan = [{"tool": names[fmt], "args": {"query": q, "top_k": k}}]
    else:
        raise ValueError("format is unknown at retrieval time")
    return {"retrieval_plan": plan}


@safe_node
def retrieval_tools(state):
    """Node: execute the retrieval plan and check that no passage comes from the wrong format."""
    passages = []
    for step in state["retrieval_plan"]:
        found = TOOLS[step["tool"]].invoke(step["args"])
        expected = TOOL_FORMAT.get(step["tool"]) or step["args"].get("format")
        assert all(p["format"] == expected for p in found), "format filter violated"      # release gate: no cross-format leakage
        passages += found
    return {"retrieved_rules": passages}


def check_evidence(state):
    """Node: decide whether the retrieved passages are sufficient evidence, and why not if they are not."""
    passages = state.get("retrieved_rules", [])
    strong = [p for p in passages if p["retrieval_score"] >= settings.retrieval.min_score]
    ok = ({p["format"] for p in strong} == set(SUPPORTED_FORMATS)) if state.get("intent") == "compare" else bool(strong)
    if not passages:
        return {"evidence_status": "insufficient", "insufficient_reason": "no_relevant_passage"}
    if not ok:
        return {"evidence_status": "insufficient", "insufficient_reason": "weak_evidence"}
    if all(p["refers_outside"] for p in strong):
        return {"evidence_status": "insufficient", "insufficient_reason": "outside_sources"}
    return {"evidence_status": "sufficient", "insufficient_reason": None}


def reformulate_query(state):
    """One alternative English query. If the model fails, keep the old query (the graph then abstains after the retry)."""
    old = state["normalized_english_query"]
    try:
        new = llm_text("reformulate", PROMPTS["reformulate"], f"QUERY: {old}") or old
    except Exception:
        new = old
    return {"normalized_english_query": new, "retrieval_attempt": state.get("retrieval_attempt", 0) + 1}


# ---- analysis / answer / validation ----------------------------------------------------------------------------
def resolve_citation(cid: str, passages: list[dict]) -> Optional[str]:
    """Models cite sloppily: the whole evidence header, the clause number, or header fragments. Map each cited string to a RETRIEVED passage
    by chunk id or clause number. A bare format name is noise and is dropped. Anything else is kept unchanged so validation rejects it."""
    for cand in (cid, cid.split("|")[0]):
        key = re.sub(r"^[\[\s'\"]+|[\]\s'\"]+$", "", cand)
        key = re.sub(r"^clause\s+", "", key, flags=re.I).lower()
        for p in passages:
            if key in (p["chunk_id"].lower(), p["clause_number"].lower()):
                return p["chunk_id"]
    if cid.strip().upper() in SUPPORTED_FORMATS:
        return None
    return cid


@safe_node
def analyse_scenario(state):
    """Node: ask the model to apply only the evidence to the facts, then resolve its citations to retrieved chunk ids."""
    ev = evidence_for_reasoning(state)
    a: Analysis = llm_structured("analyse", Analysis, PROMPTS["analyse"],
        f"QUESTION: {state['original_question']}\nFACTS: {' | '.join(state.get('scenario_facts', []))}\nEVIDENCE:\n{numbered_evidence(ev)}")
    d = a.model_dump()
    resolved = (resolve_citation(c, state["retrieved_rules"]) for c in d["cited_chunk_ids"])
    d["cited_chunk_ids"] = list(dict.fromkeys(c for c in resolved if c))
    return {"analysis": d}


def _write_body(state, extra: str = "") -> str:
    """Ask the model to write the user-facing answer from the analysis and evidence in the response language."""
    ev, an = evidence_for_reasoning(state), state["analysis"]
    return llm_text("answer", PROMPTS["answer"].format(extra=extra),
                    f"LANGUAGE: {state.get('response_language', settings.language.default)}\nQUESTION: {state['original_question']}\n"
                    f"ANALYSIS: {an['conclusion']} {an['uncertainty']}\nEVIDENCE:\n{numbered_evidence(ev)}")


@safe_node
def generate_answer(state):
    """Node: write the answer body, attach citations and render the final answer text."""
    body = _write_body(state)
    cites = build_citations(state["analysis"]["cited_chunk_ids"], state["retrieved_rules"])
    return {"answer_body": body, "citations": cites, "answer": render_answer(state, body, cites)}


@safe_node
def validate_final_answer(state):
    """Deterministic checks on the actual user-facing answer (citation membership, clause references, disclaimer)."""
    retrieved_ids = {p["chunk_id"] for p in state["retrieved_rules"]}
    retrieved_clauses = allowed_clauses(state["retrieved_rules"])
    issues = []
    if not state.get("answer_body", "").strip():
        issues.append("empty_answer")
    if not state.get("citations"):
        issues.append("no_citations")
    issues += [f"unknown_citation:{c['chunk_id']}" for c in state.get("citations", []) if c["chunk_id"] not in retrieved_ids]
    issues += [f"unknown_clause:{m.rstrip(_REF_STRIP)}" for m in _CLAUSE_REF.findall(state.get("answer_body", "")) if m.rstrip(_REF_STRIP).lower() not in retrieved_clauses]
    if S(state, "disclaimer") not in state.get("answer", ""):
        issues.append("missing_disclaimer")
    return {"validation_status": "failed" if issues else "passed", "validation_issues": issues}


@safe_node
def constrained_repair(state):
    """One repair: keep only valid citations and regenerate using only the retrieved clauses."""
    valid_ids = {p["chunk_id"] for p in state["retrieved_rules"]}
    keep = [c["chunk_id"] for c in state["citations"] if c["chunk_id"] in valid_ids] or [p["chunk_id"] for p in evidence_for_reasoning(state)[:settings.retrieval.repair_fallback_passages]]
    allowed = ", ".join(sorted(allowed_clauses(state["retrieved_rules"])))
    body = _write_body(state, PROMPTS["repair_extra"].format(issues=state["validation_issues"], allowed=allowed))
    cites = build_citations(keep, state["retrieved_rules"])
    return {"repair_attempt": state.get("repair_attempt", 0) + 1, "answer_body": body, "citations": cites, "answer": render_answer(state, body, cites)}


def save_final_state(state):
    """Diagram: 'Checkpoint final state'."""
    return {"status": "answered", "messages": [AIMessage(state["answer"])]}
