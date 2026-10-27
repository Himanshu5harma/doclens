# Baseline chunking

## Document, section, and chunk

A **document** is one parsed source page, such as Python 3.13's pathlib reference. It has a title, source identity, version, raw-content hash, and sections.

A **section** is an author-defined part of that page. Its heading path gives context: for example, pathlib → Concrete paths → Parsing and generating URIs. Sections can be very short or very long, so they are not automatically suitable retrieval units.

A **chunk** is a passage prepared for later retrieval. It contains evidence from one section and one contiguous source-anchor group. Its metadata points back to the original page and blocks. This feature prepares those passages; it does not embed, index, or retrieve them.

## Policy: section-anchor-v1

The default is a **2,000-character target**, measured with Python's `len(str)`, including heading/anchor context and separators. This counts Unicode code points, not UTF-8 bytes or model tokens. The target is an inspectable starting point and has not been optimized with retrieval evaluation.

The algorithm processes sections and their blocks in parsed order:

1. Start a new group when the section or effective source anchor changes. A missing block anchor falls back to the section anchor.
2. Repeat the heading path in the rendered text. Also include the anchor label when it differs from the section anchor, so a split API description still carries its identifier.
3. Greedily append whole adjacent blocks while the rendered text fits. Separate their text with two newlines.
4. Split an oversized paragraph or bare list item at the last available whitespace. If a word has no available boundary, split at a character boundary. Keep all characters, including boundary whitespace, in the pieces.
5. Keep code, signatures, and table rows whole. A structured block that cannot fit is emitted alone with `oversized: true`.
6. Use no overlap. No source characters are intentionally repeated between pieces. Repeated heading context is additional context, not an overlapping source span.

If heading/anchor context alone consumes the target, the command fails with an instruction to increase `--max-chars`. It does not generate empty chunks or discard content. Empty sections produce no chunks.

These choices keep API evidence and code inspectable, at the cost of short chunks and occasional oversized ones. Related prose may span a chunk boundary; an example may be separated from its preceding explanation. The repeated context helps identify the subject but is not a substitute for evaluating retrieval. Table rows can be separated from their headers; complex table semantics were already outside the parser's scope.

There is no sentence model, tokenizer, overlap tuning, or code summarization in this chunking baseline. The separate retrieval component now performs token preflight: all current chunks, including the oversized examples, fit its pinned encoder's 8,192-token limit (largest input: 1,932 tokens). A different model may need another explicit policy; text must not be silently truncated.

## Records and code layout

[records.py](../src/doclens/records.py) defines frozen standard-library dataclasses:

- `Source`: product, string version, source ID, document type, page URL, raw HTML hash, fetch time, and source-terms URL.
- `Block` and `Section`: typed block kinds, text, heading paths, anchors, and citation URLs.
- `Document`: the source, title, sections, and a fingerprint of the parsed title/sections.
- `ChunkPiece`: a whole block or a prose fragment, with its original block index and half-open character offsets `[start_char, end_char)`.
- `Chunk`: self-contained provenance, context, pieces, rendered text, text hash, stable ID, and oversized flag.

Type annotations alone do not validate JSON. `document_from_dict()` checks the existing parsed schema before creating these records, including string versions, supported block kinds, heading paths, and citation URLs that match the source page and anchor. The reviewed parser keeps its existing JSON format; this adapter defines the boundary for the new component.

[chunk.py](../src/doclens/chunk.py) separates the work:

- `_pieces()` partitions oversized prose while retaining exact source offsets.
- `chunk_document()` is the pure packing/identity algorithm; it does no I/O.
- `chunk_source()` checks local provenance, loads typed records, and replaces one output file atomically.
- `ChunkPolicy` records the algorithm version, target, size unit, and split/overlap choices. Its fingerprint is saved in every chunk and output bundle.

Before chunking, the file wrapper checks that the parsed source metadata equals the download sidecar, agrees with the current manifest, and matches the raw HTML's hash and size. Fetching a newer raw file without updating its parsed document fails this check. Run `parse` after `fetch`, or use `ingest`, before chunking again.

## Hashes and stable identity

| Field | Meaning |
| --- | --- |
| `chunk.source.content_hash` | SHA-256 of the original HTML bytes; copied from the downloader's `sha256` |
| `chunk.document_content_hash` | Hash of the typed parsed title and sections, excluding fetch metadata |
| `chunk.content_hash` | SHA-256 of the rendered chunk text, including repeated context |
| `bundle.parsed_file_sha256` | SHA-256 of the exact parsed JSON input bytes |
| `policy_id` | Fingerprint of the complete recorded chunking policy |

