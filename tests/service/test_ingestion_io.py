"""Offline transport, destination, size, snapshot and secret-redaction checks."""

from datetime import datetime, timezone
import hashlib
import socket

import httpx
import pytest

from doclens.service.ingestion_io import (ArtifactStore, IngestionError, PinnedTransport,
    RAW_LIMIT, fetch_python, public_addresses, validate_destination)
from doclens.service.settings import WorkerSettings

SOURCE = {"product": "python", "version": "3.13", "connector_kind": "https_html",
          "url": "https://docs.python.org/3.13/library/pathlib.html"}
HTML = b'<main><section id="fixture"><h1>Synthetic ingestion fixture</h1><p>Reference.</p><pre>if True:\n    print("ok")\n</pre></section></main>'


def reply(status=200, content=HTML, headers=None):
    return httpx.Response(status, headers={"content-type": "text/html", **(headers or {})},
                          stream=httpx.ByteStream(content))


@pytest.mark.parametrize("url", [
    "http://docs.python.org/3.13/library/pathlib.html", "https://docs.python.org/3.12/library/pathlib.html",
    "https://docs.python.org/3/library/pathlib.html", "https://other.example/3.13/page.html",
    "https://127.0.0.1/3.13/page.html", "https://docs.python.org:8443/3.13/page.html",
    "https://user:fixture-secret@docs.python.org/3.13/page.html",
    "https://docs.python.org/3.13/page.html?token=fixture-secret",
    "https://docs.python.org/3.13/page.html#anchor", "https://docs.python.org/3.13/../3.12/page.html",
    "https://docs.python.org/3.13/%2e%2e/3.12/page.html", "https://docs.python.org/3.13/\\page.html",
])
def test_rejects_destinations_before_any_network_call(url):
    with pytest.raises(IngestionError) as error:
        fetch_python({**SOURCE, "url": url}, transport=httpx.MockTransport(lambda request: pytest.fail("network")))
    assert error.value.code == "unsafe_destination" and "fixture-secret" not in str(error.value)


def test_redirect_is_checked_before_following_and_body_is_not_saved():
    visited = []
    def response(request):
        visited.append(str(request.url))
        return reply(302, headers={"location": "https://docs.python.org/3.12/library/pathlib.html"})
    with pytest.raises(IngestionError, match="permitted"):
        fetch_python(SOURCE, transport=httpx.MockTransport(response))
    assert visited == [SOURCE["url"]]


def test_safe_redirect_preserves_real_version_and_bytes():
    visited = []
    def response(request):
        visited.append(str(request.url))
        return reply(302, headers={"location": "./other.html"}) if len(visited) == 1 else reply()
    snapshot = fetch_python(SOURCE, transport=httpx.MockTransport(response))
    assert snapshot.content == HTML and snapshot.final_url.endswith("/3.13/library/other.html")
    assert snapshot.fetched_at.tzinfo == timezone.utc


@pytest.mark.parametrize("status,headers,content,code,retryable", [
    (429, {}, HTML, "http_temporary", True), (503, {}, HTML, "http_temporary", True),
    (404, {}, b"secret server error", "http_rejected", False),
    (200, {"content-type": "application/json"}, HTML, "invalid_html", False),
    (200, {"content-encoding": "gzip"}, HTML, "invalid_html", False),
    (200, {"content-length": str(RAW_LIMIT + 1)}, HTML, "size_limit", False),
    (200, {}, b" " * 10, "invalid_html", False),
    (200, {}, b"x" * (RAW_LIMIT + 1), "size_limit", False),
])
def test_bounded_http_failures(status, headers, content, code, retryable):
    with pytest.raises(IngestionError) as error:
        fetch_python(SOURCE, transport=httpx.MockTransport(lambda request: reply(status, content, headers)))
    assert (error.value.code, error.value.retryable) == (code, retryable)
    assert "secret server" not in str(error.value)


