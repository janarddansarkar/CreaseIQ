# CreaseIQ --- Project Specification

**Product:** CreaseIQ\
**Tagline:** Understand the situation. Find the rule. Get the answer.\
**Descriptor:** Cricket Rules Intelligence Assistant\
**Document version:** 1.0\
**Status:** Product and architecture specification --- implementation
not yet started

------------------------------------------------------------------------

## 1. Product Overview

CreaseIQ is a multilingual cricket-rules intelligence assistant. It
helps umpires, players, coaches, match officials, and cricket fans
understand how official cricket rules apply to a described match
situation.

A user describes an incident in natural language. CreaseIQ identifies
the relevant match format and context, asks for missing facts when
necessary, retrieves applicable provisions from official cricket
documents, and explains the likely rule application with traceable
citations.

CreaseIQ is a **decision-support and rules-reference tool**. It does not
replace the on-field umpire, the match referee, a competition authority,
or the official decision-making process.

### 1.1 Core user promise

> Describe what happened. CreaseIQ finds the relevant rule, explains how
> it applies, and shows where the rule comes from.

### 1.2 Product principles

1.  **Ground every rules answer in authoritative sources.**
2.  **Clarify before concluding** when a missing fact could change the
    answer.
3.  **Answer directly first**, then provide a concise explanation and
    citations.
4.  **Respect format and competition context.** MCC Laws and ICC Playing
    Conditions may both apply.
5.  **Preserve the user's language** wherever supported.
6.  **Never invent a law, clause, quotation, or citation.**
7.  **Distinguish the written rule from judgement-dependent
    application.**
8.  **Make uncertainty explicit.**
9.  **Keep the workflow inspectable and testable.**
10. **Keep all model calls, retrieval, and rule reasoning on the
    backend.**

------------------------------------------------------------------------

## 2. Problem Statement

Cricket rules are spread across long official documents. A user trying
to resolve a specific situation may need to identify the correct law,
locate the relevant clause, determine whether a format-specific playing
condition modifies or supplements it, and interpret the rule in the
context of the incident.

General-purpose chat assistants may produce lengthy answers, miss
format-specific conditions, or provide unsupported rule interpretations.
Static rule-search tools can help locate text but may not ask the right
follow-up questions or explain how a provision applies to a scenario.

CreaseIQ aims to make this process conversational, concise,
context-aware, multilingual, and evidence-backed.

------------------------------------------------------------------------

## 3. Goals and Non-Goals

### 3.1 Version 1 goals

-   Answer text-based questions about men's ODI and men's T20I cricket.
-   Support English, Hindi, Assamese, and Kannada.
-   Use official MCC Laws and applicable ICC Men's ODI/T20I Playing
    Conditions as the knowledge sources.
-   Retrieve relevant law and playing-condition sections.
-   Ask clarifying questions when the user's description is incomplete
    or ambiguous.
-   Explain the likely application of the rule to the facts supplied.
-   Return exact source references, including document
    version/effective-date context where available.
-   Compare ODI and T20I provisions when explicitly requested.
-   Maintain relevant context during a conversation.
-   Provide a concise default response, with more detailed explanation
    available on request.
-   Expose a stable backend API for a separately developed React
    frontend.

### 3.2 Explicit non-goals for Version 1

-   Men's Test cricket.
-   Women's cricket formats.
-   Domestic, league-specific, school, or junior competition rules
    unless explicitly added as a separately curated source set.
-   Voice input or spoken responses.
-   Image, video, or computer-vision analysis.
-   Ball tracking, automated umpiring, DRS decisions, or live match-feed
    integration.
-   Autonomous web browsing to decide which rule applies.
-   Autonomous changes to the official rules knowledge base.
-   Multi-agent architecture.
-   CrewAI, AutoGen, or another orchestration framework alongside
    LangGraph.
-   Kubernetes, Kafka, or distributed microservices.
-   Replacing official umpires or issuing binding decisions.

These may be considered in later versions only after the Version 1
system is reliable.

------------------------------------------------------------------------

## 4. Target Users and Use Cases

### 4.1 Target users

-   On-field and aspiring umpires.
-   Players.
-   Coaches and team support staff.
-   Cricket administrators and match officials.
-   Cricket enthusiasts who want to understand a decision.

### 4.2 Representative use cases

1.  A bowler asks whether a delivery is a no-ball after a particular
    movement.
2.  A batter asks whether they can be run out after leaving the crease
    in a described situation.
3.  An umpire asks what happens when a ball strikes a helmet placed on
    the field.
4.  A user asks whether a particular fielding restriction applies in an
    ODI or T20I.
5.  A user describes an incomplete incident and CreaseIQ asks what
    happened next.
6.  A user asks for the exact MCC Law or ICC Playing Condition
    supporting an answer.
7.  A user asks how a rule differs between ODI and T20I.
8.  A user asks in Hindi, Assamese, or Kannada and expects an answer in
    that language.

------------------------------------------------------------------------

## 5. Supported Scope and Source Authority

### 5.1 Supported formats

Version 1 supports:

-   Men's One Day Internationals (ODI).
-   Men's Twenty20 Internationals (T20I).

The system must not silently treat an unspecified match as an ODI or
T20I. It should ask for the format when that distinction could affect
the answer.

### 5.2 Canonical rule sources

The initial knowledge base should contain the applicable official
versions of:

1.  **MCC Laws of Cricket** --- the current official edition selected
    for the release.
2.  **ICC Men's ODI Playing Conditions** --- the applicable official
    edition.
3.  **ICC Men's T20I Playing Conditions** --- the applicable official
    edition.

Official source documents must be acquired from the relevant
rights-holder or official publication pages. Record the source URL and
acquisition date in the ingestion manifest.

### 5.3 Source precedence and interpretation

