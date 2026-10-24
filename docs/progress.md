# Current learning checkpoint

Last updated: 2026-10-24 (Asia/Kolkata).

## Goal and working agreement

Build DocLens to demonstrate understanding of RAG while learning LangGraph. Guide the user one small step at a time, explaining decisions and letting them write the implementation. Resume here in new chats; read `AGENTS.md` for the full working agreement.

## Verified repository state

- The repository contains a Python scaffold, setup instructions, architecture, roadmap, evaluation plan, and a learning-notes template.
- `src/doclens/__main__.py` reports scaffold status; ingestion, retrieval, generation, and LangGraph are not implemented.
- At the user's explicit request, the assistant created `corpus/sources.json` with the two starter pathlib sources, including their version labels and source-terms URLs. No documents have been downloaded.
- The manifest passes `python -m json.tool`. Both entries have the planned metadata and distinct source IDs and local paths.
- The user's earlier file-not-found error is resolved by creating the manifest. During assistant validation, `uv` could not access its default cache under the filesystem sandbox; rerunning with `UV_CACHE_DIR=/private/tmp/doclens-uv-cache` succeeded. This does not indicate a JSON error or require a project configuration change.
- Repository instructions, this checkpoint, and a README continuity link are in place. Ingestion is not implemented.
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

## Next small step

Teach a small standard-library Python function to read the manifest using `json` and `pathlib`. Explain how JSON objects and arrays become Python dictionaries and lists, then inspect the two source IDs as a concrete check. The manifest is created and syntax-checked; do not repeat the creation exercise.

Resume the default user-written teaching workflow: the user's request to create the manifest authorized that specific edit, not automatic implementation of later steps. Fetching and parsing follow in later steps; do not implement them all at once.
