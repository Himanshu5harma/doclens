"""Bounded development-only generation sample; semantic review remains explicit."""

import hashlib
import json
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path

from doclens.answers import answer_question, prepare_question
from doclens.embeddings import EmbeddingConfig, LocalEncoder
from doclens.evaluation import _code_snapshot, load_catalog, load_questions, validate_snapshot
from doclens.files import write_atomic
from doclens.generation import GenerationConfig, GenerationError, OpenRouterClient


# Fixed before any live outputs. Two supported cases and two missing-evidence cases.
# No comparison workflow or implicit held-out access in this learning unit.
DEVELOPMENT_IDS = ("dev-001", "dev-014", "dev-004", "dev-023")


def run_answer_sample(index: Path, *, root: Path, config: GenerationConfig,
                      output: Path, inspect_only: bool = False, client=None, encoder=None) -> dict:
    destination = output.resolve()
    if not destination.is_relative_to((root / "outputs" / "answers").resolve()):
        raise ValueError("Answer evaluation reports must stay under outputs/answers/; inputs are protected.")
    if destination == index.resolve():
        raise ValueError("Answer evaluation output must not overwrite the index.")
    dataset = root / "evals" / "dev.json"
    data_bytes = dataset.read_bytes()
    data = json.loads(data_bytes)
    questions = load_questions(data, split="dev")
    selected = {q.id: q for q in questions}
    if not set(DEVELOPMENT_IDS) <= selected.keys():
        raise ValueError("Development dataset does not contain the fixed generation sample.")
    index_hash = hashlib.sha256(index.read_bytes()).hexdigest()
    catalog = load_catalog(index)
    validate_snapshot(data, questions, catalog)
    if encoder is None:
        encoder = LocalEncoder(EmbeddingConfig.from_dict(catalog.metadata["embedding"]),
                               cache=root / "data" / "models", offline=True)
    client = client or OpenRouterClient()
    cases, stopped = [], False
    for identifier in DEVELOPMENT_IDS:
        q = selected[identifier]
        if len(q.versions) != 1:
            raise ValueError("Generation sample requires single-version questions.")
        prepared = prepare_question(index, q.query, version=q.versions[0], product=q.product,
                                    root=root, config=config, top_k=5, encoder=encoder)
        case = {
            "id": identifier, "category": q.category, "expected_answerable": q.answerable,
            "reference_answer": q.reference_answer, "evidence_groups": [asdict(g) for g in q.evidence_groups],
            "prepared": asdict(prepared), "outcome": "prompt_only" if inspect_only else "pending",
            "structural_validation_passed": None, "answer": None,
            "semantic_review": {"reviewer": None, "independent_human_review": False,
                                "correctness": None, "claim_support": None,
                                "citation_quality": None, "abstention": None, "notes": []},
        }
        if not inspect_only and not stopped:
            try:
                result = answer_question(prepared, config, client=client)
                case.update(outcome="generated", structural_validation_passed=True, answer=asdict(result))
            except GenerationError as error:
                case.update(outcome="error", structural_validation_passed=(
                                False if error.kind in ("invalid_answer", "invalid_response") else None),
                            error={"kind": error.kind, "message": str(error), "metadata": error.metadata})
                # Stop on provider failure rather than consume more free requests.
                # Invalid answer structures remain inspectable; no repair/retry.
                stopped = True
        elif stopped:
            case["outcome"] = "not_attempted_after_error"
        cases.append(case)
    if hashlib.sha256(index.read_bytes()).hexdigest() != index_hash:
        raise ValueError("Index changed during answer evaluation; mixed-snapshot report was not saved.")
    report = {
        "schema_version": 1, "split": "dev", "created_at": datetime.now(timezone.utc).isoformat(),
        "mode": "prompt_only" if inspect_only else "live", "selected_question_ids": DEVELOPMENT_IDS,
        "maximum_completion_requests": 4, "automatic_retries": 0,
        "dataset_sha256": hashlib.sha256(data_bytes).hexdigest(), "index_sha256": index_hash,
        "index_metadata": catalog.metadata, "generation_settings": asdict(config), "code": _code_snapshot(root),
        "annotation": data.get("annotation"), "semantic_review_status": "pending",
        "claims": "Structural validation is automated. No semantic score or independent human validation is implied.",
        "cases": cases,
    }
    write_atomic(output, (json.dumps(report, ensure_ascii=False, indent=2) + "\n").encode())
    return report
