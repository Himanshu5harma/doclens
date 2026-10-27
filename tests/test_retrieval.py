"""Offline contract tests; fake vectors test ranking, not model quality."""

import hashlib
import io
import json
import sqlite3
import unittest
from contextlib import redirect_stderr, redirect_stdout
from dataclasses import asdict, replace
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest.mock import patch

from doclens.__main__ import main
from doclens.chunk import ChunkPolicy, chunk_document
from doclens.embeddings import EmbeddingConfig, LocalEncoder, unit_vector
from doclens.parse import parse_html
from doclens.records import document_from_dict
from doclens.retrieval import build_index, search_index


CONFIG = EmbeddingConfig("test/encoder", "a" * 40, 3, 100, "search_document: ", "search_query: ")


def make_chunk(name, version="3.13"):
    page = f"https://docs.example.test/{version}/{name}.html"
    raw = f'<main><section id="guide"><h1>Guide</h1><p>{name}</p></section></main>'.encode()
    document = parse_html(raw, source_url=page)
    document["source"] = {
        "source_id": f"python-{version}-{name}", "product": "python", "version": version,
        "document_type": "reference", "url": page, "sha256": hashlib.sha256(raw).hexdigest(),
        "fetched_at": "2026-10-27T00:00:00+00:00", "source_terms_url": page,
    }
    return chunk_document(document_from_dict(document))[0]


class FakeEncoder:
    config = CONFIG
    runtime = {"backend": "test-double"}

    def __init__(self):
        self.calls = []

    def token_counts(self, texts, *, query=False):
        return [len(text.split()) for text in texts]

    def encode(self, texts, *, query=False):
        self.calls.append((texts, query))
        if query:
            return [(1, 0, 0)]
        return [(0.8, 0.6, 0) if "RIGHT" in text else (0, 1, 0) if "OTHER" in text else (1, 0, 0) for text in texts]


