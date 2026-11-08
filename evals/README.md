# Evaluation plan

## Expanded-service evaluation boundary

The [2026-11-02 service plan](../docs/expanded-rag-plan.md) introduces separate, explicitly versioned expanded-corpus development data and reports; none are created or scored in Stage 0. Its [acceptance matrix](../docs/expanded-rag-plan.md#small-demo-corpus-and-planned-acceptance-matrix) covers supported lookup, cross-source answers, wrong-version distractors, missing/partial evidence, conflicting/superseded guidance and cross-workspace denial. These are planned cases, not labels/results or security evidence. Synthetic runbooks/tickets must be identified in source content and metadata, with their assertions separated from official product facts.

The 2026-11-03 refinement adds [five proposed public questions](../docs/expanded-rag-plan.md#public-questions-and-required-evidence) for a recommended Python file-processing audience. They are pending full passage/version/terms verification and semantic evaluation, not additions to frozen `dev.json` or evidence of current success. Candidate source research alone is not answer verification. Keep default public collections and optional guided/synthetic collections distinct in inputs, prompts, reports, visitor labels and review results. Do not treat repeated synthetic guidance as independent confirmation of official behavior.

Evaluate **visitor usefulness** separately: observe an actual audience-relevant walkthrough of purpose → real question/version → answer/citations → supplied passages → optional scenario; record task outcomes, confusion and feedback with sample/participant scope. Do not invent visitors or call assistant walkthroughs independent human validation. Evaluate **semantic value** separately against supplied facts/qualifiers, claim support, citation coverage, correct/false abstention and follow-up questions. Evaluate **engineering behavior** through actual access, persistence, retrieval, worker/recovery and quota tests. A structural pass, closed issue/accepted comment, zero leak count on a fixture, or attractive interface alone establishes none of the other goals. Visitor/semantic/public-delivery criteria remain unmeasured; Stage 1's local authentication/ownership subset has the separate evidence below.

Stage 1 uses endpoint/database allow/deny integration tests for authentication and workspace/source ownership. Later retrieval/evidence/citation checks must test deliberate unauthorized matches; a zero observed leak count on a small fixture is not a broad security guarantee. Keep authorization behavior, retrieval coverage, answer correctness/support/citations/abstention, and operational recovery as separate evaluations. No numeric service targets are set before defining a workload. Version any new labels and corpus/configuration changes; do not silently add expanded sources or workspace labels to the existing measured baseline.

Stage 1 was implemented and locally verified on 2026-11-03: 28 new offline authentication/settings/redaction checks and 27 real PostgreSQL/Keycloak cases, alongside all 136 preserved baseline tests (191 combined, plus 121 unittest subtests reported by pytest). The default offline run passed 164 and skipped the 27 opt-in integration cases. Keycloak actually issued service-account access tokens verified through its JWKS; signed RSA fixtures cover negative profiles separately. An actual local HTTP report records registration/read success and role/workspace denial. See [the Stage 1 guide](../docs/stage1-workspaces.md). This is application-scoped SQL authorization, not RLS, browser login, semantic evaluation, independent human review, or production-security evidence. No frozen labels or held-out results were changed and no generation/retrieval evaluation was run.

The baseline datasets/reports and held-out reservation below remain preserved. Do not open/run held-out questions during development; byte-hash preservation checks are allowed. No new generation/retrieval or application test run is needed for Stage 0 documentation. Pending baseline v2 live improvement and independent review are not superseded by the larger plan.

Stage 2 was implemented and locally verified on 2026-11-04: its initial combined pytest passed 243 tests (plus 121 unittest subtests), default offline pytest passed 192 with 51 opt-in skips, and the original 136 unittest tests passed. The real-service cases include actual PostgreSQL/Keycloak and three Redis/Celery prefork-process cases for lost/duplicate delivery, bounded attempts and a test-owned worker termination. Fault cases use visibly synthetic acquisition fixtures; due times/claim expiry are deliberately advanced. A separate production-path public Python 3.13 page sync preserved all 80 code examples and verified artifact hashes, parser consistency and anchors. [The Stage 2 guide](../docs/stage2-ingestion.md) links the actual HTTP/JUnit outputs. This measures stated behavior; it is not retrieval quality, semantic support, visitor usefulness, independent review or a production-recovery benchmark. Frozen baseline labels/reports/index and held-out reservation are preserved; no generation or retrieval evaluation was run.

The subsequent 2026-11-05 review-fix run passed **255 tests** plus 121 unittest subtests; offline pytest passed **196** with **59** opt-in skips, and baseline unittest still passed **136**. New regressions first reproduced all three reviewed failures, then verified unlocked dispatch with real DB claims, reserved-delivery interruption/late results/worker retry timing, actual worker failure/clean-shutdown status, and real PostgreSQL URL byte-boundary/legacy-read behavior. The earlier review/Stage 2 reports remain untouched; new reports use `outputs/service/stage12-fixes-*`. No new public fetch, retrieval, generation, labels or held-out run occurred. These are behavior regressions, not new RAG quality evidence or independent human review.

## Stage 3 source verification

Stage 3's first repository/Python-source unit was locally verified on 2026-11-05: **298 full tests** plus 121 unittest subtests, **235 offline/63 opt-in skips**, and **136** original unittests. New offline tests cover curated destination/release/terms policy, reviewed SHA-256/blob integrity, exact source lines/code, bounded HTTP errors/deadlines/size limits, redaction and repeatability. Three real PostgreSQL/Keycloak cases exercise repository registration, shared job/artifact scope and failed refresh/rate handling; one additional Redis/Celery prefork case routes synthetic repository acquisition. Synthetic content/metadata are labeled. Existing behavior regressions remain in the suite.

A separate production-worker public sync acquired the 76,572-byte CPython file and normalized the 8,714-byte class at lines 947–1170. Trusted provenance/hashes/exact lines were checked, with viewer reads and wrong-workspace/write/version denials. [Actual reports and source inspection](../docs/stage3-repository.md#acceptance-and-verified-results) distinguish the earlier failed REST/API rate-limit attempt from the final explicit raw/hash policy. Source inspection is assistant-authored static review, not executed CPython tests, independent human review, Windows verification or RAG answer-quality/visitor-usefulness measurement. No retrieval/generation evaluation, new labels, index rebuild or held-out question inspection occurred; the frozen baseline and previous reports remain preserved.

## Existing baseline evaluation

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

The current answer policy is `evidence-grounding-v2`, with explicit qualifier instructions and local citation-format validation. New prepared records/reports identify the policy; saved unversioned records retain their original replay contract. The [v2 development audit](grounding-v2-dev.md) compares prompts and format behavior on frozen evidence without new retrieval/generation. It detects the old URI answer's placement problem but still accepts the known incomplete copying answer structurally. Live semantic improvement is pending; formatting errors must not be counted as correct abstentions.

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

The optional [single-release LangGraph workflow](../docs/langgraph-first-step.md) has separate orchestration verification: 19 workflow tests, actual real-index prompt-only execution, and deterministic replay of the four saved development results. The replay completion fixtures are reconstructed from validated results and retain historical metadata; they are not new model outputs or original raw HTTP responses. No held-out or fresh provider calls were made, and the saved labels/reports remain unchanged. Local verification artifacts live under `outputs/workflows/`. These checks establish direct/graph behavior parity, not better retrieval or semantic answer quality.

Save the corpus manifest hash, code revision, embedding identifier, chunking settings, filters, retriever configuration, candidate count, top-k, reranker and generator identifiers where used, and per-example outcomes. Report latency and cost measurements with their scope and sample count.

The JSON report includes dataset/index SHA-256, source hashes, full index model/runtime/policy metadata, code commit/dirty state and Python/lockfile hashes, per-call candidate counts and timings, required labels, retrieved text/URLs/scores, matched/missed regions, and missing groups. An index change during a run aborts without replacing the previous report. The model is loaded once; call timings exclude model download/load and include SQLite reads, query encoding, and ranking. Evaluation wall time also includes scoring. Local model service requests are zero; hardware/electricity costs are not estimated.

Retrieval evaluation implementation: [evaluation.py](../src/doclens/evaluation.py). Its initial 74-test checkpoint included hand-computed metric cases, duplicate/overlap handling, comparison scope, snapshot and output safety, and dev/held-out isolation. New answer/client/sample tests extend that offline coverage; they use doubles and do not measure semantic quality.

Change one retrieval component at a time. Compare the baseline, hybrid retrieval, and reranking on the same development set; keep final held-out questions out of tuning. Publish failures alongside aggregate scores. Never substitute invented scores for completed experiments.
