"""Boundary, provenance, identity, and file checks for baseline chunking."""

import copy
import hashlib
import io
import json
import unittest
from contextlib import redirect_stderr, redirect_stdout
from dataclasses import asdict
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from doclens.__main__ import main
from doclens.chunk import ChunkPolicy, chunk_document, chunk_source
from doclens.parse import parse_source
from doclens.records import BlockKind, document_from_dict


CONTEXT = "Guide > Details\napi.run\n\n"


def parsed_fixture(blocks, *, version="3.13"):
    page_url = f"https://docs.example.test/{version}/guide.html"
    records = []
    for kind, text, anchor in blocks:
        records.append({
            "kind": kind, "text": text, "anchor": anchor,
            "url": page_url + (f"#{anchor}" if anchor else ""),
        })
    return {
        "schema_version": 1, "title": "Guide",
        "source": {
            "source_id": f"python-{version}-guide", "product": "python",
            "version": version, "document_type": "reference", "url": page_url,
            "sha256": "a" * 64, "fetched_at": "2026-10-25T00:00:00+00:00",
            "source_terms_url": f"https://docs.example.test/{version}/license.html",
        },
        "sections": [{
            "heading": "Details", "level": 2, "heading_path": ["Guide", "Details"],
            "anchor": "details", "url": page_url + "#details", "blocks": records,
        }],
    }


