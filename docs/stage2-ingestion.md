# Stage 2: recoverable source ingestion

Implemented and locally verified on 2026-11-04; reviewed fixes verified on 2026-11-05 (Asia/Kolkata). An authenticated owner/editor can sync a registered source, inspect its durable job, and download a verified raw/normalized pair. This unit supports official Python 3.12/3.13 HTML pages only. It reuses the existing Python/Sphinx parser and leaves the baseline corpus, chunks, SQLite index, evaluations, answer client and optional graph in place. It adds no new source format, embeddings, search, answer endpoint or public reader.

## What the user does, and why a job exists

Registration describes a source; **sync** acquires a snapshot. The API commits a job plus dispatch intent and returns `202` without downloading or contacting Redis. The caller can poll the job even while workers are stopped. A request key is an idempotency key: repeating it for the same workspace/source returns that same job, including after completion. A new key requests another snapshot. Reusing the key for another source or starting a second active sync for a source returns `409`.

```mermaid
sequenceDiagram
    participant C as Authenticated client
    participant A as API
    participant P as PostgreSQL
    participant D as Dispatcher
    participant R as Redis/Celery
    participant W as Worker process
    participant F as Local artifact store
    C->>A: POST source/sync with request_key
    A->>P: Current membership, then job + dispatch intent in one transaction
    A-->>C: 202 + durable job ID
    D->>P: Recover expired claims; reserve deliveries and commit
    D->>R: Send job ID
    R->>W: Deliver job ID (delivery can repeat)
    D->>P: Record send result in a separate short transaction
    W->>P: Lock job, recheck permission, create timed claim
    W->>W: Fetch allowed versioned Python HTML
    W->>F: Save immutable raw bytes, then normalized JSON
    W->>P: Recheck claim/permission; commit revision + ready pointer + success
    C->>A: Read job/revision/artifact
    A->>P: Current membership and scoped lookup
    A->>F: Check size/hash before serving artifact
    A-->>C: Authorized result or readable error
```

The **dispatcher** is a small PostgreSQL outbox relay/recovery loop, run as a separate operator process. Celery owns task transport/execution; Redis is its broker. PostgreSQL owns progress, attempts, permission and the ready revision. No Redis result backend is used. `FastAPI.BackgroundTasks` alone would couple execution to the API process; adding `async def` would not move blocking parsing into another process. RabbitMQ or another queue library could also work, but the planned Celery/Redis pair supplies the commodity delivery machinery without another overlapping workflow framework.

## State, transactions and identities

Migration [0002_ingestion](../migrations/versions/0002_ingestion.py) adds four tables to the existing `doclens_service` schema:

| Record | Responsibility |
| --- | --- |
| `ingestion_jobs` | Source/workspace/requester, unique workspace/request key, status/stage, attempt count, due time, timed claim and safe error |
| `dispatch_intents` | One durable intent per job; next relay/reservation time, monotonic delivery count and safe broker error; count also fences late publisher results |
| `source_revisions` | Immutable successful snapshot metadata, source configuration, parser policy, final URL/time, sizes/hashes, artifact keys and structure counts |
| `source_publications` | One current **ready-document pointer** per source; this is not a public-reader grant or a vector-index publication |

Composite foreign keys bind jobs/revisions/pointers to the same source/workspace. A partial unique index permits only one active job per source. Source registration IDs stay unchanged. A revision ID is UUIDv5 over the job UUID and a named service namespace; retrying that job cannot create a second logical revision. A new sync has a new revision even if the bytes are unchanged. Content hashes identify the actual bytes; unchanged-content reuse/configuration-aware incremental processing belongs to Stage 6. No baseline document/chunk ID is reinterpreted.

Processing states are `queued → running → succeeded`, with transient failures entering `retry_wait`, and terminal failures entering `failed`. Running stages expose `fetching`, `parsing` and `publishing`; completion is `complete`. The API reports the latest processing error/stage/attempt plus delivery count/limit, safe broker error and earliest next dispatch/recovery time. It does not provide a complete historical event log or percentage estimate.

There are five important transaction boundaries:

1. **Accept:** job and dispatch intent commit together. A failed intent insert rolls back the job too.
2. **Reserve delivery:** a short row-lock transaction reconciles due work, increments the delivery count and commits a 30-second reservation **before** broker I/O.
3. **Record delivery result:** after sending, another short transaction records the result only if the delivery count still matches. This can run before or after a worker progresses; a worker's retry schedule is preserved.
4. **Claim:** a row lock checks current state/permission and increments the processing attempt once. An unexpired running claim or terminal job makes duplicate delivery a no-op.
5. **Publish ready content:** after both files are saved and verified, a row lock checks the current unexpired claim token and current requester role. Revision insertion, ready-pointer replacement and success commit together. Failure rolls the transaction back and retains the previous ready pointer.

No database transaction encloses broker I/O or the download/parser. This fixes the reviewed batch-lock problem: earlier publishes retained every job lock until all sends ended, and workers could hit their five-second DB lock timeout. The processing claim token is a fencing token: after recovery gives the job a different token, the old execution cannot advance progress, publish or overwrite replacement state. Separately, the monotonically increasing delivery count prevents an old publisher from clearing a newer broker failure. Both use persisted state already in migration 0002; no new schema or dependency was needed. [SQLAlchemy transaction scope](https://docs.sqlalchemy.org/en/21/orm/session_transaction.html).

## Retry, dispatch and interruption behavior

| Bound | Current policy |
| --- | --- |
| Processing attempts | At most 3 total, including a claimed attempt lost to worker termination |
| Transient retry delay | 5 seconds after attempt 1, 10 after attempt 2; the dispatcher reads the due time |
| Dispatch attempts | At most 20 committed delivery reservations per job, including interruption before send; delivery count is not processing count |
| Queued replay | Eligible unclaimed work can be relayed again after its 30-second reservation expires, including a dispatcher crash before/after send |
| Broker error | Fixed safe error code, next relay in 5 seconds; API acceptance remains durable |
| Worker limits | One prefork slot, prefetch 1, soft limit 60 s, hard limit 75 s; default claim 120 s |
| Dispatcher tick | Reserve at most 10 jobs with `SKIP LOCKED`, commit/release locks, then send; loop ticks every 2 s |

HTTP interruptions/timeouts, 429 and 5xx are retryable. Unsupported destinations, rejected non-success responses, wrong content/size and unsupported parser layouts are terminal. Unexpected failures become a fixed safe `internal_error` with the same three-attempt cap. Celery automatic task/publish retries are disabled. Late acknowledgements are enabled, but lost-worker recovery depends on PostgreSQL reconciliation rather than an exactly-once promise or an unbounded broker rejection loop. The Redis visibility timeout is 120 s. [Celery task semantics](https://docs.celeryq.dev/en/v5.6.3/userguide/tasks.html), [Redis transport behavior](https://docs.celeryq.dev/en/v5.6.3/getting-started/backends-and-brokers/redis.html), [worker time limits](https://docs.celeryq.dev/en/v5.6.3/userguide/workers.html#time-limits).

Keep both the worker and dispatcher running for progress/recovery. Starting only a worker does not discover DB jobs. A committed reservation consumes one delivery attempt even if the dispatcher crashes before sending; it remains replayable after expiry within the finite cap. A crash after sending but before recording the result can produce a duplicate. A crash after writing raw data can leave an unreferenced file; only a committed revision is exposed by the API. Local files and PostgreSQL are not one distributed transaction. Reads fail closed on missing/corrupt artifacts. Orphan cleanup, storage quotas/backup/restore and host/power-loss durability verification remain later work. Acquisition failure never means source deletion.

## Acquisition and artifact boundaries

Registration can describe other public HTTPS metadata, but this sync rejects sources outside the selected `https_html`/Python 3.12/3.13 adapter before queueing. Every request/redirect must retain HTTPS, `docs.python.org`, default TLS port, explicit requested version and an `.html` path, without credentials/query/fragment, path traversal or encoded path ambiguity. There are at most two redirects. DNS results must all be public; the transport connects to a checked IP while retaining `Host` and TLS `sni_hostname=docs.python.org`. Normal certificate verification remains enabled, proxy environment variables and transport retries are disabled. This narrow allowlist is deliberate; it is not a general URL-fetching service. [HTTPX transport APIs](https://www.python-httpx.org/advanced/transports/), [HTTPCore TLS-name extension](https://www.encode.io/httpcore/extensions/#sni_hostname).

HTTPX has explicit five-second connection/read/write/pool timeouts. A 30-second fetch deadline is checked before requests and between chunks, with the worker process limits bounding stalled DNS/parsing too. The fetch deadline is not a precise preemptive socket timer. Only nonempty successful HTML with identity content encoding is accepted; no compressed-body expansion occurs. Raw size is capped at 4 MiB, normalized JSON at 8 MiB; raw streaming stops at the cap. This is bounded acquisition, not a crawler.

The local `ArtifactStore` delegates file operations to the standard library. It creates a complete temporary file, fsyncs it, links it atomically into a hash-named path without overwriting existing content, and verifies size/SHA-256. The server constructs workspace/source/job/claim paths; callers supply no filesystem path. There is no cloud storage SDK or storage-engine implementation. API artifacts are attachments with `nosniff`/`no-store`; raw HTML is served as `application/octet-stream`, not executable inline HTML.

Normalized `doclens-service-document-v1` JSON retains source ID/workspace/product/version/purpose/URL/terms, revision ID, fetch time/final URL/raw hash, processing policy and parser information, plus title, heading paths, anchors, typed blocks and exact code whitespace. The `python-sphinx-service-v1` wrapper adapts [parse_html](../src/doclens/parse.py), retaining its parser contract rather than copying its extraction algorithm. This is still the observed Python/Sphinx layout: images, complex-table relationships and arbitrary HTML are not claimed.

## Access and process credentials

All sync/job/revision/artifact routes use Stage 1's verified identity and **current** DB workspace membership. Owner/editor may sync; any current workspace member may inspect. Job/source/revision IDs cannot override workspace scope. Workers recheck the requester's current owner/editor role before acquisition and before publication. Removed/downgraded membership can prevent queued work or ready publication; current membership independently guards subsequent artifact reads. Already-running network requests are not a revocation/cancellation service.

`doclens_app` gains SELECT on ingestion tables and INSERT on jobs/intents; it cannot claim jobs, create revisions or move ready pointers. The separate `doclens_worker` role can read required metadata and update jobs/intents, insert revisions, and insert/update ready pointers. It cannot edit source registrations, memberships, existing revisions or schema DDL. Migration/operator privileges remain separate. This remains **application-scoped SQL, not RLS**; service DB/broker credentials are trusted operator credentials, never tenant credentials. No browser/public-reader route or production isolation certification is added.

## Exact dependencies and local resources

The worker entry point now uses Celery's public `app.Worker(...).start()` lifecycle and propagates `worker.exitcode` through `SystemExit`. In the pinned 5.6.3 version, `worker_main()` discarded failed-startup status and the process exited 0. The new subprocess regression verifies a nonzero exit for unavailable-broker startup; actual broker/worker tests use the same lifecycle and verify clean shutdown returns 0. Signal handling, prefork and time limits remain library responsibilities. [Celery program worker](https://docs.celeryq.dev/en/stable/reference/celery.apps.worker.html).

The optional `worker` extra adds **Celery 5.6.3 and Billiard 4.2.4**. Its tested resolution includes Kombu 5.7.0 and redis-py 8.1.0; existing HTTPX 0.28.1/Beautiful Soup 4.15.0 and all earlier locked package versions remain unchanged. Use the `service` and `worker` extras together. PostgreSQL/Keycloak and their pinned images/volumes are reused. Redis **8.8.0 Alpine** is separately pinned by digest in [compose.stage2.yaml](../compose.stage2.yaml).

The first actual prefork run failed before task execution with Billiard 4.3.2's macOS `spawn` default and Celery 5.6.3's uninitialized fast-trace registry. Reproduced locally and checked against [the upstream issue](https://github.com/celery/celery/issues/10683); pinning [Billiard 4.2.4](https://pypi.org/project/billiard/4.2.4/) made the same real-process checks pass. No private Celery internals were patched. Revisit that pin only with another verified compatible release/process check; this is a compatibility fix, not an unrelated baseline downgrade. Database engines are created inside task execution rather than inherited active DB pools.

Installed metadata identifies BSD-3-Clause for Celery/Kombu, BSD for Billiard, and MIT for redis-py; Python client terms differ from Redis server terms. Redis 8 offers AGPLv3, RSALv2 and SSPLv1 options; this local demonstration uses the AGPLv3 option with the unmodified server. [Official license options](https://redis.io/legal/licenses/), [official Redis container](https://hub.docker.com/_/redis). Container/base-system notices still apply; this inventory is not a redistribution/legal audit. No paid infrastructure or model calls are needed. Local costs are CPU/RAM/disk: three dependency containers plus API/dispatcher/worker processes; Redis has AOF enabled, 128 MiB `noeviction`, and a separate volume. These are development settings, not capacity or disaster-recovery results.

## Run and inspect

From the repository root, with the local Docker engine running:

```bash
uv sync --extra service --extra worker --group dev
uv run --extra service --extra worker python scripts/stage2_dev.py prepare
docker compose -f compose.stage1.yaml -f compose.stage2.yaml up -d
uv run --extra service --extra worker python scripts/stage1_dev.py bootstrap
```

Preparation reuses existing DB/IdP credentials and adds separate random worker/broker credentials. Ignored `.env.worker.local` holds worker DSN/broker configuration. Ignored `data/service/dev/redis.conf` supplies the container password without putting it in the command, healthcheck or printed output; its host parent directory is private. Keep generated credentials with their existing volumes. Do not copy these development files into an image or Git. No credential or bearer token belongs in a report. Loopback HTTP/Keycloak development mode remains local-only.

Run each command in its own terminal from the repository root:

```bash
uv run --extra service --extra worker uvicorn doclens.service.app:create_app --factory --host 127.0.0.1 --port 18000 --env-file .env.service.local --no-access-log
uv run --extra service --extra worker python -m doclens.service.worker worker
uv run --extra service --extra worker python -m doclens.service.worker dispatch
```

List/register sources using the [Stage 1 commands](stage1-workspaces.md#run-and-inspect). A repeated example registration returns 409; reuse the listed source ID. For the existing local demonstration, the registered Python 3.13 pathlib source is `40d3785f-8a48-40df-b26e-99a9d2e7e196`. Fresh databases return a different source ID. Replace it with your actual registration ID:

```bash
doclens_workspace=843909a7-d634-5b3a-a119-c747ac16ff1c
doclens_source=40d3785f-8a48-40df-b26e-99a9d2e7e196
uv run --extra service --extra worker python scripts/stage2_dev.py request "/api/v1/workspaces/$doclens_workspace/sources/$doclens_source/sync" --sync
uv run --extra service --extra worker python scripts/stage2_dev.py request "/api/v1/workspaces/$doclens_workspace/sources/$doclens_source/jobs"
uv run --extra service --extra worker python scripts/stage2_dev.py request "/api/v1/workspaces/$doclens_workspace/sources/$doclens_source/revision" --identity atlas-viewer
```

`--sync` prints a record containing its request key. Repeat with `--request-key THAT_UUID` to get the same job without another acquisition. A new key deliberately requests a new snapshot. The job endpoint is `/api/v1/workspaces/{workspace_id}/jobs/{job_id}`. Revision output contains trusted `raw_artifact_url` and `parsed_artifact_url`; pass either to the request helper. Use `--output outputs/service/my-parsed-snapshot.json` to save an artifact, refusing to overwrite an existing file or write outside the separate service-output directory. `--identity atlas-viewer --sync` returns 403; `--identity boreal-owner` cannot inspect Atlas jobs/artifacts (404).

Actual public-source output from this unit:

```text
POST sync: 202, status=queued
dispatcher --once: {'sent': 1, 'broker_errors': 0, 'expired': 0, 'failed': 0}
GET job: 200, status=succeeded, stage=complete, attempts=1
GET current revision: 21 sections, 498 blocks, 80 code examples
raw_size=244770, parsed_size=168408
```

The saved normalized URI example retains:

```python
>>> p = Path.from_uri('file:///etc/hosts')
PosixPath('/etc/hosts')
```

Its location is `https://docs.python.org/3.13/library/pathlib.html#pathlib.Path.from_uri`. [The actual HTTP report](../outputs/service/stage2-http-20261104T081348805335Z.json) includes job/revision metadata, endpoint observations, hashes and the inspected example. All 80 code examples match the raw article, all anchors exist, and fresh parser output matches saved JSON. This one public page is a pipeline smoke check; it does not extend frozen parser/corpus evaluation or establish general answer accuracy. Source terms remain the separate Python documentation terms URL.

## Verification and remaining boundary

```bash
# Offline checks; real-service/worker cases are explicitly skipped
uv run --extra retrieval --extra graph --extra service --extra worker python -m pytest tests -q

# Real PostgreSQL, Keycloak, Redis and test-owned prefork workers
DOCLENS_RUN_INTEGRATION=1 DOCLENS_RUN_WORKER_INTEGRATION=1 uv run --extra retrieval --extra graph --extra service --extra worker python -m pytest tests -q

uv run --extra retrieval --extra graph python -m unittest discover -s tests -q
```

The post-review full run passed **255 tests**, plus 121 unittest subtests. The original unittest suite separately passed all **136**. [The current JUnit report](../outputs/service/stage12-fixes-full-20261105.xml) records that run; the earlier 243-test report and review outputs remain intact. Offline pytest passed **196**, skipping **59** opt-in cases. The three primary regressions were first run against the old code and all failed, as recorded in [the before-fix report](../outputs/service/stage12-fixes-regressions-before-20261105.xml). PostgreSQL tests use uniquely generated disposable DBs, not the persistent demonstration DB or baseline SQLite. Worker tests use isolated queue/key prefixes and delete only their own keys; they never flush the broker.

The three real-process cases use **explicit synthetic acquisition fixtures**, actual Redis/Celery prefork processes, real DB transactions and real Keycloak tokens. They verify broker connection failure, removal/recovery of a real queued message, duplicate delivery, three processing attempts, and killing only the test-owned process group after raw staging. Retry due times/claim expiry are advanced deliberately in those tests; no claim is made about measured production recovery time. The separate public-page HTTP check above uses the actual production fetcher/TLS path. Direct PostgreSQL tests additionally cover atomic acceptance/publication rollback, expired-token fencing, role changes before claim/publication, readable errors and artifact corruption. Offline tests check URL/DNS/TLS mapping, redirects, interrupted streams, deadlines, byte limits, artifact immutability and redaction.

This is local behavior verification, not independent human review, a penetration/load test, visitor usefulness or semantic answer evaluation. Baseline v2 live improvement and independent annotation review remain pending. No model call, model download, baseline rebuild, retrieval evaluation or held-out question inspection occurred.

The added regressions cover four slow publishes with concurrent production-config DB claims, dispatcher interruption after reservation, fast worker retry before publisher completion, and an older publisher returning after a newer delivery. URL tests reject oversized UTF-8 inputs with 422, persist the exact 2,048-byte boundary with maximum-length scope strings, and preserve reads of previously accepted oversized/compressible URLs. New registration URLs/terms links have a 2,048-UTF-8-byte input budget; shared `SourceFields` plus separate `SourceCreate`/`SourceRead` validation preserves existing stored records without changing identities or adding a migration. No public document was downloaded again for the fixes; the earlier public-page smoke report remains the recorded acquisition evidence.

Follow the important code in order: [sync/job/artifact routes](../src/doclens/service/ingestion_api.py) → [claim/run/publish/dispatch](../src/doclens/service/ingestion.py) → [HTTPX/artifact adapter](../src/doclens/service/ingestion_io.py) → [Celery configuration/process entry point](../src/doclens/service/worker.py). `sessionmaker.begin()` commits on a successful exit and rolls back on an exception; Python context managers also close HTTP streams/files/sessions. The immutable `Claim` dataclass carries execution identity without a client/session/credential in the task message.

Understanding exercise: explain why the API can safely return 202 while Redis is unavailable, and why a stale worker needs a claim-token check even after the lease expires. Trace where the previous ready revision survives a parse or publication failure. Do not equate the test count with having understood those transactions.

**This guide's boundary is Stage 2.** The subsequently requested [first Stage 3 unit](stage3-repository.md) now adds one pinned repository/Python source through this state machine; its current checks/reports are separate from the historical Stage 2 results above. Curated issue exports remain a separate request; Markdown/PDF need valuable selected sources. No automatic vector index or graph work follows. Stop API/worker/dispatcher with Ctrl-C and `docker compose -f compose.stage1.yaml -f compose.stage2.yaml stop` when finished; retain volumes and credential files.