The system must not assume that one document always overrides another in
every context. It should retrieve the relevant MCC Law and the
applicable competition/format Playing Condition, then explain their
relationship based on the actual text and stated applicability.

If a competition has special playing conditions, the system needs that
competition context and a curated source document before claiming that
those conditions apply.

### 5.4 Version and applicability metadata

Every ingested source must record, where available:

-   `source_id`
-   `source_title`
-   `source_type` --- `mcc_laws`, `icc_odi_playing_conditions`, or
    `icc_t20i_playing_conditions`
-   `publisher`
-   `edition` or `version`
-   `effective_from`
-   `effective_to`, if known
-   `competition_scope`
-   `format`
-   `source_url`
-   `retrieved_at`
-   `document_checksum`
-   `language`
-   `ingestion_status`

Do not silently replace an older document. Preserve versions so the
system can answer a historical question when the user supplies a match
date and the relevant historical source is available.

### 5.5 Source limitations

If the user asks about a competition, season, or historical date for
which the correct playing conditions are not available, CreaseIQ must
say that it cannot verify the applicable competition-specific document.
It may explain the general MCC/ICC provision if useful, but must label
that explanation as general rather than competition-specific.

------------------------------------------------------------------------

## 6. Functional Requirements

### FR-01 --- Understand the question

The backend must interpret the user's natural-language description and
identify:

-   The main cricket event or rules topic.
-   The user's intent: rule lookup, scenario interpretation,
    clarification, comparison, or follow-up.
-   Relevant entities and facts in the scenario.
-   The user's language.
-   Any stated match format, competition, or date.
-   Missing information that could materially change the answer.

### FR-02 --- Identify format and context

The system must identify whether the user is asking about ODI or T20I.

If format, competition, or date is missing, ask for it only when it is
material to the answer. Do not burden the user with unnecessary
questions.

### FR-03 --- Detect missing facts and clarify

The system must identify facts required to apply the rule.

Examples of potentially material facts include:

-   Whether the ball was live or dead.
-   Whether the batter had grounded the bat or person behind the popping
    crease.
-   Whether a fielder had touched the ball.
-   Whether the ball had crossed a boundary.
-   The delivery type or stage of the delivery.
-   The relevant match format or competition.
-   The sequence and timing of events.

These are examples, not a fixed exhaustive checklist. Required facts
depend on the rule and scenario.

When a missing fact can change the outcome:

1.  Do not guess.
2.  Ask one focused clarification question at a time where practical.
3.  Preserve the facts already supplied.
4.  Resume the workflow after the user answers.
5.  Re-evaluate whether any other material fact is still missing.

### FR-04 --- Retrieve applicable rules

The system must retrieve relevant passages from the approved source
collection.

Retrieval should consider:

-   Semantic relevance to the scenario.
-   Exact law or clause references when identified.
-   Format.
-   Source type.
-   Edition/version.
-   Effective date.
-   Competition applicability.

The system should retrieve enough surrounding context to interpret the
provision correctly, not just an isolated sentence.

### FR-05 --- Analyse the scenario

The system must compare the user's supplied facts with the retrieved
provisions.

It must distinguish:

-   Facts explicitly supplied by the user.
-   Facts inferred with high confidence.
-   Facts that remain unknown.
-   The wording of the official rule.
-   The system's explanation of how the rule appears to apply.

The model must not turn an assumption into a fact.

### FR-06 --- Generate a concise answer

The default answer should:

1.  State the likely outcome or rule directly.
2.  Explain the key reason in plain language.
3.  Cite the applicable law/playing-condition clause.
4.  Mention any material assumption or uncertainty.
5.  Include a brief decision-support caveat where appropriate.

Long explanations should be reserved for requests such as "explain in
detail" or "show the full reasoning." Do not expose hidden
chain-of-thought. Provide a concise, evidence-based explanation instead.

### FR-07 --- Provide verifiable citations

Each substantive rules answer must cite the source document and exact
law/clause reference when available.

A citation should include:

-   Source title.
-   Edition/version or effective date where available.
-   Law/section/clause number.
-   Relevant subsection or paragraph when available.

The citation must map to a retrieved source chunk or its parent section.
The model must not fabricate a citation.

If retrieval cannot find adequate evidence, the system must say that it
could not verify the rule from the available sources.

### FR-08 --- Multilingual interaction

Version 1 supports:

-   English.
-   Hindi.
-   Assamese.
-   Kannada.

Requirements:

-   Detect the input language.
-   Preserve the user's language by default.
-   Allow a response-language preference when the frontend/API supplies
    one.
-   Keep official source wording and citation identifiers intact.
-   Translate explanations, not official law identifiers.
-   Do not claim that a translated paraphrase is an official translation
    unless an official translation source is included.
-   Test cricket-specific terms and common transliterations in every
    supported language.

### FR-09 --- Compare formats

When asked to compare ODI and T20I rules:

-   Retrieve the applicable provision from each format's source.
-   Compare only the relevant clauses.
-   Identify similarities and differences.
-   Cite both sources.
-   State if one format's document is missing or its version cannot be
    confirmed.

### FR-10 --- Conversation continuity

The backend must preserve the relevant conversation context so follow-up
questions such as "What if the fielder touched it first?" can be
understood in relation to the earlier scenario.

Conversation history must be scoped to a conversation/session
identifier. The backend must not mix separate users' conversations.

### FR-11 --- Safe handling of unsupported questions

If the question is outside the supported formats, source set, or
cricket-rules domain:

-   Explain the limitation.
-   Do not invent an answer.
-   If useful, suggest the closest supported question or ask for the
    missing context.

### FR-12 --- Error handling

The system must handle:

