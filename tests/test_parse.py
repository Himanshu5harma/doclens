"""Checks for evidence structure, provenance, and offline parsing."""

import hashlib
import io
import json
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from doclens.__main__ import main
from doclens.parse import parse_html, parse_source


HTML = b'''<!doctype html><html><head>
<link rel="canonical" href="https://docs.example.test/3/paths.html">
</head><body><nav><p>GLOBAL NAVIGATION</p></nav>
<div class="body" role="main"><section id="module-paths">
<h1>Paths<a class="headerlink" href="#module-paths">&#182;</a></h1>
<p>Intro with <code>Path</code> and punctuation.</p>
<aside><p>SIDEBAR NOISE</p></aside><script>hidden()</script>
<section id="file-uris"><h2>File URIs</h2>
<dl><dt id="pathlib.Path.from_uri"><span>Path.</span><span>from_uri</span>(uri)
<a class="headerlink" href="#pathlib.Path.from_uri">&#182;</a></dt>
<dd><p>Parse a <code>file:</code> URI.</p>
<pre><span>&gt;&gt;&gt; </span>if True:
    print("hello")
</pre><div class="versionadded"><p>Added in version 3.13.</p></div>
</dd></dl>
<ul><li>A bare <code>list</code> item.</li><li><p>A paragraph item.</p></li></ul>
<table><tr><th><p>API</p></th><th>Use</th></tr>
<tr><td><p>from_uri()</p></td><td>Parse URI</td></tr></table>
</section><p>Back in the parent section.</p>
</section><footer><p>FOOTER NOISE</p></footer></div></body></html>'''


class ParseTests(unittest.TestCase):
    def setUp(self):
        temporary = TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.source = {
            "source_id": "python-3.13-paths",
            "product": "python",
            "version": "3.13",
            "document_type": "reference",
            "url": "https://docs.example.test/3.13/paths.html",
            "local_path": "data/raw/python/3.13/paths.html",
            "source_terms_url": "https://docs.example.test/3.13/license.html",
        }
        self.parsed_path = self.root / "data/parsed/python/3.13/paths.html.json"

    def save_download(self, source=None):
        source = self.source if source is None else source
        raw_path = self.root / source["local_path"]
        raw_path.parent.mkdir(parents=True, exist_ok=True)
        raw_path.write_bytes(HTML)
        metadata = {
            **source,
            "sha256": hashlib.sha256(HTML).hexdigest(),
            "size_bytes": len(HTML),
            "fetched_at": "2026-10-24T09:00:00+00:00",
        }
        metadata_path = raw_path.with_name(raw_path.name + ".metadata.json")
        metadata_path.write_text(json.dumps(metadata), encoding="utf-8")
        return raw_path, metadata_path

    def test_preserves_heading_context_and_removes_navigation(self):
        document = parse_html(HTML, source_url=self.source["url"])
        parent, child = document["sections"]
        self.assertEqual(document["title"], "Paths")
        self.assertEqual(child["heading_path"], ["Paths", "File URIs"])
        self.assertEqual(parent["blocks"][-1]["text"], "Back in the parent section.")
        output = json.dumps(document)
        for noise in ("GLOBAL NAVIGATION", "SIDEBAR NOISE", "FOOTER NOISE", "hidden()", "\\u00b6"):
            self.assertNotIn(noise, output)

    def test_preserves_api_anchor_code_indentation_and_version_note(self):
        document = parse_html(HTML, source_url=self.source["url"])
        blocks = document["sections"][1]["blocks"]
        signature, description, code, version_note = blocks[:4]
        self.assertEqual(signature["text"], "Path.from_uri(uri)")
        self.assertEqual(description["text"], "Parse a file: URI.")
        self.assertEqual(code["text"], '>>> if True:\n    print("hello")\n')
        self.assertEqual(version_note["text"], "Added in version 3.13.")
        for block in blocks[:4]:
            self.assertEqual(block["anchor"], "pathlib.Path.from_uri")
            self.assertEqual(block["url"], self.source["url"] + "#pathlib.Path.from_uri")
        self.assertNotIn("https://docs.example.test/3/paths.html", json.dumps(document))

    def test_keeps_list_and_table_content_without_duplicate_paragraphs(self):
        document = parse_html(HTML, source_url=self.source["url"])
        blocks = document["sections"][1]["blocks"]
        self.assertIn({"kind": "list_item", "text": "A bare list item.", "anchor": "file-uris", "url": self.source["url"] + "#file-uris"}, blocks)
        rows = [block["text"] for block in blocks if block["kind"] == "table_row"]
        self.assertEqual(rows, ["API | Use", "from_uri() | Parse URI"])
        self.assertFalse(any(block["text"] == "from_uri()" for block in blocks))

    def test_rejects_unsupported_or_empty_articles(self):
        for content in (b"<html><p>No main region</p></html>", b"<main><h1>Empty</h1></main>"):
            with self.subTest(content=content), self.assertRaises(ValueError):
                parse_html(content, source_url=self.source["url"])

    def test_repeated_parse_is_identical_and_preserves_source_provenance(self):
        self.save_download()
        document = parse_source(self.source, root=self.root)
        original_output = self.parsed_path.read_bytes()
        second = parse_source(self.source, root=self.root)
        self.assertEqual(document, second)
        self.assertEqual(self.parsed_path.read_bytes(), original_output)
        self.assertEqual(document["source"]["version"], "3.13")
        self.assertEqual(document["source"]["sha256"], hashlib.sha256(HTML).hexdigest())
        self.assertEqual(json.loads(original_output), document)

    def test_rejects_modified_raw_content_without_overwriting_parsed_output(self):
        raw_path, _ = self.save_download()
        parse_source(self.source, root=self.root)
        original_output = self.parsed_path.read_bytes()
        raw_path.write_bytes(HTML + b"<!-- changed -->")
        with self.assertRaisesRegex(ValueError, "does not match metadata"):
            parse_source(self.source, root=self.root)
        self.assertEqual(self.parsed_path.read_bytes(), original_output)

    def test_rejects_manifest_and_download_version_mismatch(self):
        _, metadata_path = self.save_download()
        metadata = json.loads(metadata_path.read_text())
        metadata["version"] = "3.12"
        metadata_path.write_text(json.dumps(metadata))
        with self.assertRaisesRegex(ValueError, "differs from the manifest"):
            parse_source(self.source, root=self.root)
        self.assertFalse(self.parsed_path.exists())

    def test_cli_parses_both_sources_without_network_requests(self):
        second = {
            **self.source,
            "source_id": "python-3.12-paths",
            "version": "3.12",
            "url": "https://docs.example.test/3.12/paths.html",
            "local_path": "data/raw/python/3.12/paths.html",
        }
        for source in (self.source, second):
            self.save_download(source)
        manifest_path = self.root / "sources.json"
        manifest_path.write_text(json.dumps({"sources": [self.source, second]}))
        output = io.StringIO()
        with patch("sys.argv", ["doclens", "parse", "--manifest", str(manifest_path)]):
            with patch("doclens.__main__.Path.cwd", return_value=self.root):
                with patch("doclens.fetch.urlopen", side_effect=AssertionError("Parsing must stay offline")):
                    with redirect_stdout(output):
                        main()
        self.assertIn("Parsed 2 sources", output.getvalue())
        self.assertEqual(len(list((self.root / "data/parsed").rglob("*.json"))), 2)


if __name__ == "__main__":
    unittest.main()
