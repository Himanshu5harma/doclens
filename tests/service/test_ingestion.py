"""Real PostgreSQL/Keycloak behavior, using labeled acquisition fixtures here.

Separate worker tests exercise actual Celery/Redis process delivery.
"""

from datetime import timedelta
import hashlib
import json
from uuid import UUID, uuid4

import pytest
from sqlalchemy import event, func, insert, select, text, update
from sqlalchemy.exc import IntegrityError, OperationalError, ProgrammingError
from sqlalchemy.orm import sessionmaker

from doclens.service.ingestion import (LostClaim, claim_job, dispatch_once, progress,
                                      publish_revision, run_job, utcnow)
from doclens.service.ingestion_io import ArtifactStore, IngestionError, Snapshot
from doclens.service.models import (DispatchIntent, IngestionJob, Membership, RegisteredSource,
                                    SourcePublication, SourceRevision)

HTML = b'<main><section id="fixture"><h1>Synthetic ingestion fixture</h1><p>Reference.</p><pre>if True:\n    print("ok")\n</pre></section></main>'


def enqueue(api, headers, case, key=None):
    response = api.post(case["path"] + "/sync", headers=headers("atlas-editor"),
                        json={"request_key": str(key or uuid4())})
    assert response.status_code == 202, response.text
    return response.json()


def snapshot(source):
    return Snapshot(HTML, source["url"], utcnow())


def execute(case, job, fetcher=snapshot):
    return run_job(case["sessions"], case["store"], UUID(job["id"]), fetcher=fetcher)


def job_value(api, headers, case, job):
    return api.get(case["prefix"] + "/jobs/" + job["id"], headers=headers("atlas-viewer")).json()


def make_due(real_services, job):
    with real_services.owner.begin() as con:
        con.execute(update(IngestionJob).where(IngestionJob.id == UUID(job["id"]))
                    .values(available_at=utcnow() - timedelta(seconds=1)))
        con.execute(update(DispatchIntent).where(DispatchIntent.job_id == UUID(job["id"]))
                    .values(next_dispatch_at=utcnow() - timedelta(seconds=1)))


def test_sync_is_durable_idempotent_and_one_active_job_per_source(api, headers, ingestion_case, real_services):
    case = ingestion_case
    first = enqueue(api, headers, case)
    assert (first["status"], first["stage"], first["attempts"]) == ("queued", "queued", 0)
    again = enqueue(api, headers, case, first["request_key"])
    assert again == first
    conflict = api.post(case["path"] + "/sync", headers=headers("atlas-owner"), json={"request_key": str(uuid4())})
    assert conflict.status_code == 409
    with real_services.runtime.connect() as con:
        assert con.scalar(select(func.count()).select_from(DispatchIntent).where(DispatchIntent.job_id == UUID(first["id"]))) == 1
    # No dispatcher/worker is involved, and nothing has been fetched.
    assert list(case["store"].root.rglob("*.raw")) == []
    assert api.get(case["path"] + "/jobs", headers=headers("atlas-viewer")).json() == [first]
    assert api.get(case["path"] + "/revision", headers=headers("atlas-owner")).status_code == 404


@pytest.mark.parametrize("alias,status", [("atlas-viewer", 403), ("boreal-owner", 404), ("outsider", 404)])
def test_sync_scope_and_role_denials(alias, status, api, headers, ingestion_case, real_services):
    case = ingestion_case
    response = api.post(case["path"] + "/sync", headers=headers(alias), json={"request_key": str(uuid4())})
    assert response.status_code == status
    with real_services.runtime.connect() as con:
        assert con.scalar(select(func.count()).select_from(IngestionJob).where(IngestionJob.source_id == UUID(case["source_id"]))) == 0


def test_body_scope_overrides_are_rejected(api, headers, ingestion_case):
    response = api.post(ingestion_case["path"] + "/sync", headers=headers("atlas-owner"),
                        json={"request_key": str(uuid4()), "workspace_id": str(uuid4())})
    assert response.status_code == 422


def test_failed_dispatch_intent_insert_rolls_back_the_whole_http_registration(api, headers, ingestion_case):
    case = ingestion_case
    engine = api.app.state.sessions.kw["bind"]
    def interrupt(connection, cursor, statement, parameters, context, many):
        if "INSERT INTO doclens_service.dispatch_intents" in statement:
            raise OperationalError(None, None, RuntimeError("fixture-secret interrupted transaction"))
    event.listen(engine, "before_cursor_execute", interrupt)
    try:
        response = api.post(case["path"] + "/sync", headers=headers("atlas-owner"), json={"request_key": str(uuid4())})
        assert response.status_code == 503 and "fixture-secret" not in response.text
    finally:
        event.remove(engine, "before_cursor_execute", interrupt)
    with case["sessions"]() as session:
        assert session.scalar(select(func.count()).select_from(IngestionJob).where(IngestionJob.source_id == UUID(case["source_id"]))) == 0
    assert enqueue(api, headers, case)["status"] == "queued"