-   LLM/API timeouts.
-   Invalid or unavailable model responses.
-   Retrieval failures.
-   Empty retrieval results.
-   Malformed source metadata.
-   Invalid user input.
-   Unsupported language or format.
-   Citation-validation failures.

Errors returned to the frontend must be safe and user-friendly. Do not
expose API keys, stack traces, internal prompts, or sensitive
infrastructure details.

------------------------------------------------------------------------

## 7. Non-Functional Requirements

### 7.1 Accuracy and grounding

-   Rules answers must be grounded in approved sources.
-   Citation references must be traceable to source documents.
-   Missing facts must trigger clarification when material.
-   The system must abstain when evidence is insufficient.
-   Evaluation must include adversarial and ambiguous scenarios.

### 7.2 Reliability

-   External model calls must have sensible timeout and error handling.
-   Backend endpoints must return predictable response schemas.
-   A failed optional step must not silently produce a fabricated rules
    answer.
-   Logs should make failures diagnosable without storing unnecessary
    personal data.

### 7.3 Performance

-   Keep the graph and retrieval workflow simple in Version 1.
-   Measure end-to-end response time and individual node/tool latency.
-   Avoid unnecessary model calls.
-   Use retrieval filters to reduce irrelevant context.
-   Set performance targets after establishing a baseline with the
    selected Sarvam model and deployment environment.

### 7.4 Security and privacy

-   Store model credentials only in backend environment variables or a
    secrets manager.
-   Never expose Sarvam credentials to the React application.
-   Validate and constrain user input.
-   Apply request-size limits and sensible rate limiting.
-   Avoid logging secrets or unnecessary personal information.
-   Use HTTPS in production.
-   Keep CORS restricted to the deployed frontend origin.
-   Do not execute arbitrary code or tools based on model-generated
    text.

### 7.5 Maintainability

-   Keep ingestion, retrieval, graph orchestration, API routes, prompts,
    and model configuration in separate modules.
-   Keep graph nodes small and testable.
-   Use typed state and typed API schemas.
-   Keep source documents and ingestion manifests versioned.
-   Avoid unnecessary abstractions and frameworks.

------------------------------------------------------------------------

## 8. Technology Stack

  -----------------------------------------------------------------------
  Layer                   Technology              Responsibility
  ----------------------- ----------------------- -----------------------
  LLM                     Sarvam AI               Language understanding
                                                  and response generation

  LLM integration         `langchain-openai`      Connect to Sarvam's
                          adapter, if             OpenAI-compatible
                          compatibility tests     endpoint
                          pass                    

  Orchestration           LangGraph custom        Explicit backend
                          `StateGraph`            workflow and
                                                  conditional routing

  Backend API             FastAPI                 HTTP API and request
                                                  validation

  Vector database         ChromaDB                Rule passage embeddings
                                                  and metadata

  Embeddings              To be selected and      Embed source passages
                          validated               and user queries

  Document extraction     PyMuPDF or equivalent   Extract text and
                                                  structure from official
                                                  PDFs

  Frontend                React                   User interface;
                                                  implemented separately

  Testing                 Pytest                  Unit, integration,
                                                  graph, retrieval, and
                                                  API tests

  Deployment              Docker on VPS           Package and run the
                                                  application

  Reverse proxy           Existing Traefik or     HTTPS and routing
                          Nginx                   
  -----------------------------------------------------------------------

### 8.1 Model integration notes

The intended initial model provider is Sarvam AI.

Potential configuration, subject to a live compatibility test:

-   Model: `sarvam-105b` (verify current availability before
    implementation).
-   Base URL: `https://api.sarvam.ai/v2`.
-   Chat endpoint: `/chat/completions` under the configured base URL,
    according to the current Sarvam API documentation.
-   Authentication: backend-only API subscription key / bearer
    authentication as required by the current API documentation.

An OpenAI-compatible LangChain adapter may be used if the selected
Sarvam endpoint supports the required request and response formats.

**Do not assume tool calling works just because basic chat completion
works.** Test separately:

1.  Basic text completion.
2.  Structured output or JSON-mode behavior, if needed.
3.  Tool/function calling.
4.  Multi-turn tool-call messages.
5.  Hindi, Assamese, and Kannada output quality.
6.  Timeout and error behavior.

If a capability is unsupported or inconsistent, adapt the integration
explicitly rather than silently relying on unsupported behavior.

------------------------------------------------------------------------

## 9. Backend Architecture

### 9.1 Architecture ownership

The backend workflow is owned and controlled by the project developer.

A coding agent may implement the frontend, but must not independently
change the backend's agent architecture, rule interpretation, retrieval
behavior, or API contract.

### 9.2 High-level request flow

``` text
React frontend
     |
     | POST /api/v1/chat
     v
FastAPI backend
     |
     v
LangGraph StateGraph
     |
     +--> Understand question
     |
     +--> Check context and missing facts
     |        |
     |        +--> Ask clarification --> wait for user reply
     |        |
     |        +--> Continue
     |
     +--> Retrieve applicable rules from ChromaDB
     |
     +--> Analyse scenario against retrieved evidence
     |
     +--> Validate evidence and citations
     |
     +--> Generate final concise answer
     |
     v
Structured API response
     |
     v
React frontend
```

This is the logical flow. The exact graph topology can evolve during
implementation, but changes must preserve the product requirements and
remain explicit.

### 9.3 Why custom StateGraph

The production workflow should use a custom LangGraph `StateGraph`
because CreaseIQ requires explicit control over:

-   Context and format checks.
-   Conditional clarification loops.
-   Retrieval steps.
-   Scenario analysis.
-   Citation validation.
-   Unsupported-question handling.
-   Error and retry paths.
-   Conversation state.

A prebuilt `create_agent` can be used as a small learning exercise or
embedded in a graph for a narrowly scoped tool-calling task. It should
not replace the explicit production workflow by default.

