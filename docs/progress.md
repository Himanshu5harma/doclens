# Current learning checkpoint

Last updated: 2026-10-27 (Asia/Kolkata).

## Goal and working agreement

Build DocLens to demonstrate understanding of RAG while learning LangGraph. Teach one complete useful feature per lesson, combining design, implementation when requested, and verification. The user found individual file-writing exercises too granular. Explain the decisions and code so the user can understand them.

Public descriptions focus on DocLens's purpose and honest capabilities, rather than calling it a portfolio project. Learning goals remain in the roadmap, learning notes, and assistant instructions. Read `AGENTS.md` for the full working agreement and resume here without asking the user to explain the project again.

## Verified implementation

Milestone 1 is complete and was reviewed with no blocking findings for the selected corpus. Milestone 2 now also has a complete local dense-retrieval baseline: typed chunks/results, a pinned embedding model, persistent SQLite indexing, and explicit version-filtered search. Answer generation, formal evaluation results, and LangGraph remain unimplemented.

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
- `src/doclens/__main__.py`: existing ingestion/chunk commands plus `index` and `search`. `index` supports manifest/config/index paths and chunk target; `search` requires an explicit `--version`, supports product/top-k/index/JSON output, and uses the configuration saved in the index.
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

The offline suite has 57 passing tests: 22 ingestion, 19 chunking, and 16 retrieval/encoder contract checks. The new checks cover filter-before-ranking (including an invalid vector in the excluded version), exact scores/ties, encoder compatibility, stale-row/source removal, metadata refresh, failed-build preservation, token limits including prefixes, invalid vectors, manifest snapshot consistency, and JSON CLI output. Test vectors establish behavior, not semantic quality.

The user's earlier review recommendations are resolved. The response fixture now returns a version-appropriate final URL. Failure tests also exercise interruption between HTML and metadata writes (the parser rejects the pair and preserves prior parsed output), and a two-source fetch whose second read fails (first success remains valid and previous second-source files are preserved).

## Verified chunking baseline

The selected `section-anchor-v1` policy uses a 2,000-character target, including repeated heading/anchor context and separators, with no overlap. It packs adjacent blocks without crossing a section or effective anchor. Oversized prose splits at whitespace, falling back to characters for long words; code, signatures, and table rows stay whole and are flagged oversized if necessary. A target too small for heading context fails clearly. Characters are not model tokens, and no retrieval quality has been measured.

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

## Decisions and limits to retain

- Version labels are strings identifying release lines, not immutable initial-release snapshots. Fetch time and SHA-256 identify downloaded bytes. A fresh ingestion can change hashes when upstream pages change.
- Python HTML canonical links may point to the moving `/3/` alias. Retain the manifest's `/3.12/` and `/3.13/` URLs for citations. The final response URL records redirects, not an extracted canonical link.
- A release note can mention earlier releases. Its document version does not establish the version of every API in its text.
- `source_terms_url` records the external documents' license terms, independently of DocLens's own code license. The user agreed to keep the link. Recording it has no fee; future API/hosting costs are separate.
- Answers should cite the retrieved evidence supporting their claims, not list the whole corpus. Local paths and license metadata generally stay internal.
- The parser is scoped to observed Python/Sphinx layouts. Images are not interpreted and complex table relationships are not modeled. Source presence/absence must not be inferred solely from retrieval results.
- Raw HTML is retained for debugging; indexed payloads retain source hashes and explicit version citations. No formal retrieval or answer-quality scores have been measured.
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
uv run python -m unittest discover -s tests -v
```

In this tool environment, use `UV_CACHE_DIR=/private/tmp/doclens-uv-cache` for uv if needed. Approved network access was needed for ingestion/dependency/model downloads; TLS verification remained enabled. A plain Python model-metadata request had an issuer-trust error; the system HTTPS client resolved the revision and the model library downloaded the pinned files successfully without disabling certificate checks. `HF_HUB_OFFLINE=1` was used for cached-model build/query verification. Model loading can emit upstream library messages to stderr.

## Next feature

Milestone 2 is implemented and behavior-checked. Explain vectors, prefixing, normalization/cosine, index snapshots, and filtering before ranking using the real search output if the user asks; their understanding is not assumed. Preserve the current model, chunking policy, and index as the untuned baseline.

Next is Milestone 3: read `evals/README.md`, build manually checked development questions with relevant source sections, reserve a held-out split before tuning, and compute defined retrieval metrics with saved configuration/failures. The four smoke queries have already been seen and can be development examples, not unseen held-out cases. Include paraphrases, exact terms, multiple-source needs, release distinctions, and missing evidence. Do not tune retrieval or add an answer generator, hybrid search, reranker, or LangGraph before measuring the baseline. LLM provider and UI remain undecided.
