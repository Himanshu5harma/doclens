# Current learning checkpoint

Last updated: 2026-10-29 (Asia/Kolkata).

## Goal and working agreement

Build DocLens to demonstrate understanding of RAG while learning LangGraph. Teach one complete useful feature per lesson, combining design, implementation when requested, and verification. The user found individual file-writing exercises too granular. Explain the decisions and code so the user can understand them.

Public descriptions focus on DocLens's purpose and honest capabilities, rather than calling it a portfolio project. Learning goals remain in the roadmap, learning notes, and assistant instructions. Read `AGENTS.md` for the full working agreement and resume here without asking the user to explain the project again.

## Verified implementation

Milestones 1 and 2 are implemented for the selected corpus. Milestone 3 has a source-checked development/held-out dataset, retrieval evaluation runner, provisional development scores, and failure/annotation review; independent human label review remains open. **Milestone 4's direct baseline RAG is now verified working end to end**, using the user's successful four-case live report and this chat's evidence/semantic review. Two supported questions were answered and two unsupported questions appropriately received insufficient-evidence responses, all structurally valid and reporting zero model cost. Metadata-preservation qualification and citation-placement limitations remain. Broader quality validation is open; LangGraph is proposed but not implemented.

The components are:

- `corpus/sources.json`: explicit curated sources, including source IDs, product, version strings, document type, HTTPS URL, raw destination, and source-terms URL.
- `src/doclens/manifest.py`: loads and validates the complete manifest before network requests, including required string fields, HTTPS page URLs, unique IDs/paths, and HTML destinations under `data/raw/`.
- `src/doclens/fetch.py`: downloads raw bytes with a 30-second socket timeout. Before reading or writing, final URLs must retain the requested HTTPS host/port and Python version prefix. Empty and non-HTML responses are rejected. HTTP protocol exceptions, including interrupted reads, become readable source-specific errors through the CLI.
- `src/doclens/files.py`: shared atomic file replacement. HTML and metadata are separate writes, not a single transaction; consumers must check their hashes. Old snapshots are not archived.
- `src/doclens/parse.py`: verifies raw size/hash and source metadata, selects the Python/Sphinx main article region, and saves structured JSON sections with heading paths and typed blocks. It preserves API signatures, code indentation/newlines/prompts, actual source anchors, source metadata, and version-specific citation URLs. Paragraphs, signatures, code, bare list items, and simple table rows remain distinct.
- `src/doclens/records.py`: frozen standard-library `Source`, `Block`, `Section`, `Document`, `ChunkPiece`, and `Chunk` dataclasses, a block-kind enum, and explicit validation of parsed JSON at the adapter boundary. The ingestion parser's JSON format remains unchanged. A document is one page, a section is author-defined heading context, and a chunk is a passage prepared for later retrieval.
- `src/doclens/chunk.py`: `chunk_document()` is the pure baseline algorithm; `chunk_source()` checks raw/sidecar/parsed provenance, loads typed records, and atomically replaces one source's chunk bundle. Pieces carry source block indices and exact half-open character offsets, permitting loss/duplication checks.
- `src/doclens/embeddings.py`: immutable embedding configuration, an injectable encoder protocol, vector validation/normalization, and a lazy-loaded local encoder. Query/document prefixes and special tokens count toward preflight limits. Inputs are never silently truncated.
- `src/doclens/retrieval.py`: current-manifest chunk collection, complete atomic SQLite replacement, and read-only product/version-filtered exact cosine search. Full chunk payloads and float32 vectors are persisted; typed `SearchResult`/`SearchResponse` records expose evidence.
- `src/doclens/evaluation.py`: validates typed questions, corpus hashes, reference anchors/quotes, and index scope; computes deduplicated source-region metrics, evidence-group coverage, and separate comparison/single-release results; saves full outcomes and reproducibility metadata atomically. The catalog reconstructs overlapping source pieces for quote verification. The runner aborts on changed index hashes and protects input/label files from report writes.
- `src/doclens/answers.py`: typed prepared evidence/answer records, version/hash/URL checks, whole-passage prompt budgeting, structured status/citation validation, and trusted source rendering. `prepare_question` reuses existing retrieval; `answer_question` calls an injectable generator once.
- `src/doclens/generation.py`: standard-library OpenRouter client, explicit :free ID/configuration, current zero-price/capability preflight, zero-price routing caps, disabled fallbacks/transforms, explicit socket/output/context limits, redacted readable failures, model/usage/latency metadata, and no automatic retry. No new dependency was added.
- `src/doclens/answer_evaluation.py`: fixed four-question dev sample, prompt-only inspection or at most four generations with stop-on-error behavior, read-only index/corpus checks, separate reports, and initially pending semantic-review fields. The 2026-10-29 live report is preserved unchanged; the subsequent assistant review is recorded separately in `evals/generation-dev-review.md`. Held-out labels are never opened.
- `src/doclens/__main__.py`: ingestion/chunking, `index`, `search`, `evaluate`, `ask`, and `evaluate-answers`. Retrieval evaluation defaults to `--split dev`; the answer sample is development-only. `ask --inspect-prompt` needs no provider key/API call; `--json` exposes structured answers/evidence/metadata.
- `pyproject.toml` / `uv.lock`: Beautiful Soup remains the base dependency. The optional `retrieval` extra adds Sentence Transformers; the verified runtime is sentence-transformers 5.7.0, transformers 5.21.0, and torch 2.14.1. Heavy dependencies/model loading are not required by ingestion/chunking or offline tests.

