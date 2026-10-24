# DocLens

A RAG assistant for technical documentation that compares versions, answers with source citations, and measures retrieval and answer quality.

**Status: project setup.** The repository contains a Python scaffold and a learning roadmap. Document ingestion, retrieval, generation, version comparisons, and evaluation are planned features; no quality scores or working RAG demo are claimed yet.

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

The current command prints the project status and next milestone. It does not query documents or call an LLM. No API key is needed for this scaffold.

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
| 7: Portfolio | Usable demo, reproducible results, failure analysis | Explain the complete system and its limitations |

See [the roadmap](docs/roadmap.md), [the planned architecture](docs/architecture.md), and [the evaluation plan](evals/README.md).

## Repository layout

```text
doclens/
  docs/                 Architecture, milestones, and learning notes
  evals/                Evaluation design; labeled examples come later
  src/doclens/          Python package scaffold
  pyproject.toml        Project metadata and packaging
```

## What will demonstrate understanding

Publish the corpus manifest, retrieval examples, experiment settings, measured results, and representative failures. Document why a change helps or hurts. Keep a held-out evaluation split for final comparisons and distinguish citation formatting checks from checks that evidence actually supports a claim.

## References

- [LangGraph learning resources](https://docs.langchain.com/oss/python/learn)
- [LangSmith evaluation types](https://docs.langchain.com/langsmith/evaluation-types)

Source documents retain their original licenses and attribution. Record source terms in the corpus manifest before redistributing document content.
