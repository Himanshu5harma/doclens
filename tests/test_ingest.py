"""Exercise the complete ingestion command without network access."""

import hashlib
import io
import json
import unittest
from contextlib import redirect_stderr, redirect_stdout
from email.message import Message
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from doclens.__main__ import main


class SourceResponse(io.BytesIO):
    def __init__(self, source, *, supported=True):
        content = (
            f'<main><section id="example"><h1>Example {source["version"]}</h1>'
            '<p>Documented behavior.</p><pre>if True:\n    print("example")\n</pre>'
            '</section></main>'
        ) if supported else '<html><p>Unsupported layout.</p></html>'
        super().__init__(content.encode())
        self.url = source["url"]
        self.status = 200
        self.headers = Message()
        self.headers["Content-Type"] = "text/html"

    def geturl(self):
        return self.url


class IngestTests(unittest.TestCase):
    def setUp(self):
        temporary = TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.sources = [
            {
                "source_id": f"python-{version}-example",
                "product": "python",
                "version": version,
                "document_type": "reference",
                "url": f"https://docs.example.test/{version}/example.html",
                "local_path": f"data/raw/python/{version}/example.html",
                "source_terms_url": f"https://docs.example.test/{version}/license.html",
            }
            for version in ("3.12", "3.13")
        ]
        self.manifest = self.root / "sources.json"
        self.manifest.write_text(json.dumps({"sources": self.sources}))
        self.output, self.errors = io.StringIO(), io.StringIO()

    def run_ingest(self, responses):
        with patch("sys.argv", ["doclens", "ingest", "--manifest", str(self.manifest)]):
            with patch("doclens.__main__.Path.cwd", return_value=self.root):
                with patch("doclens.fetch.urlopen", side_effect=responses) as requests:
                    with redirect_stdout(self.output), redirect_stderr(self.errors):
                        main()
                    return requests

    def test_one_command_writes_matching_raw_metadata_and_parsed_documents(self):
        self.run_ingest([SourceResponse(source) for source in self.sources])
        for source in self.sources:
            raw_path = self.root / source["local_path"]
            metadata = json.loads(raw_path.with_name(raw_path.name + ".metadata.json").read_text())
            parsed_path = self.root / f'data/parsed/python/{source["version"]}/example.html.json'
            document = json.loads(parsed_path.read_text())
            self.assertEqual(document["source"], metadata)
            self.assertEqual(metadata["sha256"], hashlib.sha256(raw_path.read_bytes()).hexdigest())
            self.assertEqual(metadata["version"], source["version"])
            code = document["sections"][0]["blocks"][-1]
            self.assertEqual(code["kind"], "code")
            self.assertEqual(code["text"], 'if True:\n    print("example")\n')
        self.assertIn("Ingested 2 sources", self.output.getvalue())
        self.assertFalse(self.errors.getvalue())

    def test_invalid_manifest_fails_before_any_network_request(self):
        self.sources[1]["version"] = 3.13
        self.manifest.write_text(json.dumps({"sources": self.sources}))
        with self.assertRaises(SystemExit) as failure:
            self.run_ingest([AssertionError("Invalid manifests must not fetch anything")])
        self.assertEqual(failure.exception.code, 1)
        self.assertIn("'version' must be a nonempty string", self.errors.getvalue())
        self.assertFalse((self.root / "data").exists())

    def test_parse_failure_keeps_completed_sources_and_reports_failure(self):
        responses = [SourceResponse(self.sources[0]), SourceResponse(self.sources[1], supported=False)]
        with self.assertRaises(SystemExit) as failure:
            self.run_ingest(responses)
        self.assertEqual(failure.exception.code, 1)
        self.assertTrue((self.root / "data/parsed/python/3.12/example.html.json").exists())
        self.assertFalse((self.root / "data/parsed/python/3.13/example.html.json").exists())
        self.assertTrue((self.root / self.sources[1]["local_path"]).exists())
        self.assertIn("Ingest failed", self.errors.getvalue())
        self.assertNotIn("Ingested 2 sources", self.output.getvalue())


if __name__ == "__main__":
    unittest.main()