## Corpus and validation

The corpus contains nine matching reference topics per release—`pathlib`, `os.path`, `glob`, `shutil`, `tempfile`, `json`, `re`, `datetime`, and `argparse`—plus each release's What’s New page. This is 10 pages for 3.12 and 10 for 3.13, with 18 reference records and two release-note records overall. Linked PEPs, tutorials, source code, and other pages are not crawled.

Full selection, exclusions, manual samples, and validation counts are recorded in [the corpus review](corpus.md).

| Release | Pages | Sections | Blocks | Code blocks |
| --- | ---: | ---: | ---: | ---: |
| 3.12 | 10 | 226 | 3,429 | 326 |
| 3.13 | 10 | 245 | 3,670 | 324 |
| Total | 20 | 471 | 7,099 | 650 |

All downloaded pages returned HTTP 200, passed the final-URL policy, and had titles identifying the requested release line. Verification checked raw hashes and sizes, all manifest/provenance fields, parsed provenance, heading counts, paragraph coverage, every code block's text and occurrence count, actual source anchors, and explicit version URLs. The 650 original code examples were preserved.

Eight manual samples were inspected against original HTML: 3.12 `tempfile.NamedTemporaryFile`, 3.13 `glob.translate`, 3.12 `json.loads`, 3.13 `re.sub`, 3.12 `datetime.fromisoformat`, 3.13 `argparse`'s deprecated subsection, and both releases' pathlib release-note sections. This was a sample review, not an exhaustive manual review of all passages.

Local outputs are ignored by Git:

- `data/raw/python/<version>/<page>.html` and adjacent `<page>.html.metadata.json`.
- `data/parsed/python/<version>/<page>.html.json`.
- `data/reports/corpus-review.json`: the latest verification run's manifest hash and per-page hashes/counts. This report was produced during the review; `ingest` does not generate it automatically.

The manifest SHA-256 for the reviewed run is `25f48fd84536b623d9efc056ac8d5f775d71217aae48c4c37bb30ec1d9b3daa8`.

