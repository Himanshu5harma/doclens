"""Offline graph/direct parity, routing, traces, and provider-call bounds."""

import builtins
import hashlib
import importlib.util
import io
import json
import sqlite3
import subprocess
import sys
import unittest
from contextlib import redirect_stderr, redirect_stdout
from dataclasses import asdict, replace
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import Mock, patch

from doclens.__main__ import main
from doclens.answers import answer_question, assemble_evidence
from doclens.chunk import ChunkPolicy, chunk_document
from doclens.embeddings import EmbeddingConfig
from doclens.generation import Completion, GenerationConfig, GenerationError
from doclens.parse import parse_html
from doclens.records import SearchResponse, SearchResult, Source, document_from_dict
from doclens.workflow import run_workflow


HAS_GRAPH = importlib.util.find_spec("langgraph") is not None
CONFIG = GenerationConfig()
KEY = "sk-or-v1-offline-workflow-secret"
CODE = '```python\nfrom pathlib import Path\np = Path.from_uri("file:///etc/hosts")\n```'


def prepared_question():
    page = "https://docs.example.test/3.13/guide.html"
    source = Source("python-3.13-guide", "python", "3.13", "reference", page,
                    "a" * 64, "2026-11-01T00:00:00Z", page)
    result = SearchResult(1, 0.7, "chunk-1", source, "Guide", ("Guide",), page + "#guide",
                          CODE, hashlib.sha256(CODE.encode()).hexdigest(), False)
    return assemble_evidence(SearchResponse("Question?", "python", "3.13", 10,
                                           "test/encoder", "a" * 40, (result,)), CONFIG)


def completion(status="answered"):
    insufficient = status == "insufficient_evidence"
    return Completion(json.dumps({
        "status": status, "answer": "" if insufficient else CODE + "\nUse this API. [E1]",
        "citations": [] if insufficient else ["E1"],
        "missing_evidence": ["Additional documentation is needed."] if status != "answered" else [],
    }), {"finish_reason": "stop", "requested_model": CONFIG.model_id, "returned_model": CONFIG.model_id,
         "usage": {"cost": 0}, "latency_seconds": 0.01})