def test_success_preserves_provenance_structure_and_artifact_integrity(api, headers, ingestion_case):
    case = ingestion_case
    job = enqueue(api, headers, case)
    assert execute(case, job) == "finished"
    result = job_value(api, headers, case, job)
    assert result["status"] == "succeeded" and result["attempts"] == 1 and result["revision_id"]
    revision = api.get(case["path"] + "/revision", headers=headers("atlas-viewer")).json()
    assert (revision["section_count"], revision["block_count"], revision["code_count"]) == (1, 2, 1)
    assert revision["raw_sha256"] == hashlib.sha256(HTML).hexdigest()
    assert "raw_key" not in revision and "parsed_key" not in revision
    raw = api.get(revision["raw_artifact_url"], headers=headers("atlas-viewer"))
    parsed = api.get(revision["parsed_artifact_url"], headers=headers("atlas-viewer"))
    assert raw.content == HTML and raw.headers["content-type"] == "application/octet-stream"
    assert raw.headers["x-content-type-options"] == "nosniff" and "attachment" in raw.headers["content-disposition"]
    assert hashlib.sha256(parsed.content).hexdigest() == revision["parsed_sha256"]
    record = parsed.json()
    assert record["schema_version"] == "doclens-service-document-v1"
    assert record["source"]["id"] == case["source_id"]
    for key in ("workspace_id", "product", "version", "url", "source_terms_url"):
        assert record["source"][key] == case["source"][key]
    section = record["document"]["sections"][0]
    assert section["anchor"] == "fixture" and section["heading_path"] == ["Synthetic ingestion fixture"]
    assert section["blocks"][1]["text"] == 'if True:\n    print("ok")\n'
    assert all(block["url"].startswith(case["source"]["url"]) for block in section["blocks"])
    # Repeated delivery and repeated request do not generate another snapshot/revision.
    assert execute(case, job, fetcher=lambda source: pytest.fail("duplicate fetched")) == "ignored"
    assert enqueue(api, headers, case, job["request_key"])["id"] == job["id"]


def test_job_revision_and_artifact_ids_do_not_bypass_workspace_scope(api, headers, ingestion_case, real_services):
    case = ingestion_case
    job = enqueue(api, headers, case); execute(case, job)
    revision = api.get(case["path"] + "/revision", headers=headers("atlas-owner")).json()
    paths = [case["prefix"] + "/jobs/" + job["id"], case["path"] + "/jobs", case["path"] + "/revision",
             revision["raw_artifact_url"], revision["parsed_artifact_url"]]
    for path in paths:
        assert api.get(path, headers=headers("boreal-owner")).status_code == 404
        substituted = path.replace(str(real_services.workspaces["atlas"]), str(real_services.workspaces["boreal"]))
        response = api.get(substituted, headers=headers("boreal-owner"))
        assert response.status_code == 404 and "Synthetic" not in response.text


def test_current_membership_removal_blocks_existing_artifact_token(api, headers, ingestion_case, real_services):
    case = ingestion_case
    job = enqueue(api, headers, case); execute(case, job)
    revision = api.get(case["path"] + "/revision", headers=headers("atlas-owner")).json()
    auth = headers("atlas-viewer")
    from doclens.service.models import Principal
    identity = api.app.state.verifier.verify(auth["Authorization"].removeprefix("Bearer "))
    with real_services.owner.begin() as con:
        pid = con.scalar(select(Principal.id).where(Principal.subject == identity.subject, Principal.issuer == identity.issuer))
        con.execute(text("DELETE FROM doclens_service.memberships WHERE workspace_id=:wid AND principal_id=:pid"),
                    {"wid": real_services.workspaces["atlas"], "pid": pid})
    try:
        assert api.get(revision["raw_artifact_url"], headers=auth).status_code == 404
        assert api.get(case["prefix"] + "/jobs/" + job["id"], headers=auth).status_code == 404
    finally:
        with real_services.owner.begin() as con:
            con.execute(insert(Membership).values(workspace_id=real_services.workspaces["atlas"], principal_id=pid, role="viewer"))


