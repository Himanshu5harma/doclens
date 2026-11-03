# RAG grounding policy v2 — offline verification

Checked on 2026-11-02. The user asked to focus on RAG before further graph work. This unit targets the two known answer issues: omitted preservation qualifications and citations collected at the end of a long answer. The direct pipeline remains the default; existing optional graph code is retained without expansion.

## Intervention

`evidence-grounding-v2` changes the generation instructions and adds a citation-placement format check. It does not change retrieval, embeddings, index contents, source selection, or the four-field provider response schema. The instructions ask the model to preserve relevant restrictions, exceptions, platform differences, and best-effort language; they do not hard-code a Python API answer.

Current answered/partial output must end every prose paragraph/list item with supporting citation IDs. Each fenced code example needs an immediate following citation line or cited explanation paragraph. Headings are exempt. Format failures are `invalid_answer` errors, not insufficient-evidence predictions; there is no automatic repair/retry. This can reject a factually correct answer that violates the explicit output format.

The check recognizes paragraphs, Markdown list-item starts, headings, and backtick fences. It is a small format checker rather than a full Markdown parser or a factual-claim detector. It does not prove that each cited passage entails its paragraph, that every caveat is included, or that headings are factual. The tests deliberately demonstrate an unsupported assertion with valid citation formatting still passing structural validation. Semantic review remains necessary.

Prepared records and new answer-evaluation reports record `prompt_policy_id`. Archived records without an ID keep their original validation contract when replayed; new preparation always selects v2. Unknown policy IDs fail rather than silently choosing a validator. Frozen outputs are not relabelled or rewritten.

## Actual offline audit

Source: the preserved `outputs/answers/dev-20261029T034534302245Z.json`, SHA-256 `603e6f1498bb8f7d054c27eb906c8c668910800cf4c93d8454ebd9b503d9594c`. Local audit: `outputs/answers/grounding-v2-offline-20261102.json`.

The audit reconstructs the four saved evidence bundles and builds current prompts without retrieval or generation. For each case, the question/evidence user message and complete citation map are identical to the saved input. Only the system instructions and local policy metadata change. Five complete passages fit each budget with no omissions.

| Case | V2 prompt bytes | Historical output under v2 formatting | Interpretation |
| --- | ---: | --- | --- |
| dev-001, URI / 3.13 | 9,120 | Rejected | Earlier prose lacks local citations. This detects the observed placement problem; it does not mean the URI facts are wrong. |
| dev-014, copying / 3.12 | 10,943 | Accepted | Its single paragraph ends with valid IDs. The known preservation caveat is still incomplete; formatting acceptance is not a semantic pass. |
| dev-004, URI / 3.12 | 8,329 | Accepted | The existing insufficient-evidence shape remains valid. No new abstention was generated. |
| dev-023, Kubernetes / 3.13 | 8,707 | Accepted | The existing insufficient-evidence shape remains valid. No new abstention was generated. |

Historical responses were reconstructed from saved validated results, not original raw HTTP response bytes. The audit also stores two **assistant-authored illustrative revisions** checked against the same supplied passages and accepted by the format validator. They are not live model outputs, independent human review, or quality scores.

For example, the intended copying explanation is:

> `shutil.copyfile` copies the file contents without metadata. [E4]
>
> `shutil.copy2` also attempts to preserve metadata via `copystat`, but it cannot preserve all metadata, and support varies by platform. [E1][E2]

These IDs map to the saved Python 3.12 copying evidence. The illustration shows how to express the qualification and place citations, not what the model has now produced.

Actual direct-CLI prompt inspection also succeeded for the copying question: `outputs/answers/grounding-v2-copy-prompt-20261102.json` records v2, five passages, and 10,943 message bytes, matching the frozen-evidence preparation. All 114 pre-existing protected corpus/config/index/label/report artifacts remain byte-identical.

All 136 offline tests pass: 129 prior tests plus seven new placement/policy/limitation checks. New report assertions verify policy metadata. Coverage includes paragraphs, list items and wrapping, per-example code citations, partial versus insufficient outcomes, archived/unknown policy handling, and the counterexample separating formatting from support. Existing version/provenance/provider/error and graph contracts still pass. No dependencies or paid services were introduced.

## Live comparison pending

`OPENROUTER_API_KEY` is unavailable to this assistant session. No live before/after answer was generated, and no improvement in model correctness, citation support, or abstention is claimed.

In the terminal where the key is configured:

```bash
uv run --extra retrieval python -m doclens ask "Compare shutil.copyfile and shutil.copy2 in Python 3.12: which copies metadata as well as file contents?" --version 3.12 --inspect-prompt
uv run --extra retrieval python -m doclens evaluate-answers
```

The first command needs no key/provider call. The second makes at most four completions, stops on error, and writes a new timestamped report. Preserve that report and the v1 baseline. Compare the supplied evidence IDs/hashes before attributing differences to the answer policy. Check preservation qualifications, individual claim support, local/relevant citations, appropriate abstention, and false abstention separately. Model serving and outputs may vary even at temperature zero; one later run is not a controlled general-accuracy estimate. Keep held-out data reserved and independent human review marked pending.
