"""Offline curated raw-file protocol/location checks, with synthetic bytes."""

import hashlib
import json
from pathlib import Path

import httpx
from pydantic import ValidationError
import pytest

from doclens.service import repository
from doclens.service.ingestion_io import IngestionError, PinnedTransport
from doclens.service.repository import (FILE_LIMIT, FILE_PATH, REGISTRATION, RAW_URL,
    SOURCE_URL, SYMBOL, fetch_repository, git_blob_sha, parse_repository, source_metadata)
from doclens.service.schemas import SourceCreate
from doclens.service.source_adapters import adapter_for

CODE = (b'# Synthetic parser/HTTP fixture, not CPython evidence.\n'
        b'raise RuntimeError("must never execute")\n\n'
        b'@decorate\nclass TestNamedTemporaryFile(Base):\n'
        b'    """A fixture class."""\n'
        b'    def test_cleanup(self):\n'
        b'        # Keep this comment and indentation.\n'
        b'        text = "caf\xc3\xa9"\n'
        b'        assert text\n\nclass Excluded:\n    pass\n')


@pytest.fixture
def reviewed_fixture(monkeypatch):
    # Change the trusted policy in this test process, never a production fault flag.
    monkeypatch.setattr(repository, "EXPECTED_SHA256", hashlib.sha256(CODE).hexdigest())
    monkeypatch.setattr(repository, "EXPECTED_BLOB_SHA1", git_blob_sha(CODE))


def reply(content=CODE, *, status=200, headers=None):
    return httpx.Response(status, stream=httpx.ByteStream(content),
        headers={"content-type": "text/plain; charset=utf-8", **(headers or {})})


def test_catalog_matches_reviewed_policy_without_changing_frozen_manifest():
    path = Path(__file__).resolve().parents[2] / "corpus/expanded/sources.json"
    catalog = json.loads(path.read_text())["sources"][0]
    assert catalog.pop("registration") == REGISTRATION
    assert catalog == source_metadata()
    assert SourceCreate(**REGISTRATION).model_dump() == REGISTRATION


@pytest.mark.parametrize("change", [
    {"version": "3.12"}, {"product": "other"}, {"document_type": "reference"},
    {"url": SOURCE_URL.replace(repository.COMMIT, "main")},
    {"url": SOURCE_URL.replace(FILE_PATH, "../LICENSE")},
    {"url": SOURCE_URL.replace("github.com", "127.0.0.1")},
    {"url": SOURCE_URL + "?token=fixture-secret"},
    {"source_terms_url": "https://example.test/license"},
])
def test_rejects_uncurated_scope_before_network_and_registration(change):
    with pytest.raises(ValidationError):
        SourceCreate(**(REGISTRATION | change))
    with pytest.raises(IngestionError) as error:
        fetch_repository(REGISTRATION | change,
                         transport=httpx.MockTransport(lambda request: pytest.fail("network")))
    assert error.value.code == "unsupported_source" and "fixture-secret" not in str(error.value)


def test_fixed_raw_read_preserves_bytes_and_does_not_forward_credentials(reviewed_fixture, monkeypatch):
    monkeypatch.setenv("GITHUB_TOKEN", "fixture-secret")
    monkeypatch.setenv("HTTPS_PROXY", "http://fixture-secret@127.0.0.1:1")
    visited = []
    snapshot = fetch_repository(REGISTRATION, transport=httpx.MockTransport(lambda request: visited.append(request) or reply()))
    assert snapshot.content == CODE and snapshot.final_url == RAW_URL
    assert len(visited) == 1
    request = visited[0]
    assert str(request.url) == RAW_URL and request.method == "GET"
    assert "authorization" not in request.headers and "cookie" not in request.headers
    assert not request.url.query and "fixture-secret" not in str(request.headers)


@pytest.mark.parametrize("content", [CODE.replace(b"assert text", b"assert None"), CODE + b"x", CODE[:-1], b"", b"version https://git-lfs.github.com/spec/v1\n"])
def test_rejects_changed_empty_truncated_or_pointer_bytes(reviewed_fixture, content):
    with pytest.raises(IngestionError) as error:
        fetch_repository(REGISTRATION, transport=httpx.MockTransport(lambda request: reply(content)))
    assert error.value.code == "repository_invalid" and not error.value.retryable


def test_git_blob_hash_must_also_match(reviewed_fixture, monkeypatch):
    monkeypatch.setattr(repository, "EXPECTED_BLOB_SHA1", "0" * 40)
    with pytest.raises(IngestionError, match="pinned"):
        fetch_repository(REGISTRATION, transport=httpx.MockTransport(lambda request: reply()))


