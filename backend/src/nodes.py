"""Non-RAG nodes: gates, web-search branch, clarification and terminal handlers."""
from __future__ import annotations

from langchain_core.messages import AIMessage

from common import S, reply, safe_node
from config import PROMPTS, settings
from guardrails import check_output
from llm import llm_text
from tools import TOOLS


# ---- pass-through gates (a diamond that feeds another diamond) -------------------------------------------------
def general_qa_gate(state):
    """Pass-through node for the 'General Q&A enabled?' decision."""
    return {}


def scope_gate(state):
    """Pass-through node for the 'Supported format and source scope?' decision."""
    return {}


def context_gate(state):
    """Pass-through node for the 'Decisive facts complete?' decision."""
    return {}


def clarification_gate(state):
    """Node: flag clarification_limit when the clarification cap is already reached."""
    return {"insufficient_reason": "clarification_limit"} if state.get("clarification_count", 0) >= settings.limits.max_clarifications else {}


# ---- web-search branch (non-cricket) ---------------------------------------------------------------------------
@safe_node
def web_search_node(state):
    """Node: run the web search tool for a non-cricket question and store its results."""
    return {"web_results": TOOLS["web_search"].invoke({"web_query": state["web_query"]})}


@safe_node
def answer_general_question(state):
    """Node: summarise the web results, run the output checks on that text, and reply with sources and a web-search label."""
    results = state.get("web_results", [])
    if not results:
        return reply(state, "answered_general", S(state, "no_web"))
    ctx = "\n".join(f"- {r['snippet']} | {r['title']} | {r['url']}" for r in results)
    body = llm_text("general", PROMPTS["general"],
                    f"LANGUAGE: {state.get('response_language', settings.language.default)}\nQUESTION: {state['question']}\nRESULTS:\n{ctx}")
    if check_output(state, body, body):      # unverified web text gets the same output checks (no repair loop on this branch)
        return reply(state, "unsupported", S(state, "unsupported_output_blocked"), blocked_reason="output:web")
    links = "\n".join(f"- {r['title']}: {r['url']}" for r in results)
    return reply(state, "answered_general", f"{body}\n\n{S(state, 'sources')}:\n{links}\n\n{S(state, 'web_label')}",
                 web_sources=[{"title": r["title"], "url": r["url"]} for r in results])


def handle_non_cricket(state):
    """Node: reply that general questions are switched off."""
    return reply(state, "out_of_scope", S(state, "non_cricket_off"))


# ---- unsupported / clarification -------------------------------------------------------------------------------
def handle_unsupported(state):
    """Node: reply with the fixed message for the recorded unsupported_reason."""
    return reply(state, "unsupported", S(state, f"unsupported_{state.get('unsupported_reason') or 'other'}"))


def ask_clarification(state):
    """Node: ask the user for the missing fact (or a rephrase when the domain is unclear) and count the clarification."""
    if state.get("cricket_relevance") == "unclear":
        q = S(state, "rephrase")
    else:
        q = S(state, "ask_fact").format(fact=S(state, f"fact_{state['missing_facts'][0]}"))
    return {"clarification_question": q, "clarification_count": state.get("clarification_count", 0) + 1, "answer": q}


def save_clarification_state(state):
    """Diagram: 'Checkpoint conversation state'. The checkpointer saves after every node; this node sets the final status."""
    return {"status": "clarification_required", "messages": [AIMessage(state["answer"])]}


# ---- terminal nodes --------------------------------------------------------------------------------------------
def handle_insufficient_evidence(state):
    """Node: abstain with the fixed message for the recorded insufficient_reason."""
    reason = state.get("insufficient_reason") or "weak_evidence"      # also reached after a failed repair
    return reply(state, "insufficient_evidence", S(state, f"insufficient_{reason}"), insufficient_reason=reason)


def handle_error(state):
    """Node: reply with the generic error message."""
    return reply(state, "error", S(state, "error"))