@unittest.skipUnless(HAS_GRAPH, "Install the graph extra to run LangGraph contract tests.")
class WorkflowTests(unittest.TestCase):
    def setUp(self):
        self.prepared = prepared_question()
        self.preparer = Mock(return_value=self.prepared)
        self.client = Mock()
        self.client.complete.return_value = completion()
        self.events = []

    def run_graph(self, **kwargs):
        return run_workflow(Path("not-read.sqlite3"), "Question?", version="3.13", root=Path.cwd(),
                            config=CONFIG, preparer=self.preparer, client=self.client,
                            on_update=self.events.append, **kwargs)

    def test_answered_and_partial_results_equal_direct_pipeline(self):
        for status in ("answered", "partial"):
            with self.subTest(status=status):
                self.client.reset_mock()
                self.events.clear()
                self.client.complete.return_value = completion(status)
                expected = answer_question(self.prepared, CONFIG, client=self.client)
                self.client.reset_mock()
                state = self.run_graph()
                self.assertEqual(asdict(state["result"]), asdict(expected))
                self.assertEqual(state["completion"], self.client.complete.return_value)
                self.client.complete.assert_called_once_with(self.prepared.messages, CONFIG)
                self.assertEqual([e["node"] for e in self.events], ["prepare", "generate", "validate"])

    def test_inspection_stops_after_prepare_without_constructing_provider_client(self):
        with patch("doclens.workflow.OpenRouterClient", side_effect=AssertionError("Must not construct client")):
            state = run_workflow(Path("not-read"), "Question?", version="3.13", root=Path.cwd(),
                                 config=CONFIG, preparer=self.preparer, inspect_only=True,
                                 on_update=self.events.append)
        self.assertEqual(state["prepared"], self.prepared)
        self.assertNotIn("completion", state)
        self.assertNotIn("result", state)
        self.assertEqual([e["node"] for e in self.events], ["prepare"])

    def test_empty_evidence_uses_existing_local_result_without_generation(self):
        empty = assemble_evidence(SearchResponse("Question?", "python", "3.13", 0,
                                                "test/encoder", "a" * 40, ()), CONFIG)
        self.preparer.return_value = empty
        expected = answer_question(empty, CONFIG, client=self.client)
        state = self.run_graph()
        self.client.complete.assert_not_called()
        self.assertEqual(asdict(state["result"]), asdict(expected))
        self.assertEqual([e["node"] for e in self.events], ["prepare", "insufficient"])

    def test_nonempty_irrelevant_evidence_still_generates_and_validates_insufficiency(self):
        self.client.complete.return_value = completion("insufficient_evidence")
        expected = answer_question(self.prepared, CONFIG, client=self.client)
        self.client.reset_mock()
        state = self.run_graph()
        self.assertEqual(asdict(state["result"]), asdict(expected))
        self.client.complete.assert_called_once()
        self.assertEqual([e["node"] for e in self.events], ["prepare", "generate", "validate"])

    def test_provider_failures_terminate_without_retries_or_abstention(self):
        for kind in ("authentication", "rate_limit", "unavailable", "pricing", "timeout"):
            self.client.reset_mock()
            self.events.clear()
            self.client.complete.side_effect = GenerationError(kind, "Readable provider failure.")
            with self.subTest(kind=kind):
                state = self.run_graph()
                self.client.complete.assert_called_once()
                self.assertEqual(state["error"].kind, kind)
                self.assertEqual(state["error"].stage, "generate")
                self.assertNotIn("result", state)
                self.assertEqual([e["node"] for e in self.events], ["prepare", "generate"])

    def test_invalid_json_citations_and_truncation_end_at_validation(self):
        values = [Completion("not JSON", {"finish_reason": "stop"}),
                  Completion(json.dumps({"status": "answered", "answer": "Wrong. [E99]", "citations": ["E99"], "missing_evidence": []}), {"finish_reason": "stop"}),
                  replace(completion(), metadata={"finish_reason": "length"})]
        for value in values:
            self.client.reset_mock()
            self.events.clear()
            self.client.complete.return_value = value
            with self.subTest(value=value):
                state = self.run_graph()
                self.assertEqual(state["error"].stage, "validate")
                self.assertEqual(state["error"].kind, "invalid_answer")
                self.assertNotIn("result", state)
                self.client.complete.assert_called_once()
                self.assertEqual(self.events[-1]["node"], "validate")

    def test_prepare_failure_terminates_before_generation(self):
        for error in (ValueError("No indexed chunks for requested version."), sqlite3.DatabaseError("Invalid index.")):
            self.events.clear()
            self.preparer.side_effect = error
            with self.subTest(error=error):
                state = self.run_graph()
                self.assertEqual(state["error"].stage, "prepare")
                self.assertNotIn("prepared", state)
                self.assertNotIn("result", state)
                self.assertEqual([e["node"] for e in self.events], ["prepare"])
        self.client.complete.assert_not_called()

    def test_trace_summaries_preserve_json_output_without_exposing_payloads(self):
        state = self.run_graph()
        trace_text = json.dumps(self.events)
        self.assertNotIn("Path.from_uri", trace_text)
        self.assertNotIn("Question?", trace_text)
        self.assertEqual(self.events[0]["prompt_sha256"], self.prepared.prompt_sha256)
        self.assertEqual(self.events[-1]["answer_status"], "answered")
        self.assertEqual(self.events[-1]["updated_fields"], ["result"])
        self.assertFalse({"client", "encoder", "config", "api_key", "root", "index"} & state.keys())

    def test_secret_echo_and_failure_details_do_not_enter_state_or_traces(self):
        with patch.dict("os.environ", {"OPENROUTER_API_KEY": KEY}):
            self.client.complete.return_value = Completion(KEY, {"finish_reason": "stop"})
            state = self.run_graph()
            self.assertNotIn("completion", state)
            self.assertEqual(state["error"].kind, "secret_redaction")
            self.assertNotIn(KEY, repr(state))
            self.assertNotIn(KEY, json.dumps(self.events))
            self.client.complete.side_effect = GenerationError("transport", "Header contained " + KEY)
            self.events.clear()
            state = self.run_graph()
            self.assertNotIn(KEY, repr(state))
            self.assertNotIn(KEY, json.dumps(self.events))
            self.assertIn("[REDACTED]", state["error"].message)

    def test_injected_transport_error_never_exposes_raw_exception(self):
        self.client.complete.side_effect = OSError("Authorization: " + KEY)
        state = self.run_graph()
        self.assertEqual(state["error"].kind, "transport")
        self.assertNotIn(KEY, repr(state))

    def test_cloud_tracing_disabled_even_when_globally_enabled(self):
        from langsmith.run_helpers import get_tracing_context
        observed = []
        def generate(*args):
            observed.append(get_tracing_context()["enabled"])
            return completion()
        self.client.complete.side_effect = generate
        with patch.dict("os.environ", {"LANGSMITH_TRACING": "true", "LANGCHAIN_TRACING_V2": "true"}):
            with patch("langsmith.client.Client.create_run") as create_run:
                self.run_graph()
                create_run.assert_not_called()
        self.assertEqual(observed, [False])

    def test_runtime_inputs_and_budget_settings_forwarded_without_changes(self):
        encoder = Mock()
        state = self.run_graph(top_k=3, encoder=encoder)
        self.preparer.assert_called_once_with(Path("not-read.sqlite3"), "Question?", version="3.13",
                                              product="python", root=Path.cwd(), config=CONFIG,
                                              top_k=3, encoder=encoder)
        self.assertEqual(state["prepared"].messages, self.prepared.messages)

    def test_cli_graph_answer_json_and_local_trace_are_separate_streams(self):
        args = ["doclens", "ask", "Question?", "--version", "3.13", "--workflow", "graph", "--trace", "--json"]
        out, err = io.StringIO(), io.StringIO()
        with patch("sys.argv", args), patch("doclens.workflow.prepare_question", return_value=self.prepared):
            with patch("doclens.workflow.OpenRouterClient", return_value=self.client), redirect_stdout(out), redirect_stderr(err):
                main()
        self.assertEqual(json.loads(out.getvalue())["status"], "answered")
        events = [json.loads(line) for line in err.getvalue().splitlines()]
        self.assertEqual([e["node"] for e in events], ["prepare", "generate", "validate"])
        self.client.complete.assert_called_once()

    def test_cli_inspection_and_provider_error(self):
        args = ["doclens", "ask", "Question?", "--version", "3.13", "--workflow", "graph", "--trace"]
        out, err = io.StringIO(), io.StringIO()
        with patch("sys.argv", args + ["--inspect-prompt"]), patch("doclens.workflow.prepare_question", return_value=self.prepared):
            with patch("doclens.workflow.OpenRouterClient", side_effect=AssertionError("No client")), redirect_stdout(out), redirect_stderr(err):
                main()
        self.assertEqual(json.loads(out.getvalue())["prepared"]["messages"], list(self.prepared.messages))
        self.client.complete.side_effect = GenerationError("rate_limit", "Wait before retrying.")
        err = io.StringIO()
        with patch("sys.argv", args), patch("doclens.workflow.prepare_question", return_value=self.prepared):
            with patch("doclens.workflow.OpenRouterClient", return_value=self.client), redirect_stderr(err), self.assertRaises(SystemExit) as failure:
                main()
        self.assertEqual(failure.exception.code, 1)
        self.assertIn("generate: Wait before retrying.", err.getvalue())
        self.assertNotIn("insufficient_evidence", err.getvalue())

    def test_real_read_only_retrieval_keeps_versions_and_all_input_bytes(self):
        class Encoder:
            config = EmbeddingConfig("test/encoder", "a" * 40, 2, 1000, "d: ", "q: ")
            runtime = {"backend": "test-double"}
            def token_counts(self, texts): return [10] * len(texts)
            def encode(self, texts, *, query=False): return [(1, 0)] * len(texts)
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            index = root / "index.sqlite3"
            raw = root / "raw.html"
            raw.write_bytes(b"Saved ingestion; graph must not change it.")
            chunks = []
            for version in ("3.12", "3.13"):
                page = f"https://docs.example.test/{version}/guide.html"
                html = b'<main><section id="guide"><h1>Guide</h1><p>Evidence.</p></section></main>'
                document = parse_html(html, source_url=page)
                document["source"] = {"source_id": f"python-{version}-guide", "product": "python", "version": version,
                                      "document_type": "reference", "url": page, "sha256": hashlib.sha256(html).hexdigest(),
                                      "fetched_at": "2026-11-01T00:00:00Z", "source_terms_url": page}
                chunks.extend(chunk_document(document_from_dict(document)))
            from doclens.retrieval import build_index
            build_index(chunks, path=index, encoder=Encoder(), manifest_hash="f" * 64, policy=ChunkPolicy())
            before = {p: p.read_bytes() for p in (index, raw)}
            state = run_workflow(index, "Question?", version="3.13", root=root, config=CONFIG,
                                 encoder=Encoder(), client=self.client, on_update=self.events.append)
            self.assertEqual(state["prepared"].retrieval["candidate_count"], 1)
            self.assertTrue(all(e.passage.source.version == "3.13" for e in state["prepared"].evidence))
            self.assertEqual(before, {p: p.read_bytes() for p in (index, raw)})
            self.client.reset_mock()
            state = run_workflow(index, "Question?", version="9.9", root=root, config=CONFIG,
                                 encoder=Encoder(), client=self.client)
            self.assertEqual(state["error"].stage, "prepare")
            self.client.complete.assert_not_called()