@pytest.mark.parametrize("status,headers,body,code,retry", [
    (302, {"location": "http://127.0.0.1/fixture-secret"}, b"secret", "http_rejected", False),
    (403, {}, b"secret", "http_rejected", False),
    (403, {"x-ratelimit-remaining": "0"}, b"secret", "repository_rate_limit", False),
    (429, {"retry-after": "3600"}, b"secret", "repository_rate_limit", False),
    (404, {}, b"secret", "http_rejected", False),
    (503, {}, b"secret", "http_temporary", True),
    (200, {"content-type": "text/html"}, b"secret", "repository_invalid", False),
    (200, {"content-encoding": "gzip"}, b"secret", "repository_invalid", False),
    (200, {"content-length": str(FILE_LIMIT + 1)}, b"secret", "size_limit", False),
    (200, {}, b"x" * (FILE_LIMIT + 1), "size_limit", False),
])
def test_bounded_redacted_http_errors(status, headers, body, code, retry):
    calls = []
    def response(request):
        calls.append(request)
        return reply(body, status=status, headers=headers)
    with pytest.raises(IngestionError) as error:
        fetch_repository(REGISTRATION, transport=httpx.MockTransport(response))
    assert len(calls) == 1
    assert (error.value.code, error.value.retryable) == (code, retry)
    assert "secret" not in str(error.value)


def test_exact_byte_limit_accepts_complete_reviewed_bytes(monkeypatch):
    content = b"#" + b"x" * (FILE_LIMIT - 2) + b"\n"
    monkeypatch.setattr(repository, "EXPECTED_SHA256", hashlib.sha256(content).hexdigest())
    monkeypatch.setattr(repository, "EXPECTED_BLOB_SHA1", git_blob_sha(content))
    snapshot = fetch_repository(REGISTRATION, transport=httpx.MockTransport(lambda request: reply(content)))
    assert snapshot.content == content and len(snapshot.content) == FILE_LIMIT


def test_interrupted_stream_and_deadline_do_not_leak_server_exception():
    class Interrupted(httpx.SyncByteStream):
        def __iter__(self):
            yield b"class Test"
            raise httpx.ReadError("fixture-secret")
    with pytest.raises(IngestionError) as error:
        fetch_repository(REGISTRATION, transport=httpx.MockTransport(lambda request:
            httpx.Response(200, headers={"content-type": "text/plain"}, stream=Interrupted())))
    assert error.value.code == "network_error" and error.value.retryable
    assert "fixture-secret" not in str(error.value)
    times = iter([0, 0, 31])
    with pytest.raises(IngestionError, match="interrupted"):
        fetch_repository(REGISTRATION, transport=httpx.MockTransport(lambda request: reply()), clock=lambda: next(times))


def test_raw_transport_preserves_tls_hostname_while_connecting_to_checked_ip(reviewed_fixture):
    transport = PinnedTransport(resolver=lambda host: ["185.199.108.133"])
    transport.transport.close()
    captured = []
    transport.transport = httpx.MockTransport(lambda request: captured.append(request) or reply())
    assert fetch_repository(REGISTRATION, transport=transport).content == CODE
    assert captured[0].url.host == "185.199.108.133"
    assert captured[0].headers["host"] == "raw.githubusercontent.com"
    assert captured[0].extensions["sni_hostname"] == "raw.githubusercontent.com"


@pytest.mark.parametrize("content", [CODE, CODE.replace(b"\n", b"\r\n")])
def test_selection_preserves_complete_code_comments_decorators_and_trusted_lines(content):
    document = parse_repository(content, source_url=SOURCE_URL)
    section = document["sections"][0]
    block = section["blocks"][0]
    assert section["heading_path"] == [FILE_PATH, SYMBOL]
    assert block["location"]["start_line"] == 4 and block["location"]["end_line"] == 10
    assert block["text"] == b"".join(content.splitlines(keepends=True)[3:10]).decode()
    assert block["content_sha256"] == hashlib.sha256(block["text"].encode()).hexdigest()
    assert block["url"] == SOURCE_URL + "#L4-L10" == section["url"]
    assert block["location"]["commit"] == repository.COMMIT
    assert "Excluded" not in block["text"] and "caf\u00e9" in block["text"]
    assert document == parse_repository(content, source_url=SOURCE_URL)


@pytest.mark.parametrize("content", [b"", b"\xff", b"class Wrong: pass", b"class : bad",
                                      CODE + b"\nclass TestNamedTemporaryFile: pass\n",
                                      b"x" * (FILE_LIMIT + 1)])
def test_unparseable_missing_duplicate_or_oversized_selection_is_explicit(content):
    with pytest.raises(IngestionError) as error:
        parse_repository(content, source_url=SOURCE_URL)
    assert error.value.code == "repository_parse"


def test_unicode_line_separator_in_string_does_not_shift_python_line_citations():
    content = CODE.replace(b"caf\xc3\xa9", "first\u2028second".encode())
    block = parse_repository(content, source_url=SOURCE_URL)["sections"][0]["blocks"][0]
    expected = content[content.index(b"@decorate"):content.index(b"\n\nclass Excluded") + 1]
    assert block["text"].encode() == expected
    assert block["location"]["end_line"] == 10


def test_adapter_selection_does_not_relabel_html_or_accept_unsupported_kinds():
    html = {"connector_kind": "https_html", "product": "python", "version": "3.13",
            "url": "https://docs.python.org/3.13/library/tempfile.html"}
    assert adapter_for(html).document_schema == "doclens-service-document-v1"
    assert adapter_for(REGISTRATION).document_schema == "doclens-service-document-v2"
    with pytest.raises(IngestionError):
        adapter_for({**REGISTRATION, "connector_kind": "git_clone"})
