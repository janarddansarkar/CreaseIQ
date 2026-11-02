"""Builds the LangGraph StateGraph from the architecture diagram."""
from __future__ import annotations

from langgraph.checkpoint.sqlite import SqliteSaver
from langgraph.graph import END, START, StateGraph

import nodes as n
import rag
from cache import cache_lookup, cache_store
from memory import MemoryStore, get_store
import routers as r
from guardrails import input_guard, output_guard
from route import load_or_initialize_state, understand_and_route
from state import CreaseState

NODES = {
    "load_or_initialize_state": load_or_initialize_state, "understand_and_route": understand_and_route,
    "general_qa_gate": n.general_qa_gate, "web_search": n.web_search_node, "answer_general_question": n.answer_general_question,
    "handle_non_cricket": n.handle_non_cricket, "scope_gate": n.scope_gate, "handle_unsupported": n.handle_unsupported,
    "context_gate": n.context_gate, "clarification_gate": n.clarification_gate, "ask_clarification": n.ask_clarification,
    "save_clarification_state": n.save_clarification_state, "retrieve_rules": rag.retrieve_rules, "retrieval_tools": rag.retrieval_tools,
    "check_evidence": rag.check_evidence, "reformulate_query": rag.reformulate_query, "analyse_scenario": rag.analyse_scenario,
    "generate_answer": rag.generate_answer, "validate_final_answer": rag.validate_final_answer, "constrained_repair": rag.constrained_repair,
    "save_final_state": rag.save_final_state, "handle_insufficient_evidence": n.handle_insufficient_evidence, "handle_error": n.handle_error,
    "input_guard": input_guard, "output_guard": output_guard,      # additions: Phase 1 guardrails
    "cache_lookup": cache_lookup, "cache_store": cache_store,      # additions: Redis response cache
}
GUARDRAIL_ADDITIONS = {"input_guard", "output_guard", "cache_lookup", "cache_store"}      # not in the architecture diagram


def build_graph(checkpointer=None, store: MemoryStore | None = None):
    """Wire all nodes and edges of the architecture diagram and compile the graph (a SqliteSaver on the memory store's database by default)."""
    b = StateGraph(CreaseState)
    for name, fn in NODES.items():
        b.add_node(name, fn)

    b.add_edge(START, "load_or_initialize_state")
    b.add_edge("load_or_initialize_state", "input_guard")
    b.add_conditional_edges("input_guard", r.route_after_input_guard, ["handle_unsupported", "understand_and_route"])   # Message safe to process?
    b.add_conditional_edges("understand_and_route", r.route_after_route,
                            ["handle_error", "general_qa_gate", "clarification_gate", "scope_gate"])   # Cricket-related? (+ exception edge)
    b.add_conditional_edges("general_qa_gate", r.route_general_qa, ["web_search", "handle_non_cricket"])   # General Q&A enabled?
    b.add_conditional_edges("web_search", r.continue_or_error("answer_general_question"), ["answer_general_question", "handle_error"])
    b.add_conditional_edges("answer_general_question", r.end_or_error, [END, "handle_error"])
    b.add_edge("handle_non_cricket", END)
    b.add_conditional_edges("scope_gate", r.route_scope, ["handle_unsupported", "context_gate"])   # Supported format and source scope?
    b.add_edge("handle_unsupported", END)
    b.add_conditional_edges("context_gate", r.route_context, ["clarification_gate", "cache_lookup"])   # Decisive facts complete?
    b.add_conditional_edges("cache_lookup", r.route_after_cache, ["save_final_state", "retrieve_rules"])   # Similar question already answered (Redis)?
    b.add_conditional_edges("clarification_gate", r.route_clarification, ["ask_clarification", "handle_insufficient_evidence"])   # Clarifications left?
    b.add_edge("ask_clarification", "save_clarification_state")
    b.add_edge("save_clarification_state", END)
    b.add_conditional_edges("retrieve_rules", r.continue_or_error("retrieval_tools"), ["retrieval_tools", "handle_error"])
    b.add_conditional_edges("retrieval_tools", r.continue_or_error("check_evidence"), ["check_evidence", "handle_error"])
    b.add_conditional_edges("check_evidence", r.route_after_evidence,
                            ["analyse_scenario", "reformulate_query", "handle_insufficient_evidence"])   # check_evidence: sufficient?
    b.add_edge("reformulate_query", "retrieve_rules")                        # one retry loop
    b.add_conditional_edges("analyse_scenario", r.continue_or_error("generate_answer"), ["generate_answer", "handle_error"])
    b.add_conditional_edges("generate_answer", r.continue_or_error("validate_final_answer"), ["validate_final_answer", "handle_error"])
    b.add_conditional_edges("validate_final_answer", r.route_after_validation,
                            ["handle_error", "output_guard", "constrained_repair", "handle_insufficient_evidence"])   # Answer and citations valid?
    b.add_conditional_edges("output_guard", r.route_after_output, ["save_final_state", "constrained_repair", "handle_unsupported"])   # Reply passes output checks?
    b.add_conditional_edges("constrained_repair", r.continue_or_error("validate_final_answer"), ["validate_final_answer", "handle_error"])
    b.add_edge("save_final_state", "cache_store")
    b.add_edge("cache_store", END)
    b.add_edge("handle_insufficient_evidence", END)
    b.add_edge("handle_error", END)
    return b.compile(checkpointer=checkpointer or SqliteSaver((store or get_store()).conn))
