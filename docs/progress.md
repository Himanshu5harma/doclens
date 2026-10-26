# Current learning checkpoint

Last updated: 2026-10-26 (Asia/Kolkata).

## Goal and working agreement

Build DocLens to demonstrate understanding of RAG while learning LangGraph. Teach one complete useful feature per lesson, combining design, implementation when requested, and verification. The user found individual file-writing exercises too granular. Explain the decisions and code so the user can understand them.

Public descriptions focus on DocLens's purpose and honest capabilities, rather than calling it a portfolio project. Learning goals remain in the roadmap, learning notes, and assistant instructions. Read `AGENTS.md` for the full working agreement and resume here without asking the user to explain the project again.

## Verified implementation

Milestone 1 is complete and was reviewed with no blocking findings for the selected corpus. The live run of `uv run python -m doclens ingest` downloaded and parsed all 20 manifest sources. Milestone 2 now has typed document/chunk records and a verified baseline chunker. Embeddings, indexing, retrieval, answer generation, evaluation results, and LangGraph remain unimplemented.

The components are:

- `corpus/sources.json`: explicit curated sources, including source IDs, product, version strings, document type, HTTPS URL, raw destination, and source-terms URL.
- `src/doclens/manifest.py`: loads and validates the complete manifest before network requests, including required string fields, HTTPS page URLs, unique IDs/paths, and HTML destinations under `data/raw/`.
- `src/doclens/fetch.py`: downloads raw bytes with a 30-second socket timeout. Before reading or writing, final URLs must retain the requested HTTPS host/port and Python version prefix. Empty and non-HTML responses are rejected. HTTP protocol exceptions, including interrupted reads, become readable source-specific errors through the CLI.
- `src/doclens/files.py`: shared atomic file replacement. HTML and metadata are separate writes, not a single transaction; consumers must check their hashes. Old snapshots are not archived.
- `src/doclens/parse.py`: verifies raw size/hash and source metadata, selects the Python/Sphinx main article region, and saves structured JSON sections with heading paths and typed blocks. It preserves API signatures, code indentation/newlines/prompts, actual source anchors, source metadata, and version-specific citation URLs. Paragraphs, signatures, code, bare list items, and simple table rows remain distinct.
- `src/doclens/records.py`: frozen standard-library `Source`, `Block`, `Section`, `Document`, `ChunkPiece`, and `Chunk` dataclasses, a block-kind enum, and explicit validation of parsed JSON at the adapter boundary. The ingestion parser's JSON format remains unchanged. A document is one page, a section is author-defined heading context, and a chunk is a passage prepared for later retrieval.
- `src/doclens/chunk.py`: `chunk_document()` is the pure baseline algorithm; `chunk_source()` checks raw/sidecar/parsed provenance, loads typed records, and atomically replaces one source's chunk bundle. Pieces carry source block indices and exact half-open character offsets, permitting loss/duplication checks.
- `src/doclens/__main__.py`: `ingest` downloads then parses each source in order. Separate `fetch`, offline `parse`, and offline `chunk` commands remain available. All accept `--manifest PATH`, with paths relative to the repository root. `chunk` also accepts `--max-chars` and an optional exact `--source-id`.
- `pyproject.toml` / `uv.lock`: direct dependency `beautifulsoup4>=4.14,<5`, currently locked to 4.15.0, using Python's built-in `html.parser`.

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

The offline suite has 41 passing tests: the existing 22 ingestion checks plus 19 chunking checks. Chunking covers exact size boundaries including headers/separators, whitespace and Unicode splitting, oversized code/signatures/table rows, section/anchor boundaries, metadata, deterministic IDs and duplicate occurrences, update behavior, stale provenance, complete output replacement, separate policy directories, and the offline CLI. The earlier ingestion checks remain passing.

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

IDs fingerprint source identity, policy, context, and scoped passage content; duplicate occurrences get distinct IDs. Fetch time, raw snapshot hash, document-wide hash, and absolute positions are excluded, so unaffected passages can retain IDs after an unrelated edit or earlier insertion. Changed content/context or policy changes affected IDs, possibly through repacking. Always refresh provenance and offsets even when IDs are unchanged. Re-running replaces the source's whole bundle, dropping outdated IDs from that file. A future index must upsert current payloads and remove old source IDs absent from the current set. Cached outputs for removed manifest sources are not automatically pruned.

## Decisions and limits to retain

- Version labels are strings identifying release lines, not immutable initial-release snapshots. Fetch time and SHA-256 identify downloaded bytes. A fresh ingestion can change hashes when upstream pages change.
- Python HTML canonical links may point to the moving `/3/` alias. Retain the manifest's `/3.12/` and `/3.13/` URLs for citations. The final response URL records redirects, not an extracted canonical link.
- A release note can mention earlier releases. Its document version does not establish the version of every API in its text.
- `source_terms_url` records the external documents' license terms, independently of DocLens's own code license. The user agreed to keep the link. Recording it has no fee; future API/hosting costs are separate.
- Answers should cite the retrieved evidence supporting their claims, not list the whole corpus. Local paths and license metadata generally stay internal.
- The parser is scoped to observed Python/Sphinx layouts. Images are not interpreted and complex table relationships are not modeled. Source presence/absence must not be inferred solely from retrieval results.
- Raw HTML is retained for debugging. Parsed sections feed the new chunker; its typed chunks are inspectable local records, with no embedding/index/retrieval component. No retrieval or answer-quality scores have been measured.
- The character target is a soft limit for structured blocks. Oversized examples require an explicit policy when a future embedding model's input limit is chosen. No-overlap and anchor boundaries can produce small or context-limited chunks; these are baseline tradeoffs to evaluate, not proven optimal choices.
- Keep `docs/learning-notes.md` for the user's own explanations; do not invent understanding or overwrite those notes.

## Commands and tool-environment notes

From the repository root:

```bash
uv run python -m doclens ingest
uv run python -m doclens parse
uv run python -m doclens chunk
uv run python -m doclens chunk --source-id python-3.13-pathlib
uv run python -m unittest discover -s tests -v
```

In this tool environment, the default uv cache is outside the writable sandbox. Use `UV_CACHE_DIR=/private/tmp/doclens-uv-cache` for tool-run uv commands if needed. The sandbox also could not resolve network hosts; approved network access succeeded for the live ingestion. TLS verification remained enabled, and no project workaround was added. These restrictions do not indicate a manifest or JSON error.

## Next feature

The requested typed-record/chunking learning unit is implemented and verified. Review or explain the actual chunks with the user using [the inspection example](chunking.md#run-and-inspect), without repeating the build. The user's own explanations and evaluation of the tradeoffs are not assumed.

When the user is ready, continue Milestone 2 with embedding-model selection and a version-filtered persistent retrieval baseline, including typed search-result records. Address model input limits for the two oversized chunks before embedding; record model/configuration and explain cost/local-resource tradeoffs. No model or storage provider has been selected. Keep answer generation, LangGraph, and retrieval experiments in their later milestones. Do not change the reviewed corpus or optimize chunking without an identified need or measured evidence.
