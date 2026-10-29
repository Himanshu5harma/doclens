# Development generation review — working baseline, limited sample

Reviewed on 2026-10-29 by the implementing assistant against the supplied passages in the user's successful live report. **The direct baseline RAG now works end to end.** This is a qualitative review of four development cases, not independent human validation or a general accuracy estimate. The URI answer is substantively supported; the copying answer gets the main distinction right but needs clearer preservation limits. Citation placement also needs improvement. Both missing-evidence cases appropriately abstain.

The last offline verification passed all 110 tests (36 answer/client/sample checks and 74 existing checks). This session changes documentation only, so the suite was not rerun. Read-only consistency checks below independently verified the live report's evidence and provenance. Structural checks and test doubles establish behavior, not semantic answer quality.

The retriever/model/index/chunk policy, frozen development/held-out labels, and retrieval reports were not tuned or rebuilt. Held-out generation and retrieval were not run. The bounded live sample is fixed to four existing development questions, with at most one completion each and no retries; it stops on the first error.

## Verified live artifact

The user configured the key and ran `ask` and `evaluate-answers`. The inspected evaluation artifact is [dev-20261029T034534302245Z.json](../outputs/answers/dev-20261029T034534302245Z.json), created at 2026-10-29 03:45:47 UTC (09:15:47 Asia/Kolkata). Its SHA-256 is `603e6f1498bb8f7d054c27eb906c8c668910800cf4c93d8454ebd9b503d9594c`.

| Check | Observed result |
| --- | --- |
| Split / IDs | dev only: dev-001, dev-014, dev-004, dev-023 |
| Completion / structure | All four generated; all finish reasons `stop`; all four structural-validation fields true |
| Model | Requested and returned `nvidia/nemotron-3.5-super-vl:free` for each case |
| Settings | Temperature 0; output cap 1,600 tokens; prompt cap 24,000 bytes; socket timeout 45 seconds |
| Routing | Zero-price checks recorded; zero automatic retries; provider fallbacks disabled |
| Reported model cost | Zero for each case; zero total for these four completions |
| Usage | 8,755 prompt tokens + 460 completion tokens = 9,215 total |
| Generation latency | Approximately 2.329 / 1.385 / 1.214 / 1.011 seconds; 5.938 seconds summed, excluding catalog preflight and local retrieval/model loading |
| Dataset | Current dev SHA matches recorded `c83255a64ac6a97d7efcd9f45d4fd191e6eca11d8325717489c85fe1cfe21e8f` |
| Index | Current SQLite SHA matches recorded `1c50c846cbcfc9e27e0dbe038a66915f7821a7aec58ba9da2510e613ae3ebb2d` |
| Code | All 16 recorded implementation/packaging file hashes match current files |
| Supplied evidence | All 20 recorded passages match indexed IDs, text, hashes, headings, source metadata, URLs, and anchors; all have the requested product/version |
| Prompt / citations | Recorded prompt hashes and byte sizes match messages; citation records match their supplied evidence; no omitted chunks |

These are observations of this run. Timing is not a controlled benchmark; reported model cost does not measure local hardware/electricity costs or account billing independently. No new provider requests or retrieval runs were needed for this review.

The original report's `semantic_review_status` and per-case review fields remain `pending`/null because it was saved before review. **This document is the separate, dated semantic review.** The immutable report was not edited to insert later judgments.

## Semantic findings

| Case | Correctness | Claim support | Citation quality | Abstention |
| --- | --- | --- | --- | --- |
| dev-001, URI / 3.13 | Correct conversion, examples, error conditions, and addition note | E1 supports the substantive claims and examples | Valid IDs/URLs, but citations appear only after the final sentence; E2 is broad URI context and does not support the final error/version claims | Answers an answerable question; no false abstention in this case |
| dev-014, copying / 3.12 | Core comparison correct; preservation qualification incomplete | E1 supports an attempt to preserve metadata using `copystat`; E4 supports copying contents without metadata. Opening sentence is too categorical without the supplied limits | E1/E4 are relevant, but grouped at paragraph end. E2's explicit preservation warning was supplied and unused | Answers an answerable question; no false abstention in this case |
| dev-004, URI / 3.12 | Correctly reports a gap in supplied conversion evidence | Does not invent a conversion or infer release-wide absence from retrieval | No factual answer citations are needed for this evidence-gap response | Appropriate insufficiency in this case |
| dev-023, Kubernetes / 3.13 | Correctly declines to invent deployment limits | Retrieved Python material supplies no DocLens Kubernetes sizing guidance | No fabricated citations or deployment advice | Appropriate insufficiency in this case |

### URI claim and citation placement

E1 (`pathlib.Path.from_uri`) contains the conversion, POSIX/Windows examples, variant URI forms, invalid-input conditions, and 3.13 addition note. The answer preserves useful code formatting and stays within those behaviors. The import is consistent with the documented `pathlib` API. The Windows examples are explicitly introduced as Windows behavior.

