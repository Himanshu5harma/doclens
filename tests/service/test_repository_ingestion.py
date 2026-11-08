"""Actual PostgreSQL/Keycloak, with explicitly synthetic acquisition only."""

import hashlib
from uuid import UUID, uuid4

import pytest
from sqlalchemy import insert, select
from sqlalchemy.orm import sessionmaker

from doclens.service import source_adapters
from doclens.service.ingestion import run_job, utcnow
from doclens.service.ingestion_io import ArtifactStore, IngestionError, Snapshot
from doclens.service.models import Membership, SourceRevision, Workspace
from doclens.service.repository import COMMIT, REGISTRATION, SOURCE_URL, git_blob_sha

CODE = (b'# Synthetic repository ingestion fixture; not CPython evidence.\n'
        b'class TestNamedTemporaryFile:\n'
        b'    def test_fixture(self):\n'
        b'        # whitespace and full method preserved\n'
        b'        assert True\n')


@pytest.fixture
def repository_case(api, headers, real_services, tmp_path, monkeypatch):
    wid = uuid4()
    with real_services.owner.begin() as con:
        con.execute(insert(Workspace).values(id=wid, slug="repo-" + wid.hex, name="Synthetic repository fixture"))
        members = con.execute(select(Membership.principal_id, Membership.role).where(
            Membership.workspace_id == real_services.workspaces["atlas"])).all()
        con.execute(insert(Membership), [{"workspace_id": wid, "principal_id": p, "role": role} for p, role in members])
    metadata = source_adapters.source_metadata()
    monkeypatch.setattr(source_adapters, "source_metadata", lambda: {
        **metadata, "synthetic": True, "authority": "synthetic_test_fixture", "origin": "synthetic_fixture",
        "expected_raw_sha256": hashlib.sha256(CODE).hexdigest(), "expected_git_blob_sha1": git_blob_sha(CODE)})
    prefix = f"/api/v1/workspaces/{wid}"
    response = api.post(prefix + "/sources", headers=headers("atlas-owner"),
                        json={**REGISTRATION, "name": "Synthetic repository fixture"})
    assert response.status_code == 201
    store = api.app.state.artifacts = ArtifactStore(tmp_path / "artifacts")
    return {"prefix": prefix, "path": prefix + "/sources/" + response.json()["id"],
            "source_id": response.json()["id"], "store": store,
            "sessions": sessionmaker(real_services.worker, expire_on_commit=False)}


def enqueue(api, headers, case):
    response = api.post(case["path"] + "/sync", headers=headers("atlas-editor"), json={"request_key": str(uuid4())})
    assert response.status_code == 202
    return UUID(response.json()["id"])


def execute(case, job, content=CODE):
    return run_job(case["sessions"], case["store"], job,
                   fetcher=lambda source: Snapshot(content, source["url"], utcnow()))


def test_repository_registration_roles_and_version_cannot_be_overridden(api, headers, repository_case):
    case = repository_case
    for alias, status in (("atlas-viewer", 403), ("boreal-owner", 404), ("outsider", 404)):
        response = api.post(case["prefix"] + "/sources", headers=headers(alias), json=REGISTRATION)
        assert response.status_code == status
        assert api.post(case["path"] + "/sync", headers=headers(alias),
                        json={"request_key": str(uuid4())}).status_code == status
    for change in ({"version": "3.12"}, {"url": SOURCE_URL.replace(COMMIT, "main")}, {"synthetic": True}):
        response = api.post(case["prefix"] + "/sources", headers=headers("atlas-owner"), json=REGISTRATION | change)
        assert response.status_code == 422


def test_repository_uses_existing_jobs_and_scoped_artifacts_with_v2_metadata(api, headers, repository_case, real_services):
    case = repository_case
    job = enqueue(api, headers, case)
    assert execute(case, job) == "finished"
    revision = api.get(case["path"] + "/revision", headers=headers("atlas-viewer")).json()
    assert (revision["section_count"], revision["block_count"], revision["code_count"]) == (1, 1, 1)
    assert revision["raw_sha256"] == hashlib.sha256(CODE).hexdigest()
    record = api.get(revision["parsed_artifact_url"], headers=headers("atlas-viewer")).json()
    assert record["schema_version"] == "doclens-service-document-v2"
    source = record["source"]
    assert source["id"] == case["source_id"] and source["commit"] == COMMIT
    assert source["workspace_id"] == case["prefix"].split("/")[-1]
    assert source["version"] == "3.13" and source["source_release"] == "3.13.0"
    assert source["synthetic"] is True and source["authority"] == "synthetic_test_fixture"
    assert source["access"] == "workspace_membership" and source["collection_key"] == "python-file-processing"
    assert source["source_terms_url"] == REGISTRATION["source_terms_url"]
    assert record["provenance"]["git_blob_sha1"] == git_blob_sha(CODE)
    block = record["document"]["sections"][0]["blocks"][0]
    assert block["text"].encode() == b"".join(CODE.splitlines(keepends=True)[1:])
    paths = [case["prefix"] + f"/jobs/{job}", case["path"] + "/jobs", case["path"] + "/revision",
             revision["raw_artifact_url"], revision["parsed_artifact_url"]]
    for path in paths:
        denied = api.get(path, headers=headers("boreal-owner"))
        assert denied.status_code == 404 and denied.json() == {"detail": "Resource not found."}
        forged = path.replace(case["prefix"], f"/api/v1/workspaces/{real_services.workspaces['boreal']}")
        assert api.get(forged, headers=headers("boreal-owner")).status_code == 404
    assert execute(case, job, b"must not fetch again") == "ignored"
    with case["sessions"]() as session:
        assert len(session.scalars(select(SourceRevision).where(SourceRevision.job_id == job)).all()) == 1


def test_repository_bad_refresh_and_rate_limit_preserve_previous_ready_revision(api, headers, repository_case):
    case = repository_case
    assert execute(case, enqueue(api, headers, case)) == "finished"
    previous = api.get(case["path"] + "/revision", headers=headers("atlas-viewer")).json()
    malformed = enqueue(api, headers, case)
    assert execute(case, malformed, b"# Synthetic fixture: selected class missing\n") == "repository_parse"
    result = api.get(case["prefix"] + f"/jobs/{malformed}", headers=headers("atlas-viewer")).json()
    assert result["status"] == "failed" and result["attempts"] == 1
    limited = enqueue(api, headers, case)
    def rate_limit(source):
        raise IngestionError("repository_rate_limit")
    assert run_job(case["sessions"], case["store"], limited, fetcher=rate_limit) == "repository_rate_limit"
    result = api.get(case["prefix"] + f"/jobs/{limited}", headers=headers("atlas-viewer")).json()
    assert result["status"] == "failed" and result["attempts"] == 1
    assert api.get(case["path"] + "/revision", headers=headers("atlas-viewer")).json() == previous
