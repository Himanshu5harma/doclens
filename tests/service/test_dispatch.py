"""Actual PostgreSQL dispatch/worker concurrency and publisher interruption."""

from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
import time
from uuid import UUID, uuid4

import pytest
from sqlalchemy import select, update
from sqlalchemy.orm import sessionmaker

from doclens.service.ingestion import claim_job, dispatch_once, run_job, utcnow
from doclens.service.ingestion_io import ArtifactStore, IngestionError
from doclens.service.models import DispatchIntent, IngestionJob


@pytest.fixture
def dispatch_case(real_services, api, headers, tmp_path):
    pytest.importorskip("celery", reason="Use the actual worker DB timeout configuration.")
    from pydantic import SecretStr
    from doclens.service.settings import WorkerSettings
    from doclens.service.worker import database_engine
    settings = WorkerSettings(_env_file=real_services.dev.ROOT / ".env.worker.local").model_copy(update={
        "database_url": SecretStr(real_services.dev.database_url("doclens_worker", real_services.owner.url.database)
                                  .render_as_string(hide_password=False))})
    engine = database_engine(settings)
    sessions = sessionmaker(engine, expire_on_commit=False)
    created = []
    auth = headers("atlas-editor")
    prefix = f"/api/v1/workspaces/{real_services.workspaces['atlas']}/sources"

    def new_job():
        source = api.post(prefix, headers=auth, json={"name": "Synthetic dispatch fixture",
            "product": "python", "version": "3.13",
            "url": f"https://docs.python.org/3.13/library/dispatch-{uuid4().hex}.html",
            "source_terms_url": "https://docs.python.org/3.13/license.html"})
        assert source.status_code == 201
        job = api.post(prefix + "/" + source.json()["id"] + "/sync", headers=auth,
                       json={"request_key": str(uuid4())})
        assert job.status_code == 202
        identifier = UUID(job.json()["id"])
        created.append(identifier)
        return identifier

    try:
        yield sessions, new_job, ArtifactStore(tmp_path / "artifacts")
    finally:
        with real_services.owner.begin() as con:
            con.execute(update(IngestionJob).where(IngestionJob.id.in_(created),
                IngestionJob.status.in_(("queued", "running", "retry_wait"))).values(
                    status="failed", stage="failed", lease_token=None, lease_expires_at=None))
        engine.dispose()


def test_slow_dispatch_batch_does_not_block_production_worker_claims(dispatch_case):
    sessions, new_job, _ = dispatch_case
    identifiers = [new_job() for _ in range(4)]
    futures = []
    with ThreadPoolExecutor(max_workers=4) as executor:
        def slow_send(job_id):
            futures.append(executor.submit(claim_job, sessions, UUID(job_id)))
            time.sleep(2)  # Each send is bounded; the whole batch exceeds the actual 5 s lock timeout.
        assert dispatch_once(sessions, slow_send)["sent"] == 4
        claims = [future.result(timeout=8) for future in futures]
    assert {claim.job_id for claim in claims} == set(identifiers)
    with sessions() as session:
        jobs = session.scalars(select(IngestionJob).where(IngestionJob.id.in_(identifiers))).all()
        assert all(job.status == "running" and job.attempts == 1 for job in jobs)


def test_interrupted_dispatch_reservation_is_replayed_after_expiry(dispatch_case, real_services):
    sessions, new_job, _ = dispatch_case
    identifier = new_job()
    def interrupted(job_id): raise KeyboardInterrupt
    with pytest.raises(KeyboardInterrupt): dispatch_once(sessions, interrupted)
    with sessions() as session:
        intent = session.get(DispatchIntent, identifier)
        assert intent.deliveries == 1 and intent.next_dispatch_at > utcnow()
        assert session.get(IngestionJob, identifier).status == "queued"
    assert dispatch_once(sessions, lambda job_id: pytest.fail("reservation bypassed"))["sent"] == 0
    with real_services.owner.begin() as con:
        con.execute(update(DispatchIntent).where(DispatchIntent.job_id == identifier)
                    .values(next_dispatch_at=utcnow() - timedelta(seconds=1)))
    sent = []
    assert dispatch_once(sessions, sent.append)["sent"] == 1
    assert sent == [str(identifier)]


@pytest.mark.parametrize("publisher_reports_error", [False, True])
def test_publisher_completion_preserves_worker_retry_schedule(publisher_reports_error, dispatch_case):
    sessions, new_job, store = dispatch_case
    identifier = new_job()
    def transient(source): raise IngestionError("http_temporary", retryable=True)
    def fast_worker(job_id):
        assert run_job(sessions, store, UUID(job_id), fetcher=transient) == "http_temporary"
        if publisher_reports_error: raise RuntimeError("Synthetic lost publish acknowledgement")
    counts = dispatch_once(sessions, fast_worker)
    assert counts["broker_errors" if publisher_reports_error else "sent"] == 1
    with sessions() as session:
        job, intent = session.get(IngestionJob, identifier), session.get(DispatchIntent, identifier)
        assert job.status == "retry_wait" and job.attempts == 1
        assert intent.next_dispatch_at == job.available_at
        assert intent.last_error_code is None


def test_late_publish_result_cannot_overwrite_newer_delivery(dispatch_case, real_services):
    sessions, new_job, _ = dispatch_case
    identifier = new_job()
    def broken_send(job_id): raise RuntimeError("Synthetic broker failure")
    def late_success(job_id):
        # Controlled expiry while the original publisher is still returning.
        with real_services.owner.begin() as con:
            con.execute(update(DispatchIntent).where(DispatchIntent.job_id == identifier)
                        .values(next_dispatch_at=utcnow() - timedelta(seconds=1)))
        assert dispatch_once(sessions, broken_send)["broker_errors"] == 1
    assert dispatch_once(sessions, late_success)["sent"] == 1
    with sessions() as session:
        intent = session.get(DispatchIntent, identifier)
        assert intent.deliveries == 2 and intent.last_error_code == "broker_unavailable"