class ChunkTests(unittest.TestCase):
    def document(self, *texts):
        return document_from_dict(parsed_fixture([("paragraph", text, "api.run") for text in texts]))

    def test_exact_boundary_counts_context_and_separators(self):
        document = self.document("abcd", "efgh")
        policy = ChunkPolicy(len(CONTEXT) + 4 + 2 + 4)
        chunks = chunk_document(document, policy)
        self.assertEqual(len(chunks), 1)
        self.assertEqual(chunks[0].text, CONTEXT + "abcd\n\nefgh")
        self.assertEqual(len(chunks[0].text), policy.max_chars)
        self.assertFalse(chunks[0].oversized)
        self.assertEqual(len(chunk_document(document, ChunkPolicy(policy.max_chars - 1))), 2)

    def test_oversized_prose_splits_at_whitespace_and_reconstructs_exactly(self):
        text = "alpha beta gamma delta " * 8 + "last"
        document = self.document(text)
        policy = ChunkPolicy(len(CONTEXT) + 12)
        chunks = chunk_document(document, policy)
        pieces = [piece for chunk in chunks for piece in chunk.pieces]
        self.assertGreater(len(chunks), 1)
        self.assertEqual(pieces[0].text, "alpha beta ")
        self.assertEqual("".join(piece.text for piece in pieces), text)
        self.assertEqual(pieces[0].start_char, 0)
        self.assertEqual(pieces[-1].end_char, len(text))
        for previous, following in zip(pieces, pieces[1:]):
            self.assertEqual(previous.end_char, following.start_char)
        for chunk in chunks:
            self.assertLessEqual(len(chunk.text), policy.max_chars)
            self.assertFalse(chunk.oversized)
            for piece in chunk.pieces:
                self.assertEqual(piece.text, text[piece.start_char:piece.end_char])

    def test_long_unbroken_unicode_text_uses_character_fallback(self):
        text = "界" * 35
        chunks = chunk_document(self.document(text), ChunkPolicy(len(CONTEXT) + 8))
        self.assertEqual([len(chunk.pieces[0].text) for chunk in chunks], [8, 8, 8, 8, 3])
        self.assertEqual("".join(chunk.pieces[0].text for chunk in chunks), text)

    def test_oversized_code_signature_and_table_rows_are_whole_and_alone(self):
        policy = ChunkPolicy(len(CONTEXT) + 20)
        for kind in ("code", "signature", "table_row"):
            with self.subTest(kind=kind):
                large = "    print('kept whole')\n" * 4
                document = document_from_dict(parsed_fixture([
                    ("paragraph", "intro", "api.run"), (kind, large, "api.run"),
                    ("paragraph", "after", "api.run"),
                ]))
                chunks = chunk_document(document, policy)
                self.assertEqual(len(chunks), 3)
                self.assertEqual([chunk.oversized for chunk in chunks], [False, True, False])
                self.assertEqual(len(chunks[1].pieces), 1)
                self.assertEqual(chunks[1].pieces[0].text, large)
                self.assertEqual(chunks[1].pieces[0].end_char, len(large))

    def test_code_at_the_limit_is_not_oversized(self):
        code = "    print('hello')\n"
        document = document_from_dict(parsed_fixture([("code", code, "api.run")]))
        chunks = chunk_document(document, ChunkPolicy(len(CONTEXT) + len(code)))
        self.assertFalse(chunks[0].oversized)
        self.assertEqual(chunks[0].text, CONTEXT + code)

    def test_chunks_do_not_cross_api_anchors_or_sections(self):
        data = parsed_fixture([("paragraph", "one", "api.one"), ("paragraph", "two", "api.two")])
        second = copy.deepcopy(data["sections"][0])
        second.update(heading="Other", heading_path=["Guide", "Other"], anchor="other")
        second["url"] = data["source"]["url"] + "#other"
        second["blocks"] = second["blocks"][:1]
        data["sections"].append(second)
        chunks = chunk_document(document_from_dict(data))
        self.assertEqual([(chunk.section_index, chunk.anchor) for chunk in chunks], [(0, "api.one"), (0, "api.two"), (1, "api.one")])

    def test_metadata_hashes_and_original_code_structure_are_preserved(self):
        code = "if True:\n\tprint('hello')\n"
        document = document_from_dict(parsed_fixture([("code", code, "api.run")]))
        chunk = chunk_document(document)[0]
        self.assertEqual(chunk.source, document.source)
        self.assertEqual(chunk.document_content_hash, document.content_hash)
        self.assertEqual(chunk.document_title, "Guide")
        self.assertEqual(chunk.heading_path, ("Guide", "Details"))
        self.assertEqual(chunk.section_anchor, "details")
        self.assertEqual(chunk.url, document.source.url + "#api.run")
        self.assertEqual(chunk.content_hash, hashlib.sha256(chunk.text.encode()).hexdigest())
        self.assertEqual(chunk.pieces[0].kind, BlockKind.CODE)
        self.assertEqual((chunk.pieces[0].block_index, chunk.pieces[0].start_char, chunk.pieces[0].end_char), (0, 0, len(code)))
        self.assertEqual(chunk.pieces[0].text, code)
        self.assertEqual(json.loads(json.dumps(asdict(chunk)))["source"]["version"], "3.13")

    def test_missing_block_anchor_uses_section_for_chunk_citation(self):
        document = document_from_dict(parsed_fixture([("paragraph", "intro", None)]))
        chunk = chunk_document(document)[0]
        self.assertEqual(chunk.anchor, "details")
        self.assertEqual(chunk.url, document.source.url + "#details")
        self.assertIsNone(chunk.pieces[0].anchor)

    def test_identical_repeated_passages_have_unique_repeatable_ids(self):
        document = self.document("same", "same")
        policy = ChunkPolicy(len(CONTEXT) + 4)
        first, second = chunk_document(document, policy), chunk_document(document, policy)
        self.assertEqual(first, second)
        self.assertEqual(len(first), 2)
        self.assertNotEqual(first[0].chunk_id, first[1].chunk_id)

    def test_raw_hash_and_fetch_time_changes_do_not_churn_content_ids(self):
        data = parsed_fixture([("paragraph", "same evidence", "api.run")])
        before = chunk_document(document_from_dict(data))[0]
        data["source"].update(sha256="b" * 64, fetched_at="2026-10-26T00:00:00+00:00")
        after = chunk_document(document_from_dict(data))[0]
        self.assertEqual(before.chunk_id, after.chunk_id)
        self.assertEqual(before.document_content_hash, after.document_content_hash)
        self.assertNotEqual(before.source.content_hash, after.source.content_hash)

    def test_changed_chunk_gets_new_id_while_unaffected_passage_keeps_id(self):
        data = parsed_fixture([("paragraph", "original", "api.one"), ("paragraph", "unchanged", "api.two")])
        before = chunk_document(document_from_dict(data))
        data["sections"][0]["blocks"][0]["text"] = "updated"
        after = chunk_document(document_from_dict(data))
        self.assertNotEqual(before[0].chunk_id, after[0].chunk_id)
        self.assertEqual(before[1].chunk_id, after[1].chunk_id)
        self.assertNotEqual(before[1].document_content_hash, after[1].document_content_hash)

    def test_earlier_insertion_does_not_change_unaffected_ids(self):
        data = parsed_fixture([("paragraph", "kept", "api.one")])
        before = chunk_document(document_from_dict(data))[0]
        inserted = copy.deepcopy(data["sections"][0]["blocks"][0])
        inserted.update(text="new", anchor="api.zero", url=data["source"]["url"] + "#api.zero")
        data["sections"][0]["blocks"].insert(0, inserted)
        after = chunk_document(document_from_dict(data))[1]
        self.assertEqual(before.chunk_id, after.chunk_id)
        self.assertNotEqual(before.pieces[0].block_index, after.pieces[0].block_index)

    def test_policy_and_version_are_part_of_identity(self):
        data = parsed_fixture([("paragraph", "same evidence", "api.run")])
        document = document_from_dict(data)
        other_version = document_from_dict(parsed_fixture([("paragraph", "same evidence", "api.run")], version="3.12"))
        baseline = chunk_document(document)[0]
        self.assertNotEqual(baseline.chunk_id, chunk_document(document, ChunkPolicy(2500))[0].chunk_id)
        self.assertNotEqual(baseline.chunk_id, chunk_document(other_version)[0].chunk_id)

    def test_invalid_targets_and_insufficient_context_budget_fail_clearly(self):
        for size in (0, -1, True, "2000"):
            with self.subTest(size=size), self.assertRaises(ValueError):
                ChunkPolicy(size)
        with self.assertRaisesRegex(ValueError, "heading/anchor context"):
            chunk_document(self.document("text"), ChunkPolicy(len(CONTEXT)))

    def test_json_boundary_rejects_invalid_records(self):
        baseline = parsed_fixture([("paragraph", "text", "api.run")])
        invalid = []
        data = copy.deepcopy(baseline)
        data["source"]["version"] = 3.13
        invalid.append(data)
        data = copy.deepcopy(baseline)
        data["sections"][0]["blocks"][0]["url"] = "https://docs.example.test/3.12/guide.html#api.run"
        invalid.append(data)
        data = copy.deepcopy(baseline)
        data["sections"][0]["blocks"][0]["kind"] = "unknown"
        invalid.append(data)
        data = copy.deepcopy(baseline)
        data["schema_version"] = 2
        invalid.append(data)
        for data in invalid:
            with self.subTest(data=data), self.assertRaises(ValueError):
                document_from_dict(data)


