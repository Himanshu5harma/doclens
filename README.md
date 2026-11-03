# DocLens

A version-aware engineering knowledge assistant with inspectable source citations. Recommended initial public focus: practical file-processing questions for Python developers maintaining tools on 3.12/3.13.

**Status: a working direct RAG baseline and an optional single-release LangGraph workflow.** The corpus has 20 official Python documentation pages across versions 3.12 and 3.13. `ask` retrieves version-scoped evidence, generates through an explicit OpenRouter free model, and validates answer structure/citations. A four-case live direct run produced two supported-question answers and two appropriate evidence-gap responses, with zero reported model cost. Assistant review found incomplete `copy2` preservation caveats and weak citation placement. The current v2 prompt/format policy addresses these in instructions and placement checks; live behavior under v2 remains unverified. The graph reuses that behavior with local node traces; its full answer path is verified offline, with real-index prompt inspection. Broader quality validation and independent human review remain open.

**Expanded service: Stage 1 workspace/source ownership is implemented and locally verified.** A separate optional FastAPI service verifies real Keycloak-issued access tokens, checks current PostgreSQL membership, and registers/lists/reads owned source metadata. Owner/editor/viewer and cross-workspace boundaries were checked against the actual database under a restricted runtime role; RLS and browser sign-in are not implemented. Registration does not fetch/index content. The useful public reader, worker, expanded retrieval/answers, new adapters and visitor interface remain planned. See the [Stage 1 guide](docs/stage1-workspaces.md) and [expanded plan](docs/expanded-rag-plan.md). The existing RAG CLI remains available; there is no public web app yet.

## The problem

Python file-processing tools can behave differently across releases and platforms. Developers need to find the applicable API, understand cleanup/metadata limits, and inspect the supporting documentation. DocLens currently addresses version-scoped documentation lookup and inspectable evidence. The planned public experience adds useful curated examples and source/revision context; authenticated workspaces support later team-specific knowledge and saved investigations/annotations. Structural checks require a separate semantic review.

## Planned public experience

A first visit should explain the scope, offer a useful question/version selection without mandatory sign-up for public reading, show an evidence-grounded answer with citations, and let the visitor expand the actual supplied passages. The example buttons will use the actual pipeline. Provider errors, missing evidence and limits stay visible; no canned answers or paid fallbacks. Real private workspace access and privileged source administration remain authenticated/authorized.

Five proposed public questions, pending full source verification and evaluation:

- How do I convert a file URI to a path in Python 3.13, and which inputs are invalid?
- Should my backup script use `copyfile` or `copy2`, and which metadata can still be lost?
- Why can reopening a `NamedTemporaryFile` on Windows fail, and how should cleanup work?
- How do I find files recursively, including hidden directories, and can I rely on their order?
- How can I replace a generated configuration file atomically, and what filesystem/durability limits remain?

