"""Hand-computed metric checks and snapshot-safe offline report generation."""

import copy
import hashlib
import io
import json
import sqlite3
import unittest
from contextlib import redirect_stdout
from dataclasses import asdict, replace
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from doclens.__main__ import main
from doclens.chunk import ChunkPolicy, chunk_document
from doclens.embeddings import EmbeddingConfig
from doclens.evaluation import (
    EvidenceCatalog, EvidenceGroup, EvidenceReference, EvaluationQuestion,
    aggregate, load_catalog, load_questions, run_evaluation, score_question, validate_snapshot,
)
from doclens.parse import parse_html
from doclens.records import SearchResponse, SearchResult, Source, document_from_dict
from doclens.retrieval import build_index, search_index


CONFIG = EmbeddingConfig("test/encoder", "a" * 40, 3, 100, "document: ", "query: ")


class FakeEncoder:
    config = CONFIG
    runtime = {"backend": "test-double"}

    def __init__(self):
        self.calls = 0

    def token_counts(self, texts, *, query=False):
        return [len(text.split()) for text in texts]

    def encode(self, texts, *, query=False):
        self.calls += 1
        return [(1, 0, 0) for _ in texts]


class MetricTests(unittest.TestCase):
    def setUp(self):
        self.catalog = EvidenceCatalog({}, {}, {}, {}, {})
        self.a = self.result("a", "3.13", "api.a")
        self.duplicate_a = self.result("a-duplicate", "3.13", "api.a")
        self.b = self.result("b", "3.13", "api.b")
        self.irrelevant = self.result("irrelevant", "3.13", "other")
        self.old = self.result("old", "3.12", "api.old")
        self.question = EvaluationQuestion(
            "q1", "multi_source", "question", "python", ("3.13",), True, "answer",
            (self.group("e1", self.a), self.group("e2", self.b)), None,
        )

    def result(self, identifier, version, anchor):
        source = Source(f"python-{version}-guide", "python", version, "reference",
                        f"https://docs.example.test/{version}/guide.html", "a" * 64,
                        "2026-10-27T00:00:00+00:00", "https://docs.example.test/license.html")
        self.catalog.sources[source.source_id] = asdict(source)
        self.catalog.chunk_sources[identifier] = asdict(source)
        self.catalog.chunk_regions[identifier] = {(source.source_id, anchor)}
        return SearchResult(1, 0.5, identifier, source, "Guide", ("Guide",), source.url + "#" + anchor,
                            "Evidence.", hashlib.sha256(b"Evidence.").hexdigest(), False)

    def group(self, identifier, *results):
        refs = [EvidenceReference(r.source.source_id, r.source.version, r.url.split('#')[1], r.url, "Evidence.") for r in results]
        return EvidenceGroup(identifier, "required fact", tuple(refs))

    def response(self, version, results):
        return SearchResponse("question", "python", version, len(results), CONFIG.model_id, CONFIG.revision, tuple(results))

    def score(self, results, *, top_k=5, question=None):
        return score_question(self.question if question is None else question,
                              {"3.13": self.response("3.13", results)}, top_k=top_k, catalog=self.catalog)

    def test_duplicate_chunks_count_once_and_rank_cutoff_is_respected(self):
        score = self.score([self.a, self.duplicate_a, self.irrelevant, self.b], top_k=3)
        self.assertEqual(score["evidence_recall_at_k"], 0.5)
        self.assertEqual(score["evidence_group_recall_at_k"], 0.5)
        self.assertEqual(score["mrr_at_k"], 1)
        self.assertEqual(score["returned_chunks"], 3)
        complete = self.score([self.a, self.duplicate_a, self.irrelevant, self.b], top_k=4)
        self.assertEqual(complete["evidence_recall_at_k"], 1)

    def test_mrr_uses_first_relevant_rank_and_zero_for_no_hit(self):
        score = self.score([self.irrelevant, self.irrelevant, self.a])
        self.assertAlmostEqual(score["mrr_at_k"], 1 / 3)
        missed = self.score([self.irrelevant])
        self.assertEqual(missed["mrr_at_k"], 0)
        self.assertEqual(missed["evidence_recall_at_k"], 0)

    def test_alternative_sources_are_distinct_from_required_group_coverage(self):
        question = replace(self.question, evidence_groups=(self.group("alternatives", self.a, self.b),))
        score = self.score([self.a], question=question)
        self.assertEqual(score["evidence_recall_at_k"], 0.5)
        self.assertEqual(score["evidence_group_recall_at_k"], 1)
        self.assertEqual(score["missed_evidence_groups"], [])

    def test_comparison_uses_separate_reciprocal_ranks(self):
        question = replace(self.question, category="comparison", versions=("3.12", "3.13"),
                           evidence_groups=(self.group("old", self.old), self.group("new", self.b)))
        irrelevant_old = self.result("irrelevant-old", "3.12", "other")
        responses = {"3.12": self.response("3.12", [irrelevant_old, self.old]),
                     "3.13": self.response("3.13", [self.b])}
        score = score_question(question, responses, top_k=2, catalog=self.catalog)
        self.assertEqual(score["mrr_at_k"], 0.75)
        self.assertEqual(score["evidence_recall_at_k"], 1)
        self.assertTrue(score["all_versions_with_evidence"])

    def test_other_compared_version_is_still_wrong_in_this_calls_pool(self):
        question = replace(self.question, category="comparison", versions=("3.12", "3.13"),
                           evidence_groups=(self.group("old", self.old), self.group("new", self.b)))
        responses = {"3.12": self.response("3.12", [self.b]), "3.13": self.response("3.13", [self.old])}
        score = score_question(question, responses, top_k=5, catalog=self.catalog)
        self.assertEqual(score["wrong_version_chunks"], 2)
        self.assertEqual(score["evidence_recall_at_k"], 0)
        self.assertEqual(score["mrr_at_k"], 0)
        self.assertFalse(score["all_versions_with_evidence"])
        self.assertEqual(aggregate([score])["wrong_version_retrieval_rate"], 1)

    def test_unsupported_questions_do_not_get_fake_zero_recall_or_mrr(self):
        question = replace(self.question, category="missing_evidence", answerable=False,
                           reference_answer=None, evidence_groups=(), unanswerable_reason="Outside corpus.")
        unsupported = self.score([self.irrelevant], question=question)
        self.assertIsNone(unsupported["evidence_recall_at_k"])
        self.assertIsNone(unsupported["mrr_at_k"])
        self.assertEqual(unsupported["returned_chunks"], 1)
        positive = self.score([self.a, self.b])
        metrics = aggregate([positive, unsupported])
        self.assertEqual(metrics["questions"], 2)
        self.assertEqual(metrics["answerable_questions"], 1)
        self.assertEqual(metrics["evidence_recall_at_k"], 1)
        self.assertIsNone(aggregate([unsupported])["mrr_at_k"])

    def test_unknown_chunk_or_wrong_result_provenance_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "outside the evaluation snapshot"):
            self.score([replace(self.a, chunk_id="unknown")])
        with self.assertRaisesRegex(ValueError, "provenance differs"):
            self.score([replace(self.a, source=replace(self.a.source, content_hash="b" * 64))])

    def test_empty_observation_denominators_are_explicitly_undefined(self):
        metrics = aggregate([])
        self.assertIsNone(metrics["evidence_recall_at_k"])
        self.assertIsNone(metrics["wrong_version_retrieval_rate"])
        self.assertEqual(metrics["answerable_questions"], 0)

    def test_decorative_api_names_do_not_count_as_evidence_hits(self):
        result = replace(self.irrelevant, text="Heading mentions api.a but the evidence belongs to another region.")
        score = self.score([result])
        self.assertEqual(score["evidence_recall_at_k"], 0)


