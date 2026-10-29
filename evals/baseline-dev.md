# Provisional development baseline

Measured on 2026-10-27 with the existing, untuned dense retriever. The 24 development questions are assistant-authored and source-checked; independent human label review remains pending. The eight held-out questions have not been scored. Do not present these numbers as general benchmark performance or answer correctness.

## Fixed inputs and configuration

- Dataset: `doclens-python-v1`, [dev.json](dev.json), SHA-256 `c83255a64ac6a97d7efcd9f45d4fd191e6eca11d8325717489c85fe1cfe21e8f`.
- Corpus: 20 official Python documents; nine reference topics and What’s New for each of 3.12 and 3.13. All source hashes are pinned in the dataset.
- Model: `nomic-ai/modernbert-embed-base` at `d556a88e332558790b210f7bdbe87da2fa94a8d8`, 768 dimensions, explicit query/document prefixes, normalized vectors, CPU.
- Chunker: `section-anchor-v1`, 2,000-character target, zero overlap; 1,474 chunks.
- Retriever: SQLite product/version filter before exact cosine ranking; deterministic chunk-ID tie breaking.
- k: 5 per requested version. The two comparison questions each make two independent retrieval calls with the unchanged question text.
- No model, query rewrite, chunking, ranking, or parameter changes were made after seeing these results.

Full run details are saved locally in ignored `outputs/evals/dev-k5.json`. The initial run is also preserved in `outputs/evals/dev-k5-initial.json`. Reports include snapshot/model/policy/code hashes, labels, reference answers, complete retrieved passages, scores, candidate counts, timings, and per-case misses.

A second development run reproduced the same aggregates on identical dataset/index hashes. Its 26 retrieval calls took about 3.54 seconds in total after model loading on this machine; this is an uncontrolled local observation, not a hardware benchmark. Timings vary and exclude initial model loading/download. No paid model service was called. The reserved held-out file's SHA-256 is `23d02a6a73f3a137d6fea64c4de09c4d414566b87a53840b515f65afdff8df5a`.

## Measured results

| Group | Questions scored for recall/MRR | Annotated-section recall@5 | MRR@5 | Evidence-group recall@5 |
| --- | ---: | ---: | ---: | ---: |
| Single release | 19 | 0.9737 | 0.8947 | 1.0000 |
| Comparison | 2 | 0.7500 | 0.4375 | 0.7500 |
| Combined descriptive aggregate | 21 | 0.9524 | 0.8512 | 0.9762 |

Wrong-version retrieval: **0 / 130 returned chunks**. The other three development questions are missing-evidence cases: they returned five candidates each, with recall/MRR/group coverage left null. No abstention or answer score exists. Candidate pools were 720 for 3.12 and 754 for 3.13.

One of two comparison questions had at least one labeled hit for both versions. The combined row weights questions equally; comparison MRR first averages the independent version-specific reciprocal ranks within each question. See [metric definitions](README.md#retrieval-metrics).

## Review before changing the retriever

### A missing alternative is different from missing required evidence

`dev-001` asks how to create a path from a file URI in 3.13. The API reference was retrieved first, while the accepted alternative pathlib release-note section was outside the first five. Section recall is therefore 0.5, MRR is 1.0, and group recall is 1.0. This is incomplete coverage of annotated alternatives, not a missing required-source group.

### The literal-glob comparison has a real gap and an annotation limitation

`dev-022` compares literal wildcard matching in 3.12 with glob-to-regex conversion in 3.13. Its 3.12 call did not return the labeled `glob.escape` region in the top five. The results were `glob.iglob`, two `glob.glob` chunks, regex introduction text, and a glob introduction/examples chunk. Passage inspection confirmed that these do not supply the requested glob-escaping instruction. A broad module anchor alone should not be mistaken for the necessary passage.

The 3.13 call ranked a What’s New `glob` passage first and the labeled `glob.translate` API second. The release note directly describes conversion to a regex but is not an accepted alternative in the frozen v1 annotations. This is a concrete candidate label gap, so the measured MRR may undercount relevant results. Preserve the v1 scores; an independently reviewed annotation correction should use a new dataset hash/version and retain both reports. Do not quietly revise labels to improve a number.

The same full comparison wording is sent to both version filters. Mixing two intents may distract retrieval toward the regex half, but that is a hypothesis, not an isolated experiment or proven root cause. No query decomposition, rewrite, reranker, or k change was tried.

### Missing-evidence queries still return passages

The three cases request an undocumented 3.12 `Path.from_uri` usage, Kubernetes deployment limits, and Requests/OAuth2 configuration. The labels describe insufficient evidence in the requested corpus scope, not proof that a feature is globally absent. Nearest-neighbor retrieval returns candidates for all three. A future grounded-answer component must decide whether evidence supports a response; retrieval scores alone cannot establish that.

## Limitations and next action

The set is small, hand-selected from known source material, and contains easy exact-name cases and previously inspected smoke questions. Labels identify API/source regions rather than exact required spans. A region hit can contain a different paragraph from the one needed, and valid unlabeled alternatives can depress recall/MRR. Group coverage is also source-region coverage, not factual entailment. These limitations rule out claims of production accuracy or answer support.

Review the questions, expected facts, accepted alternatives, quotes, and reference answers independently. Address the identified `dev-022` alternative under a versioned annotation change. Keep the held-out split unscored during label review and tuning; run it only after the final configuration is frozen. Use the saved failures to design a later isolated experiment, not to claim an improvement before measurement.
