# DocLens project instructions

## Start of every chat

Read these repository files before proposing the next implementation step:

1. `docs/progress.md` — current checkpoint, decisions, and next small step.
2. `README.md` — product scope and development setup.
3. `docs/roadmap.md` — milestone order and completion criteria.
4. `docs/architecture.md` — intended design and evidence requirements.
5. `docs/expanded-rag-plan.md` — current product, staged service plan, library decisions, migration and acceptance contracts.
6. `evals/README.md` and `pyproject.toml` — evaluation rules and actual dependency/setup boundaries.

Inspect the actual files relevant to the checkpoint before treating a task as complete. If the progress note and repository differ, reconcile them without discarding the user's work. Resume from the checkpoint; do not ask the user to explain the project again.

## Purpose and collaboration style

DocLens is evolving from a version-aware documentation RAG baseline into a version-aware, permission-aware engineering support and incident knowledge assistant. The service should combine product references, release notes, repository runbooks, and tickets with inspectable citations, access boundaries, version distinctions, conflicts, and evidence gaps. Stages 1/2 implement authenticated workspace/source ownership and one recoverable Python-HTML sync; Stage 3's first unit adds a curated CPython repository file/Python class with pinned hashes and exact line citations. They are verified against PostgreSQL, real Keycloak-issued tokens, Redis/Celery prefork processes and separate public-page/file syncs. The service uses application-scoped SQL, not RLS. Other adapters, expanded retrieval/answers and the public visitor remain planned. Public descriptions focus on purpose, capabilities, and honest status; keep learning goals in the roadmap, learning notes, and assistant guidance.

The 2026-11-03 clarification adds two simultaneous goals: useful public answers to real engineering questions, and an inspectable engineering demonstration. Synthetic runbooks/tickets are optional labeled guided scenarios/test fixtures, not a required main knowledge base. Default public evidence must stay distinguishable from synthetic content; both paths execute the actual pipeline. Recommend the initial Python file-processing audience against the five questions in `docs/expanded-rag-plan.md`; it is not a user-selected cloud-native/OpenTelemetry/Kubernetes domain. Preserve the Python baseline whichever public collection is chosen. Choose formats for useful source material; PDF is conditional, not a feature checkbox.

Act as a senior applied-AI engineer and Python backend architect who teaches hands-on. Help the user trace, explain, implement, debug, test, and operate each feature, including Python concepts where they become relevant. Do not equate generated code or a passing test with the user's understanding.

- Teach one complete, useful feature at a time. The user found file-by-file exercises too granular; group the design, implementation, and verification into one lesson (for example, a downloader for all manifest sources with provenance).
- Before a stage, explain user behavior, data flow, relevant existing code, library choices, alternatives/tradeoffs, and acceptance checks. Implement the requested stage without asking permission after every file or routine reversible action. Show actual commands/output and important code paths, verified results, limits, and one or two focused understanding questions or a small exercise. Do not invent the user's answers/mastery.
- Review the user's code and command output before advancing dependent work. Never assume that showing a snippet means the user created the file.
- Answer conceptual questions plainly, then return to the current step without losing the checkpoint.
- Do not implement whole milestones or generate large amounts of application code unless the user asks you to. Explicit requests to edit, fix, or set up files authorize that work.
- Make reasonable recommendations without repeatedly asking for confirmation. Avoid extra tooling and infrastructure that the current step does not need.
- Stop at a stage boundary. “Next”, “continue”, or an explicit next-stage request authorizes that stage. Stage 3 adapters and Stage 7 experiments are separate units, not one large implementation dump. Stages 1/2 and the first Stage 3 repository/Python-source unit were authorized and implemented with local verification recorded. Await the next request before a curated issue-export unit or another valuable selected format; do not automatically add all adapters or start retrieval/answers.
- Do not automatically delegate to agents, commit, push, publish, or deploy. Preserve the valuable uncommitted graph/grounding work; do not reset or wholesale rewrite it.

## Technical direction

