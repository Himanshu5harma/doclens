# Stage 4 dev retrieval: pgvector store vs SQLite baseline

Run 2026-11-15 (`outputs/stage4/20261115T103343Z/`, git-ignored): development split only, top-k 5 per requested version, held-out not opened, nothing tuned.

## Question

Does moving the same chunks and the same pinned model (`nomic-ai/modernbert-embed-base@d556a88…`, `section-anchor-v1`, 2,000 chars) from the SQLite exact-cosine baseline into scoped PostgreSQL 18.7 / pgvector 0.8.7 exact search change dev retrieval?

## Snapshot used — not the frozen corpus

This Windows clone had no git-ignored `data/`. The 20 manifest pages were re-fetched on 2026-11-15; **all 20 raw hashes differ** from the frozen October hashes pinned in `evals/dev.json` (the manifest hash also differs, consistent with the CRLF checkout). The run therefore used `outputs/stage4/20261115T103343Z/dev-refetched-snapshot.json`, which changes only `source_hashes`/`corpus_manifest_sha256`; questions, labels and quotes are unchanged, and every label's anchor and quote was re-verified against the new snapshot by the existing scorer before scoring. A fresh SQLite index was built from the same bytes (1,474 chunks; largest input 1,932/8,192 tokens, no truncation).

## Results

Chunk parity: the service pipeline (real job code → parsed artifact → service adapter → chunker) produced **1,474 chunks, identical in ordinal and text hash to the baseline chunker and present in the SQLite index; 0 mismatches**.

| Store | Group | Section recall@5 | MRR@5 | Group recall@5 | Wrong-version chunks |
| --- | --- | ---: | ---: | ---: | ---: |
| pgvector (scoped API search path) | Single release (19) | 0.9737 | 0.8947 | 1.0000 | 0 / 110 |
| SQLite (fresh, same snapshot) | Single release (19) | 0.9737 | 0.8947 | 1.0000 | 0 / 110 |
| pgvector | Comparison (2) | 0.7500 | 0.4375 | 0.7500 | 0 / 20 |
| SQLite | Comparison (2) | 0.7500 | 0.4375 | 0.7500 | 0 / 20 |
| Frozen [baseline](baseline-dev.md) (October snapshot) | Single / comparison | 0.9737 / 0.75 | 0.8947 / 0.4375 | 1.0 / 0.75 | 0 / 130 |

Ranking comparison over all **26** retrieval calls: **26/26 identical order**, 26/26 identical sets, largest score difference **1.9e-7** (float32 storage vs SQLite's float64 dot product).

Local timing observation, not a benchmark: summed retrieval time 1.94 s (pgvector) vs 7.81 s (SQLite pure-Python cosine), both including query encoding, same machine.

## Interpretation and limits

- The store change is neutral on dev: same chunks, same rankings, same metrics. Scope filters (membership, workspace, current publication, product/version, index config) are applied in SQL before ranking and did not remove relevant candidates.
- The re-fetched snapshot happens to reproduce the frozen dev numbers exactly. That is an observation about these pages, not proof that every frozen passage is byte-identical; the frozen reports are unchanged and remain the reference.
- Known dev weaknesses (dev-001 release-note alternative, dev-022 comparison) are unchanged because the retriever is unchanged; addressing them belongs to Stage 7 experiments.
- Evaluation used a synthetic evaluator principal in a disposable database through the `search_scope` function the API uses; HTTP/auth behavior is covered by the real-Keycloak integration tests instead.
- Labels remain assistant-authored and provisional; held-out retrieval is still reserved.