class ChunkFileTests(unittest.TestCase):
    def setUp(self):
        temporary = TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.source = {
            "source_id": "python-3.13-guide", "product": "python", "version": "3.13",
            "document_type": "reference", "url": "https://docs.example.test/3.13/guide.html",
            "local_path": "data/raw/python/3.13/guide.html",
            "source_terms_url": "https://docs.example.test/3.13/license.html",
        }
        self.manifest = self.root / "sources.json"
        self.manifest.write_text(json.dumps({"sources": [self.source]}))

    def save_snapshot(self, text="original", *, parse=True):
        raw = f'<main><section id="guide"><h1>Guide</h1><p>{text}</p></section></main>'.encode()
        path = self.root / self.source["local_path"]
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(raw)
        metadata = {
            **self.source, "sha256": hashlib.sha256(raw).hexdigest(),
            "size_bytes": len(raw), "fetched_at": "2026-10-26T00:00:00+00:00",
        }
        path.with_name(path.name + ".metadata.json").write_text(json.dumps(metadata))
        if parse:
            parse_source(self.source, root=self.root)

    def test_repeat_file_output_is_identical_and_policy_outputs_coexist(self):
        self.save_snapshot()
        path, _ = chunk_source(self.source, root=self.root)
        before = path.read_bytes()
        repeated, _ = chunk_source(self.source, root=self.root)
        alternate, _ = chunk_source(self.source, root=self.root, policy=ChunkPolicy(2500))
        self.assertEqual(repeated, path)
        self.assertEqual(path.read_bytes(), before)
        self.assertNotEqual(path, alternate)
        self.assertTrue(alternate.exists())

    def test_changed_source_replaces_chunk_set_and_stale_parsing_is_rejected(self):
        self.save_snapshot()
        path, old_chunks = chunk_source(self.source, root=self.root)
        before = path.read_bytes()
        self.save_snapshot("updated", parse=False)
        with self.assertRaisesRegex(ValueError, "stale or mismatched"):
            chunk_source(self.source, root=self.root)
        self.assertEqual(path.read_bytes(), before)
        parse_source(self.source, root=self.root)
        _, new_chunks = chunk_source(self.source, root=self.root)
        self.assertNotEqual(old_chunks[0].chunk_id, new_chunks[0].chunk_id)
        self.assertNotIn(old_chunks[0].chunk_id, path.read_text())
        self.assertEqual(len(json.loads(path.read_text())["chunks"]), len(new_chunks))

    def test_raw_hash_mismatch_preserves_previous_chunk_file(self):
        self.save_snapshot()
        path, _ = chunk_source(self.source, root=self.root)
        before = path.read_bytes()
        raw_path = self.root / self.source["local_path"]
        raw_path.write_bytes(raw_path.read_bytes() + b"<!-- changed -->")
        with self.assertRaisesRegex(ValueError, "raw content does not match"):
            chunk_source(self.source, root=self.root)
        self.assertEqual(path.read_bytes(), before)

    def test_cli_chunks_offline_and_reports_unknown_source_ids(self):
        self.save_snapshot()
        output = io.StringIO()
        args = ["doclens", "chunk", "--manifest", str(self.manifest), "--source-id", self.source["source_id"]]
        with patch("sys.argv", args), patch("doclens.__main__.Path.cwd", return_value=self.root):
            with patch("doclens.fetch.urlopen", side_effect=AssertionError("Chunking must stay offline")):
                with redirect_stdout(output):
                    main()
        self.assertIn("Wrote 1 chunks from 1 sources", output.getvalue())
        self.assertEqual(len(list((self.root / "data/chunks").rglob("*.json"))), 1)
        errors = io.StringIO()
        with patch("sys.argv", [*args[:-1], "missing"]):
            with redirect_stderr(errors), self.assertRaises(SystemExit) as failure:
                main()
        self.assertEqual(failure.exception.code, 1)
        self.assertIn("Unknown source ID", errors.getvalue())


if __name__ == "__main__":
    unittest.main()
