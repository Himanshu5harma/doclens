"""Opt-in real PostgreSQL/pgvector + Keycloak checks for Stage 4 scoped retrieval.

Each test creates its own synthetic workspaces (memberships copied from the
seeded demo identities) so no membership change leaks into other tests. The
query/document encoder is the synthetic HashingEncoder; real-model ranking is
measured separately by scripts/stage4_eval.py.
"""

from concurrent.futures import ThreadPoolExecutor
import math
from uuid import UUID, uuid4

import pytest
from sqlalchemy import delete, func, insert, select, text
from sqlalchemy.exc import ProgrammingError
from sqlalchemy.orm import sessionmaker

from doclens.ingestion.jobs import run_job, utcnow
from doclens.ingestion.artifacts import ArtifactStore
from doclens.sources.base import Snapshot
from doclens.db.models import Membership, RetrievalChunk, RevisionIndex, Workspace
from doclens.retrieval.index import RetrievalConfig, index_revision, search_scope
from retrieval_fixtures import CONFIG, HashingEncoder

PAGE = ('<main><section id="uri"><h1>Synthetic retrieval fixture {tag}</h1>'
        '<p>Convert a file URI into a path object with from_uri.</p>'
        '<section id="json"><h2>JSON</h2><p>Serialize a dictionary to JSON text with dumps.</p></section>'
        '<section id="glob"><h2>Glob</h2><p>Match wildcard patterns against file names recursively.</p></section>'
        '</section></main>')
CONFIG_ID = RetrievalConfig(CONFIG).index_id


@pytest.fixture
def workspaces(real_services):
    """Two fresh workspaces: 'alpha' mirrors Atlas members, 'beta' has only boreal-owner (+ dual-member)."""
    alpha, beta = uuid4(), uuid4()
    with real_services.owner.begin() as con:
        for wid in (alpha, beta):
            con.execute(insert(Workspace).values(id=wid, slug="s4-" + wid.hex, name="Synthetic Stage 4 fixture"))
        atlas = con.execute(select(Membership.principal_id, Membership.role).where(
            Membership.workspace_id == real_services.workspaces["atlas"])).all()
        boreal = con.execute(select(Membership.principal_id, Membership.role).where(
            Membership.workspace_id == real_services.workspaces["boreal"])).all()
        con.execute(insert(Membership), [{"workspace_id": alpha, "principal_id": p, "role": r} for p, r in atlas])
        con.execute(insert(Membership), [{"workspace_id": beta, "principal_id": p, "role": r} for p, r in boreal])
    return {"alpha": alpha, "beta": beta}


@pytest.fixture
def case(api, headers, real_services, tmp_path):
    store = api.app.state.artifacts = ArtifactStore(tmp_path / "artifacts")
    api.app.state.query_encoder = HashingEncoder()
    return {"store": store, "sessions": sessionmaker(real_services.worker, expire_on_commit=False)}


def publish(api, headers, case, workspace, owner, *, version="3.13", tag="a", source_id=None):
    """Register (once) and sync a synthetic HTML source through the real job path."""
    prefix = f"/api/v1/workspaces/{workspace}"
    if source_id is None:
        name = uuid4().hex
        body = {"name": "synthetic-" + name, "product": "python", "version": version,
                "url": f"https://docs.python.org/{version}/library/synthetic-{name}.html",
                "source_terms_url": f"https://docs.python.org/{version}/license.html"}
        created = api.post(prefix + "/sources", headers=headers(owner), json=body)
        assert created.status_code == 201, created.text
        source_id = created.json()["id"]
    job = api.post(f"{prefix}/sources/{source_id}/sync", headers=headers(owner), json={"request_key": str(uuid4())})
    assert job.status_code == 202, job.text
    html = PAGE.format(tag=tag).encode()
    assert run_job(case["sessions"], case["store"], UUID(job.json()["id"]),
                   fetcher=lambda source: Snapshot(html, source["url"], utcnow())) == "finished"
    revision = api.get(f"{prefix}/sources/{source_id}/revision", headers=headers(owner)).json()
    return source_id, UUID(revision["id"])


