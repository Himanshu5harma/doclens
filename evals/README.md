# Evaluation plan

No evaluation dataset or results exist yet. Build the first labeled examples alongside the corpus and retrieval baseline.

## Example records

Each question should record an identifier, category, requested release or releases, answerability, manually verified relevant source sections, required facts, and a reference answer where applicable. Use source sections and URLs as stable labels; chunk identifiers may change between chunking experiments.

Include:

- Direct lookup using exact technical terms.
- Paraphrased questions that do not copy the source wording.
- Questions requiring evidence from multiple sections.
- Questions whose answer differs across releases.
- Questions unsupported by the selected corpus.
- Follow-up questions after conversational context is implemented.

Start with 20 to 30 manually checked examples for development. Expand and reserve a held-out set before comparing advanced retrieval settings. Report how examples were created and checked, the split sizes, and the corpus snapshot used.

## Retrieval metrics

- **Evidence recall@k:** fraction of labeled relevant source sections represented in the first k results, averaged over answerable examples.
- **MRR@k:** reciprocal rank of the first relevant result within the first k results, with zero for no hit, averaged over answerable examples.
- **Wrong-version retrieval rate:** fraction of retrieved chunks outside the explicitly requested releases; also report affected queries.

Deduplicate source sections when measuring section recall so overlapping chunks do not inflate the result. Report single-release and comparison questions separately. Track whether comparison questions have evidence for both releases. Missing-evidence questions belong in the answerability evaluation, not retrieval recall with an undefined denominator.

## Answer metrics

- Correctness against manually verified required facts.
- Claim support against the retrieved source passages.
- Citation precision: fraction of evaluated citations whose passages support their associated claims.
- Citation coverage: fraction of factual claims with supporting citations.
- Abstention behavior: report correct abstentions on unanswerable questions and false abstentions on answerable ones separately.

Use human review for the initial small dataset. If LLM judges are added later, record their model, prompt, and agreement with a manually reviewed subset.

## Experiment report

Save the corpus manifest hash, code revision, embedding identifier, chunking settings, filters, retriever configuration, candidate count, top-k, reranker and generator identifiers where used, and per-example outcomes. Report latency and cost measurements with their scope and sample count.

Change one retrieval component at a time. Compare the baseline, hybrid retrieval, and reranking on the same development set; keep final held-out questions out of tuning. Publish failures alongside aggregate scores. Never substitute invented scores for completed experiments.
