"""Offline Stage 4 checks: service-document adapter, chunk/vector preparation, query contract.

Real PostgreSQL/pgvector scope, ranking and grant checks live in
test_retrieval_db.py (opt-in). The encoder here is synthetic (see retrieval_fixtures).
"""

from dataclasses import replace
import hashlib
import math

import pytest
from pydantic import ValidationError
from sqlalchemy.dialects import postgresql

from doclens.domain.chunking import ChunkPolicy, chunk_document
from doclens.sources.python_docs import parse_html
from doclens.sources import issue_export as issue
from doclens.sources import repository as repo
from doclens.retrieval.index import (
    IndexingError, RetrievalConfig, prepare_revision, search_scope, service_document,
)
from doclens.api.schemas import SearchCreate
from retrieval_fixtures import CONFIG, ROOT, HashingEncoder, revision_for

HTML = (b'<main><section id="paths"><h1>Synthetic paths fixture</h1><p>Create a path from a file URI.</p>'
        b'<pre>Path.from_uri("file:///tmp/x")\n</pre><section id="other"><h2>Other</h2>'
        b'<p>Unrelated JSON text.</p></section></section></main>')
HTML_URL = "https://docs.python.org/3.13/library/synthetic-fixture.html"
HTML_SOURCE = {"name": "synthetic", "connector_kind": "https_html", "product": "python", "version": "3.13",
               "document_type": "reference", "url": HTML_URL,
               "source_terms_url": "https://docs.python.org/3.13/license.html"}
CODE = (b'# Synthetic repository fixture; not CPython evidence.\n'
        b'class TestNamedTemporaryFile:\n    def test_fixture(self):\n        assert True\n')


def html_case(**source):
    return revision_for(parse_html(HTML, source_url=HTML_URL), {**HTML_SOURCE, **source},
                        schema="doclens-service-document-v1")


def test_index_identity_tracks_model_prefix_and_chunk_policy():
    base = RetrievalConfig(CONFIG)
    assert base.index_id == RetrievalConfig(CONFIG).index_id
    assert base.index_id != RetrievalConfig(replace(CONFIG, query_prefix="query: ")).index_id
    assert base.index_id != RetrievalConfig(CONFIG, ChunkPolicy(2500)).index_id
    with pytest.raises(ValueError, match="new migration"):
        RetrievalConfig(replace(CONFIG, dimensions=384))


def test_html_v1_reuses_baseline_chunker_with_service_identity():
    parsed, revision = html_case()
    service = service_document(parsed, revision)
    assert service.document.source.source_id == str(revision.source_id)
    assert service.document.source.content_hash == revision.raw_sha256
    assert all(loc["kind"] == "page_anchor" and loc["url"].startswith(HTML_URL) for loc in service.section_locations)
    chunks = chunk_document(service.document)
    assert any('Path.from_uri("file:///tmp/x")\n' in chunk.text for chunk in chunks)  # Code kept exactly.


def test_repository_v2_and_issue_v3_keep_typed_locations_and_versions():
    parsed, revision = revision_for(repo.parse_repository(CODE, source_url=repo.SOURCE_URL),
                                    repo.REGISTRATION, schema="doclens-service-document-v2")
    marker, rows = prepare_revision(parsed, revision, RetrievalConfig(CONFIG), HashingEncoder())
    assert marker.document_schema == "doclens-service-document-v2"
    assert [r.location["kind"] for r in rows] == ["repository_lines"]
    assert rows[0].location["start_line"] == 2 and rows[0].version == "3.13"
    assert "        assert True\n" in rows[0].text  # Whole class, indentation preserved.

    content = (ROOT / issue.CURATION_PATH).read_bytes()
    parsed, revision = revision_for(issue.parse_issue_export(content, source_url=issue.SOURCE_URL),
                                    issue.REGISTRATION, schema="doclens-service-document-v3")
    _, rows = prepare_revision(parsed, revision, RetrievalConfig(CONFIG), HashingEncoder())
    assert {r.version for r in rows} == {"3.8"}  # Historical issue is never relabeled as 3.13.
    assert {r.location["kind"] for r in rows} == {"issue", "issue_comment"}
    comments = [r for r in rows if r.location["kind"] == "issue_comment"]
    assert comments and all(r.location["created_at"] is None for r in comments)  # Unknown dates stay unknown.