The last full offline verification passed **110 tests**: the previous 74 ingestion/chunking/retrieval/evaluation tests plus 36 answer/client/sample tests. Checks cover exact prompt byte boundaries and whole code preservation, omitted chunks, mixed versions/URLs/hashes, metadata/repeatability, partial/insufficient outcomes, uncited/malformed/truncated responses, citation IDs/versions, provider/auth/rate/transport errors, price/capability changes, redaction, read-only behavior, and bounded dev-only reports. This documentation-only review did not rerun the suite. All recorded implementation/packaging hashes in the live report still match the current files. Test doubles establish behavior, not semantic quality.

The user's earlier review recommendations are resolved. The response fixture now returns a version-appropriate final URL. Failure tests also exercise interruption between HTML and metadata writes (the parser rejects the pair and preserves prior parsed output), and a two-source fetch whose second read fails (first success remains valid and previous second-source files are preserved).

## Verified chunking baseline

The selected `section-anchor-v1` policy uses a 2,000-character target, including repeated heading/anchor context and separators, with no overlap. It packs adjacent blocks without crossing a section or effective anchor. Oversized prose splits at whitespace, falling back to characters for long words; code, signatures, and table rows stay whole and are flagged oversized if necessary. A target too small for heading context fails clearly. Characters are not model tokens; chunk-policy alternatives have not been evaluated.

| Release | Documents | Chunks | Oversized |
| --- | ---: | ---: | ---: |
| 3.12 | 10 | 720 | 1 |
| 3.13 | 10 | 754 | 1 |
| Total | 20 | 1,474 | 2 |

The real-corpus audit reconstructed all 7,099 parsed blocks without gaps or overlap, preserved all 650 code examples as whole pieces, checked source metadata/hashes and heading/anchor context, and found all 1,474 IDs unique. A second run produced byte-identical bundles for every source. Rendered lengths ranged from 46 to 6,015 characters, median 499. The two oversized chunks hold the original long datetime examples. The Python 3.13 `Path.from_uri` sample is 937 characters and retains its signature, explanation, code, version note, and explicit version citation.

Chunk outputs live under ignored `data/chunks/section-anchor-v1-2000/python/<version>/<page>.html.json`. Alternative targets get separate directories, such as `section-anchor-v1-2500`. The latest manual audit details are in ignored `data/reports/chunk-review.json`; the command does not generate that report automatically. The full policy, record fields, code entry points, ID behavior, limitations, and inspection commands are documented in [the chunking guide](chunking.md).

IDs fingerprint source identity, policy, context, and scoped passage content; duplicate occurrences get distinct IDs. Fetch time, raw snapshot hash, document-wide hash, and absolute positions are excluded, so unaffected passages can retain IDs after an unrelated edit or earlier insertion. Changed content/context or policy changes affected IDs, possibly through repacking. Always refresh provenance and offsets even when IDs are unchanged. Re-running replaces the source's whole bundle. The new index rebuild reads the active manifest and completely replaces its database, updating payloads and dropping stale IDs/sources. Cached chunk files for removed manifest sources are not automatically pruned.

## Verified dense retrieval baseline

The next feature was explained as embedding passages/questions into vectors, persisting them locally, and returning inspectable evidence within a requested version. Chose local CPU inference to avoid a paid model service and key, and SQLite/exact cosine because the corpus has only 1,474 chunks. This requires local disk/RAM/CPU and a one-time model download of 596,070,136 bytes plus optional dependencies.

`configs/retrieval.json` pins `nomic-ai/modernbert-embed-base` to revision `d556a88e332558790b210f7bdbe87da2fa94a8d8`, 768 dimensions, 8,192-token cap, `search_document: ` / `search_query: ` prefixes, batch size 8, and four CPU threads. Model-card/license and local-resource rationale are recorded in [the retrieval guide](retrieval.md). Native model loading uses no remote custom code. The downloaded configuration's real sequence/dimension limits were checked. Prefixes are explicit and library default prompts are disabled.

