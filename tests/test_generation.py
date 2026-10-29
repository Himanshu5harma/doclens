"""HTTP doubles prove zero-price routing, bounded failures, and credential hygiene."""

import copy
import io
import json
import unittest
from dataclasses import replace
from http.client import IncompleteRead
from urllib.error import HTTPError, URLError
from unittest.mock import patch

from doclens.generation import GenerationConfig, GenerationError, OpenRouterClient


CONFIG = GenerationConfig()
MESSAGES = ({"role": "system", "content": "Instructions"}, {"role": "user", "content": "Question"})
KEY = "sk-or-v1-offline-test-secret"
MODEL = {"id": CONFIG.model_id, "canonical_slug": "nvidia/nemotron-3.5-super-vl-20261015",
         "pricing": {"prompt": "0", "completion": "0"}, "context_length": 1_000_000,
         "top_provider": {"max_completion_tokens": 131072},
         "supported_parameters": ["response_format", "structured_outputs", "temperature", "max_tokens", "reasoning"]}
RESULT = {"model": CONFIG.model_id.removesuffix(":free"), "choices": [{"finish_reason": "stop",
          "message": {"role": "assistant", "content": '{"status":"answered"}'}}],
          "usage": {"prompt_tokens": 25, "completion_tokens": 5, "total_tokens": 30, "cost": 0}}


class Transport:
    def __init__(self, catalog=None, result=None, error=None):
        self.catalog = {"data": [copy.deepcopy(MODEL)]} if catalog is None else catalog
        self.result = copy.deepcopy(RESULT) if result is None else result
        self.error = error
        self.calls = []

    def __call__(self, request, *, timeout):
        self.calls.append((request, timeout))
        if self.error:
            raise self.error
        data = self.catalog if request.data is None else self.result
        return io.BytesIO(json.dumps(data).encode())