The [public question/evidence plan](docs/expanded-rag-plan.md#public-questions-and-required-evidence) ties each request to credible sources and qualifications. The `os` material needed for the last question is not in the current baseline corpus; these examples are not measured successes. The initial Python audience is recommended, not a silent switch to the cloud-native alternative discussed separately.

Visitors may optionally explore visibly labeled synthetic runbooks/tickets showing team differences, outdated instructions, partial evidence and workspace behavior. Those collections stay separate from default public evidence. Synthetic fixtures support controlled demonstrations/tests; public demo switching is not proof of private isolation. We will review visitor task usefulness and semantic support separately from engineering tests. The original Python baseline/reports and held-out reservation remain preserved. See the [first-visit criteria](docs/expanded-rag-plan.md#first-visit-journey-and-success-criteria).

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

## Evaluate the unchanged baseline

```bash
uv run --extra retrieval python -m doclens evaluate --split dev --top-k 5
```

The source-checked set has 24 development questions and eight reserved held-out questions. The command checks corpus/index/label provenance, then saves per-query passages, misses, configuration, hashes, and timing to `outputs/evals/dev-k5.json`. It evaluates source-anchor coverage and ranking; it does not grade generated answers or tune retrieval. The held-out split has not been scored.

Read [the metric definitions and dataset format](evals/README.md) and [the provisional development results](evals/baseline-dev.md). The review records a missed required source in a comparison and a candidate annotation gap. Independent human label review remains necessary before treating the numbers as reliable quality claims.

Run the offline behavior checks (they do not download or run a model) with:

```bash
uv run python -m unittest discover -s tests -v
```

## Ask with evidence

The configurable default is `nvidia/nemotron-3.5-super-vl:free`, verified against OpenRouter's public zero input/output pricing on 2026-10-28. Every live generation rechecks pricing, enforces zero-price routing, and disables fallbacks. Questions and selected documentation are sent to OpenRouter and its provider; the selected free endpoint logs inputs. See [setup, data policy, design, and code walkthrough](docs/answers.md) before using a key.

```bash
# No API key or provider call: inspect exact messages and supplied evidence
uv run --extra retrieval python -m doclens ask "How do I create a path from a file URI?" --version 3.13 --inspect-prompt

# After setting OPENROUTER_API_KEY in your environment
uv run --extra retrieval python -m doclens ask "How do I create a path from a file URI?" --version 3.13
uv run --extra retrieval python -m doclens ask "What Kubernetes CPU and memory resource limits should I set for a DocLens deployment?" --version 3.13 --json

# Fixed four-question development sample; maximum four completions, stops on error
uv run --extra retrieval python -m doclens evaluate-answers
```

Answers can be `answered`, `partial`, or `insufficient_evidence`. Provider errors and invalid responses exit nonzero instead of being treated as evidence insufficiency. Citation links come from retrieved metadata; valid IDs alone do not establish claim support. The [live development review](evals/generation-dev-review.md) separates structural success from correctness, support, citation, and abstention findings for the four saved outputs. This establishes a working baseline with known limitations, not general accuracy. Held-out retrieval/generation have not been run.

The pending baseline grounding check remains: verify qualification preservation and citation placement under v2 live output. The [offline audit](evals/grounding-v2-dev.md) explains the checks and bounded comparison. The expanded plan preserves that uncertainty; no new model outputs or held-out results are claimed. Only public/synthetic material is suitable for the current free-endpoint demo; private/customer data requires a separate provider/privacy decision.

## Inspect the optional LangGraph workflow

```bash
uv sync --extra retrieval --extra graph
uv run --extra retrieval --extra graph python -m doclens ask "How do I create a path from a file URI?" --version 3.13 --workflow graph --inspect-prompt --trace
```

The graph prepares the same evidence/prompt and stops before generation when inspection is requested. Without `--inspect-prompt`, it generates once and validates through the existing functions. `--trace` shows local node summaries on stderr, preserving answer/inspection JSON on stdout. Direct execution remains the default. Cloud tracing and automatic retries are disabled. The [workflow guide](docs/langgraph-first-step.md) explains state, nodes, edges, offline parity, and real output. The last recorded full offline run passed 136 tests with both extras installed; Stage 0 planning did not rerun it. Expanded investigation/comparison routes remain later work.

## How we will build it

| Stage | Deliverable | Status |
| --- | --- | --- |
| 0: Plan | Product, corpus/acceptance matrix, library ownership, migration plan | Complete; documentation only |
| 1: Workspace ownership | Authenticated API, PostgreSQL migrations, memberships, source registration | Implemented; real local Keycloak/PostgreSQL verified |
| 2: Ingestion workflow | Persisted jobs, Celery/Redis, verifiable snapshots and recovery | Next, only when requested |
| 3: Source/format units | Useful repository material/Markdown and issue exports; PDF when justified | Planned, one adapter unit at a time |
| 4: Retrieval | Exact authorized PostgreSQL/pgvector search with local embeddings | Planned |
| 5: Answers | Direct grounded answer API and bounded live evaluation | Planned |
| 6: Lifecycle | Configuration-aware incremental sync, revision publication, deletion/revocation | Planned |
| 7: Experiments | Lexical versus dense, then fusion and justified reranking | Planned, one experiment at a time |
| 8: Operations and public delivery | Reproducible startup/recovery, safe telemetry, separate minimal visitor-view unit | Planned; usefulness requires an actual walkthrough |
| 9: LangGraph | Useful investigation routes over the evaluated expanded pipeline | Planned; existing optional graph preserved |

See [the roadmap](docs/roadmap.md), [architecture](docs/architecture.md), [expanded plan](docs/expanded-rag-plan.md), and [evaluation rules](evals/README.md). Stage 1's installed versions and verification are recorded separately from future library candidates. Earlier baseline milestones remain in the roadmap as history.

## Run the local workspace/source service

Requires Docker, Python 3.12+ and uv. From the repository root:

```bash
uv sync --extra service --group dev
uv run --extra service python scripts/stage1_dev.py prepare
docker compose -f compose.stage1.yaml up -d
uv run --extra service python scripts/stage1_dev.py bootstrap
uv run --extra service uvicorn doclens.service.app:create_app --factory --host 127.0.0.1 --port 18000 --env-file .env.service.local --no-access-log
```

In another terminal, `uv run --extra service python scripts/stage1_dev.py request /api/v1/workspaces` obtains a real local token without printing it and shows authorized workspace metadata. The [complete guide](docs/stage1-workspaces.md#run-and-inspect) includes source registration, denied access, the example JSON, credential/storage boundaries and cleanup. These are local demonstration service accounts, not a finished human login flow. Loopback HTTP/Keycloak development mode is for local use.

The full combined verification passed **191 tests** (plus 121 unittest subtests), including 27 real PostgreSQL/Keycloak cases. Default offline pytest passed 164 with those 27 integration cases skipped. The preserved unittest suite separately passed all 136. Use `DOCLENS_RUN_INTEGRATION=1 uv run --extra retrieval --extra graph --extra service python -m pytest tests -q` after starting the local services; it creates/drops a separate disposable test database. Source/corpus/index/report preservation and quality limitations are recorded in [progress](docs/progress.md). These checks establish tested behavior, not production security or semantic answer quality.

## Continuing in a new chat

Open a new Codex chat in this repository and say “Continue from the current checkpoint.” [AGENTS.md](AGENTS.md) records the stage-based mentoring instructions and directs the assistant to read [the checkpoint](docs/progress.md), [expanded plan](docs/expanded-rag-plan.md), and project docs first. Each requested stage includes design, implementation, verification and explanation, then stops at its boundary. Use [learning notes](docs/learning-notes.md) for your own explanations and experiments.

## Repository layout

```text
doclens/
  AGENTS.md             Instructions and learning workflow for Codex chats
  corpus/               Curated source manifest
  docs/                 Architecture, milestones, and learning notes
  evals/                Development/held-out labels, metric definitions, baseline review
  configs/              Pinned embedding configuration
  src/doclens/          Ingestion, chunking, local retrieval/evaluation, and CLI
  tests/                Offline component and metric checks
  pyproject.toml        Project metadata and packaging
```

## What will demonstrate understanding

Publish the corpus manifest, retrieval examples, experiment settings, measured results, and representative failures. Document why a change helps or hurts. Keep a held-out evaluation split for final comparisons and distinguish citation formatting checks from checks that evidence actually supports a claim.

## References

- [LangGraph learning resources](https://docs.langchain.com/oss/python/learn)
- [LangSmith evaluation types](https://docs.langchain.com/langsmith/evaluation-types)

Source documents retain their original licenses and attribution. Record source terms in the corpus manifest before redistributing document content.
