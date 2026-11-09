# Stage 3, unit 2: a curated historical issue export

This unit adds structured issue JSON to the existing authenticated ingestion service. It reuses source ownership, jobs/dispatch, bounded attempts, claim fencing, immutable artifacts and scoped reads. Its source is a reviewed local export; it is not a general GitHub/Jira ticket connector, arbitrary upload endpoint or live issue crawl. Service indexing/retrieval/answers and public visitor access remain later stages.

## Why this source and what it can establish

[CPython #88221](https://github.com/python/cpython/issues/88221), migrated from [BPO 44055](https://bugs.python.org/issue44055), discusses a Windows reopening example using `NamedTemporaryFile(delete=False)` and older documentation wording. The original tracker metadata lists Python **3.8**. The connected reader reported the issue **open**, created `2021-05-06T10:47:42Z`, updated `2022-04-10T14:40:29Z`, with three comments. This supplies historical context for the file-processing audience's reopening/cleanup question, rather than current 3.13 instructions or proof of a fix.

The selected comments are the reporter's observation, eryksun's explanation of the delete-flag/sharing distinction, and the reporter's proposed documentation wording. Review the [curation input](../corpus/expanded/issues/cpython-88221-v1.json): **attributed assistant-authored summaries and factual metadata**, not a copy of upstream prose or code. It identifies its curator, source-use review, selected original comment IDs, upstream body hashes and source observation time. It is not independent human validation. No incident, accepted fix, Windows test result or shipped/backported change was invented.

Comment timestamps were absent from the connected reader's result. They remain `null` with `timestamp_status: not_supplied`; issue-level dates are not substituted for comment creation/edit dates. An upstream-body SHA-256 identifies the reader's body string encoded as UTF-8, not a complete HTTP response or edit history. That hash does not prove our summary is correct. The current upstream URL is mutable; the stored export/artifact hashes identify what DocLens actually used.

Registration uses `version: "3.8"`, `reported_versions: ["3.8"]`, `applicability: historical_context_only`, `current_release_guidance: false` and collection label `python-file-processing-history`. Future retrieval must enforce its requested release/authorization and explicitly authorize any historical/comparison scope. Do not silently include this source in a 3.13 answer. No service retrieval or public collection read grant is implemented by these labels.

## Libraries, terms and resource choices

No package/dependency changes. Verified installed versions remain Python **3.12.12**, Pydantic **2.14.2**, HTTPX **0.28.1**, SQLAlchemy **2.1.6**, Alembic **1.20.1**, Celery **5.6.3**, Billiard **4.2.4**. Optional `service` and `worker` extras remain sufficient for operation; full regression testing also selects the existing retrieval/graph extras. No models are downloaded or invoked.

| Component | Delegated responsibility | Application responsibility / alternative |
| --- | --- | --- |
| [Pydantic JSON validation](https://docs.pydantic.dev/latest/concepts/json/), MIT | Strict typed fields, JSON date parsing, bounded strings/lists and [timezone-aware datetimes](https://docs.pydantic.dev/latest/api/standard_library_types/#datetimes) | Reject wrong identities/releases, duplicate IDs, inconsistent time/status metadata, unknown fields and unsafe relabeling. Construct trusted issue/comment locations and preserve unknowns. |
| Python `json`, `hashlib`, file APIs, PSF terms | JSON decoding/encoding, SHA-256, bounded local reads | Reject duplicate keys/nonfinite values; cap complete exports at **64 KiB**, four selected entries, twenty blocks per entry and 16,000 characters per block. Resolve only the fixed reviewed hash filename in an operator-owned directory; reject final-file symlinks/nonregular files and mismatched hashes. |
| Existing artifact store and job pipeline | Immutable hash-named writes, verification, atomic revision/head publication and recovery | Operator freezing, current membership checks, source/workspace metadata, failed-refresh preservation and explicit record schemas. These remain application policy. |
| Existing HTTPX | Local authenticated development helper requests | Fixed loopback API, timeouts, no redirects/proxy environment or token printing. Source acquisition in the worker makes **no external HTTP request**. |

LangChain's issue loaders were considered as reusable integrations for live GitHub loading. This unit intentionally consumes an already curated, structured snapshot with explicit provenance/unknowns and blocks; a live loader does not provide that curation/access/terms contract. No new loader, Markdown parser or competing RAG framework is installed. Existing LangChain direction remains; choose another parser only when the source format warrants it.

Reviewed [GitHub content/contribution terms](https://docs.github.com/en/site-policy/github-terms/github-terms-of-service) and [pinned CPython repository terms](https://github.com/python/cpython/blob/60403a5409ff2c3f3b07dd2ca91a7a3e096839c7/LICENSE). GitHub content ownership, public viewing/forking and repository contribution terms are distinct. Migrated comments, quoted material and attachments do not automatically receive blanket permission from a repository license. The curation stores our attributed summaries/facts and links/hashes rather than republishing full migrated bodies/attachments. These records describe source-use decisions, not a legal conclusion about every future source or DocLens's own code license. New sources require their own review.

A bounded direct unauthenticated GitHub API research request returned **403** and was not retried. Connected read tools supplied the reviewed issue/comments. The connector omitted comment timestamps, which remain explicit gaps. This is read-only source curation, not a verified live production API integration. There is no GitHub token, hidden network fallback, paid service or model-provider request in this feature.

## Data flow and important code

1. The committed curation has schema `doclens-curated-issue-export-v1`; the separate [service catalog](../corpus/expanded/sources.json) contains the matching registration/metadata. Application policy pins the source URL, Python 3.8 identity, terms and SHA-256. Only the display name is caller-selectable. A source request cannot supply workspace ownership, export path, authority or a version override.
2. `scripts/stage3_issues.py inspect` parses the curation without credentials, DB or network. `prepare` uses the shared artifact store to freeze verified input at `ISSUE_EXPORT_ROOT/reviewed/SHA256.raw`, refusing to overwrite inconsistent content. Operator preparation is separate from requesting a sync.
3. Migration `0004_issue_export` extends connector/purpose constraints to `issue_export`/`issue_report`. No tables/role grants or old source identities/artifacts are rewritten. Downgrade refuses incompatible rows rather than deleting history automatically.
4. The registration/sync API retains current Keycloak identity → current DB membership/role checks. It does not read arbitrary local files or fetch upstream content. A job and dispatch intent are accepted transactionally; Celery still carries only the server-issued job UUID.
5. `source_adapters.adapter_for` binds the operator export root to the issue fetcher. Per-adapter metadata/provenance callbacks replace identity-based branching; existing HTML-v1 and repository-v2 behavior remains. `run_job` obtains bytes, derives validated source metadata, stages verified files and publishes with the existing claim fence and permission recheck.
6. `fetch_issue_export` opens only `reviewed/EXPECTED_HASH.raw` under that trusted root with `O_NOFOLLOW`, verifies regular-file size/hash and validates JSON. Missing/invalid exports produce fixed terminal errors; preparing/fixing input and requesting a new sync is explicit. A failed refresh cannot erase the previous ready revision or imply deletion upstream. The current filesystem flags target the already verified macOS/Linux worker environment; Windows worker portability is not claimed.
7. `IssueExport`/`ExportEntry` validate the export. Paragraph/code block text is kept exactly; code is never executed. Blocks are structured explicitly, so Markdown parsing/truncation is unnecessary. Synthetic fixture blocks carry synthetic metadata; the real curation's content mode remains `curator_summaries`. No source facts are synthesized from `issue_state: closed`.
8. `IssueLocation` derives the fixed issue URL and `#issuecomment-ID` anchors from validated IDs. It retains source body hash and supplied/null dates. Section headings retain historical release/title/author context. Blocks preserve authorship, text SHA-256 and location. There are no model-invented links, fabricated anchors or private filesystem citations.
9. Normalized issue documents explicitly use **`doclens-service-document-v3`** / **`curated-historical-issue-v1`**. Source snapshots retain workspace/source/product/version/terms, curator/authority/access labels, selection/unknowns and frozen export hash. Provenance distinguishes original observation/update times from this worker acquisition time and raw/normalized hashes. Old HTML-v1/repository-v2 documents and frozen baseline data retain their original meanings.

Changing curation text changes its SHA-256. Review the source/summary, update the approved policy/catalog and freeze a new hash before requesting another sync. Each explicit successful job creates an immutable revision today, even for unchanged input. Content-aware reuse, deletion/retention and general access lifecycle remain later work. The stable upstream issue/comment identity differs from this immutable local revision.

## Run and inspect

From the repository root, inspect without an API key or services:

```bash
uv run --extra service --extra worker python scripts/stage3_issues.py inspect
```

Use the existing ignored credentials and [Stage 2 setup](stage2-ingestion.md#run-and-inspect). Start Docker Desktop first if its daemon is stopped:

```bash
uv sync --extra service --extra worker --group dev
uv run --extra service --extra worker python scripts/stage2_dev.py prepare
docker compose -f compose.stage1.yaml -f compose.stage2.yaml up -d
uv run --extra service --extra worker python scripts/stage1_dev.py bootstrap
uv run --extra service --extra worker python scripts/stage3_issues.py prepare
uv run --extra service --extra worker uvicorn doclens.service.app:create_app --factory --host 127.0.0.1 --port 18000 --env-file .env.service.local --no-access-log
```

In separate terminals run worker/dispatcher, then register:

```bash
uv run --extra service --extra worker python -m doclens.service.worker worker
uv run --extra service --extra worker python -m doclens.service.worker dispatch
uv run --extra service --extra worker python scripts/stage3_issues.py register
```

The helper reuses an existing matching registration without a sync; it checks the first 100 workspace registrations, so larger collections need explicit pagination. Use its actual workspace/source IDs and retain returned job/revision IDs:

```bash
uv run --extra service --extra worker python scripts/stage2_dev.py request /api/v1/workspaces/WORKSPACE_ID/sources/SOURCE_ID/sync --sync
uv run --extra service --extra worker python scripts/stage2_dev.py request /api/v1/workspaces/WORKSPACE_ID/jobs/JOB_ID
uv run --extra service --extra worker python scripts/stage2_dev.py request /api/v1/workspaces/WORKSPACE_ID/sources/SOURCE_ID/revision --identity atlas-viewer
```

The revision returns trusted relative raw/parsed artifact URLs. Save either with the same helper and `--output outputs/service/CHOOSE_A_NEW_NAME.json` (or `.raw`), which refuses overwrite. `--identity boreal-owner` must get 404 for Atlas source/job/artifact IDs, and viewer sync must get 403. These are service-account token examples, not browser sign-in. Upstream issue/comment URLs are already public; that does not grant access to local workspace artifacts.

The worker export root defaults to the `issue-exports` sibling of its configured artifact directory. Set optional `DOCLENS_ISSUE_EXPORT_ROOT` in the ignored worker env file for another operator-owned root; `prepare` and worker use the same settings. A user-supplied source field cannot change it.

## Acceptance and verification

Acceptance covers typed identities/releases/terms, bounded complete JSON with duplicate-key rejection, dates/unknowns/edits, exact code, comment URLs and hashes, repeatability, missing/tampered/final-symlink input, current scope/role denials, duplicate jobs, old-format compatibility, previous-ready preservation and actual worker execution. Static source/summary review is separate from backend checks. Verification results are recorded after the checks complete.

Verified on 2026-11-09:

- **344 full tests passed**, plus 121 unittest subtests: [final JUnit](../outputs/service/issue-unit-full-verified-20261109.xml). **277 offline / 67 opt-in skipped**: [offline JUnit](../outputs/service/issue-unit-offline-final-20261109.xml). All **136** baseline unittests passed separately. The new unit contributes 42 offline, three actual PostgreSQL/Keycloak and one actual Redis/Celery prefork case.
- Real DB migration is `0004_issue_export`; `alembic check` reported `No new upgrade operations detected`. Existing grants and old HTML/repository source records/artifacts remain preserved. A new fixture initially left temporary workspace memberships visible to older list tests; cleanup was fixed without weakening the assertions. [That initial full report](../outputs/service/issue-unit-full-20261109.xml) and [the subsequent 342-test pass](../outputs/service/issue-unit-full-final-20261109.xml) remain as intermediate history.
- Final inspection caught rejection of a directory leaving its file descriptor open and acceptance of closure before creation. Both added regressions [failed before fixes](../outputs/service/issue-unit-regressions-before-20261109.xml). The final implementation closes descriptors on every rejection path and validates closure chronology; the final suite above includes both protections.
- [Production-path HTTP report](../outputs/service/issue-unit-http-20261109T132120Z.json), [raw export copy](../outputs/service/issue-unit-http-20261109T132120Z.raw), [normalized output](../outputs/service/issue-unit-http-20261109T132120Z.parsed.json) and [final-worker repeatability report](../outputs/service/issue-unit-repeat-20261109.json). The input is **4,329 bytes**, normalized output **10,309 bytes**, with **four sections/four paragraph blocks/zero code examples** and three selected comments. Synthetic offline cases separately verify exact code-block preservation; the real source contains summaries, not reproduced code.
- Raw/export SHA-256 `ff463229c78926804125e68a03119674d0059494e7b9a29a4af22408556bc3b8`, normalized and block-text hashes match. Fresh parser output matches saved output. IDs, authorship, historical 3.8 scope, source terms, supplied/null dates and trusted links were inspected. Repeated jobs produce the same source/document/raw hash and a new immutable revision; the prior revision remains readable. Each successful run used one processing/delivery attempt.
- Viewer reads succeeded; Boreal source/job/revision/raw/parsed reads returned **404**; viewer sync returned **403**; 3.13 relabeling returned **422**. Duplicate request keys returned the same job. Direct API handlers did not choose arbitrary paths or fetch remote content. Missing/tampered refreshes retained the previous ready revision in real DB tests.
- [Source/curation review](../outputs/service/issue-unit-source-review-20261109.json) is assistant-authored static inspection, explicitly separate from independent human validation, Windows/CPython execution, retrieval/answer quality and visitor feedback. Source IDs/hashes and structural passes do not prove the summaries or future answers correct. No model request/download, index rebuild/tuning, frozen label/report change or held-out question inspection occurred.

Actual local source ID is `d6453ba3-3f58-409d-b85c-091dd4c18c85` in Atlas `843909a7-d634-5b3a-a119-c747ac16ff1c`. Initial successful job/revision: `2bd9c65e-d39c-4ceb-bb52-f01d671f3436` / `a4850e5c-817b-51b7-99b4-033c9c387a71`. Final repeat: job `0aa14031-096c-47bf-b625-b973cd26c65a`, revision `21068646-7f98-59c4-ae72-92652b12a30b`. They are local metadata, not credentials; new databases return new source/job IDs.

Inspect the actual saved output without another request:

```bash
uv run --extra service --extra worker python -m json.tool outputs/service/issue-unit-http-20261109T132120Z.parsed.json
```

For example, section 2 retains the trusted location [comment 1093914527](https://github.com/python/cpython/issues/88221#issuecomment-1093914527), `content_mode: curator_summaries` and null comment dates. Inspect the source metadata and block `authorship` together, not just the displayed link. Final preservation/cleanup details are recorded in [progress](progress.md).

Final summary/code/configuration/evidence hashes are in `outputs/service/issue-unit-verification-20261109.json` (SHA-256 `185dbd5812e97365501094e67632d9858543d868b3862cb5e9ea818646fe2153`). The audit verified 204/222 original files unchanged, eighteen intended existing changes, seven new repository files, generated-secret exclusion, 130 local links/anchors, Markdown fences and `git diff --check`. API/worker and the three local test containers are stopped with volumes/configuration retained. No model call, baseline rebuild, held-out run, agent delegation, commit/push or deployment occurred. Cleanup used only task-owned processes and the named Compose services; no unrelated Redis queues were flushed.

## Understanding exercise and boundary

Trace `scripts/stage3_issues.py prepare` → `source_adapters.py:adapter_for` → `issue_export.py:fetch_issue_export/load_export/parse_issue_export` → `ingestion.py:run_job`. Explain why a valid comment ID/hash does not prove the curator's summary or a later model answer is correct. Then explain why unknown comment timestamps must not be replaced by the issue update time.

Stop after this curated issue-export unit. Markdown requires useful selected material and PDF remains conditional; do not automatically add formats, service vectors/answers, public visitor access or graph behavior. Broader RAG quality, the earlier v2 live comparison, independent review and production operations remain open.
