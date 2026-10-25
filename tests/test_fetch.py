"""Offline checks for provenance, refreshes, and failed downloads."""

import hashlib
import io
import json
import unittest
from contextlib import redirect_stderr, redirect_stdout
from datetime import datetime
from email.message import Message
from http.client import BadStatusLine, IncompleteRead
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch
from urllib.error import URLError

from doclens.__main__ import main
from doclens.fetch import fetch_source
from doclens.files import write_atomic
from doclens.manifest import load_sources
from doclens.parse import parse_source


class HTMLResponse(io.BytesIO):
    def __init__(
        self, content=b"<html><body>Path examples</body></html>", content_type="text/html",
        *, url="https://docs.example.test/3.12/pathlib.html",
    ):
        super().__init__(content)
        self.url = url
        self.headers = Message()
        self.headers["Content-Type"] = content_type
        self.status = 200

    def geturl(self):
        return self.url


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

    def source_for_version(self, version):
        return {
            **self.source,
            "source_id": f"python-{version}-pathlib",
            "version": version,
            "url": f"https://docs.example.test/{version}/pathlib.html",
            "local_path": f"data/raw/python/{version}/pathlib.html",
            "source_terms_url": f"https://docs.example.test/{version}/license.html",
        }

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
        second = self.source_for_version("3.13")
        manifest_path = self.root / "sources.json"
        manifest_path.write_text(json.dumps({"sources": [self.source, second]}))
        output = io.StringIO()
        with patch("sys.argv", ["doclens", "fetch", "--manifest", str(manifest_path)]):
            with patch("doclens.__main__.Path.cwd", return_value=self.root):
                with patch("doclens.fetch.urlopen", side_effect=[HTMLResponse(), HTMLResponse(url=second["url"])]):
                    with redirect_stdout(output):
                        main()
        for source in (self.source, second):
            path = self.root / source["local_path"]
            metadata = json.loads(path.with_name(path.name + ".metadata.json").read_text())
            self.assertEqual(metadata["version"], source["version"])
            self.assertEqual(metadata["final_url"], source["url"])
            self.assertIn(source["source_id"], output.getvalue())

    def test_rejects_wrong_version_or_host_redirects_without_overwriting_downloads(self):
        source = self.source_for_version("3.13")
        with patch("doclens.fetch.urlopen", return_value=HTMLResponse(url=source["url"])):
            fetch_source(source, root=self.root)
        path = self.root / source["local_path"]
        metadata_path = path.with_name(path.name + ".metadata.json")
        before = (path.read_bytes(), metadata_path.read_bytes())
        for url in (
            "https://docs.example.test/3.12/pathlib.html",
            "https://docs.example.test/3/pathlib.html",
            "https://other.example.test/3.13/pathlib.html",
            "http://docs.example.test/3.13/pathlib.html",
            "https://docs.example.test:444/3.13/pathlib.html",
            "https://docs.example.test/3.130/pathlib.html",
        ):
            with self.subTest(url=url):
                response = HTMLResponse(b"<html>wrong release</html>", url=url)
                with patch("doclens.fetch.urlopen", return_value=response):
                    with self.assertRaisesRegex(ValueError, source["source_id"]):
                        fetch_source(source, root=self.root)
                self.assertEqual(before, (path.read_bytes(), metadata_path.read_bytes()))

    def test_allows_a_same_host_same_version_redirect(self):
        source = self.source_for_version("3.13")
        final_url = "https://docs.example.test/3.13/library/pathlib.html"
        with patch("doclens.fetch.urlopen", return_value=HTMLResponse(url=final_url)):
            metadata = fetch_source(source, root=self.root)
        self.assertEqual(metadata["final_url"], final_url)
        self.assertEqual(metadata["url"], source["url"])
        self.assertEqual(metadata["version"], "3.13")

    def test_cli_reports_http_read_failures_and_preserves_previous_downloads(self):
        with patch("doclens.fetch.urlopen", return_value=HTMLResponse()):
            fetch_source(self.source, root=self.root)
        before = (self.destination.read_bytes(), self.metadata_path.read_bytes())
        manifest_path = self.root / "sources.json"
        manifest_path.write_text(json.dumps({"sources": [self.source]}))
        for error in (IncompleteRead(b"partial", 20), BadStatusLine("invalid response")):
            with self.subTest(error=type(error).__name__):
                response = HTMLResponse()
                stderr = io.StringIO()
                with patch("sys.argv", ["doclens", "fetch", "--manifest", str(manifest_path)]):
                    with patch("doclens.__main__.Path.cwd", return_value=self.root):
                        with patch("doclens.fetch.urlopen", return_value=response):
                            with patch.object(response, "read", side_effect=error):
                                with redirect_stderr(stderr), self.assertRaises(SystemExit) as exit:
                                    main()
                self.assertEqual(exit.exception.code, 1)
                self.assertIn("HTTP response failed", stderr.getvalue())
                self.assertIn(self.source["source_id"], stderr.getvalue())
                self.assertNotIn("Traceback", stderr.getvalue())
                self.assertEqual(before, (self.destination.read_bytes(), self.metadata_path.read_bytes()))

    def test_parser_rejects_a_refresh_interrupted_between_html_and_metadata_writes(self):
        original = b"<main><h1>Paths</h1><p>Original documentation.</p></main>"
        with patch("doclens.fetch.urlopen", return_value=HTMLResponse(original)):
            fetch_source(self.source, root=self.root)
        parse_source(self.source, root=self.root)
        parsed_path = self.root / "data/parsed/python/3.12/pathlib.html.json"
        parsed_before = parsed_path.read_bytes()
        metadata_before = self.metadata_path.read_bytes()

        def fail_metadata_write(path, content):
            if path.name.endswith(".metadata.json"):
                raise OSError("simulated metadata write failure")
            write_atomic(path, content)

        updated = b"<main><h1>Paths</h1><p>Updated documentation.</p></main>"
        with patch("doclens.fetch.urlopen", return_value=HTMLResponse(updated)):
            with patch("doclens.fetch.write_atomic", side_effect=fail_metadata_write):
                with self.assertRaises(OSError):
                    fetch_source(self.source, root=self.root)
        self.assertEqual(self.destination.read_bytes(), updated)
        self.assertEqual(self.metadata_path.read_bytes(), metadata_before)
        with self.assertRaisesRegex(ValueError, "does not match metadata"):
            parse_source(self.source, root=self.root)
        self.assertEqual(parsed_path.read_bytes(), parsed_before)

    def test_cli_keeps_first_success_when_second_source_read_fails(self):
        second = self.source_for_version("3.13")
        with patch("doclens.fetch.urlopen", return_value=HTMLResponse(url=second["url"])):
            fetch_source(second, root=self.root)
        second_path = self.root / second["local_path"]
        second_metadata_path = second_path.with_name(second_path.name + ".metadata.json")
        before = (second_path.read_bytes(), second_metadata_path.read_bytes())
        manifest_path = self.root / "sources.json"
        manifest_path.write_text(json.dumps({"sources": [self.source, second]}))
        output, stderr = io.StringIO(), io.StringIO()
        updated_first = b"<html>First source succeeded.</html>"
        incomplete = HTMLResponse(url=second["url"])
        with patch.object(incomplete, "read", side_effect=IncompleteRead(b"partial", 20)):
            with patch("sys.argv", ["doclens", "fetch", "--manifest", str(manifest_path)]):
                with patch("doclens.__main__.Path.cwd", return_value=self.root):
                    responses = [HTMLResponse(updated_first), incomplete]
                    with patch("doclens.fetch.urlopen", side_effect=responses):
                        with redirect_stdout(output), redirect_stderr(stderr):
                            with self.assertRaises(SystemExit) as exit:
                                main()
        self.assertEqual(exit.exception.code, 1)
        self.assertIn(f"Saved {self.source['source_id']}", output.getvalue())
        self.assertNotIn("Downloaded 2 sources", output.getvalue())
        self.assertIn(second["source_id"], stderr.getvalue())
        self.assertEqual(self.destination.read_bytes(), updated_first)
        first_metadata = json.loads(self.metadata_path.read_text())
        self.assertEqual(first_metadata["sha256"], hashlib.sha256(updated_first).hexdigest())
        self.assertEqual(before, (second_path.read_bytes(), second_metadata_path.read_bytes()))


if __name__ == "__main__":
    unittest.main()