Chunk IDs are SHA-256 fingerprints of source identity (product, version, ID, page URL), policy, heading/anchor context, and the chunk's content/kinds/citation locations. An occurrence number distinguishes identical repeated passages. IDs exclude fetch timestamps, raw snapshot hashes, document-wide content hashes, and absolute block positions.

This means:

- Unchanged inputs and settings reproduce the same chunks, IDs, and output bytes.
- A footer-only HTML change or fetch-time change can update provenance while preserving IDs when the parsed evidence is unchanged.
- Changed evidence, citation context, source version, or policy produces different affected IDs. Repacking can change multiple chunks within an affected group.
- An unchanged passage can retain its ID after an unrelated earlier insertion. Its block offsets and provenance still refresh.
- Inserting/removing identical repeated passages can change their occurrence assignment. An ID identifies the scoped content occurrence, not a permanent physical address in a page.

After an update, re-run ingestion and chunking. The command atomically replaces the source's entire bundle for that policy, so that file contains only the current chunk set. The separate `index` command now refreshes chunks and builds a complete replacement database from the active manifest, updating payloads and removing stale IDs/sources. Cached chunk files for sources removed from the manifest are not automatically pruned; consumers must follow the current manifest, not indiscriminately glob every cached file or policy directory.

Algorithm changes should increment the policy name/version. Changing only the target uses a separate output directory and identity namespace, allowing baseline experiments to coexist.

## Run and inspect

From the repository root, using existing local ingestion outputs:

```bash
uv run python -m doclens chunk
uv run python -m doclens chunk --source-id python-3.13-pathlib
uv run python -m doclens chunk --max-chars 2500
```

`--manifest PATH` selects another manifest. Chunking is offline. It writes one JSON bundle per source, for example:

```text
data/chunks/section-anchor-v1-2000/python/3.13/pathlib.html.json
```

Each bundle contains its schema version, policy configuration/fingerprint, parsed-file hash, and a `chunks` list. Inspect a real API chunk:

```bash
uv run python - <<'PY'
import json
from pathlib import Path

path = Path("data/chunks/section-anchor-v1-2000/python/3.13/pathlib.html.json")
bundle = json.loads(path.read_text(encoding="utf-8"))
chunk = next(c for c in bundle["chunks"] if c["anchor"] == "pathlib.Path.from_uri")
print("ID:", chunk["chunk_id"])
print("Version:", chunk["source"]["version"])
print("Citation:", chunk["url"])
print("Raw content hash:", chunk["source"]["content_hash"])
print("Characters:", len(chunk["text"]), "Oversized:", chunk["oversized"])
print(chunk["text"])
PY
```

The reviewed example is 937 characters and contains the API signature, prose, intact URI examples, and its version note. To inspect an oversized code example, open the corresponding datetime bundle and select a chunk whose `oversized` field is true. Its single `pieces` entry retains the complete code and source offsets.

## Verified baseline on 2026-10-26

| Release line | Documents | Chunks | Oversized chunks |
| --- | ---: | ---: | ---: |
| 3.12 | 10 | 720 | 1 |
| 3.13 | 10 | 754 | 1 |
| Total | 20 | 1,474 | 2 |

All 7,099 parsed blocks reconstructed exactly from their pieces, without gaps or overlap. All 650 code examples remained single intact pieces. All chunk IDs were unique across the corpus, hashes and metadata matched, and a second run produced byte-identical bundles. The two oversized records preserve datetime code examples. Rendered sizes ranged from 46 to 6,015 characters, with a median of 499; this shows how section/anchor boundaries can produce small chunks despite a 2,000-character target.

The local review details are saved in ignored `data/reports/chunk-review.json`; `chunk` does not generate this review report automatically.

All 41 offline tests passed. The chunking tests cover exact size boundaries including context/separators, whitespace and Unicode splitting, oversized structured blocks, section/anchor boundaries, metadata, repeatability, duplicate IDs, updates, stale provenance, output replacement, separate policies, and the offline CLI. These are integrity and behavior checks, not retrieval-quality measurements.

```bash
uv run python -m unittest discover -s tests -v
```
