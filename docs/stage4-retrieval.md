# Stage 4 — scoped persistent retrieval (PostgreSQL + pgvector)

Status, 2026-11-15: **implemented and verified locally** on PostgreSQL 18.7 / pgvector 0.8.7 with real Keycloak tokens: `alembic check` clean, 8 real-DB + 16 offline Stage 4 tests passing, and a dev comparison with identical rankings to SQLite on a re-fetched snapshot ([results](../evals/stage4-pgvector-dev.md)).

## User behavior

A workspace member asks `POST /api/v1/workspaces/{workspace_id}/search` with a question, a **required** product and version, optional `document_types`, and `top_k` (1–20). The service returns ranked passages from that workspace's *currently published* source revisions only, each with its source/revision IDs, heading path, trusted citation URL, typed location (page anchor, repository line range, issue/comment) and exact text. Viewers can search; non-members get 404, missing tokens 401. Requests never write content or vectors.

## Data flow

```
ready revision (Stage 2/3)          indexer (worker role, explicit command)               API (app role)
source_publications ──► parsed artifact ──► service_document() ──► chunk_document() ──► token preflight
                        (hash-verified)     v1/v2/v3 → typed records  section-anchor-v1     (refuse, never truncate)
                                                                                 │
                                                       LocalEncoder (pinned model) ▼
                                     ONE transaction: revision_indexes marker + all retrieval_chunks rows
search: membership(issuer,subject) ∧ workspace ∧ current publication ∧ product ∧ version ∧ index_id
        ─► ORDER BY embedding <=> query  (exact cosine)  ─► LIMIT k, count(*) OVER () = candidates
```

## Design decisions and tradeoffs

| Decision | Why | Alternatives / limits |
| --- | --- | --- |
| Reuse `section-anchor-v1` chunker and `nomic-ai/modernbert-embed-base` pinned config | Stage 4 changes the **store and the authorization boundary**, not the retriever. Any ranking difference vs SQLite is then attributable to storage/float precision, not a new model | Chunking/model experiments are Stage 7 units |
| Explicit service-document adapter (`retrieval_index.service_document`) | Converts HTML v1 / repository v2 / issue v3 into typed records without reinterpreting baseline schema 1. Checks the artifact against its DB revision (revision/source/workspace IDs, raw hash, product/version/URL) and per-block hashes. Source identity is the service source UUID | v2 keeps the whole class as one (oversized) chunk; v3 keeps 3.8 and unknown comment dates |
| `index_id` = digest of model config + prefixes + chunk policy + schema | A model/prefix/policy change creates a separate, non-mixing index; search filters by it | Old index rows stay until Stage 6 lifecycle cleanup |
| `revision_indexes` marker + chunks in one transaction, `ON CONFLICT DO NOTHING` on the marker | Idempotent and safe under duplicate/concurrent indexers: one complete set or none | CPU encoding happens before the transaction (no locks held while embedding) |
| Search joins `source_publications` | Only the current revision is searchable; a newly published but not yet indexed revision makes the source temporarily return nothing rather than a mixture | Automatic index-on-publish is Stage 6; today the indexer is an explicit command like the dispatcher |
| Membership `EXISTS` inside the ranking statement (plus the HTTP dependency) | Authorization, filters, candidate count and ranking happen in one statement/snapshot; revocation needs no re-embedding | Application-scoped SQL, still no RLS |
| **Exact** search, no HNSW/IVFFlat | ~1.5k chunks per release; exact scan is cheap and has no filtered-recall loss. pgvector ANN indexes apply filters *after* the approximate scan, which can return fewer than k rows | Revisit only after measuring filtered recall/latency at larger scale |
| `vector(768)` column | Explicit, checkable schema | A different model dimension needs a migration |
| Extension installed by the trusted operator (`CREATE EXTENSION vector` needs superuser) | Owner/app/worker roles keep no extension privileges; migration 0005 only verifies it | Managed Postgres must enable pgvector per provider docs |
| Grants: app SELECT; worker SELECT+INSERT; nobody UPDATE/DELETE | Vectors are immutable once written | Deletion/retirement is Stage 6 |
| Query encoding in the API (`def` route → threadpool, one lock around the CPU model) | Simple local deployment; model loads from cache only (`offline=True`) and 503s if missing | A separate embedding service is a later operations decision |

## Packages and images