Use LangGraph only for orchestration. Do not introduce CrewAI, AutoGen,
or a separate multi-agent framework.

------------------------------------------------------------------------

## 10. LangGraph Workflow Specification

### 10.1 Proposed nodes

  -----------------------------------------------------------------------
  Node                                Responsibility
  ----------------------------------- -----------------------------------
  `understand_question`               Identify intent, language, format,
                                      topic, and supplied facts

  `check_context`                     Determine whether required context
                                      is sufficient

  `ask_clarification`                 Formulate one focused question when
                                      material information is missing

  `retrieve_rules`                    Retrieve relevant MCC/ICC source
                                      passages

  `analyse_scenario`                  Compare scenario facts with
                                      retrieved rules

  `validate_answer`                   Check evidence sufficiency,
                                      citations, scope, and unsupported
                                      claims

  `generate_answer`                   Produce concise user-facing answer

  `handle_unsupported`                Explain unsupported scope or
                                      insufficient evidence

  `handle_error`                      Convert recoverable workflow
                                      failures into safe responses
  -----------------------------------------------------------------------

The node names are proposed identifiers, not mandatory public API names.

### 10.2 Conditional routing

The graph must support decisions such as:

-   Is the request within the supported domain?
-   Is the format known or necessary?
-   Are material facts missing?
-   Did retrieval return usable evidence?
-   Is the evidence sufficient to answer?
-   Did citation validation pass?
-   Should the graph ask a clarification question, retry a controlled
    step, abstain, or generate an answer?

Example logical routing:

``` text
START
  |
  v
understand_question
  |
  v
check_context
  |
  +-- unsupported --> handle_unsupported --> END
  |
  +-- missing facts --> ask_clarification --> END
  |
  +-- enough context --> retrieve_rules
                           |
                           v
                      analyse_scenario
                           |
                           v
                      validate_answer
                           |
              +------------+-------------+
              |                          |
          evidence valid             insufficient
              |                          |
              v                          v
        generate_answer          handle_unsupported
              |                          |
              v                          v
             END                        END
```

A clarification response is a normal conversational turn. On the next
user message, the backend should restore the conversation state/history
and re-run the relevant understanding and context checks.

### 10.3 Tool calling

Tool calling may be used where the model needs to select a specific
retrieval operation. Keep tools narrow, deterministic, and read-only.

Candidate tools:

#### `search_cricket_rules`

Purpose: Search the approved knowledge base for relevant law and
playing-condition passages.

Input fields (conceptual):

-   `query`: search description.
-   `format`: `odi`, `t20i`, or an explicitly supported comparison mode.
-   Optional `competition`: competition identifier/name, if known.
-   Optional `match_date`: ISO date, if known.
-   Optional `source_type`: source restriction, if useful.
-   Optional `top_k`: bounded result count.

Output:

-   Matching passage text.
-   Source and version metadata.
-   Law/section/clause identifiers.
-   Retrieval scores or ranking metadata for internal use.

#### `get_mcc_law`

Purpose: Retrieve a specific MCC Law and its relevant surrounding text.

Input:

-   `law_number`.

Output:

-   Exact law text or approved excerpt.
-   Section metadata.
-   Source/version details.

#### `get_playing_condition`

Purpose: Retrieve a specific or topic-relevant playing condition for a
supported format.

Input:

-   `format`.
-   `topic` or `clause_number`.
-   Optional competition/date context.

Output:

-   Relevant condition text.
-   Clause metadata.
-   Source/version details.

#### `compare_format_rules`

Purpose: Retrieve corresponding provisions for ODI and T20I to support a
comparison.

Input:

-   `topic`.
-   `formats`, limited to supported formats.

Output:

-   Separate evidence sets for each format.
-   Source/version details for each.

Tools should not make final rulings. They return source evidence; the
graph controls the workflow and answer validation.

### 10.4 State schema

The graph state should be typed. The following is a conceptual field
inventory; refine types and required/optional status during
implementation.

  -----------------------------------------------------------------------
  Field                               Purpose
  ----------------------------------- -----------------------------------
  `messages`                          Conversation messages

  `question`                          Current user question

  `intent`                            Rule lookup, scenario
                                      interpretation, comparison,
                                      follow-up, etc.

  `input_language`                    Detected input language

  `response_language`                 Language to use in the answer

  `format`                            ODI, T20I, unknown

  `competition`                       Competition context, if supplied

  `match_date`                        Match date, if supplied

  `scenario_facts`                    Facts explicitly provided by the
                                      user

  `missing_information`               Material facts still required

  `clarification_question`            Question to return to the user

  `retrieved_rules`                   Retrieved source passages and
                                      metadata

  `analysis_summary`                  Concise evidence-based analysis
                                      data

  `answer`                            Draft/final answer

  `citations`                         Source references attached to
                                      claims

  `validation_status`                 Evidence/citation validation result

  `unsupported_reason`                Why the request cannot be answered
                                      reliably

  `error`                             Safe error information
  -----------------------------------------------------------------------

Do not store unnecessary duplicate state. Keep state limited to what
nodes need.

### 10.5 Checkpointing and persistence

Conversation continuity requires a persistence strategy.

-   Use an in-memory checkpointer only for local experiments.
-   Select a durable checkpointer for production after the initial
    workflow is working.
-   Scope checkpoints by a stable conversation/thread identifier.
-   Do not assume in-memory state survives a process restart.
-   Do not mix state between users.
-   Define retention and deletion behavior before storing long-lived
    conversation data.

The production database/checkpointer choice is an implementation
decision to make before deployment; it is not automatically the same as
the ChromaDB vector store.

------------------------------------------------------------------------

## 11. RAG and Knowledge-Base Design

