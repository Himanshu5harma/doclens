# Build and learning roadmap

Build one milestone at a time. Run it, inspect intermediate output, and explain the result in your own words before moving on.

## Milestone 0: Project setup

- [x] Define the product and planned demo.
- [x] Create the Python package scaffold.
- [x] Record architecture and evaluation goals.
- [x] Confirm that the development environment runs locally.

## Milestone 1: Select and ingest a corpus

- [ ] Select one product and two documented releases.
- [ ] Start with 10 to 20 useful pages per release, including reference material and release notes.
- [ ] Record URLs, version labels, document type, source terms, and intended local paths in a manifest.
- [ ] Fetch only the curated URLs; save raw files and provenance.
- [ ] Extract headings, paragraphs, and code blocks while removing navigation noise.
- [ ] Inspect several parsed pages manually against the originals.

Done when: one repeatable command creates inspectable documents with correct version and source metadata.

Explain: What information would disappear if we converted every HTML page to plain text without structure?

## Milestone 2: Retrieval baseline

- [ ] Define typed document, chunk, and search-result records.
- [ ] Implement chunking with stable identifiers and preserved source anchors.
- [ ] Choose a semantic embedding model and record its identifier and configuration.
- [ ] Build a persistent index with repeatable ingestion.
- [ ] Implement an inspectable search command with explicit version filtering.
- [ ] Show the retrieved passages, ranks, source links, and version labels.

Done when: a question returns relevant passages from the requested release and re-ingestion does not duplicate chunks.

Explain: How do chunk boundaries, embedding choice, and top-k change what the answer generator sees?

## Milestone 3: Measure the baseline

- [ ] Write a small, manually checked set of questions with relevant source passages.
- [ ] Include exact terminology, paraphrases, multiple-source questions, version distinctions, and missing evidence.
- [ ] Separate development questions from held-out questions before tuning.
- [ ] Report retrieval metrics with definitions and saved run configuration.
- [ ] Review and record failures before changing the retriever.

Done when: a reproducible report shows what the baseline retrieves correctly and where it fails. See [evaluation design](../evals/README.md).

Explain: Could an answer generator recover from a retrieval result that contains none of the required evidence?

## Milestone 4: Generate supported answers

- [ ] Select an LLM provider and keep credentials in local environment variables.
- [ ] Build an inspectable prompt from retrieved evidence.
- [ ] Return source-linked citations and an explicit insufficient-evidence response when appropriate.
- [ ] Check citation identifiers and requested versions.
- [ ] Evaluate answer correctness, claim support, citation quality, and abstention separately.

Done when: an answer can be inspected against its evidence, and unsupported questions are included in evaluation.

Explain: Why can an answer have correctly formatted citations and still be unsupported?

## Milestone 5: Improve retrieval through experiments

- [ ] Add a lexical baseline and compare it with dense retrieval.
- [ ] Evaluate hybrid retrieval with a documented fusion method.
- [ ] Evaluate reranking as a separate change.
- [ ] Compare quality, latency, and cost using the same corpus and question splits.
- [ ] Keep improvements supported by results and document regressions.

Done when: a report isolates the effect of each change and includes concrete successes and failures.

## Milestone 6: Add LangGraph and version comparison

- [ ] Define workflow state and nodes using the existing components.
- [ ] Route questions into a single-release or comparison path.
- [ ] Retrieve evidence separately for each release in a comparison.
- [ ] Add a bounded query-rewrite path and inspectable traces.
- [ ] Evaluate evidence sufficiency and the effect of retrying.

Done when: the graph handles each path predictably and produces traceable results without unbounded loops.

## Milestone 7: Present the portfolio

- [ ] Add a small interface with visible citations and version selection.
- [ ] Document setup, corpus scope, architecture, and a reproducible evaluation command.
- [ ] Publish measured results, configurations, and a failure analysis.
- [ ] Record a short demo covering lookup, version comparison, and missing evidence.
- [ ] Describe limitations and remaining work honestly.