class RetrievalTests(unittest.TestCase):
    def setUp(self):
        temporary = TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.path = self.root / "index.sqlite3"
        self.chunks = [make_chunk("WRONG", "3.12"), make_chunk("RIGHT"), make_chunk("OTHER")]
        self.encoder = FakeEncoder()
        self.build()

    def build(self, chunks=None, encoder=None):
        return build_index(
            self.chunks if chunks is None else chunks, path=self.path,
            encoder=self.encoder if encoder is None else encoder,
            manifest_hash="f" * 64, policy=ChunkPolicy(),
        )

    def search(self, **kwargs):
        return search_index(self.path, "question", version="3.13", root=self.root, encoder=self.encoder, **kwargs)

    def test_version_filter_precedes_scoring_and_top_k(self):
        # The wrong version has the closest vector. Its invalid bytes would
        # also fail decoding if it entered the pool being scored.
        with sqlite3.connect(self.path) as connection:
            connection.execute("UPDATE chunks SET embedding = ? WHERE version = '3.12'", (b"invalid",))
        response = self.search(top_k=1)
        self.assertEqual(response.candidate_count, 2)
        self.assertEqual(len(response.results), 1)
        result = response.results[0]
        self.assertEqual(result.source.version, "3.13")
        self.assertEqual(result.chunk_id, self.chunks[1].chunk_id)
        self.assertAlmostEqual(result.score, 0.8, places=6)
        self.assertEqual(result.rank, 1)
        self.assertEqual(result.url, self.chunks[1].url)
        self.assertEqual(result.source.content_hash, self.chunks[1].source.content_hash)

    def test_search_is_read_only_and_preserves_index_bytes(self):
        before = self.path.read_bytes()
        self.search()
        self.assertEqual(before, self.path.read_bytes())

    def test_unknown_version_fails_before_query_encoding(self):
        before = len(self.encoder.calls)
        with self.assertRaisesRegex(ValueError, "No indexed chunks"):
            search_index(self.path, "question", version="9.99", root=self.root, encoder=self.encoder)
        self.assertEqual(before, len(self.encoder.calls))

    def test_query_encoder_must_match_recorded_configuration(self):
        self.encoder.config = replace(CONFIG, revision="b" * 40)
        with self.assertRaisesRegex(ValueError, "does not match"):
            self.search()

    def test_full_rebuild_deduplicates_and_removes_old_sources(self):
        first = self.build()
        second = self.build()
        self.assertEqual(first["chunk_set_hash"], second["chunk_set_hash"])
        with sqlite3.connect(self.path) as connection:
            self.assertEqual(connection.execute("SELECT count(*) FROM chunks").fetchone()[0], 3)
        self.build([self.chunks[1]])
        with sqlite3.connect(self.path) as connection:
            ids = [row[0] for row in connection.execute("SELECT chunk_id FROM chunks")]
        self.assertEqual(ids, [self.chunks[1].chunk_id])

    def test_same_ids_receive_updated_provenance_on_rebuild(self):
        changed = replace(self.chunks[1], source=replace(self.chunks[1].source, content_hash="b" * 64))
        self.build([changed])
        result = self.search().results[0]
        self.assertEqual(result.chunk_id, self.chunks[1].chunk_id)
        self.assertEqual(result.source.content_hash, "b" * 64)

    def test_token_overflow_fails_before_encoding_or_replacing_index(self):
        before = self.path.read_bytes()
        fake = FakeEncoder()
        fake.token_counts = lambda texts: [CONFIG.max_tokens + 1] * len(texts)
        with self.assertRaisesRegex(ValueError, "No text was truncated"):
            self.build(encoder=fake)
        self.assertFalse(fake.calls)
        self.assertEqual(self.path.read_bytes(), before)

    def test_invalid_vectors_preserve_previous_index(self):
        before = self.path.read_bytes()
        for vector in ((0, 0, 0), (1, 0), (float("nan"), 0, 1), (float("inf"), 0, 1)):
            with self.subTest(vector=vector):
                fake = FakeEncoder()
                fake.encode = lambda texts, vector=vector: [vector] * len(texts)
                with self.assertRaises(ValueError):
                    self.build(encoder=fake)
                self.assertEqual(self.path.read_bytes(), before)

    def test_failed_sqlite_build_preserves_previous_index(self):
        before = self.path.read_bytes()
        with patch("doclens.retrieval.sqlite3.connect", side_effect=sqlite3.OperationalError("simulated failure")):
            with self.assertRaises(sqlite3.Error):
                self.build()
        self.assertEqual(self.path.read_bytes(), before)
        self.assertEqual(list(self.root.iterdir()), [self.path])

    def test_ties_are_deterministic(self):
        chunks = [make_chunk("TIE_A"), make_chunk("TIE_B")]
        self.build(chunks)
        response = self.search()
        self.assertEqual([result.chunk_id for result in response.results], sorted(chunk.chunk_id for chunk in chunks))

    def test_invalid_queries_top_k_and_corrupt_vectors_fail_clearly(self):
        with self.assertRaises(ValueError):
            search_index(self.path, " ", version="3.13", root=self.root, encoder=self.encoder)
        with self.assertRaises(ValueError):
            self.search(top_k=0)
        with sqlite3.connect(self.path) as connection:
            connection.execute("UPDATE chunks SET embedding = ? WHERE version = '3.13'", (b"bad",))
        with self.assertRaisesRegex(ValueError, "Invalid stored vector size"):
            self.search()

    def test_cli_search_returns_inspectable_json(self):
        output = io.StringIO()
        args = ["doclens", "search", "question", "--version", "3.13", "--index", str(self.path), "--json"]
        with patch("sys.argv", args), patch("doclens.retrieval.LocalEncoder", return_value=self.encoder):
            with redirect_stdout(output):
                main()
        data = json.loads(output.getvalue())
        self.assertEqual(data["candidate_count"], 2)
        self.assertEqual(data["results"][0]["source"]["version"], "3.13")
        self.assertIn("text", data["results"][0])

    def test_cli_index_records_a_consistent_manifest_snapshot(self):
        manifest = self.root / "sources.json"
        original = '{"sources": []}'
        manifest.write_text(original)
        config = self.root / "config.json"
        config.write_text(json.dumps(asdict(CONFIG)))
        args = ["doclens", "index", "--manifest", str(manifest), "--config", str(config), "--index", str(self.path)]
        with patch("sys.argv", args), patch("doclens.__main__.collect_chunks", return_value=self.chunks):
            with patch("doclens.__main__.LocalEncoder", return_value=self.encoder), redirect_stdout(io.StringIO()):
                main()
        with sqlite3.connect(self.path) as connection:
            digest = json.loads(connection.execute("SELECT value FROM metadata WHERE key='manifest_sha256'").fetchone()[0])
        self.assertEqual(digest, hashlib.sha256(original.encode()).hexdigest())
        before = self.path.read_bytes()

        def change_manifest(*args):
            manifest.write_text("changed during collection")
            return self.chunks

        with patch("sys.argv", args), patch("doclens.__main__.collect_chunks", side_effect=change_manifest):
            with redirect_stderr(io.StringIO()), self.assertRaises(SystemExit) as failure:
                main()
        self.assertEqual(failure.exception.code, 1)
        self.assertEqual(self.path.read_bytes(), before)


class LocalEncoderContractTests(unittest.TestCase):
    def encoder(self, max_tokens=100):
        tokenizer = SimpleNamespace(encode=lambda text, **kwargs: text.split())
        calls = []

        def encode(texts, **kwargs):
            calls.append(texts)
            return [(3, 4, 0) for _ in texts]

        instance = object.__new__(LocalEncoder)
        instance.config = replace(CONFIG, max_tokens=max_tokens)
        instance.model = SimpleNamespace(tokenizer=tokenizer, encode=encode)
        return instance, calls

    def test_required_prefixes_and_normalization(self):
        encoder, calls = self.encoder()
        documents = encoder.encode(["document"])
        encoder.encode(["question"], query=True)
        self.assertEqual(calls, [["search_document: document"], ["search_query: question"]])
        self.assertEqual(documents, [(0.6, 0.8, 0)])

    def test_prefix_tokens_count_toward_limit_and_no_truncation_occurs(self):
        encoder, calls = self.encoder(max_tokens=3)
        self.assertEqual(encoder.token_counts(["two words"]), [3])
        encoder.encode(["two words"])
        with self.assertRaisesRegex(ValueError, "refusing to truncate"):
            encoder.encode(["three separate words"], query=True)
        self.assertEqual(len(calls), 1)

    def test_model_revision_is_immutable_and_bad_configuration_is_rejected(self):
        with self.assertRaises(ValueError):
            replace(CONFIG, revision="main")
        with self.assertRaises(ValueError):
            replace(CONFIG, dimensions=0)
        self.assertEqual(unit_vector((3, 4, 0), 3), (0.6, 0.8, 0))


if __name__ == "__main__":
    unittest.main()