class ClientTests(unittest.TestCase):
    def setUp(self):
        patcher = patch.dict("os.environ", {"OPENROUTER_API_KEY": KEY})
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_explicit_free_model_zero_caps_no_fallback_and_recorded_metadata(self):
        transport = Transport()
        result = OpenRouterClient(transport=transport).complete(MESSAGES, CONFIG)
        self.assertEqual(len(transport.calls), 2)
        get, post = [r for r, _ in transport.calls]
        self.assertIsNone(get.get_header("Authorization"))
        self.assertEqual(post.get_header("Authorization"), "Bearer " + KEY)
        payload = json.loads(post.data)
        self.assertEqual(payload["model"], CONFIG.model_id)
        self.assertNotIn("models", payload)
        self.assertFalse(payload["provider"]["allow_fallbacks"])
        self.assertEqual(payload["provider"]["max_price"], {"prompt": 0, "completion": 0, "request": 0})
        self.assertTrue(payload["provider"]["require_parameters"])
        self.assertEqual(payload["transforms"], [])
        self.assertEqual(payload["max_tokens"], 1600)
        self.assertFalse(payload["reasoning"]["enabled"])
        self.assertEqual(result.metadata["usage"]["total_tokens"], 30)
        self.assertEqual(result.metadata["requested_model"], CONFIG.model_id)
        self.assertEqual(result.metadata["returned_model"], RESULT["model"])
        self.assertTrue(all(timeout == CONFIG.timeout_seconds for _, timeout in transport.calls))
        self.assertNotIn(KEY, json.dumps(result.metadata))

    def test_paid_or_router_ids_are_rejected(self):
        for model in ("nvidia/paid-model", "openrouter/free", "openrouter/auto", "provider/name:free:online"):
            with self.subTest(model=model), self.assertRaises(ValueError):
                replace(CONFIG, model_id=model)

    def test_missing_key_fails_without_network(self):
        transport = Transport()
        with patch.dict("os.environ", {"OPENROUTER_API_KEY": ""}), self.assertRaises(GenerationError) as error:
            OpenRouterClient(transport=transport).complete(MESSAGES, CONFIG)
        self.assertEqual(error.exception.kind, "configuration")
        self.assertFalse(transport.calls)

    def test_price_changes_missing_prices_or_unavailable_model_block_post(self):
        for update in ({"pricing": {"prompt": "0.1", "completion": "0"}},
                       {"pricing": {"prompt": "0", "completion": "0", "request": "0.01"}},
                       {"pricing": {"prompt": "NaN", "completion": "0"}},
                       {"pricing": {}}, {"id": "gone"}):
            model = copy.deepcopy(MODEL)
            model.update(update)
            transport = Transport(catalog={"data": [model]})
            with self.subTest(update=update), self.assertRaises(GenerationError):
                OpenRouterClient(transport=transport).complete(MESSAGES, CONFIG)
            self.assertEqual(len(transport.calls), 1)

    def test_catalog_context_output_and_parameter_limits_block_post(self):
        for update in ({"context_length": 100}, {"top_provider": {"max_completion_tokens": 100}},
                       {"top_provider": []}, {"supported_parameters": []}, {"supported_parameters": [{}]}):
            model = copy.deepcopy(MODEL)
            model.update(update)
            transport = Transport(catalog={"data": [model]})
            with self.subTest(update=update), self.assertRaises(GenerationError):
                OpenRouterClient(transport=transport).complete(MESSAGES, CONFIG)
            self.assertEqual(len(transport.calls), 1)

    def test_auth_rate_unavailable_http_errors_are_readable_and_never_echo_bodies(self):
        for code, kind in ((401, "authentication"), (402, "account"), (403, "access"),
                           (404, "unavailable"), (429, "rate_limit"), (503, "unavailable")):
            error = HTTPError("https://openrouter.ai", code, KEY, {}, io.BytesIO(KEY.encode()))
            transport = Transport(error=error)
            with self.subTest(code=code), self.assertRaises(GenerationError) as failure:
                OpenRouterClient(transport=transport).complete(MESSAGES, CONFIG)
            self.assertEqual(failure.exception.kind, kind)
            self.assertNotIn(KEY, str(failure.exception))
            self.assertEqual(len(transport.calls), 1)

    def test_timeout_interrupted_read_and_network_fail_without_retries(self):
        for error in (TimeoutError(KEY), URLError(KEY), IncompleteRead(b"partial")):
            transport = Transport(error=error)
            with self.subTest(error=error), self.assertRaises(GenerationError) as failure:
                OpenRouterClient(transport=transport).complete(MESSAGES, CONFIG)
            self.assertIn(failure.exception.kind, ("timeout", "transport"))
            self.assertNotIn(KEY, str(failure.exception))
            self.assertEqual(len(transport.calls), 1)

    def test_interruption_during_completion_body_read_is_reported_cleanly(self):
        class InterruptedBody(io.BytesIO):
            def read(self, size=-1):
                raise IncompleteRead(b"partial")
        calls = []
        def transport(request, *, timeout):
            calls.append(request)
            if request.data is None:
                return io.BytesIO(json.dumps({"data": [MODEL]}).encode())
            return InterruptedBody()
        with self.assertRaises(GenerationError) as failure:
            OpenRouterClient(transport=transport).complete(MESSAGES, CONFIG)
        self.assertEqual(failure.exception.kind, "transport")
        self.assertEqual(len(calls), 2)

    def test_http_200_provider_error_remains_provider_failure(self):
        transport = Transport(result={"error": {"code": 429, "message": KEY}})
        with self.assertRaises(GenerationError) as failure:
            OpenRouterClient(transport=transport).complete(MESSAGES, CONFIG)
        # Even an HTTP-200 provider body containing credentials is discarded.
        self.assertEqual(failure.exception.kind, "secret_redaction")
        self.assertNotIn(KEY, str(failure.exception))
        transport = Transport(result={"error": {"code": 429, "message": "capacity"}})
        with self.assertRaises(GenerationError) as failure:
            OpenRouterClient(transport=transport).complete(MESSAGES, CONFIG)
        self.assertEqual(failure.exception.kind, "rate_limit")

    def test_truncated_empty_or_mismatched_model_completions_are_rejected(self):
        changes = [{"model": "other/model"}, {"choices": []},
                   {"choices": [{"finish_reason": "length", "message": {"content": "partial"}}]},
                   {"choices": [{"finish_reason": "stop", "message": {"content": None}}]},
                   {"choices": [{"finish_reason": "error", "error": {"message": "provider failure"}}]}]
        for change in changes:
            result = copy.deepcopy(RESULT)
            result.update(change)
            with self.subTest(change=change), self.assertRaises(GenerationError):
                OpenRouterClient(transport=Transport(result=result)).complete(MESSAGES, CONFIG)

    def test_malformed_json_large_body_and_secret_echo_are_discarded(self):
        for body in (b"not JSON", b"x" * 4_000_001, json.dumps({"data": KEY}).encode()):
            calls = []
            def transport(request, *, timeout):
                calls.append(request)
                return io.BytesIO(body)
            with self.subTest(size=len(body)), self.assertRaises(GenerationError) as failure:
                OpenRouterClient(transport=transport).complete(MESSAGES, CONFIG)
            self.assertNotIn(KEY, str(failure.exception))
            self.assertEqual(len(calls), 1)

    def test_nonzero_reported_cost_is_rejected_and_usage_strings_not_saved(self):
        result = copy.deepcopy(RESULT)
        result["usage"] = {"cost": 0.001}
        with self.assertRaises(GenerationError) as failure:
            OpenRouterClient(transport=Transport(result=result)).complete(MESSAGES, CONFIG)
        self.assertEqual(failure.exception.kind, "pricing")
        result["usage"] = {"cost": 0, "prompt_tokens": 4, "provider_note": "untrusted string"}
        completed = OpenRouterClient(transport=Transport(result=result)).complete(MESSAGES, CONFIG)
        self.assertEqual(completed.metadata["usage"], {"cost": 0, "prompt_tokens": 4})
        result["usage"] = {"cost": "0.001"}
        with self.assertRaises(GenerationError) as failure:
            OpenRouterClient(transport=Transport(result=result)).complete(MESSAGES, CONFIG)
        self.assertEqual(failure.exception.kind, "invalid_response")

    def test_secret_or_oversized_prompt_is_blocked_before_network(self):
        transport = Transport()
        for text in (KEY, "x" * 25000):
            with self.subTest(text_size=len(text)), self.assertRaises(GenerationError):
                OpenRouterClient(transport=transport).complete(({"role": "user", "content": text},), CONFIG)
        self.assertFalse(transport.calls)


if __name__ == "__main__":
    unittest.main()