Two actual builds encoded the full corpus and persisted 1,474 unique chunks from 20 sources (720 for 3.12; 754 for 3.13) in `data/indexes/baseline.sqlite3`. The largest prefixed input was 1,932/8,192 tokens, so both oversized code examples remained whole and no chunking change/truncation was needed. All stored vectors had 768 dimensions, finite values/unit norm within float32 tolerance; payload hashes/version columns matched. Both builds retained the same chunk-set fingerprint and row count, without appending duplicates. The fingerprint is `cfa0b0fba32273cf5902b8ec9b0e2f88cde4376d07f80bcbc0f9508c8426ff59`.

Real smoke queries returned the requested version only and did not change index bytes. Python 3.13's file-URI question ranked `Path.from_uri` first (0.7088). The same question in 3.12 returned the related reverse operation `PurePath.as_uri` first (0.5752): similarity is not proof of answer support. Wildcard-to-regex ranked the pathlib pattern-language section first and `glob.translate` second. Dictionary-to-JSON ranked `json.dumps` first. These are smoke observations, not labeled recall/MRR, a held-out evaluation, or an abstention decision. Saved details: ignored `data/reports/retrieval-smoke.json`.

Indexing refreshes verified chunk bundles, checks all lengths, encodes locally, then builds a temporary database and replaces the old file only after success. It currently re-encodes all passages on each build. Querying opens the existing DB read-only, filters product/version in SQL before selecting vectors to score, and uses cached model files with the saved index configuration. It serves that snapshot until an explicit rebuild; it does not compare ingestion files or mutate data/index state. Full policy/model/runtime/manifest/chunk-set metadata is saved in SQLite.

## Provisional development evaluation

The retriever/model/index/chunking policy were left unchanged. `evals/dev.json` has 24 questions: six exact, eight paraphrase, five multi-source, two comparison, and three missing-evidence cases. `evals/heldout.json` reserves eight different questions, source-validated without running retrieval. The four earlier smoke questions belong to development. Reference answers and required facts were authored by the assistant and checked against saved source passages; they are not human-reviewed or passed into retrieval. All labels/results remain provisional pending independent review.

The source/API-anchor labels include verification quotes and accepted alternatives grouped by required source region. Both datasets pin all 20 raw source hashes and the manifest hash. Dev dataset SHA-256: `c83255a64ac6a97d7efcd9f45d4fd191e6eca11d8325717489c85fe1cfe21e8f`. Held-out SHA-256: `23d02a6a73f3a137d6fea64c4de09c4d414566b87a53840b515f65afdff8df5a`. Do not silently revise frozen labels after seeing scores; version a reviewed correction and preserve the prior report.

Two actual dev evaluations at k=5 per requested version produced identical metrics on the same dataset/index hashes. No held-out retrieval was run. The latest full report is ignored `outputs/evals/dev-k5.json`; the original report is preserved at `outputs/evals/dev-k5-initial.json`. The committed [development baseline review](../evals/baseline-dev.md) records the measurements and limitations.

| Group | Answerable cases | Annotated-section recall@5 | MRR@5 | Evidence-group recall@5 |
| --- | ---: | ---: | ---: | ---: |
| Single release | 19 | 0.9737 | 0.8947 | 1.0000 |
| Comparison | 2 | 0.7500 | 0.4375 | 0.7500 |

Wrong-version chunks: 0/130 returned chunks, including 15 candidates for the three unsupported cases. Those cases have null recall/MRR/coverage: this retrieval-only report does not measure answer abstention. Comparison MRR averages reciprocal ranks independently per requested version within each question, then across comparison questions. One of two comparisons found any labeled evidence for both versions.

Reviewed cases: `dev-001` found the URI API but not its alternative release note (section recall 0.5, group recall 1.0). `dev-022` missed the 3.12 `glob.escape` anchor; the returned glob/re introductions/examples do not provide that needed instruction. On its 3.13 side, a useful What’s New glob passage ranked first but is absent from the frozen accepted labels, while the labeled API ranked second. This is a specific annotation-gap candidate; do not silently inflate scores by editing labels. Mixing two intents in the full comparison query is a plausible retrieval hypothesis, not a proven root cause. No rewrite, reranker, or tuning was tried.