### 11.1 Ingestion pipeline

``` text
Official PDF/source
      |
      v
Document extraction
      |
      v
Structure and section detection
      |
      v
Cleaning and normalization
      |
      v
Section-aware chunking
      |
      v
Metadata attachment
      |
      v
Embedding generation
      |
      v
ChromaDB collection
      |
      v
Retrieval and citation mapping
```

### 11.2 Extraction

Use PyMuPDF or an equivalent PDF extraction tool.

Requirements:

-   Preserve law and clause numbering.
-   Preserve headings and subsection labels.
-   Remove repeated headers/footers where safe.
-   Preserve tables and structured lists as faithfully as possible.
-   Detect pages with poor text extraction.
-   Record page numbers.
-   Do not silently discard text that may change the meaning of a rule.
-   Inspect the original PDF when extraction is incomplete or garbled.

### 11.3 Chunking strategy

Use section-aware chunking rather than blindly splitting every fixed
number of characters.

Preferred approach:

1.  Identify document title and top-level sections.
2.  Identify individual Laws, Playing Conditions, clauses, and
    subclauses.
3.  Keep a complete short clause together.
4.  Split long sections at logical paragraph/subsection boundaries.
5.  Add limited overlap only where needed to preserve context.
6.  Retain parent section and clause identifiers for citation
    reconstruction.

Avoid chunks that combine unrelated laws or clauses.

### 11.4 Chunk metadata

Each chunk should carry metadata such as:

-   `chunk_id`
-   `source_id`
-   `source_title`
-   `source_type`
-   `publisher`
-   `edition`
-   `version`
-   `effective_from`
-   `effective_to`
-   `format`
-   `competition_scope`
-   `law_number`
-   `law_title`
-   `section_number`
-   `clause_number`
-   `subclause_number`
-   `page_start`
-   `page_end`
-   `language`
-   `document_checksum`

Use only metadata fields that can be reliably populated. Do not invent
values.

### 11.5 Retrieval behavior

Retrieval should:

-   Apply format filters when format is known.
-   Apply date/version filters when match date is known and the metadata
    supports them.
-   Include relevant MCC Law and ICC Playing Condition evidence where
    applicable.
-   Retrieve enough context for interpretation.
-   Prefer exact clause matches when available.
-   Avoid returning large amounts of irrelevant text.
-   Preserve source identifiers and clause metadata through every
    processing step.

Potential later enhancements include hybrid lexical/vector retrieval,
reranking, and query expansion. Do not add these before a basic
retrieval baseline has been evaluated.

### 11.6 Citation traceability

Every returned passage must retain its source identity and section
metadata. The answer generator should cite only retrieved evidence. A
citation validator should check that each cited law/clause exists in the
retrieved evidence or source index.

------------------------------------------------------------------------

## 12. Answer Format and UX Behavior

### 12.1 Default answer structure

Use a compact structure:

``` text
[Direct answer]

[One or two sentences explaining why.]

Rule reference: [Official source, Law/Clause number, version if available]

[Important assumption or caveat, only if needed.]
```

Do not force every response into a large template. Simple factual
lookups can be shorter.

### 12.2 Clarification response

A clarification response should:

-   Ask one focused question.
-   Explain briefly why the detail matters if that is not obvious.
-   Avoid repeating the entire scenario.
-   Avoid asking for facts already supplied.

### 12.3 Uncertainty response

When the evidence is incomplete or the scenario depends on umpire
judgement:

-   State what the source clearly says.
-   State which fact or judgement remains unresolved.
-   Avoid claiming certainty beyond the evidence.
-   Recommend referring to the on-field umpire or relevant match
    authority for an actual match decision.

### 12.4 Role and authority disclaimer

CreaseIQ provides informational decision support. It does not issue
official match decisions and must not represent its answer as binding.

------------------------------------------------------------------------

## 13. Backend API Specification

The API contract should be agreed before frontend integration. The
following is the initial proposal.

### 13.1 `POST /api/v1/chat`

Purpose: Submit a user message and receive an answer, clarification
request, or safe limitation response.

Example request:

``` json
{
  "conversation_id": "optional-client-generated-id",
  "message": "The ball hit the batter's helmet while it was on the ground. What happens?",
  "response_language": "en",
  "format": "t20i",
  "competition": null,
  "match_date": null
}
```

Example response:

``` json
{
  "conversation_id": "conversation-id",
  "status": "answered",
  "message": "The concise answer goes here.",
  "response_language": "en",
  "format": "t20i",
  "clarification_question": null,
  "citations": [
    {
      "source_title": "MCC Laws of Cricket",
      "edition": "configured edition",
      "law_number": "configured law number",
      "clause_number": null,
      "page": null
    }
  ],
  "limitations": [],
  "error": null
}
```

Possible `status` values:

-   `answered`
-   `clarification_required`
-   `unsupported`
-   `insufficient_evidence`
-   `error`

The exact response schema must be formalized with Pydantic models before
frontend integration. Do not allow arbitrary model-generated JSON to
become the API response without validation.

### 13.2 Supporting endpoints

Proposed endpoints:

-   `GET /api/v1/health` --- application health.
-   `GET /api/v1/languages` --- supported languages.
-   `GET /api/v1/formats` --- supported formats.
-   `GET /api/v1/sources` --- active source-set/version metadata, if
    appropriate for the UI.

Do not expose internal prompts, API credentials, raw stack traces, or
unrestricted database access.

### 13.3 API design requirements

-   Validate request fields.
-   Use consistent HTTP status codes.
-   Keep error payloads predictable.
-   Support conversation continuity.
-   Add request IDs for observability.
-   Set request size and timeout limits.
-   Document the API using FastAPI's OpenAPI output.
-   Keep frontend integration independent of internal graph node names.