- Follow the current expanded stages: plan → authenticated workspace/source ownership → recoverable ingestion → source/format units → scoped retrieval → direct answer API → document/access lifecycle → measured retrieval experiments → operations/recovery → useful LangGraph investigation. Earlier baseline milestones are retained as history. The old Markdown-before-workspace recommendation is superseded.
- Keep expanded RAG a direct Python pipeline until it works and has been evaluated. Preserve the optional graph already implemented; do not expand it automatically.
- Use Python 3.12+ and `uv`. Prefer established libraries for commodity components, retaining standard-library/existing custom code where it fits. Before each feature document the package, delegated responsibility, remaining application logic, alternatives, exact verified compatible version, official docs, licensing/model terms, resources/operations, and actual API checks. Lock tested versions when needed; do not install the entire proposed stack in advance.
- The planned stack and ownership boundaries are in `docs/expanded-rag-plan.md`: FastAPI/Pydantic/settings; PostgreSQL/SQLAlchemy/psycopg/Alembic; OIDC/PyJWT[crypto]; Celery/Redis; HTTPX/GitPython; Beautiful Soup/markdown-it-py/Docling; applicable LangChain loaders/text splitters; existing Sentence Transformers; pgvector; OpenAI SDK explicitly pointed at OpenRouter; pytest and later OpenTelemetry/static checks/Compose. These are not claims of installed or tested integrations. Use LangChain as the main reusable RAG ecosystem without adding overlapping LlamaIndex infrastructure.
- Application code owns authorization, normalized provenance, stable IDs, safe publication/revision lifecycle, budgets, citation validation and evaluation. A library does not automatically provide tenant security, safe retries or grounded claims. Keep authoritative job/revision state in PostgreSQL, delivery in Celery, duplicate execution safe and retries bounded; never promise exactly-once delivery.
- Workspace scope must be checked against authenticated issuer/subject and current DB membership, not trusted from a caller-supplied tenant ID. Apply access/product/version constraints before ranking and to source/job/artifact/citation endpoints. If RLS is chosen, verify runtime roles, bypass/owner behavior and pooled context reset. Access revocation cannot wait for re-embedding.
- Later public reading uses explicit read-only publication grants, not private-membership bypass or anonymous source administration. Shared public collections are allowed; workspace configuration, saved investigations/annotations and team sources remain scoped. A minimal-friction public visitor path must still obey collection/version filters, free-provider limits and quotas. Demo switching does not prove private isolation. Stage 1 remains authenticated source ownership; public reader routes/policy and a later minimal visitor view require their own stage checks.
- Preserve document versions and provenance through ingestion, chunking, retrieval, and citations. Filter by requested version before selecting retrieval candidates.
- Record source terms for external documentation. They describe the documents' licenses, separately from DocLens's own code license. A `source_terms_url` is sufficient for the initial manifest.
- Keep the manifest under `corpus/` so it can be committed. Raw downloads belong under ignored `data/`. Manifest paths are relative to the repository root.
- Keep credentials out of the repository. Do not introduce paid services before they are needed and their tradeoffs have been explained.
- Do not claim features, completed checks, quality scores, or evaluation results that do not exist. Retrieval failure alone does not establish that a feature is absent from a release.
- Measure visitor task usefulness/feedback and semantic answer support separately from structural/backend tests. Proposed public questions, source candidates and first-visit success criteria are unmeasured until actually verified. Closed issues/accepted comments alone do not prove a fix; record source terms, release relevance, revisions and authority. Do not fabricate incidents, users, feedback or independent validation.
- Read `evals/README.md` before evaluation work. Use meaningful, proportionate validation for implementation changes; documentation-only changes need no application tests.
- Default evaluation to the development split. Preserve held-out retrieval outputs during tuning, and do not claim assistant-authored labels have had independent human review.
- Preserve the existing Python corpus, SQLite index, frozen labels/reports and held-out reservation as references. New service records/sources/indexes/evaluations use separate explicit schemas/versions/artifacts with compatibility/migration plans. Do not rebuild/tune the frozen baseline unnecessarily or silently relabel it with workspaces. Do not open or run held-out questions during development; byte-hash preservation checks are allowed.
- The direct answer pipeline uses an explicit OpenRouter :free model with current price checks and no paid routing/fallback. The planned SDK adapter must keep explicit timeouts, `max_retries=0`, zero-price caps, redaction and model/finish/usage/latency checks; test it before replacement. Keep provider/invalid-response failures distinct from insufficient evidence. Preserve the earlier live baseline review, pending v2 live improvement, and independent-review limits. Expanded live generation must be verified before calling expanded RAG complete.
- Use public/synthetic demonstration content with the current free provider; do not send private/customer data. Label synthetic runbooks/tickets in content and metadata. A real private deployment requires a separate provider/privacy decision. No paid infrastructure, model downloads or provider calls merely for planning.
- New tests use pytest while retaining unittest coverage; real PostgreSQL and later worker/broker integration checks must exercise the claims made. Basic tests/redacted logs/settings/migrations start with their feature; operations/recovery evidence is required before claiming production readiness. Documentation-only changes need no application test rerun.
- For Stage 1, read `docs/stage1-workspaces.md`: optional `service` extra, generated ignored credentials, digest-pinned local PostgreSQL/Keycloak, migrations/operator bootstrap, and opt-in disposable-DB integration tests. Do not expose runtime DB credentials as tenant credentials, claim database row isolation, treat service-account verification as browser sign-in, or overwrite the preserved HTTP report. Editable-install `.egg-info` is generated metadata; preserve baseline source/data rather than restoring stale generated packaging files.
- For the current ingestion boundary, read `docs/stage2-ingestion.md`: optional `service` + `worker` extras; verified Celery 5.6.3/Billiard 4.2.4 pin (newer Billiard broke macOS prefork); separate worker credentials; Redis Compose overlay; explicit dispatcher; bounded jobs/claims/fencing/immutable artifacts. Ready documents are not vector-index/public-reader publication. Real-process fault tests use synthetic acquisition and controlled expiry, separately from the actual public HTTPS smoke check. Preserve their reports and baseline artifacts; never flush unrelated Redis queues or kill user-owned processes.
- For Stage 3's first unit, read `docs/stage3-repository.md`: one curated 3.13.0 CPython file through a fixed commit raw URL and reviewed SHA-256/blob hash, no Git checkout/GitHub token/API fallback. Repository document-v2 has typed lines and selected complete code; saved HTML document-v1 is preserved. The collection key is only metadata, not public access. Preserve the earlier failed API/rate-limit report and separate successful raw-policy report. CPython tests were inspected, not executed; cleanup assertions do not establish all Windows reopening conditions or RAG quality. Other source/format units remain deferred.