def test_prepared_rows_carry_scope_unit_vectors_and_complete_set_identity():
    parsed, revision = html_case()
    config = RetrievalConfig(CONFIG)
    marker, rows = prepare_revision(parsed, revision, config, HashingEncoder())
    assert marker.chunk_count == len(rows) >= 2 and marker.index_id == config.index_id
    assert [r.ordinal for r in rows] == list(range(len(rows)))
    for row in rows:
        assert (row.workspace_id, row.source_id, row.revision_id) == (revision.workspace_id, revision.source_id, revision.id)
        assert (row.product, row.version, row.document_type) == ("python", "3.13", "reference")
        assert math.isclose(math.sqrt(sum(v * v for v in row.embedding)), 1.0, rel_tol=1e-9)
        assert hashlib.sha256(row.text.encode()).hexdigest() == row.content_hash
    again, rows_again = prepare_revision(parsed, revision, config, HashingEncoder())
    assert [r.id for r in rows_again] == [r.id for r in rows]  # Deterministic row IDs.
    assert again.chunk_set_hash == marker.chunk_set_hash


@pytest.mark.parametrize("change", ["revision", "version", "raw_hash", "block_hash", "missing_location", "schema"])
def test_mismatched_or_tampered_artifacts_are_refused(change):
    if change in ("block_hash", "missing_location"):
        parsed, revision = revision_for(repo.parse_repository(CODE, source_url=repo.SOURCE_URL),
                                        repo.REGISTRATION, schema="doclens-service-document-v2")
        section = parsed["document"]["sections"][0]
        if change == "block_hash":
            section["blocks"][0]["text"] += "# tampered\n"
        else:
            section.pop("location")
    else:
        parsed, revision = html_case()
        if change == "revision":
            parsed["revision_id"] = "00000000-0000-0000-0000-000000000000"
        elif change == "version":
            parsed["source"]["version"] = "3.12"  # Artifact claims another release than the DB revision.
            revision.source_snapshot = {**revision.source_snapshot, "version": "3.13"}
        elif change == "raw_hash":
            parsed["provenance"]["raw_sha256"] = "b" * 64
        else:
            parsed["schema_version"] = 1  # Baseline schema 1 is never silently reinterpreted.
    encoder = HashingEncoder()
    with pytest.raises(ValueError):
        prepare_revision(parsed, revision, RetrievalConfig(CONFIG), encoder)
    assert encoder.encoded == 0


def test_long_chunks_are_refused_not_truncated():
    parsed, revision = html_case()
    small = replace(CONFIG, max_tokens=5)
    encoder = HashingEncoder(small)
    with pytest.raises(IndexingError, match="No text was truncated"):
        prepare_revision(parsed, revision, RetrievalConfig(small), encoder)
    assert encoder.encoded == 0


def test_encoder_must_match_configuration():
    parsed, revision = html_case()
    with pytest.raises(IndexingError):
        prepare_revision(parsed, revision, RetrievalConfig(CONFIG), HashingEncoder(replace(CONFIG, batch_size=4)))


def test_search_statement_filters_scope_before_ordering():
    captured = {}

    class Recorder:
        def execute(self, statement):
            captured["sql"] = str(statement.compile(dialect=postgresql.dialect()))
            return type("Result", (), {"all": lambda self: []})()

    count, hits = search_scope(Recorder(), workspace_id=__import__("uuid").uuid4(), issuer="i", subject="s",
                               query_vector=[1.0] + [0.0] * 767, product="python", version="3.13",
                               top_k=5, index_id="x", document_types=("reference",))
    sql = " ".join(captured["sql"].split())
    where, order = sql.split(" WHERE ", 1)[1].split(" ORDER BY ", 1)
    for column in ("retrieval_chunks.workspace_id", "retrieval_chunks.product", "retrieval_chunks.version",
                   "retrieval_chunks.index_id", "retrieval_chunks.document_type", "EXISTS", "memberships"):
        assert column in where
    assert "<=> %(embedding_1)s AS distance" in sql and order.startswith("distance,") and "LIMIT" in order
    assert "source_publications" in sql.split(" WHERE ", 1)[0]  # Only the currently published revision.
    assert (count, hits) == (0, [])
    with pytest.raises(ValueError):
        search_scope(Recorder(), workspace_id=None, issuer="i", subject="s", query_vector=[1.0] * 768,
                     product="python", version="3.13", top_k=0, index_id="x")


