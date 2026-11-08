# Stage 3, unit 1: a pinned repository file

This unit adds one public GitHub source and one Python-code format to the authenticated ingestion service. It reuses Stage 2 jobs, bounded retries, claim fencing, immutable artifacts and workspace authorization. It does not add service embeddings/search/answers, public reader grants, Markdown/issues/PDF adapters, Git checkout or LangGraph behavior.

## Why this source

The proposed Python file-processing collection includes the question: “How can I reopen a NamedTemporaryFile on Windows, and what happens at cleanup?” Official reference pages remain the primary API contract. CPython's tests provide supplementary examples of intended behavior at a particular source revision. This is a useful second source type, not a claim that adding tests has improved answer quality.

The reviewed source is [CPython's test_tempfile.py at the 3.13.0 commit](https://github.com/python/cpython/blob/60403a5409ff2c3f3b07dd2ca91a7a3e096839c7/Lib/test/test_tempfile.py). Only the complete `TestNamedTemporaryFile` class is normalized. It contains examples for `delete_on_close=False`, context-manager cleanup and finalization. The complete file is retained as the raw artifact. Imports, other classes and surrounding helpers remain in raw, rather than being silently presented as part of the selected class. Extracted code is a reference passage, not a standalone executable example.

The inspected class contributes cleanup assertions. It does not itself establish every Windows reopening/share-mode or directory delete-permission condition; keep the applicable official reference as primary evidence for those qualifications.

Three identities have different meanings:

- `version: "3.13"` is the product release family used for future filtering.
- `source_release: "3.13.0"` records the historical release curated here. This is not the latest 3.13 patch.
- Commit `60403a5409ff2c3f3b07dd2ca91a7a3e096839c7` identifies the exact repository snapshot; the observed blob SHA-1 identifies this file and SHA-256 protects local artifact bytes.

Authority is `official_test_code`, with `tests_executed: false`. We did not run CPython tests or establish Windows behavior on this Mac. Comments/assertions at this snapshot do not prove a fix in later releases or replace the documented platform qualifications. Public-origin evidence stays distinguishable from explicitly synthetic acquisition fixtures used in tests. No answer/retrieval evaluation or visitor task measurement is part of this unit.

The committed [source catalog](../corpus/expanded/sources.json) is separate from the frozen baseline manifest. Its registration entry matches the application's deliberately small allowlist; a test prevents drift. Adding another commit/path/release requires a reviewed policy/catalog change, rather than allowing callers to relabel arbitrary files. `collection_key` is a grouping label, **not a collection table, public grant or implemented retrieval filter**. Source administration, jobs and artifact reads still require current workspace membership.

## Libraries and application responsibilities

No dependencies were added or upgraded. Compatible versions actually present: Python **3.12.12**, HTTPX **0.28.1**, Pydantic **2.14.2**, SQLAlchemy **2.1.6**, Alembic **1.20.1**, Celery **5.6.3**, Billiard **4.2.4**. Existing optional `service` and `worker` extras remain the installation boundary; versions are recorded in `uv.lock`. No embedding model, parser model or external model request is needed.

| Component | Delegated responsibility | DocLens responsibility / alternative |
| --- | --- | --- |
| [HTTPX](https://www.python-httpx.org/advanced/transports/), BSD-3-Clause | HTTP/TLS, streaming and explicit socket timeouts | Curated destinations, public-IP pinning, fixed API paths, deadline/size limits, no redirects/auth/proxy forwarding, fixed safe errors. Reuse the existing transport instead of installing another network client. |
| Python [ast](https://docs.python.org/3.12/library/ast.html), PSF terms | Parse syntax and locate the selected class/decorators | Preserve original lines, construct trusted permalinks and reject missing/invalid selection. Nothing is imported/executed. The running interpreter grammar is recorded; arbitrary Python 3.13+ syntax is not promised under Python 3.12. |
| [Pydantic](https://docs.pydantic.dev/latest/concepts/models/), MIT | Validate registration fields and typed repository line locations | Pin product/release/revision/path/terms and reviewed byte hashes; trusted authority/access metadata is application-owned. |
| Existing Alembic/SQLAlchemy/PostgreSQL and Celery/Redis | Migrations, transactions and task execution/delivery | Reuse authorization, short transactions, reservation generations, claims/replay, verified artifact staging and fenced publication. No new DB/broker service. |

[GitPython](https://gitpython.readthedocs.io/en/stable/intro.html) and [LangChain GitLoader](https://reference.langchain.com/python/langchain-community/document_loaders/git/GitLoader) were considered. GitLoader loads text files from a local/cloned repository. For this one small, public, pinned file, a checkout adds Git process/disk/cleanup responsibilities without supplying the required bounded acquisition, class selection or line-level provenance. HTTPX + `ast` are the narrower fit. This is a GitHub file connector, not a verified generic Git/GitPython integration. LangChain remains the planned reusable RAG ecosystem where its interfaces fit; no overlapping LlamaIndex stack was added. Markdown parsing is deferred until a useful selected Markdown source warrants it.

Source content terms are [CPython's pinned LICENSE](https://github.com/python/cpython/blob/60403a5409ff2c3f3b07dd2ca91a7a3e096839c7/LICENSE), including PSF licensing and historical notices. The terms URL and source attribution are retained; these differ from DocLens's own code license and from GitHub's API/service terms. These are source-use records, not a legal determination about every future redistribution. No paid infrastructure, credentials or model service is introduced by this adapter.

## Data flow and limits

1. `SourceCreate` permits `github_file`/`test_code` only for the reviewed URL, product/version and terms. Registration performs no external fetch. Users choose a display name; they cannot supply workspace/authority/access overrides.
2. Migration `0003_repository_source` extends the two source enum constraints. It does not rewrite source identities, old metadata or artifacts and does not alter runtime role grants. A downgrade refuses to discard incompatible repository rows; it requires an explicit operator migration plan.
3. A sync request checks role/current membership, creates the same durable job/dispatch intent and returns. `source_adapters.adapter_for` selects acquisition, parser, document schema and processing policy. The job/retry/publication state machine stays shared.
4. `fetch_repository` makes **one GET** to a locally constructed `raw.githubusercontent.com` URL containing the exact reviewed commit and path. Both the reviewed SHA-256 and Git blob SHA-1 (`blob <length>\0<bytes>` framing) must match before raw storage. This is curation of one known regular file, not generic tree/type discovery: arbitrary repository paths, symlinks, submodules and directories are not supported. An LFS pointer or different payload cannot match the reviewed bytes; no pointer/download URL is followed.
5. Requests use verified public-IP pinning with the original TLS hostname, no authorization/cookies, no proxy environment, no redirects or transport retries. Each operation has a five-second timeout; a checked 30-second acquisition deadline and the existing 60/75-second worker limits bound execution. The checked deadline is not an instantaneous cancellation of DNS/active socket operations. Source bytes are capped at **256 KiB**; original artifact limits still apply. GitHub's [raw-file view](https://docs.github.com/en/repositories/working-with-files/using-files/viewing-and-understanding-files) supplies bytes; the trusted display citation remains the commit-pinned `github.com/.../blob/...#L...` permalink.
6. HTTP 429 and signaled 403 rate limits stop terminally with a readable error; other 403/4xx/redirect responses also stop without automatic retry. Network interruptions/5xx use the existing three-attempt job budget. The first REST API prototype used commit/tree/blob endpoints with API version 2026-03-10; its actual first request hit the [shared-IP API limit](https://docs.github.com/en/rest/using-the-rest-api/rate-limits-for-the-rest-api) and stopped after one attempt without publication. That report is preserved. The final explicit `github-curated-raw-sha256-v1` policy uses the reviewed raw URL/hashes directly, not an automatic fallback or token. Raw delivery can still be unavailable/rate limited; wait/check availability before requesting another sync. No paid fallback or authenticated GitHub integration is configured.
7. The parser locates exactly one top-level selected class, includes decorators, and slices complete original source lines. Indentation, comments, LF/CRLF, Unicode text and line URLs are preserved. A whole class is intentionally one code block; later chunking must handle its size explicitly, not silently cut methods/code. Selection is configured, not inferred by an LLM.
8. Repository documents use **`doclens-service-document-v2`**, processing policy **`cpython-selected-class-v1`**, typed `repository_lines` locations and exact pinned `#Lstart-Lend` URLs. Source snapshot carries workspace/source IDs, catalog/collection label, product/version/release, repository/commit/path, selection, authority, synthetic/access labels and terms. Provenance carries fetched time, final URL, raw SHA-256/size and Git blob SHA-1; each selected code block has its own text SHA-256. Saved HTML stays `doclens-service-document-v1` / `python-sphinx-service-v1`.
9. Raw and normalized artifacts are verified before revision/current-ready pointer publication. Every read checks current membership and artifact hashes. A failed refresh retains the previous ready revision. A 404 is a failed fetch, not proof of upstream deletion. A new source commit needs a new curated registration; even identical content synced in a new job creates a new immutable revision today. Content/configuration reuse, retention and deletion are later lifecycle work.

## Run and inspect

Use the same Stage 1/2 services and preserved ignored credentials:

```bash
uv sync --extra service --extra worker --group dev
uv run --extra service --extra worker python scripts/stage2_dev.py prepare
docker compose -f compose.stage1.yaml -f compose.stage2.yaml up -d
uv run --extra service --extra worker python scripts/stage1_dev.py bootstrap
uv run --extra service --extra worker uvicorn doclens.service.app:create_app --factory --host 127.0.0.1 --port 18000 --env-file .env.service.local --no-access-log
```

In separate terminals run the worker and dispatcher, then register:

```bash
uv run --extra service --extra worker python -m doclens.service.worker worker
uv run --extra service --extra worker python -m doclens.service.worker dispatch
uv run --extra service --extra worker python scripts/stage3_dev.py register
```

Registration prints the workspace/source IDs. Repeating the helper reuses the existing matching registration and never syncs automatically. It inspects the first 100 local example registrations; larger lists require explicit pagination. Substitute those IDs below and retain the returned job/revision IDs. These local helpers obtain Keycloak service-account tokens without printing them; they are not browser sign-in.

```bash
uv run --extra service --extra worker python scripts/stage2_dev.py request /api/v1/workspaces/WORKSPACE_ID/sources/SOURCE_ID/sync --sync
uv run --extra service --extra worker python scripts/stage2_dev.py request /api/v1/workspaces/WORKSPACE_ID/jobs/JOB_ID
uv run --extra service --extra worker python scripts/stage2_dev.py request /api/v1/workspaces/WORKSPACE_ID/sources/SOURCE_ID/revision
```

The revision response supplies trusted relative `raw_artifact_url` and `parsed_artifact_url` values. Download each with `scripts/stage2_dev.py request URL --output outputs/service/CHOOSE_A_NEW_NAME.raw` (or `.json`). Existing outputs are never overwritten. `--identity atlas-viewer` should read; `--identity boreal-owner` should get 404 for Atlas resources. API endpoints can restrict access to local artifacts; the cited upstream file is already public.

Inspect the selected block and compare it against the saved raw file, rather than treating parsed JSON shape alone as correctness:

```python
import io, json
from pathlib import Path

record = json.loads(Path("outputs/service/CHOOSE_A_NEW_NAME.json").read_text())
raw = Path("outputs/service/CHOOSE_A_NEW_NAME.raw").read_bytes()
block = record["document"]["sections"][0]["blocks"][0]
location = block["location"]
lines = io.StringIO(raw.decode("utf-8"), newline="").readlines()
assert block["text"] == "".join(lines[location["start_line"] - 1:location["end_line"]])
print(record["source"])
print(block["url"])
print(block["text"])
```

## Acceptance and verified results

Acceptance checks cover curated source validation before network I/O; exact pinned destination/reviewed SHA-256 and blob hash consistency; byte limits, interruption, rate handling and safe errors; exact code/line preservation and repeatability; metadata/version preservation; real PostgreSQL/Keycloak registration and scoped job/revision/artifact reads; shared worker routing; failed-refresh preservation; migration/baseline compatibility. Synthetic transport/fault fixtures are separate from the actual public-file smoke check. Verification results are recorded here after the checks complete.

Verified on 2026-11-05:

- **298 full tests passed**, plus 121 unittest subtests: [final raw-policy JUnit report](../outputs/service/stage3-raw-full-20261105.xml). This includes 63 opt-in real-service cases: the previous 59, three new PostgreSQL/Keycloak cases and one new prefork-worker case. All use disposable test DBs/isolated queues; synthetic acquisition is labeled in content and metadata.
- **235 offline passed / 63 opt-in skipped**: [offline report](../outputs/service/stage3-offline-final-20261105.xml). All **136** original unittests also passed separately. No dependency/lockfile changes. `alembic check` reported `No new upgrade operations detected`; the real DB is on `0003_repository_source` with the new connector/purpose checks.
- [Actual public raw-policy HTTP/inspection report](../outputs/service/stage3-raw-public-20261105T155537Z.json), [saved raw](../outputs/service/stage3-raw-public-20261105T155537Z.raw), and [saved normalized JSON](../outputs/service/stage3-raw-public-20261105T155537Z.parsed.json). The production worker completed in one processing/delivery attempt, with **76,572 raw bytes**, **12,665 normalized bytes**, one section/code block, and **8,714 selected code bytes** at **947–1170**. All 17 class methods (16 named test methods plus a helper) are preserved. This count does not mean those tests ran.
- Exact raw SHA-256 `08f33f84addf1cb7a99747857d093246973a49f238a63eeb64fe395205bd2c36`, Git blob SHA-1 `a5e182cef23dc54f534fe04dcc2aafcf0e35fe6a`, normalized hash and selected-code SHA-256 were checked. Fresh parser output matches saved output. Trusted source/workspace/release/revision/terms/authority/access metadata and exact raw line slice match. The real viewer read succeeded; Boreal access to Atlas source/job/current revision/raw/parsed returned 404; viewer sync returned 403 and a 3.12 relabel returned 422. Repeated request-key acceptance returned the same job.
- [Assistant-authored static source review](../outputs/service/stage3-source-inspection-20261105.json) separately records cleanup assertions, citation inspection and evidence gaps. This is not independent human review, execution of CPython tests, a Windows runtime check, or retrieval/answer/usefulness evaluation. The earlier public HTML revision still has its original hashes and 80 examples.
- [The failed REST/API prototype attempt](../outputs/service/stage3-api-ratelimited-20261105.json) remains preserved: one rate-limited attempt, no revision. Intermediate JUnit outputs remain as history; only `stage3-raw-full-20261105.xml` verifies the final acquisition policy. There was no repeated API-limit retry or hidden fallback.

Actual local registration: workspace `843909a7-d634-5b3a-a119-c747ac16ff1c`, source `c89cbe92-1899-4606-a07a-ca64ebe29b30`, successful job `5302f567-470b-4e39-a0f9-2a4f3c0be49d`, revision `2b1adb67-c846-5e4a-9663-ecf48efd7a8c`. These are local example IDs, not credentials; fresh DBs generate new source/job IDs. Inspect saved output without another provider request:

```bash
uv run --extra service --extra worker python -m json.tool outputs/service/stage3-raw-public-20261105T155537Z.parsed.json
```

The selected citation is [the complete class at lines 947–1170](https://github.com/python/cpython/blob/60403a5409ff2c3f3b07dd2ca91a7a3e096839c7/Lib/test/test_tempfile.py#L947-L1170). No model calls, model downloads, baseline rebuild/tuning, retrieval evaluation or held-out question inspection occurred. Frozen labels/reports/index and prior Stage 1/2 evidence are preserved. Cleanup uses Ctrl-C for task-owned processes and `docker compose -f compose.stage1.yaml -f compose.stage2.yaml stop`, retaining volumes/configuration.

[Final verification/preservation summary](../outputs/service/stage3-verification-20261106T022338Z.json), finalized 2026-11-06, records code/configuration/evidence hashes and known limits. It confirms 180/197 original files byte-identical, with seventeen intended existing changes and eight new repository files. The baseline corpus/index/labels/reports, earlier service artifacts, packaging/lockfile and learning notes are preserved. Generated-secret checks, 128 local link/anchor checks, Markdown fences and `git diff --check` passed. API/worker exited and the three containers are stopped; volumes/credentials remain. No commit/push/deployment was performed.

## Trace the code

Read `schemas.py:SourceCreate.curated_repository`, `source_adapters.py:adapter_for`, `repository.py:fetch_repository` / `parse_repository`, and `ingestion.py:run_job` in that order. Acquisition obtains bytes; parsing maps them into inspectable evidence; the shared ingestion state machine decides whether a revision may become ready. A library/parser does not grant access or prove semantic support.

Exercise: explain why changing only `version` to `3.12` must fail even though GitHub can still serve the file. Then explain why `collection_key: python-file-processing` must not grant an anonymous visitor access to the stored artifact. Record your own explanation/experiment in the learning notes if useful; no understanding is assumed.

Stop after this repository/Python-source unit. Curated issue JSON is a separate potential next unit; Markdown requires valuable selected material and PDF remains conditional. Expanded retrieval, answers, public visitor access and LangGraph remain later stages.