------------------------------------------------------------------------

## 14. Frontend Specification for the Coding Agent

The React frontend is a separate workstream. The coding agent may own
the frontend implementation, while the backend architecture and agentic
workflow remain under the project developer's control.

### 14.1 Frontend responsibilities

-   Provide a clean chat interface.
-   Display user and assistant messages.
-   Display citations clearly.
-   Display clarification questions.
-   Allow the user to answer a clarification question.
-   Provide supported format selection where useful.
-   Provide response-language selection.
-   Show loading, timeout, empty, and error states.
-   Preserve the conversation identifier for follow-up messages.
-   Work on desktop and mobile screen sizes.
-   Call only the CreaseIQ FastAPI backend.

### 14.2 Frontend restrictions

The coding agent must not:

-   Call Sarvam AI directly from the browser.
-   Store or expose Sarvam API keys.
-   Connect directly to ChromaDB.
-   Implement independent cricket-rule reasoning.
-   invent or hardcode rule answers.
-   Change LangGraph architecture or node behavior.
-   Add another agent framework.
-   Change the API contract without agreement.
-   Add backend features or dependencies without approval.

### 14.3 Backend/frontend integration

The backend owns:

-   Language understanding.
-   Agent orchestration.
-   Tool calling.
-   Rule retrieval.
-   Scenario analysis.
-   Citation validation.
-   Final answer generation.

The frontend owns presentation and interaction. It should render the
backend's status and citations without independently interpreting them.

------------------------------------------------------------------------

## 15. Testing and Evaluation

### 15.1 Unit tests

Test:

-   Input parsing and validation.
-   Language and format normalization.
-   Individual graph nodes.
-   Conditional routing.
-   Clarification detection.
-   Retrieval filters.
-   Citation mapping and validation.
-   Error handling.
-   API request/response schemas.

### 15.2 Integration tests

Test:

-   Sarvam basic completion.
-   Sarvam tool calling.
-   Sarvam multi-turn tool-call behavior.
-   ChromaDB ingestion and retrieval.
-   Graph execution with mocked model responses.
-   Graph execution with the live model in controlled tests.
-   FastAPI endpoints.
-   Conversation checkpointing.

Use mocks for most automated tests so that test runs do not depend on
paid external API calls.

### 15.3 Scenario evaluation dataset

Build a curated test set containing:

-   Straightforward rule questions.
-   Scenarios requiring one clarification.
-   Scenarios requiring multiple facts.
-   ODI-specific questions.
-   T20I-specific questions.
-   Questions where MCC Law and ICC Playing Conditions both matter.
-   Historical/version-sensitive questions.
-   Ambiguous scenarios.
-   Out-of-scope questions.
-   Questions with misleading or false assumptions.
-   English, Hindi, Assamese, and Kannada examples.

Every expected answer should be reviewed against the selected official
source edition.

### 15.4 Evaluation metrics

Track at least:

-   Answer correctness.
-   Citation correctness.
-   Citation coverage.
-   Retrieval relevance.
-   Clarification precision --- whether clarification is requested when
    genuinely needed.
-   Clarification usefulness.
-   Unsupported-answer/abstention quality.
-   Format identification accuracy.
-   Language identification and response quality.
-   Hallucination rate.
-   End-to-end latency.
-   Model and retrieval error rate.

Do not optimize only for response speed or answer fluency. Rules
accuracy and evidence traceability take priority.

### 15.5 Release gate

Do not release a feature merely because the happy-path demo works. It
must pass:

-   Relevant unit and integration tests.
-   The curated rules evaluation set.
-   Citation validation tests.
-   Out-of-scope and ambiguity tests.
-   Multilingual smoke tests for every supported language.

------------------------------------------------------------------------

## 16. Security, Guardrails, and Failure Policies

1.  Treat user messages and retrieved document text as data, not
    executable instructions.
2.  Do not allow retrieved content to override system-level workflow
    constraints.
3.  Keep tools read-only in Version 1.
4.  Restrict tool arguments and result sizes.
5.  Validate all tool inputs and outputs.
6.  Do not expose internal prompts or secrets.
7.  Do not fabricate a source, law number, clause, quote, or edition.
8.  If no reliable evidence is retrieved, abstain.
9.  If the scenario is ambiguous, clarify.
10. If the question is outside scope, state the limitation.
11. If a model response fails schema or validation checks, retry only
    under a bounded policy or return a safe error.
12. Do not claim that CreaseIQ has made an official umpiring decision.

------------------------------------------------------------------------

## 17. Observability and Logging

Record enough information to debug and improve the application without
collecting unnecessary personal data.

Recommended operational fields:

-   Request ID.
-   Conversation ID (non-sensitive identifier).
-   Timestamp.
-   Graph node start/end times.
-   Model name and latency.
-   Retrieval latency and result count.
-   Selected source IDs and clause references.
-   Clarification/answer/unsupported status.
-   Error category.

Avoid logging API keys, authentication headers, or unnecessary raw
personal data. Define a retention policy before production use.

------------------------------------------------------------------------

## 18. Deployment Architecture

### 18.1 Initial deployment target

Deploy the backend and frontend using Docker on a VPS.

The project owner already has experience with a Hostinger VPS, Docker,
and Traefik. Existing infrastructure may be reused after checking
available ports, resource capacity, routing, and operational impact.

### 18.2 Production considerations

-   Separate frontend and backend containers where appropriate.
-   Keep secrets in server-side environment configuration.
-   Use persistent storage for ChromaDB data and the selected
    checkpointer.
-   Back up source manifests and vector-store data as appropriate.
-   Configure HTTPS through Traefik or Nginx.
-   Configure health checks and restart policies.
-   Pin dependency versions for reproducible builds.
-   Keep development and production environment variables separate.
-   Do not expose internal databases or admin interfaces publicly.
-   Test container restart and persistence behavior.