Reports include dataset/index/source hashes, full model/policy/runtime metadata, code commit/dirty status and implementation hashes, labels/reference answers, complete retrieved passages, matched/missed regions, per-version candidate counts, and timing. The final run's 26 retrieval calls took about 3.54 seconds after model loading; timings are local observations, not controlled benchmarks. Model-service calls were zero; hardware/electricity costs were not estimated. Index bytes remained unchanged.

## Direct RAG implementation and first check, 2026-10-28

This section records the earlier offline checkpoint. Its missing-key/live-pending status was superseded by the verified live run below; the original reports remain unchanged.

The user explicitly requested one complete answer-pipeline learning unit before LangGraph. The design was explained first: reuse unchanged version-filtered retrieval; assign trusted evidence IDs; preserve whole passages/code and explicit context limits; generate a strict JSON status/answer/citation/gap record; validate structure; resolve display links from local metadata. Similarity is not an answerability threshold and model sufficiency judgments remain fallible.

Selected `nvidia/nemotron-3.5-super-vl:free` after checking official OpenRouter API/routing/error/structured-output documentation and the public model catalog on 2026-10-28. The catalog listed zero input/output prices, JSON-schema support, a 1,000,000-token context, and a 131,072-token provider output cap. `configs/generation.json` uses temperature 0, max output 1,600 tokens, max serialized prompt 24,000 bytes, and 45-second socket timeouts. Reasoning is disabled. Temperature 0 does not guarantee deterministic generation. Every live call rechecks prices, sends zero prompt/completion/request price caps, disables fallbacks and context transforms, and makes no automatic retry. No paid route is substituted. Returned base/canonical IDs are accepted only for the requested model and recorded separately.

Generation sends the question and selected public passage text/heading/anchor/hash metadata through OpenRouter to its provider. The selected free endpoint logs session data for security/product improvement and prohibits confidential/personal data. Setup, data disclosure, free-tier constraints, code paths, failure behavior, commands, and limits are in [the answer guide](answers.md). No credential was read into a report or written to source/Git. The key is read from the environment at request time; `.env` is not automatically loaded.

Real development prompt inspection used only dev-001 (URI 3.13), dev-014 (copyfile/copy2 3.12), dev-004 (URI evidence gap 3.12), and dev-023 (Kubernetes outside corpus). All four fit the budget with five complete passages each and zero omissions: 8,138 / 9,961 / 7,347 / 7,725 serialized message bytes respectively. Every supplied passage matched the requested release and content hash. E1 in dev-001 contains the actual `Path.from_uri('file:///etc/hosts')` example. Dev-014 supplies both `copyfile`'s no-metadata behavior and `copy2`'s qualified preservation behavior. The other two prompts do not supply the requested instructions; appropriate abstention remains to be verified in live output. This source/prompt review was authored by the implementing assistant, not an independent human.

Actual local reports: `outputs/answers/openrouter-model-verification.json`, `dev-prompts.json`, `uri-prompt.json`, and `dev-live-attempt.json`. Prompt-only commands succeeded. The application HTTP client also read the real public catalog successfully with normal TLS verification and no key/question/evidence sent. The live-sample command exited 1 at the missing-key configuration check before any provider HTTP request; first case is an error, remaining cases not attempted, all generated-answer fields null. No live correctness/support/citation/abstention scores are invented. The report records four as the request ceiling, not an actual completion count. See [the development generation check](../evals/generation-dev-review.md).

Verified with the full 110-test offline suite and `git diff --check`. A hash comparison of 86 existing corpus/raw/parsed/chunk/index/label/retrieval-report files found no changes. Both frozen dataset hashes still match the prior checkpoint. Held-out files were hash-compared for preservation only; their questions were not retrieved or generated. The existing index was neither rebuilt nor tuned. Existing user modifications and prior untracked evaluation work were preserved; no commit/push was made.

## Verified live baseline and semantic review, 2026-10-29