However, the first claim, both code blocks, and the URI-variant paragraph have no nearby citation markers. `[E1][E2]` appears only at the end of the last sentence. E1 supports that final sentence; E2 (`parsing-and-generating-uris`) gives general file-URI context and portability information rather than the API's error conditions or addition date. Grouping both there makes the claim-to-source mapping ambiguous. This is not evidence of a fabricated API, but it prevents claiming precise, complete claim-level citation coverage.

### copy2 metadata limits

The actual answer opens with “shutil.copy2 copies metadata as well as file contents” and later says it “attempts to preserve” metadata. The second wording is appropriately qualified; the first can be read as a guarantee. The response omits the available warning that even `copy2` cannot preserve all metadata. E2 explicitly describes omitted ownership/ACL/resource-fork/alternate-stream information across platforms. E1 also describes platform-dependent symbolic-link metadata support.

The core `copyfile` versus `copy2` choice is correct, but the answer does not fully express the reference answer's platform limitation. This is a completeness/qualification issue, rather than a reason to mark all supported claims incorrect. `answered` is the model's saved status, not a semantic-quality pass. There is no need to rewrite the frozen output or relabel the question.

A suggested revision for a future answer, **not a replacement live result**, would be:

> `copyfile` copies file contents without metadata. [E4] `copy2` also attempts to preserve metadata using `copystat`, but cannot preserve every metadata field, and support varies by platform. [E1][E2]

### Missing evidence and outcome scope

dev-004 retrieves the reverse `as_uri` operation, file I/O/iteration, and a 3.12 release-note passage. Those do not supply the requested conversion instructions. The model identifies that missing documentation and the renderer explicitly avoids concluding that the feature is absent from the release. dev-023 receives unrelated Python CPU/container, JSON, and release-note material; it provides no deployment-resource numbers. Both are appropriate evidence-limited abstentions.

There were two supported answers and two appropriate abstentions in this fixed sample. Do not turn those four observations into a broad accuracy, citation-precision, or calibrated-abstention score. No live `partial` outcome, injected-document attack, provider failure, or version-comparison answer is evaluated by this successful run; related offline contracts remain separate.

## Earlier outputs retained

- `outputs/answers/openrouter-model-verification.json`: public catalog ID, canonical ID, zero input/output prices, context/capabilities, and catalog hash. The actual application HTTP client successfully fetched the public catalog with ordinary TLS verification and no key/question/evidence sent. This verifies pricing metadata and the public HTTPS path, not live generation availability.
- `outputs/answers/dev-prompts.json`: exact prepared messages, full citation map, hashes, scope, omissions, and pending semantic-review fields for the four dev cases. No model API call.
- `outputs/answers/uri-prompt.json`: actual CLI `ask --inspect-prompt` output for the supported URI question.
- `outputs/answers/dev-live-attempt.json`: first case has a `configuration` error; remaining cases were not attempted. All generated-answer fields are null. CLI exited 1 with a readable missing-key message. This is not an insufficient-evidence prediction.

These earlier outputs are local and ignored by Git. They remain as historical records of the 2026-10-28 prompt preparation and missing-key attempt. The successful report above supersedes their pending-live status. No report or synthetic answer was substituted for the user's actual output.

## Earlier prompt inspection, 2026-10-28

This is a review of the **retrieved passages and prompts**, not a review of generated claims. It was performed by the implementing assistant, without independent human validation.

| Dev ID | Requested release | Serialized prompt bytes | Supplied passages | Evidence inspection |
| --- | --- | ---: | ---: | --- |
| dev-001 | 3.13 | 8,138 | 5 | E1 is `pathlib.Path.from_uri`, with the file-URI example, error conditions, and 3.13 addition note. Enough evidence for a direct conversion answer. |
| dev-014 | 3.12 | 9,961 | 5 | E1 describes `copy2` metadata attempts; E4 describes `copyfile` copying content without metadata. E2 warns that not all metadata can be copied. Review whether the answer avoids promising complete metadata preservation. |
| dev-004 | 3.12 | 7,347 | 5 | Related URI/file APIs and release notes are supplied, without the requested `Path.from_uri` conversion instruction. Appropriate behavior is to describe the evidence gap, not assert release-wide absence. |
| dev-023 | 3.13 | 7,725 | 5 | Python release notes/library passages do not establish Kubernetes CPU/memory limits. Appropriate behavior is to decline to guess. |

All 20 supplied passages retain the requested version; all four prompts fit the 24,000-byte budget with zero omissions. The actual first passage in dev-001 contains:

```python
>>> p = Path.from_uri('file:///etc/hosts')
PosixPath('/etc/hosts')
```

This is retrieved documentation, not generated output. Its trusted citation target is `https://docs.python.org/3.13/library/pathlib.html#pathlib.Path.from_uri`.

## Remaining quality validation

Improve explicit metadata-preservation caveats and claim-local citation placement in a future focused change, preserving this report as the baseline. Independent human review, broader development coverage, held-out assessment, and quantitative claim/citation annotation remain open. These are quality-validation tasks beyond establishing a working direct RAG pipeline. A graph wrapper will reuse this behavior and will not itself resolve the observed answer-quality issues.
