# Testing CreaseIQ

All commands run from `backend/` with the project venv.

| Suite | Where | What it covers | Speed |
|---|---|---|---|
| Unit | `tests/unit-tests/` | Pure logic in isolation: config consistency, guardrails, routing decisions, routers, context/history, SQLite memory, Redis cache (fakeredis), RAG helpers, citation resolution, stub LLM, web-tool plumbing, API models | ~2 s |
| Integration | `tests/integration-test/` | The real LangGraph graph + real hybrid knowledge base + real SQLite, with the deterministic stub model: answering, clarification, scope/safety, memory, cache, repair + requery safety net, failure handling, and the FastAPI app (REST + SSE) | ~12 s |
| Regression | `tests/regression-test/` | Behaviour that must not change: one test per fixed defect (`REG-001…016`), 17 golden conversations replayed through the whole agent, a retrieval-recall baseline on the real knowledge base, and a routing-decision snapshot | ~7 s |
| Frontend client | `tests/integration-test/frontend/` | The browser SSE client (`frontend/src/api.js`) and the answer splitter (`frontend/src/answer.js`), with a faked `fetch` (Node's built-in runner, no install) | <1 s |
| Live | `tests/integration-test/live/` | Real local Ollama model through the API | minutes |

```bash
# everything offline (unit + integration, stub model, no Redis/Ollama/network needed)
.venv/bin/python -m pytest

.venv/bin/python -m pytest tests/unit-tests            # unit only
.venv/bin/python -m pytest tests/integration-test      # integration only
.venv/bin/python -m pytest tests/regression-test       # regression only
node --test "tests/integration-test/frontend/*.test.mjs"   # frontend stream client

# live, against Ollama (OLLAMA_MODEL / OLLAMA_BASE_URL from .env); slow and model-dependent
RUN_LIVE=1 .venv/bin/python -m pytest tests/integration-test/live -v
```

## How the tests stay deterministic
`tests/conftest.py` runs before any project import and: writes a temp copy of `config.toml` with `use_stub = true` (the repo config is untouched),
points the memory DB and cache prefix at throw-away locations, and gives every test its own in-memory fake Redis. Web search is faked per test.
With `RUN_LIVE=1` the stub is switched off and only `live` tests run.

## Regression suite
- `test_known_defects.py`: every bug that was found and fixed has a `REG-nnn` test that recreates the failing condition (listed in the file's docstring). Add one whenever you fix a bug.
- `golden/conversations.json`: multi-turn conversations with the expected status, format, citations and path. Add a case by adding JSON, no code.
- `golden/retrieval.json`: queries that must retrieve a given passage from the real knowledge base, and off-corpus queries that must stay below `retrieval.min_score`. Re-run after any re-ingest, chunking, embedding or reranker change.
- `test_routing_snapshot.py`: the deterministic routing decisions for many phrasings (plurals, Hindi names, clause numbers, comparisons, unsupported scopes).
When a golden or snapshot test fails after an intentional change, update the expectation in the same commit and say why.