def test_transient_errors_back_off_and_stop_after_three_attempts(api, headers, ingestion_case, real_services):
    case = ingestion_case; job = enqueue(api, headers, case)
    def interrupted(source): raise IngestionError("network_error", retryable=True)
    for attempt in range(1, 4):
        execute(case, job, interrupted)
        value = job_value(api, headers, case, job)
        assert value["attempts"] == attempt
        assert value["status"] == ("retry_wait" if attempt < 3 else "failed")
        if attempt < 3:
            assert execute(case, job, interrupted) == "ignored"  # Backoff not silently bypassed.
            make_due(real_services, job)
    assert execute(case, job, interrupted) == "ignored"
    assert api.get(case["path"] + "/revision", headers=headers("atlas-owner")).status_code == 404


def test_failed_refresh_keeps_previous_ready_revision_and_redacts_errors(api, headers, ingestion_case, caplog):
    case = ingestion_case; good = enqueue(api, headers, case); execute(case, good)
    previous = api.get(case["path"] + "/revision", headers=headers("atlas-owner")).json()
    bad = enqueue(api, headers, case)
    def broken(source): raise RuntimeError("Bearer fixture-secret provider body DSN password")
    execute(case, bad, broken)
    result = job_value(api, headers, case, bad)
    assert result["error_code"] == "internal_error" and "fixture-secret" not in json.dumps(result) + caplog.text
    assert api.get(case["path"] + "/revision", headers=headers("atlas-owner")).json() == previous


def test_interruption_between_artifact_writes_cannot_publish_partial_revision(api, headers, ingestion_case, monkeypatch):
    case = ingestion_case; job = enqueue(api, headers, case)
    original = case["store"].put
    def interrupted(prefix, content, kind):
        if kind == "parsed": raise OSError("fixture-secret interrupted write")
        return original(prefix, content, kind)
    monkeypatch.setattr(case["store"], "put", interrupted)
    execute(case, job)
    assert len(list(case["store"].root.rglob("*.raw"))) == 1
    assert not list(case["store"].root.rglob("*.parsed"))
    assert api.get(case["path"] + "/revision", headers=headers("atlas-owner")).status_code == 404
    with case["sessions"]() as session:
        assert session.scalar(select(func.count()).select_from(SourceRevision).where(SourceRevision.job_id == UUID(job["id"]))) == 0


def test_publication_transaction_rollback_keeps_old_pointer_and_no_new_revision(api, headers, ingestion_case):
    case = ingestion_case; first = enqueue(api, headers, case); execute(case, first)
    previous = api.get(case["path"] + "/revision", headers=headers("atlas-owner")).json()
    second = enqueue(api, headers, case)
    engine = case["sessions"].kw["bind"]
    def interrupt(connection, cursor, statement, parameters, context, many):
        if "INSERT INTO doclens_service.source_publications" in statement:
            raise OperationalError(None, None, RuntimeError("fixture-secret interrupted publication"))
    event.listen(engine, "before_cursor_execute", interrupt)
    try: execute(case, second)
    finally: event.remove(engine, "before_cursor_execute", interrupt)
    assert api.get(case["path"] + "/revision", headers=headers("atlas-owner")).json() == previous
    with case["sessions"]() as session:
        assert session.scalar(select(func.count()).select_from(SourceRevision).where(SourceRevision.job_id == UUID(second["id"]))) == 0
    assert job_value(api, headers, case, second)["error_code"] == "internal_error"


def test_expired_claim_recovery_fences_stale_worker(api, headers, ingestion_case):
    case = ingestion_case; job = enqueue(api, headers, case)
    old = claim_job(case["sessions"], UUID(job["id"]))
    replacement = claim_job(case["sessions"], UUID(job["id"]), now=utcnow() + timedelta(seconds=121))
    assert replacement and replacement.token != old.token
    with pytest.raises(LostClaim): progress(case["sessions"], old, "publishing")
    with pytest.raises(LostClaim): publish_revision(case["sessions"], old, None)
    assert claim_job(case["sessions"], UUID(job["id"])) is None


def test_permission_is_rechecked_before_claim_and_publication(api, headers, ingestion_case, real_services):
    case = ingestion_case; job = enqueue(api, headers, case)
    wid, pid = real_services.workspaces["atlas"], UUID(job["requested_by"])
    def role(value):
        with real_services.owner.begin() as con:
            con.execute(update(Membership).where(Membership.workspace_id == wid, Membership.principal_id == pid).values(role=value))
    role("viewer")
    try:
        assert execute(case, job, fetcher=lambda source: pytest.fail("revoked job acquired content")) == "ignored"
        assert job_value(api, headers, case, job)["error_code"] == "access_revoked"
    finally: role("editor")
    pending = enqueue(api, headers, case)
    def revoke_after_fetch(source):
        role("viewer")
        return snapshot(source)
    try:
        execute(case, pending, revoke_after_fetch)
        assert job_value(api, headers, case, pending)["error_code"] == "access_revoked"
        assert api.get(case["path"] + "/revision", headers=headers("atlas-owner")).status_code == 404
    finally: role("editor")