### 18.3 Deployment diagram

``` text
User browser
    |
    v
HTTPS reverse proxy (Traefik/Nginx)
    |
    +--------------------+
    |                    |
    v                    v
React frontend       FastAPI backend
                         |
                         v
                    LangGraph
                    /       \
                   v         v
              Sarvam AI   ChromaDB
                             |
                             v
                      Official rule data

LangGraph checkpoint storage:
A separately configured persistent store
```

------------------------------------------------------------------------

## 19. Project Milestones

Implementation should proceed incrementally. Do not build the entire
product in one pass.

### Milestone 0 --- Project setup and decisions

Deliverables:

-   Confirm official source editions and source manifest.
-   Confirm Sarvam model/API configuration.
-   Create repository structure.
-   Create Python environment and dependency file.
-   Add `.env.example` and `.gitignore`.
-   Establish formatting, linting, and test conventions.
-   Agree the first API contract draft.

Exit criteria:

-   Backend starts locally.
-   Secrets are not committed.
-   Basic project tests run.

### Milestone 1 --- LangGraph fundamentals and model connection

Purpose: Learn and validate the orchestration foundation using mock
cricket data.

Deliverables:

-   Verify Sarvam basic chat completion.
-   Verify tool calling independently.
-   Define typed graph state.
-   Build a small custom `StateGraph`.
-   Implement a basic understanding node.
-   Implement a context-check node.
-   Implement conditional routing.
-   Implement a mock cricket-rule retrieval tool.
-   Implement a clarification path.
-   Add graph tests with mocked model/tool responses.

Learning sequence:

1.  Create a tiny `create_agent` exercise with one mock cricket tool to
    understand the prebuilt tool-calling loop.
2.  Rebuild the same behavior using a custom `StateGraph`.
3.  Compare the control flow and state handling.
4.  Continue with the custom `StateGraph` for the production workflow.

Exit criteria:

-   The graph can route between answering, retrieving, and asking for
    clarification.
-   Tool calling works with the selected Sarvam integration or a
    documented fallback.
-   Tests prove the intended conditional paths.

### Milestone 2 --- Official rules knowledge base and RAG

Deliverables:

-   Acquire and version the selected official PDFs.
-   Extract document text and structure.
-   Build section-aware chunking.
-   Attach source and clause metadata.
-   Select and validate embeddings.
-   Create ChromaDB collections.
-   Implement ingestion scripts.
-   Implement filtered retrieval.
-   Preserve source references and page/section metadata.
-   Create retrieval evaluation cases.

Exit criteria:

-   A query retrieves the expected official section for a curated set of
    test questions.
-   Each result can be traced back to its source document and clause.

### Milestone 3 --- Scenario intelligence and answer validation

Deliverables:

-   Improve scenario fact extraction.
-   Implement material-missing-fact detection.
-   Add clarification loops.
-   Implement scenario-to-rule analysis.
-   Add citation validation.
-   Add unsupported and insufficient-evidence paths.
-   Add adversarial and ambiguity tests.

Exit criteria:

-   The system asks for missing material facts instead of guessing.
-   Unsupported claims and fabricated citations are caught by tests.

### Milestone 4 --- Multilingual support

Deliverables:

-   Language detection and response-language control.
-   Hindi, Assamese, and Kannada prompt/evaluation examples.
-   Cricket terminology glossary where useful.
-   Multilingual retrieval/query tests.
-   Citation preservation in translated answers.

Exit criteria:

-   Each supported language passes a reviewed smoke-test set.
-   Official source references remain unchanged and traceable.

### Milestone 5 --- FastAPI and React integration

Deliverables:

-   Finalize Pydantic request/response models.
-   Implement `/api/v1/chat`.
-   Implement health and metadata endpoints.
-   Add conversation ID/checkpoint behavior.
-   Implement CORS and safe errors.
-   Provide API documentation.
-   Coding agent implements the React frontend against the agreed API.
-   Integrate frontend and backend.

Exit criteria:

-   A user can complete a question, clarification, and follow-up cycle
    through the UI.
-   Citations and status messages render correctly.
-   Frontend does not call Sarvam or ChromaDB directly.

### Milestone 6 --- Docker and VPS deployment

Deliverables:

-   Dockerfiles and compose configuration.
-   Persistent volumes.
-   Environment configuration.
-   Reverse-proxy routing and HTTPS.
-   Health checks and restart policies.
-   Logging and basic monitoring.
-   Backup and restore procedure.
-   Production smoke tests.

Exit criteria:

-   The deployed application survives container restart.
-   Secrets are not exposed.
-   End-to-end production smoke tests pass.

### Future milestone --- Voice

Voice is explicitly deferred until text-based behavior is reliable. It
may include speech-to-text, spoken responses, and language-specific
voice UX. It must reuse the same backend rules workflow rather than
creating a separate rules engine.

------------------------------------------------------------------------

## 20. Repository Structure Proposal

This is a starting structure, not a requirement to create every file
immediately.

``` text
creaseiq/
├── backend/
│   ├── app/
│   │   ├── main.py
│   │   ├── api/
│   │   │   ├── routes/
│   │   │   └── schemas/
│   │   ├── core/
│   │   │   ├── config.py
│   │   │   └── logging.py
│   │   ├── graph/
│   │   │   ├── state.py
│   │   │   ├── builder.py
│   │   │   ├── nodes/
│   │   │   └── routing.py
│   │   ├── llm/
│   │   │   └── sarvam.py
│   │   ├── tools/
│   │   ├── retrieval/
│   │   │   ├── vector_store.py
│   │   │   ├── retriever.py
│   │   │   └── citations.py
│   │   ├── ingestion/
│   │   │   ├── extract.py
│   │   │   ├── chunk.py
│   │   │   └── ingest.py
│   │   ├── prompts/
│   │   └── services/
│   ├── data/
│   │   ├── source_documents/
│   │   └── manifests/
│   ├── tests/
│   │   ├── unit/
│   │   ├── integration/
│   │   └── evaluation/
│   ├── .env.example
│   ├── .gitignore
│   ├── requirements.txt
│   └── README.md
├── frontend/
│   └── (React application owned by the frontend coding agent)
├── docker-compose.yml
├── .gitignore
└── specification.md
```