def index(case, revision_id, encoder=None):
    return index_revision(case["sessions"], case["store"], revision_id, RetrievalConfig(CONFIG), encoder or HashingEncoder())


def search(api, headers, workspace, alias, query="file URI to path", **extra):
    return api.post(f"/api/v1/workspaces/{workspace}/search", headers=headers(alias),
                    json={"query": query, "product": "python", "version": "3.13", **extra})


def test_migration_requires_vector_and_keeps_api_read_only(real_services):
    with real_services.owner.connect() as con:
        assert con.scalar(text("SELECT version_num FROM doclens_service.alembic_version")) == "0005_retrieval_index"
        assert con.scalar(text("SELECT extversion FROM pg_extension WHERE extname = 'vector'"))
    with real_services.runtime.connect() as con:
        assert con.scalar(select(func.count()).select_from(RetrievalChunk)) >= 0
        with pytest.raises(ProgrammingError):
            con.execute(text("DELETE FROM doclens_service.retrieval_chunks"))
        con.rollback()
        with pytest.raises(ProgrammingError):
            con.execute(text("UPDATE doclens_service.revision_indexes SET chunk_count = 1"))
        con.rollback()
    with real_services.worker.connect() as con:
        with pytest.raises(ProgrammingError):  # Indexer appends complete sets; it never rewrites vectors.
            con.execute(text("UPDATE doclens_service.retrieval_chunks SET text = 'x'"))
        con.rollback()


def test_index_is_idempotent_and_search_is_exact_within_scope(api, headers, workspaces, case, real_services):
    alpha = workspaces["alpha"]
    source_id, revision_id = publish(api, headers, case, alpha, "atlas-owner")
    publish(api, headers, case, alpha, "atlas-owner", version="3.12")  # Same text, other release.
    assert index(case, revision_id) == "indexed"
    encoder = HashingEncoder()
    assert index(case, revision_id, encoder) == "exists" and encoder.encoded == 0
    with real_services.owner.connect() as con:
        marker = con.execute(select(RevisionIndex).where(RevisionIndex.revision_id == revision_id)).one()
        stored = con.scalar(select(func.count()).select_from(RetrievalChunk).where(RetrievalChunk.revision_id == revision_id))
    assert stored == marker.chunk_count >= 3

    response = search(api, headers, alpha, "atlas-viewer", top_k=20)
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["candidate_count"] == stored  # 3.12 rows and unindexed revisions are not candidates.
    assert {hit["source_id"] for hit in body["results"]} == {source_id}
    assert body["results"][0]["anchor"] == "uri" and body["search"] == "exact-cosine"
    # Exactness: identical order to brute-force cosine over the same filtered rows.
    query = HashingEncoder().encode(["file URI to path"], query=True)[0]
    with real_services.owner.connect() as con:
        rows = con.execute(select(RetrievalChunk.id, RetrievalChunk.embedding).where(
            RetrievalChunk.workspace_id == alpha, RetrievalChunk.version == "3.13")).all()
    brute = sorted(rows, key=lambda r: -sum(a * b for a, b in zip(query, r.embedding)))
    assert [hit["chunk_id"] for hit in body["results"]] == [str(r.id) for r in brute]
    for hit, row in zip(body["results"], brute):
        assert math.isclose(hit["score"], sum(a * b for a, b in zip(query, row.embedding)), abs_tol=1e-5)


@pytest.mark.parametrize("alias,status", [("boreal-owner", 404), ("outsider", 404)])
def test_non_members_cannot_search_a_workspace(alias, status, api, headers, workspaces, case):
    _, revision_id = publish(api, headers, case, workspaces["alpha"], "atlas-owner")
    index(case, revision_id)
    assert search(api, headers, workspaces["alpha"], alias).status_code == status
    assert api.post(f"/api/v1/workspaces/{workspaces['alpha']}/search",
                    json={"query": "q", "product": "python", "version": "3.13"}).status_code == 401