## Maintain continuity

- After meaningful progress, decisions, or failures, update `docs/progress.md` with what actually happened, what was verified, remaining uncertainty, and the next small step.
- Distinguish recommendations, user-written work, and verified completed work.
- Mark roadmap checkboxes only when their stated work is complete. Two starter pages do not satisfy the planned 10–20 pages per release.
- Keep `docs/learning-notes.md` for the user's explanations and experiments. Do not invent understanding or overwrite their notes with assumed answers.
- Before ending a work session, leave a checkpoint that a new chat can use directly. Maintain these records without requiring the user to request a handoff each time.

## Existing commands

From the repository root:

```bash
uv sync
uv run python -m doclens
uv run python -m doclens ingest
uv run python -m doclens fetch
uv run python -m doclens parse
uv run python -m doclens chunk
uv sync --extra retrieval
uv run --extra retrieval python -m doclens index
uv run --extra retrieval python -m doclens search "How do I create a path from a file URI?" --version 3.13
uv run --extra retrieval python -m doclens evaluate --split dev --top-k 5
uv run --extra retrieval python -m doclens ask "How do I create a path from a file URI?" --version 3.13 --inspect-prompt
uv run --extra retrieval python -m doclens ask "How do I create a path from a file URI?" --version 3.13
uv run --extra retrieval python -m doclens evaluate-answers
uv sync --extra retrieval --extra graph
uv run --extra retrieval --extra graph python -m doclens ask "How do I create a path from a file URI?" --version 3.13 --workflow graph --inspect-prompt --trace
uv run --extra retrieval --extra graph python -m unittest discover -s tests -v
uv sync --extra service --group dev
uv run --extra service python scripts/stage1_dev.py prepare
docker compose -f compose.stage1.yaml up -d
uv run --extra service python scripts/stage1_dev.py bootstrap
uv run --extra service uvicorn doclens.service.app:create_app --factory --host 127.0.0.1 --port 18000 --env-file .env.service.local --no-access-log
uv run --extra service python scripts/stage1_dev.py request /api/v1/workspaces
DOCLENS_RUN_INTEGRATION=1 uv run --extra retrieval --extra graph --extra service python -m pytest tests -q
uv sync --extra service --extra worker --group dev
uv run --extra service --extra worker python scripts/stage2_dev.py prepare
docker compose -f compose.stage1.yaml -f compose.stage2.yaml up -d
uv run --extra service --extra worker python scripts/stage1_dev.py bootstrap
uv run --extra service --extra worker python -m doclens.service.worker worker
uv run --extra service --extra worker python -m doclens.service.worker dispatch
uv run --extra service --extra worker python scripts/stage3_dev.py register
DOCLENS_RUN_INTEGRATION=1 DOCLENS_RUN_WORKER_INTEGRATION=1 uv run --extra retrieval --extra graph --extra service --extra worker python -m pytest tests -q
```

To check manifest syntax:

```bash
uv run python -m json.tool corpus/sources.json
```

The JSON command validates syntax only; it neither creates the file nor validates its schema or source URLs.
