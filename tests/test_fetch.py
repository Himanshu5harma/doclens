"""Offline checks for provenance, refreshes, and failed downloads."""

import hashlib
import io
import json
import unittest
from contextlib import redirect_stdout
from datetime import datetime
from email.message import Message
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch
from urllib.error import URLError

from doclens.__main__ import main
from doclens.fetch import fetch_source
from doclens.manifest import load_sources


class HTMLResponse(io.BytesIO):
    def __init__(self, content=b"<html><body>Path examples</body></html>", content_type="text/html"):
        super().__init__(content)
        self.headers = Message()
        self.headers["Content-Type"] = content_type
        self.status = 200

    def geturl(self):
        return "https://docs.example.test/3.12/pathlib.html"


class FetchTests(unittest.TestCase):
    def setUp(self):
        temporary = TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.source = {
            "source_id": "python-3.12-pathlib",
            "product": "python",
            "version": "3.12",
            "document_type": "reference",
            "url": "https://docs.example.test/3.12/pathlib.html",
            "local_path": "data/raw/python/3.12/pathlib.html",
            "source_terms_url": "https://docs.example.test/3.12/license.html",
        }
        self.destination = self.root / self.source["local_path"]
        self.metadata_path = self.destination.with_name(self.destination.name + ".metadata.json")

    def test_saved_bytes_match_provenance_and_preserve_source_metadata(self):
        content = b"<!doctype html><html>\r\n<pre>caf\xc3\xa9</pre></html>"
        with patch("doclens.fetch.urlopen", return_value=HTMLResponse(content)):
            result = fetch_source(self.source, root=self.root)

        saved = self.destination.read_bytes()
        metadata = json.loads(self.metadata_path.read_text())
        self.assertEqual(saved, content)
        self.assertEqual(metadata, result)
        self.assertEqual(metadata["sha256"], hashlib.sha256(saved).hexdigest())
        self.assertEqual(metadata["size_bytes"], len(saved))
        self.assertEqual(datetime.fromisoformat(metadata["fetched_at"]).utcoffset().total_seconds(), 0)
        for field, value in self.source.items():
            self.assertEqual(metadata[field], value)

    def test_refresh_replaces_existing_files_and_updates_hash(self):
        hashes = []
        for body in (b"<html>first</html>", b"<html>updated</html>"):
            with patch("doclens.fetch.urlopen", return_value=HTMLResponse(body)):
                hashes.append(fetch_source(self.source, root=self.root)["sha256"])
        self.assertNotEqual(*hashes)
        self.assertEqual(self.destination.read_bytes(), b"<html>updated</html>")
        self.assertEqual(len(list(self.destination.parent.iterdir())), 2)

    def test_network_failure_preserves_previous_download(self):
        with patch("doclens.fetch.urlopen", return_value=HTMLResponse()):
            fetch_source(self.source, root=self.root)
        before = (self.destination.read_bytes(), self.metadata_path.read_bytes())
        with patch("doclens.fetch.urlopen", side_effect=URLError("offline")):
            with self.assertRaises(URLError):
                fetch_source(self.source, root=self.root)
        self.assertEqual(before, (self.destination.read_bytes(), self.metadata_path.read_bytes()))

    def test_rejects_empty_or_non_html_responses_without_saving(self):
        for content, content_type in ((b"", "text/html"), (b'{"error": "no page"}', "application/json")):
            with self.subTest(content_type=content_type):
                with patch("doclens.fetch.urlopen", return_value=HTMLResponse(content, content_type)):
                    with self.assertRaises(ValueError):
                        fetch_source(self.source, root=self.root)
                self.assertFalse(self.destination.exists())
                self.assertFalse(self.metadata_path.exists())

    def test_manifest_rejects_ambiguous_or_invalid_records(self):
        manifest_path = self.root / "sources.json"
        cases = [
            [self.source, dict(self.source)],
            [{**self.source, "version": 3.12}],
            [{**self.source, "local_path": "data/raw/../../outside.html"}],
            [{**self.source, "url": "file:///etc/hosts"}],
        ]
        for sources in cases:
            with self.subTest(sources=sources):
                manifest_path.write_text(json.dumps({"sources": sources}))
                with self.assertRaises(ValueError):
                    load_sources(manifest_path)

    def test_cli_fetches_both_versions_to_distinct_paths(self):
        second = {
            **self.source,
            "source_id": "python-3.13-pathlib",
            "version": "3.13",
            "url": "https://docs.example.test/3.13/pathlib.html",
            "local_path": "data/raw/python/3.13/pathlib.html",
        }
        manifest_path = self.root / "sources.json"
        manifest_path.write_text(json.dumps({"sources": [self.source, second]}))
        output = io.StringIO()
        with patch("sys.argv", ["doclens", "fetch", "--manifest", str(manifest_path)]):
            with patch("doclens.__main__.Path.cwd", return_value=self.root):
                with patch("doclens.fetch.urlopen", side_effect=[HTMLResponse(), HTMLResponse()]):
                    with redirect_stdout(output):
                        main()
        for source in (self.source, second):
            path = self.root / source["local_path"]
            metadata = json.loads(path.with_name(path.name + ".metadata.json").read_text())
            self.assertEqual(metadata["version"], source["version"])
            self.assertIn(source["source_id"], output.getvalue())


if __name__ == "__main__":
    unittest.main()
