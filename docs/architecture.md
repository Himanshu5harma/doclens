# Planned architecture

This document describes the target design. Manifest-driven ingestion and baseline chunking are implemented for 20 curated Python documentation pages. `doclens ingest` runs the downloader and Python/Sphinx parser; `doclens chunk` loads verified local documents into typed records and writes inspectable chunks. Embedding, indexing, retrieval, and answers remain planned. See the README for commands, [the corpus review](corpus.md) for the input scope, and [the chunking guide](chunking.md) for policy and update behavior.

## Indexing

```mermaid
flowchart LR
    A[Curated source manifest] --> B[Fetch official documents]
    B --> C[Parse sections and code blocks]
    C --> D[Chunk and attach source metadata]
    D --> E[Embed]
    E --> F[Persist versioned index]
```

Preserve product, release, document type, canonical URL, section anchor, title, fetch time, and content hash. Stable source and chunk identifiers make repeat ingestion and document updates inspectable. Preserve code and heading structure during parsing. Retain raw downloads locally for debugging.

The current chunker uses a 2,000-character target including heading/anchor context, without crossing section/anchor groups or adding overlap. It splits oversized prose and preserves oversized structured blocks intact with a flag. IDs fingerprint source identity, policy, context, and passage content, while provenance separately records the raw snapshot and parsed document hashes. Re-running replaces each source's current chunk bundle. A later index must update current payloads and remove old IDs absent from the replacement set; source removals and index synchronization are not implemented.

## Retrieval and answers

```mermaid
flowchart TD
    Q[Question and explicit version selection] --> V[Validate requested versions]
    V --> R[Retrieve within version filters]
    R --> E[Assemble evidence]
    E --> S{Enough evidence?}
    S -->|Yes| G[Generate answer with citations]
    S -->|No, retry available| W[Rewrite query once]
    W --> R
    S -->|No, retry exhausted| U[Explain insufficient evidence]
    G --> C[Check citation identifiers and versions]
    C --> A[Answer with inspectable sources]
```

Begin with a direct Python pipeline. Add LangGraph when conditional retrieval and version comparisons need explicit state and routing. Keep the baseline retriever available for experiments.

The evidence-sufficiency decision will need calibration and evaluation. A similarity threshold or an LLM judgment is not proof that evidence supports an answer. Report uncertainty and evaluate the decision independently.

For comparisons, retrieve evidence separately for each requested release. Do not infer that a feature is absent merely because search returned no passage. Show which version each claim describes and where evidence is missing.

## Design choices to validate

1. Use official, explicitly versioned documents from one product to keep labeling manageable.
2. Build and measure dense retrieval before adding hybrid search or a reranker.
3. Apply version constraints before selecting retrieval candidates.
4. Keep ingestion explicit and repeatable; answering questions must not silently mutate the index.
5. Bound query rewriting and log the retrieval path so failures can be reproduced.
6. Treat retrieved text as untrusted evidence and keep instructions separate from it.

## Citation checks

Programmatic checks can verify that a citation refers to a retrieved chunk, has a valid source URL, and matches the selected version. Claim support requires a separate evaluation against the source passage. A valid citation identifier alone does not establish factual grounding.

## Components to choose during implementation

The embedding model, storage adapter, LLM provider, reranker, and user interface are intentionally undecided. Record the final choices with cost, local resource needs, and reproducibility in mind. Avoid introducing infrastructure that the first milestone does not need.
