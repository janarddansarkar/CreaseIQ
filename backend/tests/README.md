# CreaseIQ tests: unit, integration and regression

The three kinds of test answer three different questions. Everything here runs offline with a deterministic stand-in model, so no Ollama, Redis or internet is needed (see `../TESTING.md` for the commands).

| | **Unit** | **Integration** | **Regression** |
|---|---|---|---|
| Question it answers | Does this one piece of logic work? | Do the pieces work together? | Did something that used to work break? |
| Scope | One function or class, in isolation | The real graph, knowledge base, SQLite, API | The whole agent, against recorded expectations |
| Dependencies | Faked or none (fake Redis, scripted values) | Real, except the model (stub), Redis (fake) and web search (fake) | Same as integration |
| Written from | The code's contract | A user's or system's flow | A past bug or a behaviour worth freezing |
| Fails when | A function's logic is wrong | Components disagree or a flow breaks | An earlier fix is undone, or output drifts |
| Speed | ~2 s | ~13 s | ~10 s |
| Count | 190 | 78 (+4 live) | 86 |

A bug usually shows up in more than one level. A unit test tells you *where*, an integration test tells you *that a flow broke*, and a regression test stops it *coming back*.

---

## Unit tests: `unit-tests/`

Test one small piece with everything around it replaced. They are fast and pinpoint the faulty function.

Example here: `resolve_citation("[chunk | clause 21.18 | T20I]", passages)` should return the chunk id. No graph, no model, no database.

| File | What it checks in CreaseIQ |
|---|---|
| `test_config.py` | `config.toml` is consistent: every language has the same message keys, every refusal reason has a message, prompts exist, limits are sane |
| `test_language.py` | English vs Hindi (Devanagari) detection and script statistics |
| `test_common.py` | `safe_node` turns exceptions into an error state, `S()` picks the right language string, `reply()` builds the terminal update |
| `test_guardrails.py` | PII redaction (email, phone), control-character stripping, blocking of empty, too-long, injection, toxic and wrong-script input, output checks (secrets, prompt leaks, authority claims, wrong language) |
| `test_routing.py` | Format detection, intent (scenario, clause lookup, compare), unsupported scopes, missing-fact clarification, remembered format, per-turn state reset |
| `test_routers.py` | Every graph branching decision, including the repair, retry and abstain order after a failed validation |
| `test_context.py` | Conversation digests, which past turns are usable, follow-up detection, the history block, its token budget and prompt-injection fence |
| `test_memory.py` | SQLite memory: the 25-user and 25-turn caps, eviction, long-term profile, topic limit, deletion, old-schema migration |
| `test_cache.py` | The Redis semantic cache (with fakeredis): hits, buckets, clause matching, key-term guard, expiry, eviction, and that Redis failure never breaks an answer |
| `test_rag_helpers.py` | Evidence formatting, the format-free search query, citation resolution, the sufficient-evidence check, answer validation, query reformulation and the original-wording retry |
| `test_llm_stub.py` | The offline stand-in model and the structured-output retry logic |
| `test_web_tools.py` | Web-search plumbing (provider dispatch, Tavily parsing, missing key), with no network |
| `test_api_models.py` | Request validation (length, id pattern) and SSE framing |

## Integration tests: `integration-test/`

Run the real parts together, so they catch problems at the seams: a node producing something the next node cannot use, a wrong graph edge, memory not reaching routing.

Example here: ask "How many overs can one bowler bowl in T20I?" and check it travels through retrieval, analysis, validation and the output guard, returns T20I-only citations, writes a memory turn and fills the cache.

| File | What it checks in CreaseIQ |
|---|---|
| `test_knowledge_base.py` | The real hybrid knowledge base: per-format filtering, score ordering, `top_k`, clause lookup, blank queries |
| `test_agent_flows.py` | The agent end to end: answering in both formats, clause lookup, comparison, Hindi replies, the clarification round trip, the clarification cap, refusals (Test matches, IPL, injection, toxic, too long), PII redaction, the web-search branch, memory (profile, remembered format, follow-ups), the user and turn caps, checkpoint pruning, cache hits and misses, Redis-down behaviour |
| `test_agent_resilience.py` | Failure handling: the single repair, the retry from the original wording, bounded abstention, blocked drafts (authority claim, secret leak), weak or outside-corpus evidence, a crashing model, a cross-format retrieval leak |
| `test_api.py` | The FastAPI app over HTTP: health, languages, formats, `/chat`, conversation ids, validation errors (422), clean 500s, CORS, and the `/chat/stream` Server-Sent Events |
| `frontend/stream-client.test.mjs` | The browser stream client in `frontend/src/api.js`, with a faked `fetch`: split chunks, error events, HTTP errors, aborts |
| `live/test_live_ollama.py` | Optional. The real Ollama model through the API (`RUN_LIVE=1`). Slow, and it only checks things that must hold whatever the model says |

## Regression tests: `regression-test/`

Freeze behaviour so it cannot silently change. They are not about new features. They exist because something went wrong once, or because a result matters enough to guard.

Example here: with an earlier ODI question in the conversation, the next T20I question used to be reworded and abstain. `REG-002` recreates that exact situation and checks it now answers.

| File | What it guards in CreaseIQ |
|---|---|
| `test_known_defects.py` | One test per fixed bug (`REG-001` to `REG-012`): plural `T20Is`, history rewording a self-contained question, citations copied as a whole evidence header, the retry using `And in ODI?`, the repair budget not resetting, Redis outage, the cache serving a changed fact, PII or failed answers being cached, evicted users' checkpoints, the stream's step events, an off-corpus question that names a format being answered from unrelated passages |
| `test_golden_conversations.py` + `golden/conversations.json` | 17 recorded conversations (answers, clarification, refusals, follow-ups, cache hit, abstention, web branch, Hindi) with their expected status, format, citations and path |
| `test_retrieval_golden.py` + `golden/retrieval.json` | The knowledge base still returns the right passage for known questions, and off-topic questions still score below the evidence threshold, so the agent abstains |
| `test_routing_snapshot.py` | A table of phrasings and the routing decision each must produce (plurals, Hindi names, clause numbers, comparisons, unsupported scopes) |

If a golden or snapshot test fails after an intentional change, update the expectation in the same commit and say why. If it fails unexpectedly, behaviour changed and that needs a look.

---

## Which one should I write?

| Situation | Add a… |
|---|---|
| New helper or branch of logic | **Unit** test next to the closest file |
| New node, route, endpoint or cross-component flow | **Integration** test |
| You just fixed a bug | **Regression** test (`REG-nnn`) that fails without the fix |
| New must-keep conversation or query | A case in a **golden JSON** file |
| Changed the PDFs, chunking, embeddings or reranker | Re-run the **retrieval golden** set |

## How the suite stays reliable
- `conftest.py` forces a rule-based stand-in model, a throw-away memory database and a fresh in-memory Redis per test. The real `config.toml` and `memory.sqlite` are never touched.
- Web search is faked per test, so nothing depends on the network.
- The stand-in model copies redacted text, placeholders included, into the retrieval query. A real model would clean it. Tests assert on redaction and caching, not on retrieval luck, in those cases.
- None of these tests judge answer quality from a real model. Only the optional `live/` tests use one, and they check invariants, not wording.
