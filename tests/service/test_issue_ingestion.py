"""Actual PostgreSQL/Keycloak, with a reviewed frozen local issue input."""

import hashlib
from pathlib import Path
from uuid import UUID, uuid4

import pytest
from sqlalchemy import delete, insert, select
from sqlalchemy.orm import sessionmaker

from doclens.service.ingestion import run_job
from doclens.service.ingestion_io import ArtifactStore
from doclens.service.issue_export import CURATION_PATH, REGISTRATION, EXPECTED_SHA256
from doclens.service.models import Membership, SourceRevision, Workspace

CONTENT = (Path(__file__).resolve().parents[2] / CURATION_PATH).read_bytes()


@pytest.fixture
def issue_case(api, headers, real_services, tmp_path):
    wid = uuid4()
    with real_services.owner.begin() as con:
        con.execute(insert(Workspace).values(id=wid, slug="issue-" + wid.hex, name="Issue export verification"))
        rows = con.execute(select(Membership.principal_id, Membership.role).where(
            Membership.workspace_id == real_services.workspaces["atlas"])).all()
        con.execute(insert(Membership), [{"workspace_id": wid, "principal_id": p, "role": r} for p, r in rows])
    prefix = f"/api/v1/workspaces/{wid}"
    response = api.post(prefix + "/sources", headers=headers("atlas-owner"), json=REGISTRATION)
    assert response.status_code == 201
    store = api.app.state.artifacts = ArtifactStore(tmp_path / "artifacts")
    exports = tmp_path / "exports"
    key, _ = ArtifactStore(exports).put("reviewed", CONTENT, "raw")
    try:
        yield {"prefix": prefix, "path": prefix + "/sources/" + response.json()["id"],
               "source_id": response.json()["id"], "store": store, "exports": exports, "export_file": exports / key,
               "sessions": sessionmaker(real_services.worker, expire_on_commit=False)}
    finally:
        # The session-scoped disposable DB retains rows until teardown, but later
        # tests must not inherit memberships introduced by this function fixture.
        with real_services.owner.begin() as con:
            con.execute(delete(Membership).where(Membership.workspace_id == wid))


def enqueue(api, headers, case, key=None):
    response = api.post(case["path"] + "/sync", headers=headers("atlas-editor"), json={"request_key": str(key or uuid4())})
    assert response.status_code == 202
    return response.json()


def execute(case, job):
    return run_job(case["sessions"], case["store"], UUID(job["id"]), export_root=case["exports"])


def test_historical_issue_registration_and_sync_enforce_roles_and_release(api, headers, issue_case):
    case = issue_case
    for alias, status in (("atlas-viewer", 403), ("boreal-owner", 404), ("outsider", 404)):
        assert api.post(case["prefix"] + "/sources", headers=headers(alias), json=REGISTRATION).status_code == status
        assert api.post(case["path"] + "/sync", headers=headers(alias), json={"request_key": str(uuid4())}).status_code == status
    for change in ({"version": "3.13"}, {"document_type": "reference"}, {"export_root": "/fixture-secret"}):
        r = api.post(case["prefix"] + "/sources", headers=headers("atlas-owner"), json=REGISTRATION | change)
        assert r.status_code == 422 and r.json() == {"detail": "Invalid request."}


def test_issue_job_preserves_historical_provenance_locations_and_scope(api, headers, issue_case, real_services):
    case = issue_case; job = enqueue(api, headers, case)
    assert enqueue(api, headers, case, job["request_key"])["id"] == job["id"]
    assert execute(case, job) == "finished"
    revision = api.get(case["path"] + "/revision", headers=headers("atlas-viewer")).json()
    assert (revision["section_count"], revision["block_count"], revision["code_count"]) == (4, 4, 0)
    assert revision["raw_sha256"] == EXPECTED_SHA256 == hashlib.sha256(CONTENT).hexdigest()
    parsed_response = api.get(revision["parsed_artifact_url"], headers=headers("atlas-viewer"))
    assert hashlib.sha256(parsed_response.content).hexdigest() == revision["parsed_sha256"]
    record = parsed_response.json()
    assert record["schema_version"] == "doclens-service-document-v3"
    source = record["source"]
    assert source["id"] == case["source_id"] and source["version"] == "3.8"
    assert source["workspace_id"] == case["prefix"].split("/")[-1]
    assert source["synthetic"] is False and source["content_mode"] == "curator_summaries"
    assert source["applicability"] == "historical_context_only" and source["current_release_guidance"] is False
    assert source["authority"] == "curated_historical_issue" and source["access"] == "workspace_membership"
    assert source["comment_timestamps_complete"] is False and source["independent_review"] is False
    assert record["document"]["sections"][1]["location"]["created_at"] is None
    assert record["document"]["sections"][2]["url"].endswith("#issuecomment-1093914527")
    raw = api.get(revision["raw_artifact_url"], headers=headers("atlas-viewer"))
    assert raw.content == CONTENT and "attachment" in raw.headers["content-disposition"]
    for path in (case["path"], case["path"] + "/revision", case["prefix"] + "/jobs/" + job["id"],
                 revision["raw_artifact_url"], revision["parsed_artifact_url"]):
        assert api.get(path, headers=headers("boreal-owner")).status_code == 404
        forged = path.replace(case["prefix"], f"/api/v1/workspaces/{real_services.workspaces['boreal']}")
        assert api.get(forged, headers=headers("boreal-owner")).status_code == 404
    assert execute(case, job) == "ignored"
    with case["sessions"]() as session:
        assert len(session.scalars(select(SourceRevision).where(SourceRevision.job_id == UUID(job["id"]))).all()) == 1


def test_tampered_or_missing_refresh_keeps_previous_ready_issue_revision(api, headers, issue_case):
    case = issue_case
    assert execute(case, enqueue(api, headers, case)) == "finished"
    previous = api.get(case["path"] + "/revision", headers=headers("atlas-viewer")).json()
    case["export_file"].write_bytes(CONTENT.replace(b'3.8', b'3.9'))
    bad = enqueue(api, headers, case)
    assert execute(case, bad) == "issue_export_invalid"
    state = api.get(case["prefix"] + "/jobs/" + bad["id"], headers=headers("atlas-viewer")).json()
    assert state["status"] == "failed" and state["attempts"] == 1 and str(case["exports"]) not in state["error_message"]
    assert api.get(case["path"] + "/revision", headers=headers("atlas-viewer")).json() == previous
    case["export_file"].unlink()
    missing = enqueue(api, headers, case)
    assert execute(case, missing) == "issue_export_unavailable"
    assert api.get(case["path"] + "/revision", headers=headers("atlas-viewer")).json() == previous
