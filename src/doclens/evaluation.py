"""Source-anchored retrieval evaluation without tuning or an answer grader."""

import hashlib
import json
import sqlite3
import subprocess
import time
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from statistics import mean

from doclens.embeddings import EmbeddingConfig, Encoder, LocalEncoder
from doclens.files import write_atomic
from doclens.records import SearchResponse, citation_url
from doclens.retrieval import search_index


@dataclass(frozen=True)
class EvidenceReference:
    source_id: str
    version: str
    anchor: str
    url: str
    quote: str

    @property
    def key(self) -> tuple[str, str]:
        return self.source_id, self.anchor


@dataclass(frozen=True)
class EvidenceGroup:
    id: str
    fact: str
    references: tuple[EvidenceReference, ...]


@dataclass(frozen=True)
class EvaluationQuestion:
    id: str
    category: str
    query: str
    product: str
    versions: tuple[str, ...]
    answerable: bool
    reference_answer: str | None
    evidence_groups: tuple[EvidenceGroup, ...]
    unanswerable_reason: str | None


def _text(value: object, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{label} must be a nonempty string.")
    return value


def load_questions(data: dict, *, split: str) -> tuple[EvaluationQuestion, ...]:
    if not isinstance(data, dict) or type(data.get("schema_version")) is not int or data["schema_version"] != 1 or data.get("split") != split:
        raise ValueError("Evaluation dataset schema/split does not match the requested split.")
    if not isinstance(data.get("questions"), list) or not data["questions"]:
        raise ValueError("Evaluation dataset needs a nonempty questions list.")
    questions, ids, queries = [], set(), set()
    categories = {"exact", "paraphrase", "multi_source", "comparison", "missing_evidence"}
    for record in data["questions"]:
        if not isinstance(record, dict):
            raise ValueError("Each evaluation question must be an object.")
        identifier = _text(record.get("id"), "question ID")
        query = _text(record.get("query"), "query")
        if identifier in ids or " ".join(query.lower().split()) in queries:
            raise ValueError("Question IDs and query text must be unique within a split.")
        ids.add(identifier)
        queries.add(" ".join(query.lower().split()))
        if record.get("category") not in categories:
            raise ValueError(f"Question {identifier}: unsupported category.")
        versions = record.get("versions")
        if not isinstance(versions, list) or not versions or any(not isinstance(v, str) or not v.strip() for v in versions):
            raise ValueError("Requested versions must be a nonempty list of strings.")
        if len(set(versions)) != len(versions):
            raise ValueError("Requested versions must be unique.")
        if (record["category"] == "comparison") != (len(versions) > 1):
            raise ValueError("Only comparison questions can request multiple versions.")
        if type(record.get("answerable")) is not bool:
            raise ValueError("answerable must be a boolean.")
        raw_groups = record.get("evidence_groups")
        if not isinstance(raw_groups, list):
            raise ValueError("evidence_groups must be a list.")
        groups, group_ids = [], set()
        for group in raw_groups:
            if not isinstance(group, dict) or not isinstance(group.get("references"), list) or not group["references"]:
                raise ValueError("Evidence groups need a nonempty references list.")
            group_id = _text(group.get("id"), "evidence group ID")
            if group_id in group_ids:
                raise ValueError("Evidence group IDs must be unique within a question.")
            group_ids.add(group_id)
            references = []
            for ref in group["references"]:
                if not isinstance(ref, dict):
                    raise ValueError("Each evidence reference must be an object.")
                references.append(EvidenceReference(**{
                    key: _text(ref.get(key), f"reference.{key}")
                    for key in ("source_id", "version", "anchor", "url", "quote")
                }))
            if len({ref.key for ref in references}) != len(references):
                raise ValueError("Duplicate references within an evidence group.")
            if len({ref.version for ref in references}) != 1:
                raise ValueError("Alternatives within a group must describe the same version.")
            groups.append(EvidenceGroup(group_id, _text(group.get("fact"), "required fact"), tuple(references)))
        if record["answerable"]:
            answer = _text(record.get("reference_answer"), "reference answer")
            covered = {ref.version for group in groups for ref in group.references}
            if not groups or covered != set(versions):
                raise ValueError("Answerable questions need evidence for every requested version.")
            reason = None
            if record["category"] == "missing_evidence":
                raise ValueError("Missing-evidence questions cannot be marked answerable.")
        else:
            if groups or record.get("reference_answer") is not None or record["category"] != "missing_evidence":
                raise ValueError("Missing-evidence questions require no positive labels/reference answer.")
            answer, reason = None, _text(record.get("unanswerable_reason"), "missing-evidence reason")
        questions.append(EvaluationQuestion(
            identifier, record["category"], query, _text(record.get("product"), "product"),
            tuple(versions), record["answerable"], answer, tuple(groups), reason,
        ))
    return tuple(questions)


@dataclass
class EvidenceCatalog:
    metadata: dict
    sources: dict
    regions: dict
    chunk_regions: dict
    chunk_sources: dict


def load_catalog(index: Path) -> EvidenceCatalog:
    """Recover source regions from original pieces, not decorative context text."""
    connection = sqlite3.connect(index.resolve().as_uri() + "?mode=ro", uri=True)
    try:
        metadata = {k: json.loads(v) for k, v in connection.execute("SELECT key,value FROM metadata")}
        rows = connection.execute("SELECT chunk_id,product,version,source_id,payload FROM chunks").fetchall()
    finally:
        connection.close()
    if metadata.get("schema_version") != 1 or not rows or metadata.get("chunks") != len(rows):
        raise ValueError("Unsupported or empty evaluation index.")
    sources, spans, locations, chunk_sources = {}, {}, {}, {}
    for chunk_id, product, version, source_id, payload in rows:
        chunk = json.loads(payload)
        source = chunk["source"]
        if (source["product"], source["version"], source["source_id"]) != (product, version, source_id):
            raise ValueError("Indexed evidence metadata disagrees with its source/version columns.")
        if source_id in sources and sources[source_id] != source:
            raise ValueError("Mixed source snapshots in the evaluation index.")
        sources[source_id] = source
        chunk_sources[chunk_id] = source
        locations[chunk_id] = set()
        for piece in chunk["pieces"]:
            anchor = piece["anchor"] or chunk["anchor"]
            key = (source_id, anchor)
            locations[chunk_id].add(key)
            block = (key, chunk["section_index"], piece["block_index"])
            span = (piece["start_char"], piece["end_char"])
            if span[0] < 0 or span[1] - span[0] != len(piece["text"]):
                raise ValueError("Invalid evidence-piece offsets.")
            previous = spans.setdefault(block, {}).get(span)
            if previous is not None and previous != piece["text"]:
                raise ValueError("Conflicting duplicate evidence pieces.")
            spans[block][span] = piece["text"]
    regions = {}
    for (key, section_index, block_index), parts in sorted(spans.items(), key=lambda item: repr(item[0])):
        text = ""
        for (start, end), part in sorted(parts.items()):
            if start > len(text):
                raise ValueError("Gap in indexed evidence pieces.")
            overlap = min(len(text), end) - start
            if overlap > 0 and text[start:start + overlap] != part[:overlap]:
                raise ValueError("Overlapping evidence pieces disagree.")
            if end > len(text):
                text += part[len(text) - start:]
        regions.setdefault(key, []).append(text)
    return EvidenceCatalog(metadata, sources, {key: " ".join(" ".join(parts).split()) for key, parts in regions.items()}, locations, chunk_sources)


def validate_snapshot(data: dict, questions: tuple[EvaluationQuestion, ...], catalog: EvidenceCatalog) -> None:
    expected = data.get("source_hashes")
    actual = {identifier: source["content_hash"] for identifier, source in catalog.sources.items()}
    if not isinstance(expected, dict) or not expected or expected != actual:
        raise ValueError("Dataset and index source snapshots differ; review labels before updating the dataset.")
    if data.get("corpus_manifest_sha256") != catalog.metadata.get("manifest_sha256"):
        raise ValueError("Dataset and index corpus manifests differ.")
    for question in questions:
        for version in question.versions:
            if not any(s["version"] == version and s["product"] == question.product for s in catalog.sources.values()):
                raise ValueError(f"Question {question.id}: requested product/version is not indexed.")
        for group in question.evidence_groups:
            for ref in group.references:
                source = catalog.sources.get(ref.source_id)
                if source is None or source["version"] != ref.version or source["product"] != question.product:
                    raise ValueError(f"Question {question.id}: reference source/version mismatch.")
                if ref.version not in question.versions or ref.url != citation_url(source["url"], ref.anchor):
                    raise ValueError(f"Question {question.id}: reference is outside the requested scope.")
                if ref.key not in catalog.regions or " ".join(ref.quote.split()) not in catalog.regions[ref.key]:
                    raise ValueError(f"Question {question.id}: evidence anchor/quote was not found in this snapshot.")


def score_question(question: EvaluationQuestion, responses: dict[str, SearchResponse], *, top_k: int, catalog: EvidenceCatalog) -> dict:
    if set(responses) != set(question.versions) or type(top_k) is not int or top_k <= 0:
        raise ValueError("Scoring requires every requested version and a positive top_k.")
    gold = {ref.key for group in question.evidence_groups for ref in group.references}
    hits, reciprocal_ranks, hit_versions = set(), [], set()
    wrong, total, returned = 0, 0, {}
    for version in question.versions:
        response = responses[version]
        if response.version != version or response.product != question.product:
            raise ValueError("Search response scope does not match its evaluation call.")
        results = response.results[:top_k]
        returned[version] = [asdict(result) for result in results]
        first_hit = None
        for rank, result in enumerate(results, 1):
            if result.chunk_id not in catalog.chunk_regions:
                raise ValueError("Retriever returned a chunk outside the evaluation snapshot.")
            stored = catalog.chunk_sources[result.chunk_id]
            if asdict(result.source) != stored:
                raise ValueError("Retriever result provenance differs from the evaluation snapshot.")
            total += 1
            if result.source.version != version or result.source.product != question.product:
                wrong += 1
                continue  # A compared version is still wrong in the other version's call.
            matched = catalog.chunk_regions[result.chunk_id] & gold
            if matched:
                hits.update(matched)
                hit_versions.add(version)
                if first_hit is None:
                    first_hit = rank
        if question.answerable:
            reciprocal_ranks.append(0.0 if first_hit is None else 1.0 / first_hit)
    missed_groups = [group.id for group in question.evidence_groups if not ({ref.key for ref in group.references} & hits)]
    return {
        "id": question.id, "category": question.category, "query": question.query,
        "versions": list(question.versions), "answerable": question.answerable,
        "reference_answer": question.reference_answer, "unanswerable_reason": question.unanswerable_reason,
        "evidence_recall_at_k": len(hits) / len(gold) if question.answerable else None,
        "mrr_at_k": mean(reciprocal_ranks) if question.answerable else None,
        "evidence_group_recall_at_k": 1 - len(missed_groups) / len(question.evidence_groups) if question.answerable else None,
        "all_versions_with_evidence": set(question.versions) == hit_versions if question.answerable else None,
        "matched_sections": [list(key) for key in sorted(hits)],
        "missed_sections": [list(key) for key in sorted(gold - hits)],
        "missed_evidence_groups": missed_groups,
        "returned_chunks": total, "wrong_version_chunks": wrong, "retrieved": returned,
    }


def aggregate(cases: list[dict]) -> dict:
    positives = [case for case in cases if case["answerable"]]
    retrieved = sum(case["returned_chunks"] for case in cases)
    wrong = sum(case["wrong_version_chunks"] for case in cases)
    return {
        "questions": len(cases), "answerable_questions": len(positives),
        **{key: mean(case[key] for case in positives) if positives else None for key in (
            "evidence_recall_at_k", "mrr_at_k", "evidence_group_recall_at_k",
        )},
        "all_versions_with_evidence_rate": mean(case["all_versions_with_evidence"] for case in positives) if positives else None,
        "wrong_version_retrieval_rate": wrong / retrieved if retrieved else None,
        "wrong_version_chunks": wrong, "retrieved_chunks": retrieved,
        "affected_question_ids": [case["id"] for case in cases if case["wrong_version_chunks"]],
    }


def _code_snapshot(root: Path) -> dict:
    hashes = {str(path.relative_to(root)): hashlib.sha256(path.read_bytes()).hexdigest() for path in sorted((root / "src" / "doclens").glob("*.py"))}
    for name in ("pyproject.toml", "uv.lock"):
        path = root / name
        if path.exists():
            hashes[name] = hashlib.sha256(path.read_bytes()).hexdigest()
    try:
        commit = subprocess.run(["git", "rev-parse", "HEAD"], cwd=root, capture_output=True, text=True, timeout=5)
        dirty = subprocess.run(["git", "status", "--porcelain"], cwd=root, capture_output=True, text=True, timeout=5)
        return {"commit": commit.stdout.strip() if commit.returncode == 0 else None, "dirty": bool(dirty.stdout) if dirty.returncode == 0 else None, "file_hashes": hashes}
    except (OSError, subprocess.TimeoutExpired):
        return {"commit": None, "dirty": None, "file_hashes": hashes}


def run_evaluation(
    dataset: Path, index: Path, *, root: Path, split: str = "dev", top_k: int = 5,
    output: Path, encoder: Encoder | None = None, searcher=search_index,
) -> dict:
    """Evaluate one explicit split; held-out files are never implicitly opened."""
    if type(top_k) is not int or top_k <= 0:
        raise ValueError("top_k must be a positive integer.")
    dataset_bytes = dataset.read_bytes()
    data = json.loads(dataset_bytes)
    questions = load_questions(data, split=split)
    if output.resolve() in (dataset.resolve(), index.resolve()) or output.resolve().is_relative_to((root / "evals").resolve()):
        raise ValueError("Evaluation output must not overwrite a dataset or index, or write into the evals label directory.")
    index_hash = hashlib.sha256(index.read_bytes()).hexdigest()
    catalog = load_catalog(index)
    validate_snapshot(data, questions, catalog)
    code = _code_snapshot(root)
    config = EmbeddingConfig.from_dict(catalog.metadata.get("embedding"))
    if encoder is None:
        encoder = LocalEncoder(config, cache=root / "data" / "models", offline=True)
    if encoder.config != config:
        raise ValueError("Evaluation encoder does not match the indexed configuration.")
    started = time.perf_counter()
    cases = []
    for question in questions:
        responses, timings = {}, {}
        for version in question.versions:
            before = time.perf_counter()
            responses[version] = searcher(index, question.query, version=version, root=root, product=question.product, top_k=top_k, encoder=encoder)
            timings[version] = time.perf_counter() - before
            if (responses[version].model_id, responses[version].model_revision) != (config.model_id, config.revision):
                raise ValueError("Search response model differs from the recorded index configuration.")
        scored = score_question(question, responses, top_k=top_k, catalog=catalog)
        scored.update(
            retrieval_seconds=timings, candidate_counts={version: response.candidate_count for version, response in responses.items()},
            evidence_groups=[asdict(group) for group in question.evidence_groups],
        )
        cases.append(scored)
    if hashlib.sha256(index.read_bytes()).hexdigest() != index_hash:
        raise ValueError("Index changed during evaluation; refusing to save a mixed-snapshot report.")
    report = {
        "schema_version": 1, "created_at": datetime.now(timezone.utc).isoformat(),
        "dataset_name": data.get("name"), "split": split, "top_k_per_version": top_k,
        "dataset_sha256": hashlib.sha256(dataset_bytes).hexdigest(), "index_sha256": index_hash,
        "dataset_source_hashes": data["source_hashes"],
        "index_metadata": catalog.metadata, "encoder_runtime": encoder.runtime,
        "code": code, "evaluation_seconds": time.perf_counter() - started,
        "retrieval_seconds_total": sum(sum(case["retrieval_seconds"].values()) for case in cases),
        "timing_scope": "per-call DB/query-encoding/ranking time after shared model load; evaluation_seconds also includes scoring",
        "model_service_requests": 0, "annotation": data.get("annotation"),
        "overall": aggregate(cases),
        "single_release": aggregate([case for case in cases if len(case["versions"]) == 1]),
        "comparison": aggregate([case for case in cases if len(case["versions"]) > 1]),
        "by_category": {category: aggregate([case for case in cases if case["category"] == category]) for category in sorted({case["category"] for case in cases})},
        "cases": cases,
    }
    write_atomic(output, (json.dumps(report, indent=2, ensure_ascii=False) + "\n").encode("utf-8"))
    return report