def test_parse_failure_is_terminal_and_does_not_publish(api, headers, ingestion_case):
    case = ingestion_case; job = enqueue(api, headers, case)
    assert execute(case, job, lambda source: Snapshot(b"<html>unsupported fixture</html>", source["url"], utcnow())) == "parse_error"
    value = job_value(api, headers, case, job)
    assert value["status"] == "failed" and value["attempts"] == 1
    assert api.get(case["path"] + "/revision", headers=headers("atlas-owner")).status_code == 404


def test_repeated_worker_loss_has_a_finite_attempt_budget(api, headers, ingestion_case, real_services):
    case = ingestion_case; job = enqueue(api, headers, case)
    for attempt in range(1, 4):
        assert claim_job(case["sessions"], UUID(job["id"]))
        with real_services.owner.begin() as con:
            con.execute(update(IngestionJob).where(IngestionJob.id == UUID(job["id"]))
                        .values(lease_expires_at=utcnow() - timedelta(seconds=1)))
        make_due(real_services, job)
        dispatch_once(case["sessions"], lambda job_id: None)
    result = job_value(api, headers, case, job)
    assert result["status"] == "failed" and result["attempts"] == 3 and result["error_code"] == "worker_lost"
    assert claim_job(case["sessions"], UUID(job["id"])) is None


def test_dispatch_reconciles_unsent_or_lost_messages_and_bounds_delivery(api, headers, ingestion_case, real_services):
    case = ingestion_case; job = enqueue(api, headers, case)
    def broken_send(job_id): raise RuntimeError("redis://:fixture-secret@broker")
    result = dispatch_once(case["sessions"], broken_send)
    assert result["broker_errors"] >= 1
    queued = job_value(api, headers, case, job)
    assert queued["status"] == "queued" and queued["delivery_attempts"] == 1
    assert queued["dispatch_error_code"] == "broker_unavailable"
    assert "durable job" in queued["dispatch_error_message"] and "fixture-secret" not in json.dumps(queued)
    sent = []
    make_due(real_services, job)
    dispatch_once(case["sessions"], sent.append)
    assert job["id"] in sent
    make_due(real_services, job)  # Simulate a successful send lost before any worker claims it.
    dispatch_once(case["sessions"], sent.append)
    assert sent.count(job["id"]) == 2
    with real_services.owner.begin() as con:
        con.execute(update(DispatchIntent).where(DispatchIntent.job_id == UUID(job["id"]))
                    .values(deliveries=20, next_dispatch_at=utcnow(), last_error_code="broker_unavailable"))
    dispatch_once(case["sessions"], lambda job_id: pytest.fail("delivery limit bypassed"))
    terminal = job_value(api, headers, case, job)
    assert terminal["error_code"] == "dispatch_exhausted"
    assert terminal["next_dispatch_at"] is None and terminal["dispatch_error_message"] is None


def test_revision_artifact_corruption_is_reported_without_serving_bytes(api, headers, ingestion_case):
    case = ingestion_case; job = enqueue(api, headers, case); execute(case, job)
    revision = api.get(case["path"] + "/revision", headers=headers("atlas-owner")).json()
    raw = next(case["store"].root.rglob("*.raw")); raw.write_bytes(b"x" * len(HTML))
    response = api.get(revision["raw_artifact_url"], headers=headers("atlas-viewer"))
    assert response.status_code == 503 and "failed integrity" in response.text


def test_composite_foreign_keys_reject_cross_workspace_jobs(api, headers, ingestion_case, real_services):
    case = ingestion_case; job = enqueue(api, headers, case)
    with pytest.raises(IntegrityError):
        with real_services.runtime.begin() as con:
            con.execute(insert(IngestionJob).values(id=uuid4(), workspace_id=real_services.workspaces["boreal"],
                source_id=UUID(case["source_id"]), requested_by=UUID(job["requested_by"]),
                request_key=uuid4(), status="queued", stage="queued", attempts=0))


def test_api_and_worker_database_privileges_remain_separate(real_services):
    for engine, statements in [(real_services.runtime, ["UPDATE doclens_service.ingestion_jobs SET stage='queued'",
                            "DELETE FROM doclens_service.source_revisions"]),
                              (real_services.worker, ["UPDATE doclens_service.memberships SET role='owner'",
                            "DELETE FROM doclens_service.sources", "UPDATE doclens_service.source_revisions SET title='bad'"])]:
        for statement in statements:
            with pytest.raises(ProgrammingError) as error:
                with engine.begin() as con: con.execute(text(statement))
            assert error.value.orig.sqlstate == "42501"
