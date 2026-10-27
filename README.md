# DocLens

A version-aware RAG assistant for technical documentation, with source citations and retrieval evaluation.

**Status: local semantic retrieval implemented.** The curated corpus has 20 official Python documentation pages across versions 3.12 and 3.13. Commands ingest documents, build inspectable chunks, persist local embeddings, and search within an explicit release. Answer generation, version-comparison workflows, and formal evaluation remain planned; retrieval quality has not been measured on a labeled dataset.

## The problem

Technical answers depend on the product version. A relevant passage from the wrong release can produce a convincing but incorrect answer. DocLens will retrieve evidence for the requested version, make sources inspectable, and explain when the indexed documents cannot support an answer.

## Planned demo

- Ask a question about a specific release and inspect the cited passages.
- Compare a feature across two releases, with evidence for both versions.
- Ask a question missing from the corpus and inspect an explicit insufficient-evidence response.
- Compare a simple retrieval baseline with measured improvements.

Start with one product and a small, curated collection of official documentation and release notes. Select and record the corpus before implementing ingestion.

## Development setup

Requires Python 3.12 or newer. From this repository, use either:

```bash
uv sync
uv run python -m doclens
```

Or use Python's standard environment tools:

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -e .
python -m doclens
```

Without a subcommand, the command prints the project status. No API key is needed for ingestion, chunking, or local retrieval. Retrieval has an optional dependency group and a one-time model download, described below.

## Ingest the corpus

From the repository root:

```bash
uv run python -m doclens ingest
```

This validates the manifest, then downloads and parses every source. Each release has the same nine library references plus its What’s New page. See [the corpus scope and inspection record](docs/corpus.md) for the selection, exclusions, and verified results. No model API is called.

The separate commands below let you inspect or repeat either stage. `ingest`, `fetch`, and `parse` all accept `--manifest PATH`. Re-running ingestion refreshes the same files; upstream documentation changes can produce different hashes.

## Download the corpus

From the repository root, run:

```bash
uv run python -m doclens fetch
```

The downloader validates `corpus/sources.json`, then fetches each listed page without crawling links. The corpus covers `pathlib`, `os.path`, `glob`, `shutil`, `tempfile`, `json`, `re`, `datetime`, `argparse`, and What’s New for each release.

Each source produces two files under ignored `data/`, for example:

```text
data/raw/python/3.12/pathlib.html
data/raw/python/3.12/pathlib.html.metadata.json
```

The HTML is saved as bytes so later parsing can be checked against the original content. The metadata contains the manifest record, final response URL, UTC fetch timestamp, HTTP status, content type, byte count, and SHA-256 hash. The hash fingerprints the downloaded bytes so changes can be detected even when the page URL stays the same. The final response URL records redirects; it is not an extracted HTML canonical link. Before reading or saving content, the downloader checks that this URL stays on the requested HTTPS host and port. For Python sources it must also retain the manifest's `/{version}/` path prefix; redirects to another release or the moving `/3/` alias are rejected.

Running the command again refreshes the same files. This stores the latest download, not an archive of every snapshot. Empty or non-HTML responses and network errors stop the command with an error. Interrupted HTTP reads and other HTTP protocol failures produce a readable error identifying the source, with a nonzero exit status. Previously completed sources remain on disk; a failed network request does not overwrite an existing download. Each file is replaced atomically, but HTML and metadata are two separate writes; the parser rejects a mismatched pair after an interrupted write, preserving any previous parsed output.

To use another manifest (its download paths are still relative to the repository root):

```bash
uv run python -m doclens fetch --manifest corpus/sources.json
```

## Parse the downloaded pages

After downloading, run from the repository root:

```bash
uv run python -m doclens parse
```

This command works offline. It verifies the raw HTML's SHA-256 hash and size against its metadata, checks the metadata against the manifest, and extracts only the article's main region. It writes one structured document per source:

```text
data/parsed/python/3.12/pathlib.html.json
data/parsed/python/3.13/pathlib.html.json
```

Each document retains the original source metadata and groups content into sections with heading paths and source anchors. Blocks distinguish paragraphs, API signatures, code, bare list items, and simple table rows. Code indentation, line breaks, and interactive prompts are preserved. Navigation, sidebar content, scripts, styles, and permalink symbols are excluded. Citation URLs retain the manifest's explicit version: the pages' HTML canonical links point to `/3/`, which could describe a different release.

Inspect the Python 3.13 URI example with:

```bash
uv run python - <<'PY'
import json
from pathlib import Path

document = json.loads(Path("data/parsed/python/3.13/pathlib.html.json").read_text())
for section in document["sections"]:
    for block in section["blocks"]:
        if block["anchor"] == "pathlib.Path.from_uri":
            print(block["kind"], block["url"])
            print(block["text"])