Keep original official source PDFs in a controlled data directory or
separately managed storage. Do not commit copyrighted source files to a
public repository unless the applicable licence permits it.

------------------------------------------------------------------------

## 21. Ownership and Collaboration

  -----------------------------------------------------------------------
  Area                    Owner                   Boundary
  ----------------------- ----------------------- -----------------------
  Product requirements    Project developer       Defines supported
                                                  behavior and scope

  Backend architecture    Project developer       Owns graph, state,
                                                  nodes, routing, and
                                                  tools

  LangGraph workflow      Project developer       Full control over
                                                  orchestration

  Sarvam integration      Project developer       Owns model
                                                  configuration and
                                                  tool-call validation

  RAG and ChromaDB        Project developer       Owns ingestion,
                                                  retrieval, metadata,
                                                  and citations

  Rule interpretation and Project developer       Owns prompts, evidence
  guardrails                                      requirements, and
                                                  validation

  React frontend          Coding agent            Implements UI against
                                                  agreed API

  API contract            Shared, approved by     Frontend must not
                          project developer       change it unilaterally

  Integration and         Shared                  Backend and frontend
  deployment                                      are integrated and
                                                  deployed together
  -----------------------------------------------------------------------

### 21.1 Instructions for the frontend coding agent

The coding agent may:

-   Build React pages and components.
-   Implement responsive layouts.
-   Implement chat message rendering.
-   Implement loading, error, and clarification states.
-   Display source citations returned by the backend.
-   Call the documented FastAPI endpoints.
-   Improve frontend accessibility and usability.

The coding agent must not:

-   Call Sarvam AI from the browser.
-   Access ChromaDB directly.
-   store backend secrets in frontend code.
-   Implement its own cricket-rules reasoning.
-   Modify the LangGraph workflow.
-   Add CrewAI, AutoGen, or another orchestration framework.
-   Change API fields or semantics without approval.
-   Present a frontend-generated answer as an official rules result.

------------------------------------------------------------------------

## 22. Definition of Done for Version 1

CreaseIQ Version 1 is ready for release when:

-   [ ] ODI and T20I are supported within the defined source scope.
-   [ ] The selected official source editions and applicability metadata
    are recorded.
-   [ ] English, Hindi, Assamese, and Kannada are supported to the
    agreed quality level.
-   [ ] The custom LangGraph StateGraph handles the complete
    question-to-answer workflow.
-   [ ] Clarification works for material missing facts.
-   [ ] Retrieval returns relevant official rule passages.
-   [ ] Every substantive answer has traceable citations or explicitly
    abstains.
-   [ ] Citation validation and unsupported-question paths are tested.
-   [ ] Conversation continuity works without cross-user state leakage.
-   [ ] FastAPI request and response schemas are validated.
-   [ ] React frontend is integrated using the backend API only.
-   [ ] Automated tests and curated evaluation cases pass the release
    gate.
-   [ ] Secrets are protected and production HTTPS is configured.
-   [ ] Docker deployment, persistence, restart, and backup behavior are
    tested.
-   [ ] The product clearly states that it is decision support, not an
    official umpire.

------------------------------------------------------------------------

## 23. Architectural Decisions and Principles

1.  **Custom LangGraph StateGraph is the production orchestration
    choice.**
2.  `create_agent` is permitted as a small learning exercise or a
    contained subcomponent, not as a reason to surrender control of the
    overall workflow.
3.  LangGraph is the only orchestration framework in Version 1.
4.  Sarvam AI is the intended LLM provider, subject to API and
    tool-calling verification.
5.  ChromaDB is the Version 1 vector store.
6.  Official English documents are the canonical rules sources;
    generated multilingual explanations do not change source authority.
7.  Backend owns all AI and retrieval logic.
8.  Frontend is a client of the backend, not a second agent.
9.  Retrieval evidence and citations must remain traceable end-to-end.
10. Build the smallest testable slice first; add complexity only when
    evaluation demonstrates a need.

------------------------------------------------------------------------

## 24. Open Decisions to Resolve During Implementation

These are intentionally not guessed in this specification:

-   Exact official document editions and effective dates for the initial
    release.
-   Whether competition-specific playing conditions are included in the
    first source set or only generic ICC format documents.
-   Embedding model and hosting strategy.
-   ChromaDB persistence and backup strategy.
-   Production LangGraph checkpointer/database.
-   Exact Sarvam model identifier and tool-calling compatibility.
-   Exact retrieval configuration (`top_k`, similarity thresholds,
    hybrid retrieval, reranking).
-   Final API schema and streaming/non-streaming behavior.
-   Authentication and user-account requirements, if any.
-   Data retention and deletion policy.
-   Performance targets after baseline measurement.

Resolve these decisions explicitly and update this document when the
architecture or scope changes.

------------------------------------------------------------------------

## 25. Change Log

  -----------------------------------------------------------------------
  Version                 Date                    Change
  ----------------------- ----------------------- -----------------------
  1.0                     2026-11-02              Initial consolidated
                                                  product, architecture,
                                                  workflow, RAG, API,
                                                  testing, and deployment
                                                  specification

  -----------------------------------------------------------------------

**End of specification.**