def test_identical_content_in_another_workspace_never_leaks(api, headers, workspaces, case):
    alpha_source, alpha_revision = publish(api, headers, case, workspaces["alpha"], "atlas-owner")
    beta_source, beta_revision = publish(api, headers, case, workspaces["beta"], "boreal-owner")
    index(case, alpha_revision), index(case, beta_revision)
    alpha_hits = search(api, headers, workspaces["alpha"], "dual-member", top_k=20).json()["results"]
    beta_hits = search(api, headers, workspaces["beta"], "dual-member", top_k=20).json()["results"]
    assert {h["source_id"] for h in alpha_hits} == {alpha_source}
    assert {h["source_id"] for h in beta_hits} == {beta_source}
    # Body scope injection is rejected rather than honoured.
    injected = search(api, headers, workspaces["alpha"], "atlas-viewer", workspace_id=str(workspaces["beta"]))
    assert injected.status_code == 422


def test_revocation_applies_inside_the_ranking_statement(api, headers, workspaces, case, real_services):
    alpha = workspaces["alpha"]
    _, revision_id = publish(api, headers, case, alpha, "atlas-owner")
    index(case, revision_id)
    identity = real_services.dev  # Resolve the viewer's real issuer/subject from its token.
    from doclens.access.tokens import TokenVerifier
    viewer = TokenVerifier(real_services.settings).verify(identity.token("atlas-viewer"))
    vector = HashingEncoder().encode(["file URI"], query=True)[0]
    with sessionmaker(real_services.runtime)() as session:
        count, hits = search_scope(session, workspace_id=alpha, issuer=viewer.issuer, subject=viewer.subject,
                                   query_vector=vector, product="python", version="3.13", top_k=5, index_id=CONFIG_ID)
        assert count >= 1 and hits
    with real_services.owner.begin() as con:
        con.execute(delete(Membership).where(Membership.workspace_id == alpha, Membership.role == "viewer"))
    with sessionmaker(real_services.runtime)() as session:
        # Even a caller that skipped the HTTP dependency gets no rows: no re-embedding needed.
        assert search_scope(session, workspace_id=alpha, issuer=viewer.issuer, subject=viewer.subject,
                            query_vector=vector, product="python", version="3.13", top_k=5,
                            index_id=CONFIG_ID) == (0, [])
    assert search(api, headers, alpha, "atlas-viewer").status_code == 404


def test_new_revision_replaces_old_chunks_only_after_complete_indexing(api, headers, workspaces, case):
    alpha = workspaces["alpha"]
    source_id, first = publish(api, headers, case, alpha, "atlas-owner", tag="first")
    index(case, first)
    assert "first" in search(api, headers, alpha, "atlas-viewer", query="fixture first").json()["results"][0]["text"]
    _, second = publish(api, headers, case, alpha, "atlas-owner", tag="second", source_id=source_id)
    assert second != first
    # Published but not yet indexed: old chunks are retired from search, never mixed.
    assert search(api, headers, alpha, "atlas-viewer").json()["candidate_count"] == 0
    index(case, second)
    hits = search(api, headers, alpha, "atlas-viewer", query="fixture second", top_k=20).json()["results"]
    assert hits and {h["revision_id"] for h in hits} == {str(second)}


def test_concurrent_indexers_commit_one_complete_set(api, headers, workspaces, case, real_services):
    _, revision_id = publish(api, headers, case, workspaces["alpha"], "atlas-owner")
    with ThreadPoolExecutor(2) as pool:
        outcomes = sorted(pool.map(lambda _: index(case, revision_id), range(2)))
    assert outcomes == ["exists", "indexed"]
    with real_services.owner.connect() as con:
        marker = con.execute(select(RevisionIndex).where(RevisionIndex.revision_id == revision_id)).one()
        assert con.scalar(select(func.count()).select_from(RetrievalChunk).where(
            RetrievalChunk.revision_id == revision_id)) == marker.chunk_count
