# Evaluation plan

The evaluation runner and first dataset are implemented. [dev.json](dev.json) contains 24 development questions; [heldout.json](heldout.json) reserves eight questions whose retrieval outputs have not been run. Labels and reference answers were authored by the assistant and checked against saved source passages. **Independent human label review is pending**, so the [development baseline](baseline-dev.md) is provisional.

Run against the existing local index:

```bash
uv run --extra retrieval python -m doclens evaluate --split dev --top-k 5
```

This reads the frozen dataset/index snapshot and writes `outputs/evals/dev-k5.json`. It does not tune the retriever, mutate the index, generate answers, or implicitly open the held-out file. Use a distinct `--output` path to retain another run. `--dataset PATH` and `--index PATH` select explicit inputs. Output cannot overwrite the selected inputs or write into the `evals/` label directory.

## Example records

Each question records an ID, category, query, product, requested version strings, answerability, required evidence groups/facts, a reference answer when answerable, and a missing-evidence rationale otherwise. A reference records the source ID/version, API or section anchor, URL, and a verification quote. Use source anchors rather than chunk IDs so labels can survive a chunking experiment.

An evidence group describes one required source region/fact and lists accepted alternative references. For example, either the API reference or a release-note section can document the same addition. Alternatives within one group must describe the same version. Comparison questions have evidence for every requested version. Reference answers support annotation review; they are not passed to the retriever or used as generated-answer scores.

Include:

- Direct lookup using exact technical terms.
- Paraphrased questions that do not copy the source wording.
- Questions requiring evidence from multiple sections.
- Questions whose answer differs across releases.
- Questions unsupported by the selected corpus.
- Follow-up questions after conversational context is implemented.

The current dev split has six exact-term, eight paraphrase, five multiple-source, two comparison, and three missing-evidence questions. The four earlier smoke queries belong to development. The held-out split was authored/reserved before this evaluation and source-validated without running retrieval. It is a small assistant-authored holdout, not an independently collected benchmark. Follow-up/conversational examples remain for later work.

Both files pin the manifest hash and all 20 raw source hashes. Before loading the model, the runner checks those against index provenance and verifies every reference anchor/quote against original indexed pieces. If the corpus changes, review annotations and version the dataset; do not silently accept a different snapshot. Annotation quotes establish that the labeled source text exists, not that a retrieved chunk entails every required fact.

## Retrieval metrics

- **Evidence recall@k:** the fraction of distinct annotated `(source_id, anchor)` references hit in the first k results, macro-averaged over answerable questions. This includes all annotated alternative references, so adequate evidence can be found even when section recall is below one.
- **Evidence-group recall@k:** the fraction of required groups with at least one accepted reference hit, macro-averaged over answerable questions. This supplements section recall to distinguish alternative sources from independently required sources.
- **MRR@k:** reciprocal rank of the first hit on any accepted reference, zero for no hit. Single-release MRR averages over answerable questions. For a comparison, compute a reciprocal rank independently for each requested version, average them within the question, then average comparison questions.
- **Wrong-version retrieval rate:** wrong-version/product chunks divided by all returned chunks, including missing-evidence cases. A chunk from the other compared release is still wrong in the current version's retrieval call. Report numerator, denominator, and affected IDs.

Hits use original piece anchors, not API names repeated in decorative heading context. Repeated or overlapping chunks from one region count once toward section coverage. The index catalog reconstructs overlapping fragments consistently for quote validation. These are coarse source-region metrics: hitting one chunk from an API region does not prove the exact needed sentence was retrieved or that all reference-answer claims are supported.

Comparison retrieval runs the same unchanged query separately for each version, with k results **per version**; it does not implement an answer-comparison workflow. Report singles/comparisons separately and whether every requested version has any labeled evidence. All results and scores are saved for inspection. Missing-evidence cases have null recall/MRR/group coverage and remain in a separate report category. The current retriever returns nearest passages and has no abstention decision, so no answerability/abstention score is claimed. Undefined aggregates use null and expose their counts.

## Answer metrics

The direct answer pipeline and fixed four-case development runner are implemented and verified live. The user's `dev-20261029T034534302245Z.json` contains four structurally valid outputs: two supported-question answers and two appropriate insufficient-evidence responses, all reporting zero model cost. A [separate qualitative assistant review](generation-dev-review.md) records correctness, support, citation, and abstention findings, including incomplete `copy2` caveats and weak citation placement. This is a working baseline with limited development evidence, not independent human validation, general accuracy, or a numeric claim-support/citation-quality score.

See [setup/design](../docs/answers.md). `uv run --extra retrieval python -m doclens evaluate-answers --inspect-prompt` saves prompts without a provider call. Without that flag, at most four completions are attempted, with no retries and stop-on-error behavior. Reports stay under `outputs/answers/`, separately from frozen retrieval results. No additional API calls or retrieval runs were made during the saved-output review.

The sample is fixed to dev-001, dev-014, dev-004, and dev-023: supported lookup, multiple-source copying, a version-specific evidence gap, and an outside-corpus question. It reads only development labels and never opens held-out data. Reference answers/facts remain local; they are not passed to generation. Exact prompts, trusted citation maps, index/dataset/code hashes, generation settings, model/usage/latency when available, errors, and initially pending semantic-review fields are saved. The successful report's original fields remain unchanged; the dated Markdown review records subsequent judgments. Structural checks are automated; model sufficiency judgments are not ground truth. Live `partial` outcomes, broader development coverage, held-out assessment, and independent human review remain open.

- Correctness against manually verified required facts.
- Claim support against the retrieved source passages.
- Citation precision: fraction of evaluated citations whose passages support their associated claims.
- Citation coverage: fraction of factual claims with supporting citations.
- Abstention behavior: report correct abstentions on unanswerable questions and false abstentions on answerable ones separately.

Use human review for the initial small dataset. If LLM judges are added later, record their model, prompt, and agreement with a manually reviewed subset.

## Experiment report

Save the corpus manifest hash, code revision, embedding identifier, chunking settings, filters, retriever configuration, candidate count, top-k, reranker and generator identifiers where used, and per-example outcomes. Report latency and cost measurements with their scope and sample count.

The JSON report includes dataset/index SHA-256, source hashes, full index model/runtime/policy metadata, code commit/dirty state and Python/lockfile hashes, per-call candidate counts and timings, required labels, retrieved text/URLs/scores, matched/missed regions, and missing groups. An index change during a run aborts without replacing the previous report. The model is loaded once; call timings exclude model download/load and include SQLite reads, query encoding, and ranking. Evaluation wall time also includes scoring. Local model service requests are zero; hardware/electricity costs are not estimated.

Retrieval evaluation implementation: [evaluation.py](../src/doclens/evaluation.py). Its initial 74-test checkpoint included hand-computed metric cases, duplicate/overlap handling, comparison scope, snapshot and output safety, and dev/held-out isolation. New answer/client/sample tests extend that offline coverage; they use doubles and do not measure semantic quality.

Change one retrieval component at a time. Compare the baseline, hybrid retrieval, and reranking on the same development set; keep final held-out questions out of tuning. Publish failures alongside aggregate scores. Never substitute invented scores for completed experiments.
