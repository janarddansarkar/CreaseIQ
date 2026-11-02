"""LLM access: deterministic stub (default) or an OpenAI-compatible endpoint such as local Ollama.
Nodes only use llm_text / llm_structured, so they are identical for both."""
from __future__ import annotations

import os
import re

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage

from config import LEXICON, settings
from state import Analysis, RouteResult

_STUB = LEXICON["stub"]
_EVIDENCE_LINE = r"^\[(.+?) \| clause (\S+) \| (\S+)\] (.*)$"


def field(user: str, key: str) -> str:
    """Value of a 'KEY: value' line in a prompt."""
    m = re.search(rf"^{key}: ?(.*)$", user, re.M)
    return m.group(1).strip() if m else ""


class StubLLM:
    """Offline, rule-based stand-in for the chat model. Deterministic; lets the graph run without a model server."""

    def with_structured_output(self, schema, **kw):
        """Return a stub that mimics structured output for the given schema."""
        return _StubStructured(schema)

    def invoke(self, messages):
        """Answer a chat request by rule, keyed on the TASK tag in the system message (answer, reformulate or general)."""
        system, user = messages[0].content, messages[-1].content
        task = field(system, "TASK")
        if task == "answer":
            body = self._answer(user)
        elif task == "reformulate":
            body = field(user, "QUERY")
            for k, v in _STUB["synonyms"].items():
                body = re.sub(rf"\b{k}\b", v, body, flags=re.I)
        elif task == "general":
            snippets = re.findall(r"^- (.*?) \| ", user, re.M)
            body = _STUB["general_prefix"] + (snippets[0] if snippets else _STUB["general_none"]) + "."
        else:
            body = ""
        return AIMessage(content=body)

    def _answer(self, user):
        """Compose a plain-text answer from the evidence lines in the prompt."""
        lines = re.findall(_EVIDENCE_LINE, user, re.M)
        parts = [_STUB["answer_line"].format(clause=clause, fmt=fmt, text=text[:settings.stub.max_quote_chars]) for _id, clause, fmt, text in lines[:settings.stub.max_cited_passages]]
        return (_STUB["hindi_prefix"] if field(user, "LANGUAGE") == "hi" else "") + (" ".join(parts) or _STUB["no_evidence"])


class _StubStructured:
    def __init__(self, schema):
        """Remember the schema being requested."""
        self.schema = schema

    def invoke(self, messages):
        """Return a RouteResult or an Analysis built by rules from the prompt text."""
        user = messages[-1].content
        return self._route(user) if self.schema is RouteResult else self._analyse(user)

    def _route(self, user):
        """Classify the message as cricket / non_cricket / unclear and extract a normalised English query."""
        msg, pending = field(user, "MESSAGE"), field(user, "PENDING_QUESTION")
        text = f"{pending} {msg}".lower()
        tokens = set(re.findall(r"[\w\-]+", text))
        is_cricket = (bool(tokens & set(_STUB["cricket_words"])) or any(p in text for p in _STUB["cricket_phrases"])
                      or bool(re.search(_STUB["cricket_format_pattern"], text)))
        is_non = any(h in text for h in _STUB["non_cricket_hints"])
        relevance = "cricket" if is_cricket else ("non_cricket" if is_non else "unclear")
        q = f"{pending} {msg}".strip()
        for k, v in _STUB["hi_to_en"].items():
            q = q.replace(k, v)
        q = re.sub(r"\s+", " ", re.sub(r"[^\w\s\-]", " ", q)).strip()
        return RouteResult(cricket_relevance=relevance, scenario_facts=[msg] if relevance == "cricket" and msg else [],
                           normalized_english_query=q, web_query=msg)

    def _analyse(self, user):
        """Build an Analysis that cites the first evidence passages."""
        lines = re.findall(_EVIDENCE_LINE, user, re.M)[:settings.stub.max_cited_passages]
        return Analysis(requirements=[l[3] for l in lines], fact_mapping=[_STUB["analysis_mapping"].format(clause=l[1]) for l in lines],
                        conclusion=_STUB["analysis_conclusion"], uncertainty="", cited_chunk_ids=[l[0] for l in lines])


def _build_llm():
    """Create the chat model selected in [settings.llm]: the offline stub or an OpenAI-compatible client (local Ollama)."""
    cfg = settings.llm
    if cfg.use_stub:
        return StubLLM()
    from langchain_openai import ChatOpenAI
    return ChatOpenAI(model=os.getenv(cfg.model_env, cfg.model_default), base_url=os.getenv(cfg.base_url_env, cfg.base_url_default),
                      api_key=cfg.api_key, temperature=cfg.temperature, timeout=cfg.timeout_seconds, max_retries=cfg.max_retries)


llm = _build_llm()


def llm_text(task: str, system: str, user: str) -> str:
    """Call the model with a TASK-tagged system prompt and return the plain-text reply."""
    return llm.invoke([SystemMessage(f"TASK: {task}\n{system}"), HumanMessage(user)]).content.strip()


def llm_structured(task: str, schema, system: str, user: str):
    """Automatic retries on a schema failure (llm.structured_attempts), then raise (the node records the error)."""
    runnable = llm.with_structured_output(schema, method=settings.llm.structured_method)
    msgs, last = [SystemMessage(f"TASK: {task}\n{system}"), HumanMessage(user)], None
    for _ in range(settings.llm.structured_attempts):
        try:
            return runnable.invoke(msgs)
        except Exception as e:
            last = e
    raise last
