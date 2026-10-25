# Current learning checkpoint

Last updated: 2026-10-25 (Asia/Kolkata).

## Goal and working agreement

Build DocLens to demonstrate understanding of RAG while learning LangGraph. Teach one complete useful feature per lesson, combining design, implementation when requested, and verification. The user found individual file-writing exercises too granular. Explain the decisions and code so the user can understand them.

Public descriptions focus on DocLens's purpose and honest capabilities, rather than calling it a portfolio project. Learning goals remain in the roadmap, learning notes, and assistant instructions. Read `AGENTS.md` for the full working agreement and resume here without asking the user to explain the project again.

## Verified implementation

Milestone 1 is complete for the selected corpus. The latest live run of `uv run python -m doclens ingest` downloaded and parsed all 20 manifest sources. No chunking, embeddings, index, retrieval, answer generation, evaluation results, or LangGraph workflow exist yet.

The components are:

- `corpus/sources.json`: explicit curated sources, including source IDs, product, version strings, document type, HTTPS URL, raw destination, and source-terms URL.
- `src/doclens/manifest.py`: loads and validates the complete manifest before network requests, including required string fields, HTTPS page URLs, unique IDs/paths, and HTML destinations under `data/raw/`.
- `src/doclens/fetch.py`: downloads raw bytes with a 30-second socket timeout. Before reading or writing, final URLs must retain the requested HTTPS host/port and Python version prefix. Empty and non-HTML responses are rejected. HTTP protocol exceptions, including interrupted reads, become readable source-specific errors through the CLI.
- `src/doclens/files.py`: shared atomic file replacement. HTML and metadata are separate writes, not a single transaction; consumers must check their hashes. Old snapshots are not archived.
- `src/doclens/parse.py`: verifies raw size/hash and source metadata, selects the Python/Sphinx main article region, and saves structured JSON sections with heading paths and typed blocks. It preserves API signatures, code indentation/newlines/prompts, actual source anchors, source metadata, and version-specific citation URLs. Paragraphs, signatures, code, bare list items, and simple table rows remain distinct.
- `src/doclens/__main__.py`: `ingest` downloads then parses each source in order. Separate `fetch` and offline `parse` commands remain available. All accept `--manifest PATH`, with paths relative to the repository root.
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

The offline suite has 22 passing tests. These cover downloader refresh/provenance, redirect rejection and allowed redirects, HTTP read failures and previous-file preservation, manifest validation, parser structure and code whitespace, unsupported/empty layouts, altered raw content, version metadata mismatch, deterministic offline parsing, and complete-ingestion success and failure. Ingestion tests verify that invalid manifests make no network requests and that a later parse failure leaves earlier completed documents available.

The user's earlier review recommendations are resolved. The response fixture now returns a version-appropriate final URL. Failure tests also exercise interruption between HTML and metadata writes (the parser rejects the pair and preserves prior parsed output), and a two-source fetch whose second read fails (first success remains valid and previous second-source files are preserved).

## Decisions and limits to retain

- Version labels are strings identifying release lines, not immutable initial-release snapshots. Fetch time and SHA-256 identify downloaded bytes. A fresh ingestion can change hashes when upstream pages change.
- Python HTML canonical links may point to the moving `/3/` alias. Retain the manifest's `/3.12/` and `/3.13/` URLs for citations. The final response URL records redirects, not an extracted canonical link.
- A release note can mention earlier releases. Its document version does not establish the version of every API in its text.
- `source_terms_url` records the external documents' license terms, independently of DocLens's own code license. The user agreed to keep the link. Recording it has no fee; future API/hosting costs are separate.
- Answers should cite the retrieved evidence supporting their claims, not list the whole corpus. Local paths and license metadata generally stay internal.
- The parser is scoped to observed Python/Sphinx layouts. Images are not interpreted and complex table relationships are not modeled. Source presence/absence must not be inferred solely from retrieval results.
- Raw HTML is retained for debugging. Parsed sections are not retrieval chunks yet. No retrieval or answer-quality scores have been measured.
- Keep `docs/learning-notes.md` for the user's own explanations; do not invent understanding or overwrite those notes.

## Commands and tool-environment notes

From the repository root:

```bash
uv run python -m doclens ingest
uv run python -m doclens parse
uv run python -m unittest discover -s tests -v
```

In this tool environment, the default uv cache is outside the writable sandbox. Use `UV_CACHE_DIR=/private/tmp/doclens-uv-cache` for tool-run uv commands if needed. The sandbox also could not resolve network hosts; approved network access succeeded for the live ingestion. TLS verification remained enabled, and no project workaround was added. These restrictions do not indicate a manifest or JSON error.

## Next feature

Begin Milestone 2 with typed document/chunk records and a chunker as one complete learning unit. Read the parsed JSON and [architecture](architecture.md), explain document vs. section vs. chunk, choose and record a simple baseline chunking policy, preserve source/version/heading/anchor metadata and code structure, use stable identifiers, and expose inspectable output with meaningful checks.

Do not repeat corpus selection, downloader, or parser work. Do not jump to embedding providers, answer generation, or LangGraph before the chunking inputs and output are understood. Keep feature-sized lessons and update this checkpoint after meaningful progress.
