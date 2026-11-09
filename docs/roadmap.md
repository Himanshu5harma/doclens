# Build and learning roadmap

Build one complete useful feature per stage. Explain behavior/data flow, existing code, libraries/tradeoffs and acceptance checks before coding; show actual results and teach the important paths afterward. Stop at the boundary until the user requests the next stage. Separate adapter and experiment units must not become one large implementation dump.

## Current expanded service stages

The 2026-11-02 user-authorized handoff expands DocLens into a version-aware, permission-aware engineering support and incident knowledge assistant. It supersedes the earlier Markdown-before-workspace proposal. The baseline milestones below are historical references; completed baseline work does not mark the expanded service complete. Detailed decisions, library/version gates, the public/synthetic demo corpus, and acceptance matrix are in [the expanded plan](expanded-rag-plan.md).

The 2026-11-03 refinement keeps the stage order and Stage 1 boundary: serve real public questions and demonstrate engineering behavior, with optional visibly labeled synthetic scenarios. The initial Python file-processing audience/collection is recommended, not a user-selected domain pivot. [Five public questions](expanded-rag-plan.md#public-questions-and-required-evidence) and [first-visit/usefulness criteria](expanded-rag-plan.md#first-visit-journey-and-success-criteria) are proposed, not measured successes. Shared published public collections are allowed; private/admin endpoints remain authenticated. Formats follow valuable evidence, so PDF is conditional.

- [x] **Stage 0 — Reconcile the plan.** Inspect the repository, record purpose/users, sources/questions, current versus planned behavior, library responsibilities, migration/preservation strategy, mentoring boundaries, and concrete Stage 1 checks. Documentation only; no app scaffolding/dependency installation. Verified results belong in [progress](progress.md).
- [x] **Stage 1 — Authenticated workspace/source ownership.** Implemented on 2026-11-03: optional FastAPI/Pydantic API, PostgreSQL/SQLAlchemy/psycopg/Alembic, Keycloak access-token verification, membership roles, source registration/list/read. Actual endpoint/DB allow/deny tests use a non-owner restricted runtime role; real Keycloak-issued service-account tokens and JWKS were exercised. Combined suite: 191 tests; schema/model consistency check passes. No RLS, browser sign-in, anonymous reader or ingestion claim. See the [implementation/verification guide](stage1-workspaces.md).
- [x] **Stage 2 — One recoverable ingestion workflow.** Implemented/locally verified 2026-11-04, review fixes verified 2026-11-05: authenticated jobs/dispatch intent, Redis/Celery prefork worker, immutable artifacts and fenced ready publication. The earlier actual public-page sync remains preserved. Duplicate/lost delivery, bounded attempts, rollback and interruption preserve consistent records/previous ready content. Post-review suite: 255 tests, including unlocked slow dispatch, worker exit status and UTF-8 URL boundaries/legacy reads. See [commands, evidence and limits](stage2-ingestion.md); no expanded retrieval or production-readiness claim.
- [x] **Stage 3 — Selected source/format units.** Repository/Python-code unit verified 2026-11-05; curated historical issue-JSON unit verified 2026-11-09. The service now normalizes HTML, one pinned CPython class and one reviewed local issue export through the same scoped jobs/artifacts. Final issue unit: 344 full/277 offline tests, real API/DB/IdP/worker checks, exact summaries/locations/hashes and failed-refresh preservation. [Repository guide](stage3-repository.md), [issue guide/evidence/limits](stage3-issues.md). The issue contains attributed curator summaries about 3.8, not a live tracker feed or 3.13 guarantees. Collection keys are metadata, not public grants. Markdown has no selected valuable source; PDF/page citations, OCR/multimodal and further connectors remain explicitly deferred, not implemented.
- [ ] **Stage 4 — Scoped persistent retrieval.** Existing local embedding contract plus PostgreSQL/pgvector exact authorized search. Done when access/product/version filters precede ranking, repeated indexing is safe, revision/provenance is inspectable, real queries work and queries do not mutate content/indexes. Preserve SQLite measurements; ANN is not assumed.
- [ ] **Stage 5 — Grounded answer API.** Direct authorized retrieval → budgeted evidence → SDK transport → validation → trusted citations, with explicit public-reader grants/limits alongside authenticated workspace routes. Done after offline contracts plus bounded new-dev live generation, with correctness, support, citation quality, partial/missing evidence, abstention and failures reviewed separately. Public examples execute the actual pipeline; synthetic collections stay separate by default. Keep free-routing/price/privacy constraints and old reports; no LangGraph extension yet.
- [ ] **Stage 6 — Document/permission lifecycle.** Content/configuration-aware incremental detection, safe revision publication, stale-chunk retirement, confirmed deletions/revocations and failed-sync reconciliation. Done when unchanged/changed/deleted/denied/interrupted outcomes are tested. Confirmed revocation blocks retrieval independently of reprocessing; failed listing/download is not deletion.
- [ ] **Stage 7 — Retrieval experiments.** Separate units for lexical versus dense, fusion, and then justified reranking. Done per experiment with one changed variable, versioned frozen dev inputs, full configurations/outputs, successes/regressions and scoped latency/resource/cost observations. PostgreSQL full-text ranking is not BM25. Held-out stays reserved.
- [ ] **Stage 8 — Operate and verify/public delivery.** Complete safe tracing/metrics, health/readiness, CI/static checks, reproducible containers, migrations, backup/restore and bounded load/failure/recovery checks. A separate minimal visitor-view unit after the grounded API supports the planned public journey. Done with actual deployment/recovery evidence, an actual visitor walkthrough and honest limits; usefulness/semantic outcomes are distinct from backend checks. No invented numeric targets. Basic logs/tests/settings/migrations begin earlier.
- [ ] **Stage 9 — Useful LangGraph investigation.** After expanded direct RAG works and is evaluated, add approved single-version/comparison/evidence-gathering routes, typed state, separately authorized evidence, strict call/retry limits and traces. Done with explicit route/orchestration evaluation separate from answer quality; no autonomous production actions.

Current boundary: **stop after Stage 3's curated issue-export unit**. The two selected adapter units meet their stated ingestion contract; additional formats remain conditional. The next requested stage is Stage 4: design compatible service chunks/locations and scoped persistent retrieval over ready revisions, preserving the frozen baseline. Do not start embeddings/vector indexing, answers, public reader or graph behavior automatically. Use explicit service schemas and separate artifacts/evaluations. Production readiness requires verified security, deployment and operational recovery evidence beyond these local checks.

Review prerequisite resolved, 2026-11-05: the user authorized fixes for dispatch-batch lock contention, worker-startup exit-status loss and multibyte-URL/index-limit mismatch. The three primary regressions first failed on the old code; the corrected code and added interruption/concurrency/compatibility checks passed. [The checkpoint](progress.md#stage-12-review-fixes-2026-11-05) records 255 full/196 offline tests and preserved review reports. A subsequent next-stage request authorized only the first Stage 3 adapter, now completed separately.

## Historical baseline milestones

The milestones below retain the original implementation record and unresolved quality work. They are not the current service-stage order. The last recorded full offline run passed 136 tests; earlier live baseline generation works with limited development evidence, while v2 live improvement and independent review remain pending.

## Milestone 0: Project setup

- [x] Define the product and planned demo.
- [x] Create the Python package scaffold.
- [x] Record architecture and evaluation goals.
- [x] Confirm that the development environment runs locally.

## Milestone 1: Select and ingest a corpus

- [x] Select one product and two documented releases: Python 3.12 and 3.13.
- [x] Start with 10 to 20 useful pages per release, including reference material and release notes (10 per release: nine references and What’s New).
- [x] Record URLs, version labels, document type, source terms, and intended local paths in a manifest (20 sources).
- [x] Fetch only the curated URLs; save raw files and provenance (all 20 pages verified).
- [x] Extract headings, paragraphs, and code blocks while removing navigation noise (Python/Sphinx parser; all 20 pages).
- [x] Inspect several parsed pages manually against the originals (eight samples across both versions; see [corpus review](corpus.md)).

Done when: one repeatable command creates inspectable documents with correct version and source metadata.

Completed for the selected scope on 2026-10-25: `uv run python -m doclens ingest`. Verification results and remaining parser limits are recorded in [the corpus review](corpus.md).

Explain: What information would disappear if we converted every HTML page to plain text without structure?

## Milestone 2: Retrieval baseline

- [x] Define typed document, section, block, and chunk records.
- [x] Define typed search-result records alongside retrieval.
- [x] Implement chunking with stable identifiers and preserved source anchors (section-anchor-v1 baseline; see [chunking guide](chunking.md)).
- [x] Choose a semantic embedding model and record its identifier and configuration (pinned ModernBERT baseline; see [retrieval guide](retrieval.md)).
- [x] Build a persistent index with repeatable ingestion (SQLite replacement; two actual builds verified).
- [x] Implement an inspectable search command with explicit version filtering.
- [x] Show the retrieved passages, ranks, source links, and version labels.

Done when: a question returns relevant passages from the requested release and re-ingestion does not duplicate chunks.

Completed for the selected scope on 2026-10-27: local embeddings for all 1,474 chunks, repeatable index replacement, and version-filtered search. Smoke examples establish working behavior, not evaluation scores.

Explain: How do chunk boundaries, embedding choice, and top-k change what the answer generator sees?

## Milestone 3: Measure the baseline

- [x] Write a small source-checked question set with relevant passages (24 dev, eight held-out; provisional assistant-authored labels).
- [x] Include exact terminology, paraphrases, multiple-source questions, version distinctions, and missing evidence.
- [x] Separate development questions from held-out questions before tuning (held-out retrieval has not been run).
- [x] Report retrieval metrics with definitions and saved run configuration (see [development baseline](../evals/baseline-dev.md)).
- [x] Review and record failures before changing the retriever (including a labeled miss and a candidate annotation gap).
- [ ] Obtain independent human label review and version any annotation corrections before relying on quality claims.

Done when: a reproducible report shows what the baseline retrieves correctly and where it fails. See [evaluation design](../evals/README.md).

The runner and provisional development report are implemented on 2026-10-27. Independent annotation review remains open; held-out and answer-quality scores are not claimed.

Explain: Could an answer generator recover from a retrieval result that contains none of the required evidence?

## Milestone 4: Generate supported answers

- [x] Select an LLM provider and keep credentials in local environment variables (explicit OpenRouter :free model; key setup documented).
- [x] Build an inspectable prompt from retrieved evidence (real four-case dev prompts checked).
- [x] Implement source-linked citations, partial answers, and explicit insufficient-evidence output (offline contracts plus live answered/insufficient cases; live partial remains unexercised).
- [x] Check citation identifiers and requested versions (including malformed/truncated response rejection).
- [x] Verify live end-to-end generation using the configured free model (four saved dev outputs, 2026-10-29).
- [x] Review answer correctness, claim support, citation quality, and abstention separately on the bounded dev sample (assistant review with explicit caveats).
- [x] Add explicit qualification instructions and paragraph/list/code citation-placement checks (v2 policy, verified offline).
- [ ] Verify the v2 model behavior with preserved before/after outputs; expand semantic quality validation and obtain independent review.

Done when: an answer can be inspected against its evidence, and unsupported questions are included in evaluation.

The working direct baseline RAG is complete for this implementation scope as of 2026-10-29. The [live development review](../evals/generation-dev-review.md) records four structurally valid generations, two supported-question answers, two appropriate abstentions, and zero reported model cost. It also records incomplete `copy2` preservation caveats and weak citation placement. Broader quality validation, held-out assessment, and independent human review remain open. A single-release LangGraph wrapper was subsequently added without changing that answer behavior.

Explain: Why can an answer have correctly formatted citations and still be unsupported?

## Proposed RAG expansion

Historical proposal, superseded by the user-authorized Stage 0 handoff later on 2026-11-02. The earlier recommendation put website/local Markdown adapters before workspace partitioning. The current service plan instead begins with authenticated workspace/source ownership, then recoverable ingestion and separate adapter units. The acquisition/format/document-purpose distinction and preservation rules still apply. See [current stages](#current-expanded-service-stages).

## Milestone 5: Improve retrieval through experiments

- [ ] Add a lexical baseline and compare it with dense retrieval.
- [ ] Evaluate hybrid retrieval with a documented fusion method.
- [ ] Evaluate reranking as a separate change.
- [ ] Compare quality, latency, and cost using the same corpus and question splits.
- [ ] Keep improvements supported by results and document regressions.

Done when: a report isolates the effect of each change and includes concrete successes and failures.

## Milestone 6: Add LangGraph and version comparison

The [first LangGraph unit](langgraph-first-step.md) is implemented as of 2026-11-01: a single-release graph with typed state, existing prepare/generate/validate functions, an inspection branch, terminal errors, and local node traces. Direct execution remains the default. Verified by offline contracts/replay and actual prompt-only graph execution; no new live generation or quality improvement is claimed. Retrieval experiments above remain unimplemented.

- [x] Define workflow state and nodes using the existing components.
- [x] Add inspect/answer routing and local node traces with offline direct/graph parity checks.
- [ ] Route questions into a single-release or comparison path.
- [ ] Retrieve evidence separately for each release in a comparison.
- [ ] Add a bounded query-rewrite path and inspectable traces.
- [ ] Evaluate evidence sufficiency and the effect of retrying.

Done when: the graph handles each path predictably and produces traceable results without unbounded loops.

## Milestone 7: Present the demo and results

- [ ] Add a small interface with visible citations and version selection.
- [ ] Document setup, corpus scope, architecture, and a reproducible evaluation command.
- [ ] Publish measured results, configurations, and a failure analysis.
- [ ] Record a short demo covering lookup, version comparison, and missing evidence.
- [ ] Describe limitations and remaining work honestly.