The user configured OPENROUTER_API_KEY and successfully ran `ask` and `evaluate-answers`. This chat inspected `outputs/answers/dev-20261029T034534302245Z.json` itself and reviewed the answers against their supplied passages. Report SHA-256: `603e6f1498bb8f7d054c27eb906c8c668910800cf4c93d8454ebd9b503d9594c`. All four outcomes are generated, all finish reasons are `stop`, all structural-validation fields are true, and requested/returned model IDs are `nvidia/nemotron-3.5-super-vl:free`. Each records zero cost, no automatic retries, and disabled fallbacks. Total reported usage is 8,755 prompt + 460 completion = 9,215 tokens; summed generation HTTP latency is about 5.938 seconds, excluding preflight/local retrieval/loading. These are four-run observations, not a performance/billing guarantee.

Read-only checks confirmed the live report's index SHA `1c50c846cbcfc9e27e0dbe038a66915f7821a7aec58ba9da2510e613ae3ebb2d`, dev dataset SHA, and all 16 implementation/packaging hashes still match current files. Each of the 20 supplied passages matches the indexed chunk text, content/source metadata, heading, anchor, URL, and requested product/version. Prompt sizes/hashes and cited-evidence records match the supplied messages/map; no chunks were omitted. No new retrieval, provider request, embedding run, or index rebuild was needed.

The assistant's qualitative findings are saved separately in [the live development review](../evals/generation-dev-review.md):

- dev-001 / Python 3.13: conversion, examples, invalid-input conditions, and addition note are supported by E1. Citations appear only at the end; E2 is general URI context rather than support for the final error/version claims. Claim-local placement/coverage is not established by valid IDs.
- dev-014 / Python 3.12: the core `copyfile`/`copy2` distinction and use of `copystat` are correct. The opening wording is too categorical; later “attempts to preserve” helps, but explicit platform/metadata limits from the supplied E1/E2 are omitted. E1/E4 are relevant citations, grouped at paragraph end. This is a known qualification/completeness limitation, not a fully clean semantic pass.
- dev-004 / Python 3.12: appropriately identifies missing conversion evidence and avoids claiming release-wide feature absence.
- dev-023 / Python 3.13: appropriately declines to invent Kubernetes resource limits from unrelated Python passages.

This verifies a **working direct baseline RAG**, with two supported-question answers and two appropriate evidence-limited abstentions in this fixed sample. It does not establish general accuracy, calibrated sufficiency, complete citation coverage, or independent human review. No live partial outcome or version-comparison answer was exercised. Independent retrieval-label review and broader answer-quality validation remain open.

The original report and its pending/null semantic-review fields are preserved as saved; the dated Markdown review records subsequent judgments. Earlier prompt-only and missing-key reports are retained. A final byte-hash comparison found all 111 protected corpus/config/metadata/index/label/report artifacts unchanged; implementation hashes still match, local Markdown targets resolve, and `git diff --check` passes. This session changes documentation only and does not rerun the 110-test suite or access provider credentials. LangGraph is explained in [a proposed first unit](langgraph-first-step.md); no graph code or dependency has been added.

## Decisions and limits to retain