def test_interrupted_read_is_redacted_and_retryable():
    class Interrupted(httpx.SyncByteStream):
        def __iter__(self):
            yield b"<main>"
            raise httpx.ReadError("Bearer fixture-secret provider body")
    with pytest.raises(IngestionError) as error:
        fetch_python(SOURCE, transport=httpx.MockTransport(lambda request:
            httpx.Response(200, headers={"content-type": "text/html"}, stream=Interrupted())))
    assert error.value.code == "network_error" and error.value.retryable
    assert "fixture-secret" not in str(error.value)


def test_stream_deadline_is_checked_and_redirect_loop_is_bounded():
    times = iter([0, 0, 31])
    with pytest.raises(IngestionError, match="interrupted"):
        fetch_python(SOURCE, transport=httpx.MockTransport(lambda request: reply()), clock=lambda: next(times))
    calls = []
    def redirect(request):
        calls.append(request)
        return reply(302, headers={"location": SOURCE["url"]})
    with pytest.raises(IngestionError):
        fetch_python(SOURCE, transport=httpx.MockTransport(redirect))
    assert len(calls) == 3


def test_dns_rejects_mixed_public_private_and_transport_pins_tls_identity(monkeypatch):
    def result(ip): return (socket.AF_INET, socket.SOCK_STREAM, 6, "", (ip, 443))
    monkeypatch.setattr(socket, "getaddrinfo", lambda *a, **kw: [result("151.101.0.223"), result("127.0.0.1")])
    with pytest.raises(IngestionError, match="permitted"):
        public_addresses("docs.python.org")
    transport = PinnedTransport(resolver=lambda host: ["151.101.0.223"])
    captured = []
    transport.transport.close()
    transport.transport = httpx.MockTransport(lambda request: captured.append(request) or reply())
    fetch_python(SOURCE, transport=transport)
    assert captured[0].url.host == "151.101.0.223"
    assert captured[0].headers["host"] == "docs.python.org"
    assert captured[0].extensions["sni_hostname"] == "docs.python.org"


def test_hash_named_artifacts_are_repeatable_and_corruption_is_not_overwritten(tmp_path):
    store = ArtifactStore(tmp_path)
    key, digest = store.put("workspace/source/job/claim", HTML, "raw")
    assert digest == hashlib.sha256(HTML).hexdigest()
    assert store.put("workspace/source/job/claim", HTML, "raw") == (key, digest)
    assert store.read(key, digest, len(HTML)) == HTML
    (tmp_path / key).write_bytes(b"x" * len(HTML))
    with pytest.raises(IngestionError, match="artifact"):
        store.put("workspace/source/job/claim", HTML, "raw")
    assert (tmp_path / key).read_bytes() == b"x" * len(HTML)


def test_artifact_paths_size_and_hash_are_checked(tmp_path):
    store = ArtifactStore(tmp_path / "root")
    with pytest.raises(IngestionError): store.put("../escape", HTML, "raw")
    with pytest.raises(IngestionError): store.put("ok", b"", "raw")
    key, digest = store.put("ok", HTML, "raw")
    with pytest.raises(IngestionError): store.read(key, "0" * 64, len(HTML))
    with pytest.raises(IngestionError): store.read(key, digest, len(HTML) + 1)


def test_worker_settings_and_celery_transport_bounds_do_not_expose_secrets(service_settings):
    pytest.importorskip("celery", reason="Optional worker extra.")
    from doclens.service.worker import create_worker
    settings = WorkerSettings(database_url=service_settings.database_url,
                              broker_url="redis://:fixture-secret@127.0.0.1:16379/0")
    assert "fixture-secret" not in repr(settings)
    app = create_worker(settings)
    assert app.conf.task_publish_retry is False and app.conf.result_backend is None
    assert app.conf.task_time_limit < settings.lease_seconds
    assert app.conf.task_soft_time_limit < app.conf.task_time_limit
    assert app.conf.worker_prefetch_multiplier == 1 and app.conf.accept_content == ["json"]