def test_search_request_rejects_scope_overrides_and_requires_version():
    assert SearchCreate(query=" uri ", product="python", version="3.13").query == "uri"
    for body in ({"query": "q", "product": "python"},
                 {"query": "q", "product": "python", "version": "3.13", "workspace_id": "x"},
                 {"query": "q", "product": "python", "version": "3.13", "top_k": 21},
                 {"query": "", "product": "python", "version": "3.13"},
                 {"query": "q", "product": "python", "version": "3.13", "document_types": ["secret"]}):
        with pytest.raises(ValidationError):
            SearchCreate(**body)


def _offline_client(monkeypatch, service_settings, encoder):
    from uuid import uuid4
    from fastapi.testclient import TestClient
    from doclens.api import app as app_module, deps, search as retrieval_api
    from doclens.access.tokens import Identity
    from doclens.db.models import RetrievalChunk
    from doclens.retrieval.index import ScopedHit
    app = app_module.create_app(service_settings, verifier=object())
    workspace = uuid4()
    calls = []
    identity = Identity.__new__(Identity)
    object.__setattr__(identity, "issuer", "https://idp.example.test/realms/test")
    object.__setattr__(identity, "subject", "viewer")
    app.dependency_overrides[deps.get_identity] = lambda: identity
    app.dependency_overrides[deps.get_session] = lambda: None
    app.dependency_overrides[deps.require_workspace] = lambda: deps.WorkspaceAccess(workspace, uuid4(), "viewer")
    row = RetrievalChunk(id=uuid4(), chunk_key="chunk-x", source_id=uuid4(), revision_id=uuid4(),
                         document_type="reference", document_title="T", heading_path=["T"], anchor="a",
                         url="https://docs.python.org/3.13/x.html#a", location={"kind": "page_anchor"},
                         text="t", content_hash="h", oversized=False, token_count=3)

    def fake_search(session, **kwargs):
        calls.append(kwargs)
        return 7, [ScopedHit(1, 0.5, row, "source-name")]
    monkeypatch.setattr(retrieval_api, "search_scope", fake_search)
    if encoder is not None:
        app.state.query_encoder = encoder
    else:
        monkeypatch.setattr(retrieval_api, "load_embedding_config", lambda path: (_ for _ in ()).throw(OSError()))
    return TestClient(app), workspace, calls


def test_search_endpoint_passes_identity_scope_and_returns_typed_hits(monkeypatch, service_settings):
    client, workspace, calls = _offline_client(monkeypatch, service_settings, HashingEncoder())
    response = client.post(f"/api/v1/workspaces/{workspace}/search",
                           json={"query": "uri", "product": "python", "version": "3.13", "top_k": 3})
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["candidate_count"] == 7 and body["results"][0]["source_name"] == "source-name"
    assert body["index_id"] == RetrievalConfig(CONFIG).index_id and body["model_id"] == CONFIG.model_id
    (call,) = calls
    assert call["workspace_id"] == workspace and call["subject"] == "viewer" and call["top_k"] == 3
    assert (call["product"], call["version"], call["document_types"]) == ("python", "3.13", None)


def test_search_endpoint_reports_missing_model_without_details(monkeypatch, service_settings):
    client, workspace, calls = _offline_client(monkeypatch, service_settings, None)
    response = client.post(f"/api/v1/workspaces/{workspace}/search",
                           json={"query": "uri", "product": "python", "version": "3.13"})
    assert response.status_code == 503 and response.json() == {"detail": "Retrieval model unavailable."}
    assert calls == []