- `pgvector` (pgvector-python) **0.4.2**, MIT, added to the `service` extra (SQLAlchemy `Vector` type, `cosine_distance`). `uv.lock` adds only this package; numpy 2.5.4 was already locked via the retrieval extra.
- Image `pgvector/pgvector:0.8.7-pg18-bookworm@sha256:38681dc6eaf55308e2a4c6de392d131652dcfac70e1263e35cd9b5ea3fe39782` (pgvector 0.8.7, PostgreSQL License) replaces `postgres:18.6-alpine` in `compose.stage1.yaml`. The tag was published 2026-11-12; it runs PostgreSQL 18.7. **An existing alpine-created volume should be recreated** (musl → glibc collation change can invalidate text indexes).
- The API now needs the `retrieval` extra too (query encoding).

## Code map

- `migrations/versions/0005_retrieval_index.py` — verifies extension, creates `revision_indexes`, `retrieval_chunks`, scope index, grants.
- `src/doclens/service/models.py` — `RevisionIndex`, `RetrievalChunk`.
- `src/doclens/service/retrieval_index.py` — `RetrievalConfig`, `service_document`, `prepare_revision`, `index_revision`, `pending_revisions`, `search_scope`.
- `src/doclens/service/indexer.py` — `python -m doclens.service.indexer` (worker credentials).
- `src/doclens/service/retrieval_api.py` — the search route.
- `scripts/stage4_eval.py` — disposable-DB dev evaluation vs SQLite (see below).
- `scripts/stage1_dev.py` — provisioning now also runs `CREATE EXTENSION IF NOT EXISTS vector`.

## Commands

```bash
uv sync --extra service --extra worker --extra retrieval --group dev
docker compose -f compose.stage1.yaml -f compose.stage2.yaml up -d
uv run --extra service --extra worker python scripts/stage1_dev.py bootstrap
uv run --extra retrieval --extra service python -m doclens.service.indexer --env-file .env.worker.local
uv run --extra retrieval --extra service uvicorn doclens.service.app:create_app --factory --host 127.0.0.1 --port 18000 --env-file .env.service.local --no-access-log
DOCLENS_RUN_INTEGRATION=1 uv run --extra retrieval --extra graph --extra service python -m pytest tests -q
uv run --extra retrieval --extra service python scripts/stage4_eval.py
```

The first indexer run needs the pinned model files in `data/models` (596 MB). Use `--allow-download` once, deliberately.

## Evaluation plan (dev split only)

`scripts/stage4_eval.py` creates a disposable database, registers the 20 manifest pages in a synthetic evaluator workspace, runs the **real job code** with a local-file fetcher (same raw bytes as the SQLite build), indexes them with the real model, then:

1. **Chunk parity** — each service chunk must equal the baseline chunker's chunk for that page (ordinal + text hash) and exist in the SQLite index; otherwise it aborts.
2. **Metrics** — runs the unchanged scorer over `evals/dev.json` through scoped pgvector search and through SQLite, writing both reports and a per-call ranking comparison (`same_order`, `same_set`, max score difference).

Held-out is never opened, nothing is tuned, and `evals/` is never written. If the local raw pages differ from the frozen hashes (a re-fetched corpus), `--derive-refetched-dataset` writes a labeled copy under `outputs/` that changes only the hashes; quotes are still verified against the new snapshot, and results must be reported as a re-fetched snapshot, not as the frozen baseline. Results go in [the Stage 4 results note](../evals/stage4-pgvector-dev.md).

## Tests

- Offline (`tests/service/test_retrieval_index.py`, 16 cases, passing): index identity, v1/v2/v3 adapters and typed locations, 3.8 issue not relabeled, unit vectors/deterministic IDs, six tamper/mismatch refusals before any encoding, token-limit refusal without truncation, encoder/config mismatch, SQL shape (all scope filters in `WHERE`, ranking in `ORDER BY`, publication join), request validation (no scope override, required version, bounded `top_k`), endpoint identity/scope pass-through and 503 on a missing model.
- Opt-in real Postgres (`tests/service/test_retrieval_db.py`, 8 cases, passing 2026-11-15): migration/extension/grants, idempotent indexing, exact ordering vs brute-force cosine, non-member 404/401, identical content in another workspace never leaks, revocation inside the ranking statement, revision replacement without mixing, concurrent indexers commit one set. They use the synthetic `HashingEncoder`, not the real model.

## Limits

No RLS; no automatic indexing on publish; no cleanup of superseded chunk sets; no lexical/hybrid/reranking (Stage 7); no answer generation (Stage 5); query encoding serialized per API process; exact scan cost grows linearly with a workspace's rows for one product/version.
