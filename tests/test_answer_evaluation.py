"""Fixed-sample development isolation and honest, failure-preserving reports."""

import hashlib
import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import Mock

from doclens.answer_evaluation import DEVELOPMENT_IDS, run_answer_sample
from doclens.chunk import ChunkPolicy, chunk_document
from doclens.embeddings import EmbeddingConfig
from doclens.generation import Completion, GenerationConfig, GenerationError
from doclens.parse import parse_html
from doclens.records import document_from_dict
from doclens.retrieval import build_index


class Encoder:
    config = EmbeddingConfig("test/encoder", "a" * 40, 2, 1000, "d: ", "q: ")
    runtime = {"backend": "test-double"}
    def token_counts(self, texts): return [10] * len(texts)
    def encode(self, texts, *, query=False): return [(1, 0)] * len(texts)


class AnswerEvaluationTests(unittest.TestCase):
    def setUp(self):
        temporary = TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.index = self.root / "baseline.sqlite3"
        self.output = self.root / "outputs" / "answers" / "run.json"
        self.encoder = Encoder()
        source_url = "https://docs.example.test/3.13/guide.html"
        raw = b'<main><section id="guide"><h1>Guide</h1><p>Evidence for testing.</p></section></main>'
        document = parse_html(raw, source_url=source_url)
        document["source"] = {
            "source_id": "python-3.13-guide", "product": "python", "version": "3.13", "document_type": "reference",
            "url": source_url, "sha256": hashlib.sha256(raw).hexdigest(),
            "fetched_at": "2026-10-28T00:00:00Z", "source_terms_url": source_url,
        }
        chunks = chunk_document(document_from_dict(document))
        build_index(chunks, path=self.index, encoder=self.encoder, manifest_hash="f" * 64, policy=ChunkPolicy())
        questions = []
        for i, identifier in enumerate(DEVELOPMENT_IDS):
            positive = i < 2
            questions.append({
                "id": identifier, "category": "exact" if positive else "missing_evidence",
                "query": f"Question {i}?", "product": "python", "versions": ["3.13"], "answerable": positive,
                "reference_answer": "Evidence for testing." if positive else None,
                "unanswerable_reason": None if positive else "Outside corpus.",
                "evidence_groups": [{"id": "fact1", "fact": "Test fact", "references": [{
                    "source_id": "python-3.13-guide", "version": "3.13", "anchor": "guide",
                    "url": source_url + "#guide", "quote": "Evidence for testing.",
                }]}] if positive else [],
            })
        data = {"schema_version": 1, "split": "dev", "name": "fixture", "corpus_manifest_sha256": "f" * 64,
                "source_hashes": {"python-3.13-guide": document["source"]["sha256"]}, "questions": questions}
        (self.root / "evals").mkdir()
        (self.root / "evals" / "dev.json").write_text(json.dumps(data))
        self.heldout = self.root / "evals" / "heldout.json"
        self.heldout.write_text("Invalid JSON; held-out file must not be opened.")
        self.client = Mock()
        self.client.complete.return_value = Completion(json.dumps({
            "status": "answered", "answer": "Evidence for testing. [E1]", "citations": ["E1"], "missing_evidence": [],
        }), {"finish_reason": "stop", "requested_model": "offline-test-double"})

    def run_sample(self, **kwargs):
        return run_answer_sample(self.index, root=self.root, config=GenerationConfig(), output=self.output,
                                 encoder=self.encoder, client=self.client, **kwargs)

    def test_fixed_four_cases_and_separate_pending_semantic_review(self):
        before = self.index.read_bytes()
        report = self.run_sample()
        self.assertEqual(self.client.complete.call_count, 4)
        self.assertEqual(report["split"], "dev")
        self.assertEqual(report["maximum_completion_requests"], 4)
        self.assertEqual(report["semantic_review_status"], "pending")
        self.assertEqual([case["id"] for case in report["cases"]], list(DEVELOPMENT_IDS))
        for case in report["cases"]:
            self.assertTrue(case["structural_validation_passed"])
            self.assertIsNone(case["semantic_review"]["correctness"])
            self.assertFalse(case["semantic_review"]["independent_human_review"])
        self.assertEqual(before, self.index.read_bytes())
        self.assertEqual(self.heldout.read_text(), "Invalid JSON; held-out file must not be opened.")

    def test_prompt_only_inspects_real_evidence_without_client_calls(self):
        report = self.run_sample(inspect_only=True)
        self.client.complete.assert_not_called()
        self.assertTrue(all(case["outcome"] == "prompt_only" for case in report["cases"]))
        self.assertTrue(all(case["answer"] is None for case in report["cases"]))

    def test_failure_saved_separately_and_stops_remaining_requests(self):
        self.client.complete.side_effect = GenerationError("authentication", "Check environment key.")
        report = self.run_sample()
        self.assertEqual(self.client.complete.call_count, 1)
        first = report["cases"][0]
        self.assertEqual(first["outcome"], "error")
        self.assertEqual(first["error"]["kind"], "authentication")
        self.assertIsNone(first["structural_validation_passed"])
        self.assertIsNone(first["answer"])
        self.assertTrue(all(case["outcome"] == "not_attempted_after_error" for case in report["cases"][1:]))
        self.assertTrue(self.output.exists())

    def test_output_cannot_overwrite_labels_or_index(self):
        for output in (self.heldout, self.index, self.root / "data" / "raw" / "page.html"):
            with self.subTest(output=output), self.assertRaises(ValueError):
                run_answer_sample(self.index, root=self.root, config=GenerationConfig(), output=output,
                                  encoder=self.encoder, client=self.client)
        self.client.complete.assert_not_called()

    def test_index_change_preserves_previous_report(self):
        self.output.parent.mkdir(parents=True)
        self.output.write_text("previous report")
        value = self.client.complete.return_value
        def changed(*args):
            self.index.write_bytes(self.index.read_bytes() + b"change")
            return value
        self.client.complete.side_effect = changed
        with self.assertRaisesRegex(ValueError, "Index changed"):
            self.run_sample()
        self.assertEqual(self.output.read_text(), "previous report")


if __name__ == "__main__":
    unittest.main()
