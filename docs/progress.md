# Current learning checkpoint

Last updated: 2026-10-24 (Asia/Kolkata).

## Goal and working agreement

Build DocLens to demonstrate understanding of RAG while learning LangGraph. The user clarified that individual file-writing exercises were too granular: now teach one complete useful feature per lesson, combining design, implementation when requested, and verification. Explain the code so the user can understand it. Resume here in new chats; read `AGENTS.md` for the full working agreement.

## Verified repository state

- The repository contains a manifest reader, downloader, CLI, setup instructions, architecture, roadmap, evaluation plan, and a learning-notes template.
- `uv run python -m doclens fetch` downloads the curated manifest sources. Parsing, chunking, retrieval, generation, and LangGraph are not implemented.
- At the user's explicit request, the assistant created `corpus/sources.json` with the two starter pathlib sources, including their version labels and source-terms URLs. Both pages have now been downloaded and verified.
- The manifest passes `python -m json.tool`. Both entries have the planned metadata and distinct source IDs and local paths.
- `src/doclens/manifest.py` exposes `load_sources(manifest_path: Path) -> list[dict]`. It reads UTF-8 JSON, checks required nonempty string fields, HTTPS page URLs, distinct IDs and paths, and HTML destinations under `data/raw/`, then returns the `sources` list. The downloader validates the manifest before starting network requests.
- Verified the reader against the actual manifest using `uv run python` with the temporary cache override below: it returns a list with source IDs `python-3.12-pathlib` and `python-3.13-pathlib`, preserving string versions `3.12` and `3.13`.
- The user's earlier file-not-found error is resolved by creating the manifest. During assistant validation, `uv` could not access its default cache under the filesystem sandbox; rerunning with `UV_CACHE_DIR=/private/tmp/doclens-uv-cache` succeeded. This does not indicate a JSON error or require a project configuration change.
- `src/doclens/fetch.py` exposes `fetch_source(source, root=...)`. It uses `urllib.request`, a 30-second socket timeout, and a project User-Agent. It rejects empty and non-HTML responses, preserves raw bytes, and records the original source fields, final response URL, UTC fetch time, HTTP status, content type, size, and SHA-256 in a sidecar `<filename>.metadata.json`.
- Repeat downloads refresh the same files. Each file replacement is atomic; the HTML and metadata pair is not a single transaction. Network failures occur before writes. Old snapshots are not archived.
- Live verification succeeded: Python 3.12 HTML was 210,454 bytes (title identified 3.12.15), and Python 3.13 HTML was 244,770 bytes (title identified 3.13.17). Recomputed hashes, byte counts, version labels, and source metadata matched both sidecars; responses were HTTP 200. These are snapshots at download time, not fixed future sizes or patch versions.
- Six offline checks in `tests/test_fetch.py` passed via `uv run python -m unittest discover -s tests -v`: byte/provenance consistency, refresh behavior, preservation on network failure, empty/non-HTML rejection, invalid manifests, and both-version CLI downloads. CLI help/status and `git diff --check` also passed. Downloaded files remain ignored by Git.
- In this tool environment the live fetch first failed because sandbox networking could not resolve the host; rerunning the same command with approved network access succeeded. TLS verification remained enabled. No project network workaround or dependency was added.
- Repository instructions, this checkpoint, README usage, and architecture status are updated. The roadmap marks the manifest and starter fetch work done; corpus expansion and the remainder of ingestion remain open.
- Existing roadmap setup checkmarks predate this checkpoint; this documentation session did not rerun the development environment checks.

## Corpus plan discussed

Recommended product: Python. Version labels: `3.12` and `3.13` (strings).

Start with the same reference topic in each version to exercise provenance and later version filtering:

| Source ID | URL | Intended local path |
| --- | --- | --- |
| `python-3.12-pathlib` | https://docs.python.org/3.12/library/pathlib.html | `data/raw/python/3.12/pathlib.html` |
| `python-3.13-pathlib` | https://docs.python.org/3.13/library/pathlib.html | `data/raw/python/3.13/pathlib.html` |

Both entries use `product: "python"` and `document_type: "reference"`.

The two pages are a starter exercise, not the completed corpus. Subsequently add the corresponding What’s New pages, then curate toward 10–20 pages per release, including reference material and release notes. Do not mark corpus selection complete yet.

Useful later comparison: the official Python 3.13 pathlib documentation explicitly marks `Path.from_uri()` as added in 3.13. Evaluate claims against explicit evidence rather than assuming absence from an unsuccessful search.

## Manifest design and explanations already covered

Created file: `corpus/sources.json`, containing a top-level `sources` list. Each entry has:

- `source_id`: stable identity for a page and version.
- `product`, `version`, `document_type`: source metadata for later filtering and inspection.
- `url`: official source URL for fetching and citations.
- `local_path`: intended raw download location, relative to the repository root.
- `source_terms_url`: link to the source documentation's license terms, e.g. `https://docs.python.org/3.12/license.html` for the 3.12 source and the corresponding `/3.13/license.html` for 3.13.

The initially suggested nested license object was simplified to `source_terms_url`. The user questioned its purpose and cost, then agreed to retain a source-terms link. This is about the external documents, not choosing a license for DocLens's code. Recording the link has no fee. Any future API or hosting costs are separate.

The user also learned that answers should cite the sources supporting that answer, not list the entire corpus. Source URLs and versions travel with retrieved chunks; local paths and license metadata generally stay in internal records.

Version-specific documentation URLs can still change within a release line. Fetch timestamps and content hashes will later identify the downloaded snapshot.

## Next feature

Build the HTML parser as a complete learning unit: explain the design, extract article headings/paragraphs/code blocks from both saved pages, remove navigation noise, preserve anchors and source/version metadata, save inspectable structured output, and check examples against the originals. Verify raw-file hashes against sidecars when consuming them. Choose a proportionate parsing approach and explain any dependency before adding it.

The current feature is complete for the two starter sources; do not repeat manifest creation or downloader exercises. The corpus still needs expansion and release notes before Milestone 1 is complete.

The user explicitly authorized implementing the complete downloader. Continue in feature-sized lessons, explaining decisions and offering a concrete run/inspection command. Do not jump ahead to retrieval, generation, or LangGraph while teaching parsing.
