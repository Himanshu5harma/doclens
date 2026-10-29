# Build and learning roadmap

Build one milestone at a time. Run it, inspect intermediate output, and explain the result in your own words before moving on.

## Milestone 0: Project setup

- [x] Define the product and planned demo.
- [x] Create the Python package scaffold.
- [x] Record architecture and evaluation goals.
- [x] Confirm that the development environment runs locally.

## Milestone 1: Select and ingest a corpus

- [x] Select one product and two documented releases: Python 3.12 and 3.13.
- [x] Start with 10 to 20 useful pages per release, including reference material and release notes (10 per release: nine references and What’s New).
- [x] Record URLs, version labels, document type, source terms, and intended local paths in a manifest (20 sources).
- [x] Fetch only the curated URLs; save raw files and provenance (all 20 pages verified).
- [x] Extract headings, paragraphs, and code blocks while removing navigation noise (Python/Sphinx parser; all 20 pages).
- [x] Inspect several parsed pages manually against the originals (eight samples across both versions; see [corpus review](corpus.md)).

Done when: one repeatable command creates inspectable documents with correct version and source metadata.

Completed for the selected scope on 2026-10-25: `uv run python -m doclens ingest`. Verification results and remaining parser limits are recorded in [the corpus review](corpus.md).

Explain: What information would disappear if we converted every HTML page to plain text without structure?

## Milestone 2: Retrieval baseline

- [x] Define typed document, section, block, and chunk records.
- [x] Define typed search-result records alongside retrieval.
- [x] Implement chunking with stable identifiers and preserved source anchors (section-anchor-v1 baseline; see [chunking guide](chunking.md)).
- [x] Choose a semantic embedding model and record its identifier and configuration (pinned ModernBERT baseline; see [retrieval guide](retrieval.md)).
- [x] Build a persistent index with repeatable ingestion (SQLite replacement; two actual builds verified).
- [x] Implement an inspectable search command with explicit version filtering.
- [x] Show the retrieved passages, ranks, source links, and version labels.

Done when: a question returns relevant passages from the requested release and re-ingestion does not duplicate chunks.

Completed for the selected scope on 2026-10-27: local embeddings for all 1,474 chunks, repeatable index replacement, and version-filtered search. Smoke examples establish working behavior, not evaluation scores.

Explain: How do chunk boundaries, embedding choice, and top-k change what the answer generator sees?

## Milestone 3: Measure the baseline

- [x] Write a small source-checked question set with relevant passages (24 dev, eight held-out; provisional assistant-authored labels).
- [x] Include exact terminology, paraphrases, multiple-source questions, version distinctions, and missing evidence.
- [x] Separate development questions from held-out questions before tuning (held-out retrieval has not been run).
- [x] Report retrieval metrics with definitions and saved run configuration (see [development baseline](../evals/baseline-dev.md)).
- [x] Review and record failures before changing the retriever (including a labeled miss and a candidate annotation gap).
- [ ] Obtain independent human label review and version any annotation corrections before relying on quality claims.

Done when: a reproducible report shows what the baseline retrieves correctly and where it fails. See [evaluation design](../evals/README.md).

The runner and provisional development report are implemented on 2026-10-27. Independent annotation review remains open; held-out and answer-quality scores are not claimed.

Explain: Could an answer generator recover from a retrieval result that contains none of the required evidence?

## Milestone 4: Generate supported answers

- [x] Select an LLM provider and keep credentials in local environment variables (explicit OpenRouter :free model; key setup documented).
- [x] Build an inspectable prompt from retrieved evidence (real four-case dev prompts checked).
- [x] Implement source-linked citations, partial answers, and explicit insufficient-evidence output (offline contracts plus live answered/insufficient cases; live partial remains unexercised).
- [x] Check citation identifiers and requested versions (including malformed/truncated response rejection).
- [x] Verify live end-to-end generation using the configured free model (four saved dev outputs, 2026-10-29).
- [x] Review answer correctness, claim support, citation quality, and abstention separately on the bounded dev sample (assistant review with explicit caveats).
- [ ] Improve metadata-preservation qualifications and claim-local citation placement; expand quality validation and obtain independent review.

Done when: an answer can be inspected against its evidence, and unsupported questions are included in evaluation.

The working direct baseline RAG is complete for this implementation scope as of 2026-10-29. The [live development review](../evals/generation-dev-review.md) records four structurally valid generations, two supported-question answers, two appropriate abstentions, and zero reported model cost. It also records incomplete `copy2` preservation caveats and weak citation placement. Broader quality validation, held-out assessment, and independent human review remain open. LangGraph has not been implemented.

Explain: Why can an answer have correctly formatted citations and still be unsupported?

## Milestone 5: Improve retrieval through experiments

- [ ] Add a lexical baseline and compare it with dense retrieval.
- [ ] Evaluate hybrid retrieval with a documented fusion method.
- [ ] Evaluate reranking as a separate change.
- [ ] Compare quality, latency, and cost using the same corpus and question splits.
- [ ] Keep improvements supported by results and document regressions.

Done when: a report isolates the effect of each change and includes concrete successes and failures.

## Milestone 6: Add LangGraph and version comparison

The user requested an explanation of the first LangGraph lesson after verifying baseline RAG. The [proposed first unit](langgraph-first-step.md) reuses the single-release pipeline with typed state, explicit nodes, an inspection branch, and local execution traces. This is a proposal only; dependency installation and graph implementation have not begun. Retrieval experiments above remain unimplemented.

- [ ] Define workflow state and nodes using the existing components.
- [ ] Route questions into a single-release or comparison path.
- [ ] Retrieve evidence separately for each release in a comparison.
- [ ] Add a bounded query-rewrite path and inspectable traces.
- [ ] Evaluate evidence sufficiency and the effect of retrying.

Done when: the graph handles each path predictably and produces traceable results without unbounded loops.

## Milestone 7: Present the demo and results

- [ ] Add a small interface with visible citations and version selection.
- [ ] Document setup, corpus scope, architecture, and a reproducible evaluation command.
- [ ] Publish measured results, configurations, and a failure analysis.
- [ ] Record a short demo covering lookup, version comparison, and missing evidence.
- [ ] Describe limitations and remaining work honestly.