class OptionalWorkflowTests(unittest.TestCase):
    def test_missing_optional_extra_has_readable_install_message(self):
        original_import = builtins.__import__
        def without_graph(name, *args, **kwargs):
            if name.startswith("langgraph"):
                raise ModuleNotFoundError("langgraph unavailable")
            return original_import(name, *args, **kwargs)
        with patch("builtins.__import__", side_effect=without_graph):
            with self.assertRaisesRegex(ValueError, "uv sync --extra retrieval --extra graph"):
                run_workflow(Path("not-read"), "Question?", version="3.13", root=Path.cwd(), config=CONFIG)

    def test_direct_cli_import_does_not_import_langgraph(self):
        result = subprocess.run([sys.executable, "-c", "import sys; import doclens.__main__; assert 'langgraph' not in sys.modules"],
                                 capture_output=True, text=True, timeout=10)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_trace_requires_graph_before_any_retrieval(self):
        args = ["doclens", "ask", "Question?", "--version", "3.13", "--trace"]
        with patch("sys.argv", args), patch("doclens.__main__.prepare_question") as prepare:
            with redirect_stderr(io.StringIO()), self.assertRaises(SystemExit) as failure:
                main()
            self.assertEqual(failure.exception.code, 2)
            prepare.assert_not_called()

    def test_credential_input_is_blocked_before_graph_creation(self):
        with patch.dict("os.environ", {"OPENROUTER_API_KEY": KEY}), patch("doclens.workflow._build_graph") as build:
            with self.assertRaises(GenerationError) as failure:
                run_workflow(Path("not-read"), KEY, version="3.13", root=Path.cwd(), config=CONFIG)
            self.assertEqual(failure.exception.kind, "secret_redaction")
            build.assert_not_called()


if __name__ == "__main__":
    unittest.main()
