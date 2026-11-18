"""Baseline CLI answering over the SQLite index (replaced in the unified answer step)."""

import time
from dataclasses import replace
from pathlib import Path

from doclens.answers.grounding import (
    AnswerResult,
    PreparedQuestion,
    _safe_input,
    assemble_evidence,
)
from doclens.answers.ports import GenerationConfig
from doclens.legacy.retrieval import search_index


def prepare_question(index: Path, question: str, *, version: str, root: Path,
                     config: GenerationConfig, product: str = "python", top_k: int = 5,
                     encoder=None) -> PreparedQuestion:
    # Block credential mistakes before even encoding the question locally.
    _safe_input(question)
    if type(top_k) is not int or not 1 <= top_k <= 20:
        raise ValueError("ask top_k must be between 1 and 20.")
    started = time.perf_counter()
    response = search_index(index, question, version=version, product=product, root=root, top_k=top_k, encoder=encoder)
    prepared = assemble_evidence(response, config)
    return replace(prepared, retrieval={
        **prepared.retrieval, "seconds": time.perf_counter() - started,
        "includes_encoder_load": encoder is None,
    })


def display_answer(result: AnswerResult) -> str:
    lines = [f"{result.status.value} — {result.prepared.product} {result.prepared.version}", "", result.answer]
    if result.missing_evidence:
        lines += ["", "Missing evidence:", *[f"- {gap}" for gap in result.missing_evidence]]
    for item in result.citations:
        passage = item.passage
        lines += ["", f"[{item.citation_id}] {passage.source.source_id} — {' > '.join(passage.heading_path)}",
                  passage.url]
    if result.prepared.omitted_chunk_ids:
        lines += ["", f"Prompt budget omitted {len(result.prepared.omitted_chunk_ids)} whole retrieved passages; inspect --json."]
    if result.generation:
        lines += ["", f"Model: {result.generation.get('requested_model')} -> {result.generation.get('returned_model')}"]
    return "\n".join(lines)