- Version labels are strings identifying release lines, not immutable initial-release snapshots. Fetch time and SHA-256 identify downloaded bytes. A fresh ingestion can change hashes when upstream pages change.
- Python HTML canonical links may point to the moving `/3/` alias. Retain the manifest's `/3.12/` and `/3.13/` URLs for citations. The final response URL records redirects, not an extracted canonical link.
- A release note can mention earlier releases. Its document version does not establish the version of every API in its text.
- `source_terms_url` records the external documents' license terms, independently of DocLens's own code license. The user agreed to keep the link. Recording it has no fee; future API/hosting costs are separate.
- Answers should cite the retrieved evidence supporting their claims, not list the whole corpus. Local paths and license metadata generally stay internal.
- The parser is scoped to observed Python/Sphinx layouts. Images are not interpreted and complex table relationships are not modeled. Source presence/absence must not be inferred solely from retrieval results.
- Raw HTML is retained for debugging; indexed payloads retain source hashes and explicit version citations. Development retrieval metrics use provisional labels. Four live development outputs now have a qualitative assistant review; held-out outputs and numeric claim-support/citation-quality scores have not been measured.
- Answer validation checks IDs, versions, formatting/status consistency, and finish reasons. It requires citations for substantive output but does not prove individual claim support, complete citation coverage, correct generated code, or calibrated sufficiency. Insufficiency is distinct from provider/invalid-response errors. The renderer supplies links from trusted metadata; model-authored HTTP/Markdown links are rejected.
- Generation uses a conservative UTF-8 byte/schema/framing admission estimate, not the model's exact tokenizer. Whole passages are omitted explicitly when the prompt budget fills; a too-large first passage fails. No passage/code is silently cut. Socket timeouts are not strict overall wall-clock deadlines. Free availability and serving weights can change.
- Evaluation coverage is at source/API-anchor granularity. A hit can contain another paragraph from the region; source-quote validation is not entailment checking. Valid unannotated alternatives can also depress scores. Do not turn these metrics into claims of answer correctness or broad production accuracy.
- The character target is a soft limit for structured blocks. Current token preflight fits every chunk, but a different embedding model may need another explicit policy. No-overlap and anchor boundaries can produce small or context-limited chunks; these are baseline tradeoffs to evaluate, not proven optimal choices.
- Keep `docs/learning-notes.md` for the user's own explanations; do not invent understanding or overwrite those notes.

## Commands and tool-environment notes

From the repository root:

```bash
uv run python -m doclens ingest
uv run python -m doclens parse
uv run python -m doclens chunk
uv run python -m doclens chunk --source-id python-3.13-pathlib
uv sync --extra retrieval
uv run --extra retrieval python -m doclens index
uv run --extra retrieval python -m doclens search "How do I create a path from a file URI?" --version 3.13 --top-k 3
uv run --extra retrieval python -m doclens evaluate --split dev --top-k 5
uv run --extra retrieval python -m doclens ask "How do I create a path from a file URI?" --version 3.13 --inspect-prompt
uv run --extra retrieval python -m doclens ask "How do I create a path from a file URI?" --version 3.13
uv run --extra retrieval python -m doclens evaluate-answers --inspect-prompt
uv run --extra retrieval python -m doclens evaluate-answers
uv run python -m unittest discover -s tests -v
```

In this tool environment, use `UV_CACHE_DIR=/private/tmp/doclens-uv-cache` for uv if needed. Approved network access was needed for ingestion/dependency/model downloads; TLS verification remained enabled. A plain Python model-metadata request had an issuer-trust error; the system HTTPS client resolved the revision and the model library downloaded the pinned files successfully without disabling certificate checks. `HF_HUB_OFFLINE=1` was used for cached-model build/query verification. Model loading can emit upstream library messages to stderr.

## Next feature

The user asked to explain the first useful LangGraph unit after updating this baseline checkpoint. [The proposal](langgraph-first-step.md) introduces typed workflow state, prepare/generate/validate nodes reusing existing functions, an explicit prompt-inspection route, terminal error/empty-evidence behavior, and local node-update traces. Preserve the direct pipeline as a reference; verify graph parity offline with injected completions and at most one generation per answer. No LangGraph implementation was requested in this turn; do not treat the proposal as implemented or start it automatically.

Known answer refinements remain explicit preservation limits and claim-local citation placement; these need their own focused change/review rather than a graph-quality claim. Independent retrieval-label review also remains open, including the dev-022 candidate alternative. Version corrected labels and preserve frozen scores/reports. Keep held-out retrieval/generation reserved, and avoid unnecessary baseline rebuilds, tuning, or provider calls. Query rewriting, comparisons, hybrid retrieval, reranking, persistence, and UI remain later work.