class EvaluationRunTests(unittest.TestCase):
    def setUp(self):
        temporary = TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.index = self.root / "index.sqlite3"
        self.dataset = self.root / "dev.json"
        self.output = self.root / "report.json"
        self.encoder = FakeEncoder()
        raw = b'<main><section id="guide"><h1>Guide</h1><p>Evidence for testing.</p></section></main>'
        doc = parse_html(raw, source_url="https://docs.example.test/3.13/guide.html")
        doc["source"] = {
            "source_id": "python-3.13-guide", "product": "python", "version": "3.13",
            "document_type": "reference", "url": "https://docs.example.test/3.13/guide.html",
            "sha256": hashlib.sha256(raw).hexdigest(), "fetched_at": "2026-10-27T00:00:00+00:00",
            "source_terms_url": "https://docs.example.test/license.html",
        }
        chunks = chunk_document(document_from_dict(doc))
        build_index(chunks, path=self.index, encoder=self.encoder, manifest_hash="f" * 64, policy=ChunkPolicy())
        self.data = {
            "schema_version": 1, "split": "dev", "name": "fixture",
            "corpus_manifest_sha256": "f" * 64,
            "source_hashes": {"python-3.13-guide": doc["source"]["sha256"]},
            "questions": [{
                "id": "dev-001", "category": "exact", "query": "question", "product": "python",
                "versions": ["3.13"], "answerable": True, "reference_answer": "Evidence for testing.",
                "unanswerable_reason": None, "evidence_groups": [{"id": "e1", "fact": "A fact", "references": [{
                    "source_id": "python-3.13-guide", "version": "3.13", "anchor": "guide",
                    "url": "https://docs.example.test/3.13/guide.html#guide", "quote": "Evidence for testing.",
                }]}],
            }],
        }
        self.save_dataset()

    def save_dataset(self):
        self.dataset.write_text(json.dumps(self.data))

    def run_eval(self, **kwargs):
        return run_evaluation(self.dataset, self.index, root=self.root, output=self.output, encoder=self.encoder, **kwargs)

    def test_report_is_reproducible_and_dev_does_not_open_heldout(self):
        heldout = self.root / "heldout.json"
        heldout.write_text("Deliberately not valid JSON; must not be opened.")
        index_before = self.index.read_bytes()
        first, second = self.run_eval(), self.run_eval()
        self.assertEqual(first["overall"], second["overall"])
        self.assertEqual(first["dataset_sha256"], hashlib.sha256(self.dataset.read_bytes()).hexdigest())
        self.assertEqual(first["index_sha256"], second["index_sha256"])
        self.assertEqual(first["overall"]["evidence_recall_at_k"], 1)
        self.assertEqual(first["cases"][0]["candidate_counts"], {"3.13": 1})
        self.assertEqual(index_before, self.index.read_bytes())
        self.assertEqual(json.loads(self.output.read_text())["split"], "dev")
        self.assertEqual(heldout.read_text(), "Deliberately not valid JSON; must not be opened.")

    def test_snapshot_mismatch_fails_before_search_and_preserves_report(self):
        self.output.write_text("previous report")
        self.data["source_hashes"]["python-3.13-guide"] = "b" * 64
        self.save_dataset()
        calls = self.encoder.calls
        with self.assertRaisesRegex(ValueError, "source snapshots differ"):
            self.run_eval()
        self.assertEqual(self.encoder.calls, calls)
        self.assertEqual(self.output.read_text(), "previous report")

    def test_missing_quote_or_foreign_reference_is_rejected(self):
        for field, value in (("quote", "not present"), ("anchor", "not-present"), ("version", "3.12")):
            data = copy.deepcopy(self.data)
            data["questions"][0]["evidence_groups"][0]["references"][0][field] = value
            with self.subTest(field=field), self.assertRaises(ValueError):
                validate_snapshot(data, load_questions(data, split="dev"), load_catalog(self.index))

    def test_duplicate_or_contradictory_question_labels_are_rejected(self):
        cases = []
        data = copy.deepcopy(self.data)
        data["questions"].append(copy.deepcopy(data["questions"][0]))
        cases.append(data)
        data = copy.deepcopy(self.data)
        data["questions"][0]["answerable"] = False
        cases.append(data)
        data = copy.deepcopy(self.data)
        data["questions"][0]["versions"] = [3.13]
        cases.append(data)
        for data in cases:
            with self.subTest(data=data), self.assertRaises(ValueError):
                load_questions(data, split="dev")
        with self.assertRaises(ValueError):
            load_questions(self.data, split="heldout")

    def test_index_change_during_run_does_not_replace_previous_report(self):
        self.output.write_text("previous report")

        def changed_search(*args, **kwargs):
            response = search_index(*args, **kwargs)
            self.index.write_bytes(self.index.read_bytes() + b"changed")
            return response

        with self.assertRaisesRegex(ValueError, "Index changed during evaluation"):
            self.run_eval(searcher=changed_search)
        self.assertEqual(self.output.read_text(), "previous report")

    def test_dataset_and_index_cannot_be_used_as_report_paths(self):
        heldout = self.root / "evals" / "heldout.json"
        heldout.parent.mkdir()
        heldout.write_text("reserved labels")
        for path in (self.dataset, self.index, heldout):
            before = path.read_bytes()
            with self.subTest(path=path), self.assertRaisesRegex(ValueError, "must not overwrite"):
                run_evaluation(self.dataset, self.index, root=self.root, output=path, encoder=self.encoder)
            self.assertEqual(path.read_bytes(), before)

    def test_quote_validation_merges_overlaps_and_rejects_conflicting_text(self):
        with sqlite3.connect(self.index) as connection:
            row = connection.execute("SELECT chunk_id,product,version,source_id,payload,embedding FROM chunks").fetchone()
            original = json.loads(row[4])
            body = original["pieces"][0]["text"]
            first, second = copy.deepcopy(original), copy.deepcopy(original)
            first["pieces"][0].update(text=body[:12], end_char=12)
            second["chunk_id"] += "-overlap"
            second["pieces"][0].update(text=body[8:], start_char=8)
            connection.execute("UPDATE chunks SET payload=?", (json.dumps(first),))
            connection.execute("INSERT INTO chunks VALUES (?,?,?,?,?,?)", (second["chunk_id"],*row[1:4],json.dumps(second),row[5]))
            connection.execute("UPDATE metadata SET value='2' WHERE key='chunks'")
        catalog = load_catalog(self.index)
        self.assertEqual(catalog.regions[("python-3.13-guide", "guide")], body)
        validate_snapshot(self.data, load_questions(self.data, split="dev"), catalog)
        second["pieces"][0]["text"] = "X" + second["pieces"][0]["text"][1:]
        with sqlite3.connect(self.index) as connection:
            connection.execute("UPDATE chunks SET payload=? WHERE chunk_id=?", (json.dumps(second),second["chunk_id"]))
        with self.assertRaisesRegex(ValueError, "Overlapping evidence pieces disagree"):
            load_catalog(self.index)

    def test_cli_outputs_metrics_and_report_location(self):
        args = ["doclens", "evaluate", "--dataset", str(self.dataset), "--index", str(self.index), "--output", str(self.output)]
        output = io.StringIO()
        with patch("sys.argv", args), patch("doclens.evaluation.LocalEncoder", return_value=self.encoder):
            with redirect_stdout(output):
                main()
        self.assertIn("evidence_recall@5=1.0000", output.getvalue())
        self.assertIn("Wrong-version chunks: 0/1", output.getvalue())
        self.assertTrue(self.output.exists())


if __name__ == "__main__":
    unittest.main()
