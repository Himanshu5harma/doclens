# Local semantic retrieval baseline

## What the vectors do

An embedding model converts text into a list of numbers. The model places related text near each other in that vector space, so a question can find a passage even when its wording differs. This is a learned similarity signal, not a guarantee that the passage answers the question.

The baseline normalizes vectors to length one. Their dot product is then cosine similarity. Search filters the product/version in SQLite first, computes exact similarity for that candidate set, and selects the highest scores. It returns passages, ranks, source metadata, and citation URLs.

For 1,474 chunks, an exact scan makes the behavior easy to inspect. SQLite persists metadata and vectors without a separate database service. This is linear scanning within a version; a much larger corpus may need a different storage/search adapter after measurement.

## Model and resource decisions

The selected model is [nomic-ai/modernbert-embed-base](https://huggingface.co/nomic-ai/modernbert-embed-base), pinned to commit `d556a88e332558790b210f7bdbe87da2fa94a8d8`. The model card documents the required `search_document: ` and `search_query: ` prefixes and 768-dimensional output. The downloaded model configuration establishes an 8,192-token sequence limit. Its published license is Apache-2.0.

[configs/retrieval.json](../configs/retrieval.json) records the model ID/revision, dimensions, token limit, prefixes, batch size 8, and four CPU threads. The baseline runs on CPU with L2 normalization and full 768-dimensional vectors; it does not use dimensional truncation. Exact installed library versions are pinned by `uv.lock` and saved in index metadata.

This choice keeps inference local, with no model API key or per-request service charge. It requires a one-time model download of about 596 MB plus the optional Python/PyTorch dependencies, local disk space, RAM, and CPU time. It has not been shown to be the best model for this corpus. These are baseline choices to evaluate, not benchmark conclusions.

All document and query inputs are tokenized with their prefixes and special tokens before encoding. Inputs exceeding the configured/model limit fail instead of being silently truncated. The largest current document input is 1,932 tokens, so both oversized datetime code chunks fit intact without changing the reviewed chunking policy. Library default prompts are disabled because the adapter supplies prefixes explicitly.

## Install, build, and search

From the repository root:

```bash
uv sync --extra retrieval
uv run --extra retrieval python -m doclens index
uv run --extra retrieval python -m doclens search "How do I create a path from a file URI?" --version 3.13 --top-k 3
```

Indexing refreshes verified chunk bundles from the active manifest, loads the pinned model (downloading it on first use), checks token lengths, encodes all passages, and writes `data/indexes/baseline.sqlite3`. The model cache is under ignored `data/models/`. The manifest and raw/parsed inputs already need to exist; run `ingest` first on a fresh checkout.

The default index records all 20 source documents. Index inputs follow the current manifest, so stale files from removed sources do not enter the new index. Configuration and inputs can be selected explicitly:

```bash
uv run --extra retrieval python -m doclens index --config configs/retrieval.json --manifest corpus/sources.json --max-chars 2000 --index data/indexes/baseline.sqlite3
```

Search requires a version and supports `--product`, `--top-k`, `--index`, and `--json`. It opens SQLite read-only and uses the embedding configuration stored in that index, not a possibly edited configuration file. Query-model files must already be cached; search does not download them. The optional dependencies still need to be installed. For a fully offline build after the initial model download, set `HF_HUB_OFFLINE=1` when running `index`.

```bash
uv run --extra retrieval python -m doclens search "Serialize a Python dictionary to a JSON string" --version 3.12 --top-k 3 --json
```

Text output prints the complete returned passages. JSON output includes the query, requested version/product, filtered candidate count, model/revision, and typed results with rank, score, chunk ID, text, source/version/hash metadata, heading path, and citation URL. Model loading may emit library progress messages to stderr.

## Read the code in this order

1. [embeddings.py](../src/doclens/embeddings.py): `EmbeddingConfig` records the contract; `LocalEncoder` applies prefixes, checks token lengths, and encodes locally. Heavy imports are lazy, so ingestion/chunking and unit tests do not need a model download.
2. [retrieval.py](../src/doclens/retrieval.py): `collect_chunks()` follows the active manifest; `build_index()` stores complete chunk payloads and little-endian float32 vectors; `search_index()` filters with SQL before decoding/scoring candidates.
3. [records.py](../src/doclens/records.py): `SearchResult` and `SearchResponse` define inspectable typed output.
4. [__main__.py](../src/doclens/__main__.py): CLI wiring for the explicit `index` and `search` actions.

The SQL candidate filter is:

```sql
SELECT chunk_id, payload, embedding
FROM chunks
WHERE product = ? AND version = ?
ORDER BY chunk_id;
```

Only these rows are scored. Ties are broken by chunk ID. Scores are cosine similarity, not probabilities or calibrated confidence.

## Persistence and updates

The index contains a primary-keyed chunk table, a product/version index, and metadata for the embedding configuration/runtime, chunking policy, manifest hash, chunk-set fingerprint, build timestamp, input token maximum, and source/chunk counts. Full chunk payloads retain the evidence provenance and piece offsets.

Rebuilding performs a complete replacement: current IDs/payloads/vectors replace the previous set. This removes stale chunks and sources and refreshes metadata for IDs whose text did not change. It currently re-encodes every chunk; no incremental embedding cache is implemented. Build a separate `--index` path when retaining experiments with another model or policy.

Encoding and validation happen before database replacement. SQLite is built in a temporary file, committed and closed, then atomically replaces the old path. A failed validation, encoding, or database build leaves the previous index available. Tests cover these failure paths. A search sees the saved index snapshot and does not check current ingestion files; after changing the corpus, explicitly rebuild the index. Searching never fetches documents or updates the index.

## Verification on 2026-10-27

- The actual pinned local model encoded all 1,474 chunks into 768-dimensional normalized vectors without truncation. Maximum document length, including prefix/special tokens: 1,932 of 8,192 tokens.
- Two actual builds produced 1,474 rows with unique IDs, retaining the 720/754 version split and the same chunk-set fingerprint. This verifies replacement behavior; SQLite file bytes need not match because build timestamps change.
- Index payload text hashes and source/version columns matched, all stored vectors had the expected length and unit norm within float32 tolerance, and searches left the database bytes unchanged.
- All 57 offline tests passed. Artificial vectors isolate filter-before-ranking, scores, ties, configuration mismatches, stale-row removal, metadata refresh, token overflow, invalid vectors, failed-build preservation, consistent manifest capture, and JSON CLI behavior. Those tests establish behavior, not semantic quality.

Observed real-model smoke results at top-k 3:

| Query | Version | First result | Observation |
| --- | --- | --- | --- |
| Create a path from a file URI | 3.13 | `pathlib.Path.from_uri`, score 0.7088 | Requested API passage ranked first |
| Same URI question | 3.12 | `pathlib.PurePath.as_uri`, score 0.5752 | Related reverse operation; similarity alone does not establish support |
| Convert a wildcard pattern to a regular expression | 3.13 | `pathlib` pattern-language section, score 0.6564 | `glob.translate` ranked second; a concrete ranking case to evaluate |
| Serialize a dictionary to a JSON string | 3.12 | `json.dumps`, score 0.6426 | Relevant serialization passage ranked first |

All returned results stayed within the requested version; the candidate pools were 720 for 3.12 and 754 for 3.13. These four smoke queries are not a labeled evaluation set, a held-out split, or measured recall/MRR. No similarity threshold, insufficient-evidence decision, answer generator, or LangGraph workflow is implemented. Next follow [the evaluation plan](../evals/README.md) before tuning retrieval.

The local smoke details are stored in ignored `data/reports/retrieval-smoke.json`; the CLI does not create this report automatically.
