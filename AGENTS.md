# DocLens project instructions

## Start of every chat

Read these repository files before proposing the next implementation step:

1. `docs/progress.md` — current checkpoint, decisions, and next small step.
2. `README.md` — product scope and development setup.
3. `docs/roadmap.md` — milestone order and completion criteria.
4. `docs/architecture.md` — intended design and evidence requirements.

Inspect the actual files relevant to the checkpoint before treating a task as complete. If the progress note and repository differ, reconcile them without discarding the user's work. Resume from the checkpoint; do not ask the user to explain the project again.

## Purpose and collaboration style

DocLens is a version-aware RAG assistant for technical documentation. The user wants to demonstrate understanding of RAG while learning LangGraph. Public descriptions should focus on the tool's purpose, capabilities, and honest implementation status; keep learning goals in the roadmap, learning notes, and assistant guidance rather than labeling the tool a portfolio project.

- Teach one complete, useful feature at a time. The user found file-by-file exercises too granular; group the design, implementation, and verification into one lesson (for example, a downloader for all manifest sources with provenance).
- Explain what the feature accomplishes and why each important decision is made, then implement when requested and show a concrete way to run and inspect it. Preserve the user's goal of understanding the code.
- Review the user's code and command output before advancing dependent work. Never assume that showing a snippet means the user created the file.
- Answer conceptual questions plainly, then return to the current step without losing the checkpoint.
- Do not implement whole milestones or generate large amounts of application code unless the user asks you to. Explicit requests to edit, fix, or set up files authorize that work.
- Make reasonable recommendations without repeatedly asking for confirmation. Avoid extra tooling and infrastructure that the current step does not need.

## Technical direction

- Follow the roadmap: curated corpus and ingestion, retrieval baseline, evaluation, grounded answers, retrieval experiments, LangGraph, then presentation.
- Begin with a direct Python pipeline. Add LangGraph when routing, explicit state, bounded retries, and version comparisons make its role understandable.
- Use Python 3.12+ and the existing `uv` setup. Prefer the standard library for simple manifest handling.
- Preserve document versions and provenance through ingestion, chunking, retrieval, and citations. Filter by requested version before selecting retrieval candidates.
- Record source terms for external documentation. They describe the documents' licenses, separately from DocLens's own code license. A `source_terms_url` is sufficient for the initial manifest.
- Keep the manifest under `corpus/` so it can be committed. Raw downloads belong under ignored `data/`. Manifest paths are relative to the repository root.
- Keep credentials out of the repository. Do not introduce paid services before they are needed and their tradeoffs have been explained.
- Do not claim features, completed checks, quality scores, or evaluation results that do not exist. Retrieval failure alone does not establish that a feature is absent from a release.
- Read `evals/README.md` before evaluation work. Use meaningful, proportionate validation for implementation changes; documentation-only changes need no application tests.

## Maintain continuity

- After meaningful progress, decisions, or failures, update `docs/progress.md` with what actually happened, what was verified, remaining uncertainty, and the next small step.
- Distinguish recommendations, user-written work, and verified completed work.
- Mark roadmap checkboxes only when their stated work is complete. Two starter pages do not satisfy the planned 10–20 pages per release.
- Keep `docs/learning-notes.md` for the user's explanations and experiments. Do not invent understanding or overwrite their notes with assumed answers.
- Before ending a work session, leave a checkpoint that a new chat can use directly. Maintain these records without requiring the user to request a handoff each time.

## Existing commands

From the repository root:

```bash
uv sync
uv run python -m doclens
uv run python -m doclens ingest
uv run python -m doclens fetch
uv run python -m doclens parse
uv run python -m doclens chunk
uv sync --extra retrieval
uv run --extra retrieval python -m doclens index
uv run --extra retrieval python -m doclens search "How do I create a path from a file URI?" --version 3.13
```

To check manifest syntax:

```bash
uv run python -m json.tool corpus/sources.json
```

The JSON command validates syntax only; it neither creates the file nor validates its schema or source URLs.
