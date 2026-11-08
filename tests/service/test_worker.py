"""Opt-in real Redis/Celery process checks with labeled synthetic documents."""

from datetime import timedelta
import os
from pathlib import Path
import signal
import subprocess
import sys
import time
from uuid import UUID, uuid4

import pytest
pytest.importorskip("celery", reason="Install the optional worker extra for broker/process checks.")
redis = pytest.importorskip("redis")
from pydantic import SecretStr
from sqlalchemy import func, select, update

from doclens.service.ingestion import dispatch_once, utcnow
from doclens.service.models import DispatchIntent, IngestionJob, RegisteredSource, SourceRevision
from doclens.service.settings import WorkerSettings
from doclens.service.worker import create_worker, sender


class Harness:
    def __init__(self, real, case, root):
        local = WorkerSettings(_env_file=real.dev.ROOT / ".env.worker.local")
        self.settings = local.model_copy(update={
            "database_url": SecretStr(real.dev.database_url("doclens_worker", real.owner.url.database).render_as_string(hide_password=False)),
            "artifact_root": case["store"].root, "queue": "stage2-test-" + uuid4().hex})
        self.app = create_worker(self.settings)
        self.log = root / "worker.log"
        self.processes = []

    def start(self):
        env = {**os.environ, "DOCLENS_DATABASE_URL": self.settings.database_url.get_secret_value(),
               "DOCLENS_BROKER_URL": self.settings.broker_url.get_secret_value(),
               "DOCLENS_ARTIFACT_ROOT": str(self.settings.artifact_root), "DOCLENS_QUEUE": self.settings.queue}
        with self.log.open("ab") as stream:
            process = subprocess.Popen([sys.executable, str(Path(__file__).with_name("fixture_worker.py"))],
                env=env, stdout=stream, stderr=subprocess.STDOUT, start_new_session=True)
        self.processes.append(process)
        return process

    def stop(self, process, *, crash=False):
        if process.poll() is None:
            os.killpg(process.pid, signal.SIGKILL if crash else signal.SIGTERM)
            try:
                process.wait(timeout=8)
            except subprocess.TimeoutExpired:
                os.killpg(process.pid, signal.SIGKILL)
                process.wait(timeout=3)

    def cleanup(self):
        for process in self.processes: self.stop(process)
        # Remove only this generated queue's isolated key prefix, never FLUSHDB.
        client = redis.Redis.from_url(self.settings.broker_url.get_secret_value(), socket_timeout=2)
        keys = list(client.scan_iter(match=f"doclens:{self.settings.queue}:*", count=100))
        if keys: client.delete(*keys)
        client.close()
        if self.log.exists():
            text = self.log.read_text()
            for secret in (self.settings.database_url.get_secret_value(),
                           self.settings.broker_url.get_secret_value().split(":", 2)[2].split("@")[0]):
                assert secret not in text


@pytest.fixture
def worker_harness(real_services, ingestion_case, tmp_path):
    if os.environ.get("DOCLENS_RUN_WORKER_INTEGRATION") != "1":
        pytest.skip("Set DOCLENS_RUN_WORKER_INTEGRATION=1 with PostgreSQL/Keycloak/Redis prepared.")
    harness = Harness(real_services, ingestion_case, tmp_path)
    try:
        client = redis.Redis.from_url(harness.settings.broker_url.get_secret_value(), socket_timeout=2)
        assert client.ping()
        client.close()
        yield harness
    finally:
        harness.cleanup()


def enqueue(api, headers, case):
    response = api.post(case["path"] + "/sync", headers=headers("atlas-owner"), json={"request_key": str(uuid4())})
    assert response.status_code == 202
    return response.json()


def value(case, job):
    with case["sessions"]() as session:
        return session.get(IngestionJob, UUID(job["id"]))


def wait_for(predicate, seconds=20):
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        result = predicate()
        if result: return result
        time.sleep(0.1)
    pytest.fail("Bounded real-worker observation timed out; inspect its local fixture log.")


def make_due(real, job, *, expire=False):
    with real.owner.begin() as con:
        values = {"available_at": utcnow() - timedelta(seconds=1)}
        if expire: values["lease_expires_at"] = utcnow() - timedelta(seconds=1)
        con.execute(update(IngestionJob).where(IngestionJob.id == UUID(job["id"])).values(**values))
        con.execute(update(DispatchIntent).where(DispatchIntent.job_id == UUID(job["id"]))
                    .values(next_dispatch_at=utcnow() - timedelta(seconds=1)))