PY
```

The parser uses Beautiful Soup with Python's `html.parser` and targets the current Python/Sphinx layout. It fails on pages without the expected article region, rather than treating the entire page as evidence. Images are not interpreted, complex table relationships are not modeled, and future documentation layouts may need a new adapter. Repeating `parse` with unchanged inputs and parser produces the same JSON files. The chunking command below turns parsed sections into passages for later retrieval.

On a failure, completed sources remain available and the command exits with an error. A hash or source-metadata mismatch requires re-fetching or correcting the manifest before parsing.

## Build and inspect baseline chunks

Using the existing local ingestion outputs:

```bash
uv run python -m doclens chunk
uv run python -m doclens chunk --source-id python-3.13-pathlib
```

The baseline packs adjacent blocks within a section and source anchor toward 2,000 characters, including repeated heading/anchor context. It uses no overlap, splits oversized prose, and preserves whole code, signatures, and table rows with an oversized flag when needed. Character sizes do not establish a future model's token limits.

Output for the example source is `data/chunks/section-anchor-v1-2000/python/3.13/pathlib.html.json`. It includes source/version/hash metadata, typed content pieces with source offsets, stable IDs, and inspectable text. `--max-chars 2500` writes a separate policy directory; `--manifest PATH` selects another corpus. Chunking works offline and refuses stale or mismatched ingestion provenance.

The verified default run produced 1,474 chunks from all 20 documents, preserving every source block and all 650 code examples. See [the chunking guide](docs/chunking.md) for document/section/chunk definitions, policy tradeoffs, identity/update behavior, code entry points, and a command that prints a real API chunk.

## Build the local index and search

After ingestion, install the optional local embedding dependencies and build the index:

```bash
uv sync --extra retrieval
uv run --extra retrieval python -m doclens index
uv run --extra retrieval python -m doclens search "How do I create a path from a file URI?" --version 3.13 --top-k 3
```

The baseline uses a pinned local `nomic-ai/modernbert-embed-base` model and SQLite. Indexing refreshes verified chunks from the current manifest, checks model token limits without truncation, and replaces `data/indexes/baseline.sqlite3`. The first run downloads about 596 MB of model weights in addition to Python dependencies; subsequent inference runs on CPU with no per-request model service charge.

Search opens the saved index read-only, filters the version before ranking, and displays complete passages with scores, source URLs, and version labels. `--json` returns structured results. The model and configuration are stored with the index so queries use the same encoder contract. The actual corpus fits within its token limit, including both large code examples.

See [the retrieval guide](docs/retrieval.md) for the model/configuration, local resource tradeoffs, code walkthrough, update behavior, smoke results, and limits. The first URI result for 3.13 is `Path.from_uri`; the same 3.12 query returns a related reverse operation. Similarity is a ranking signal and does not by itself establish answer support.

Run the offline behavior checks (they do not download or run a model) with:

```bash
uv run python -m unittest discover -s tests -v
```

## How we will build it

| Milestone | Deliverable | Learning outcome |
| --- | --- | --- |
| 0: Setup | This repository, scope, architecture, roadmap | Explain the product and its evidence requirements |
| 1: Corpus | Source manifest, downloaded documents, parsed sections | Understand provenance, versions, and parsing |
| 2: Retrieval baseline | Chunking, semantic embeddings, version filtering, inspectable search | Explain what gets retrieved and why |
| 3: Evaluation | Labeled questions, retrieval metrics, baseline report | Diagnose retrieval failures before tuning |
| 4: Answers | Grounded generation, citations, insufficient-evidence behavior | Distinguish a plausible answer from a supported answer |
| 5: Experiments | Hybrid search and reranking comparisons | Measure quality, latency, and cost tradeoffs |
| 6: LangGraph | Explicit state, routing, bounded retries, version comparison | Orchestrate the workflow and inspect failures |
| 7: Demo and results | Usable demo, reproducible results, failure analysis | Explain the complete system and its limitations |

See [the roadmap](docs/roadmap.md), [the planned architecture](docs/architecture.md), and [the evaluation plan](evals/README.md).

## Continuing in a new chat

Open a new Codex chat in this repository and say “Continue from the current checkpoint.” [AGENTS.md](AGENTS.md) records the project instructions and the preference for small, explained, user-written implementation steps. It directs the assistant to read [the current checkpoint](docs/progress.md) and the project docs before continuing. Keep the checkpoint current as work is completed; use [learning notes](docs/learning-notes.md) for your own explanations and experiments.

## Repository layout

```text
doclens/
  AGENTS.md             Instructions and learning workflow for Codex chats
  corpus/               Curated source manifest
  docs/                 Architecture, milestones, and learning notes
  evals/                Evaluation design; labeled examples come later
  configs/              Pinned embedding configuration
  src/doclens/          Ingestion, chunking, local encoding/search, and CLI
  tests/                Offline ingestion, chunking, and retrieval checks
  pyproject.toml        Project metadata and packaging
```

## What will demonstrate understanding

Publish the corpus manifest, retrieval examples, experiment settings, measured results, and representative failures. Document why a change helps or hurts. Keep a held-out evaluation split for final comparisons and distinguish citation formatting checks from checks that evidence actually supports a claim.

## References

- [LangGraph learning resources](https://docs.langchain.com/oss/python/learn)
- [LangSmith evaluation types](https://docs.langchain.com/langsmith/evaluation-types)

Source documents retain their original licenses and attribution. Record source terms in the corpus manifest before redistributing document content.