def test_real_worker_routes_repository_job_and_preserves_v2_locations(api, headers, ingestion_case, real_services, worker_harness):
    from doclens.service.repository import COMMIT, REGISTRATION, SOURCE_URL
    case, harness = ingestion_case, worker_harness
    # The disposable test DB has one curated repo registration in this workspace.
    with real_services.owner.begin() as con:
        con.execute(update(RegisteredSource).where(RegisteredSource.id == UUID(case["source_id"]))
                    .values(**{**REGISTRATION, "name": "Synthetic repository worker fixture"}))
    job = enqueue(api, headers, case)
    process = harness.start()
    assert dispatch_once(case["sessions"], sender(harness.app))["sent"] == 1
    wait_for(lambda: value(case, job).status == "succeeded")
    revision = api.get(case["path"] + "/revision", headers=headers("atlas-viewer")).json()
    parsed = api.get(revision["parsed_artifact_url"], headers=headers("atlas-viewer")).json()
    assert parsed["schema_version"] == "doclens-service-document-v2"
    assert parsed["source"]["synthetic"] is True
    block = parsed["document"]["sections"][0]["blocks"][0]
    assert block["url"] == SOURCE_URL + "#L2-L4" and block["location"]["commit"] == COMMIT
    harness.stop(process)
    assert process.returncode == 0


def rename(real, case, prefix):
    with real.owner.begin() as con:
        con.execute(update(RegisteredSource).where(RegisteredSource.id == UUID(case["source_id"]))
                    .values(name=prefix + uuid4().hex))


def test_real_broker_failure_lost_message_recovery_and_duplicate_delivery(api, headers, ingestion_case, real_services, worker_harness):
    case, harness = ingestion_case, worker_harness
    job = enqueue(api, headers, case)
    bad = create_worker(harness.settings.model_copy(update={"broker_url": SecretStr("redis://:dummy@127.0.0.1:1/0")}))
    assert dispatch_once(case["sessions"], sender(bad))["broker_errors"] == 1
    assert value(case, job).status == "queued"
    make_due(real_services, job)
    assert dispatch_once(case["sessions"], sender(harness.app))["sent"] == 1
    # Remove a real queued message before consumption; DB intent must recover it.
    with harness.app.connection_for_write() as connection:
        assert connection.channel().queue_purge(harness.settings.queue) == 1
    make_due(real_services, job)
    dispatch_once(case["sessions"], sender(harness.app))
    process = harness.start()
    wait_for(lambda: value(case, job).status == "succeeded")
    sender(harness.app)(job["id"]); sender(harness.app)(job["id"])
    wait_for(lambda: harness.log.exists() and harness.log.read_text().count("outcome=ignored") >= 2)
    assert process.poll() is None and value(case, job).attempts == 1
    with case["sessions"]() as session:
        assert session.scalar(select(func.count()).select_from(SourceRevision).where(SourceRevision.job_id == UUID(job["id"]))) == 1
    assert len(list(case["store"].root.rglob("*.raw"))) == 1
    harness.stop(process)
    assert process.returncode == 0  # Clean shutdown through the production lifecycle.


def test_real_worker_exhausts_three_attempts_and_keeps_previous_revision(api, headers, ingestion_case, real_services, worker_harness):
    case, harness = ingestion_case, worker_harness
    harness.start()
    original = enqueue(api, headers, case)
    dispatch_once(case["sessions"], sender(harness.app))
    wait_for(lambda: value(case, original).status == "succeeded")
    previous = api.get(case["path"] + "/revision", headers=headers("atlas-owner")).json()
    rename(real_services, case, "retry-")
    retry = enqueue(api, headers, case)
    for attempt in range(1, 4):
        dispatch_once(case["sessions"], sender(harness.app))
        wait_for(lambda: value(case, retry).attempts == attempt and
                 value(case, retry).status == ("failed" if attempt == 3 else "retry_wait"))
        assert value(case, retry).attempts == attempt
        if attempt < 3: make_due(real_services, retry)  # Controlled clock advancement, not a production delay.
    assert value(case, retry).error_code == "http_temporary"
    assert api.get(case["path"] + "/revision", headers=headers("atlas-viewer")).json() == previous


def test_killed_real_worker_after_raw_staging_recovers_without_partial_publication(api, headers, ingestion_case, real_services, worker_harness):
    case, harness = ingestion_case, worker_harness
    process = harness.start()
    original = enqueue(api, headers, case)
    dispatch_once(case["sessions"], sender(harness.app))
    wait_for(lambda: value(case, original).status == "succeeded")
    previous = api.get(case["path"] + "/revision", headers=headers("atlas-owner")).json()
    rename(real_services, case, "crash-")
    interrupted = enqueue(api, headers, case)
    dispatch_once(case["sessions"], sender(harness.app))
    wait_for(lambda: (case["store"].root.parent / "parser-barrier").exists())
    harness.stop(process, crash=True)
    assert value(case, interrupted).status == "running" and value(case, interrupted).stage == "parsing"
    assert len(list(case["store"].root.rglob("*.raw"))) == 2  # Previous + staged orphan.
    assert api.get(case["path"] + "/revision", headers=headers("atlas-owner")).json() == previous
    make_due(real_services, interrupted, expire=True)  # Controlled expiry after an actual process kill.
    harness.start()
    assert dispatch_once(case["sessions"], sender(harness.app))["expired"] == 1
    wait_for(lambda: value(case, interrupted).status == "succeeded")
    current = api.get(case["path"] + "/revision", headers=headers("atlas-viewer")).json()
    assert current["id"] != previous["id"] and value(case, interrupted).attempts == 2
    assert len(list(case["store"].root.rglob("*.parsed"))) == 2
