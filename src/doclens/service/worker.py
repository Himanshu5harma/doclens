"""Run a Celery worker or PostgreSQL dispatch/recovery loop as a local process."""

import argparse
import logging
from pathlib import Path
import ssl
from socket import gethostname
import time
from uuid import UUID

from celery import Celery
from pydantic import ValidationError
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import NullPool

from doclens.service.ingestion import dispatch_once, run_job
from doclens.service.ingestion_io import ArtifactStore
from doclens.service.settings import WorkerSettings

logger = logging.getLogger("doclens.worker")
TASK_NAME = "doclens.ingest_source"


def database_engine(settings):
    return create_engine(settings.database_url.get_secret_value(), poolclass=NullPool,
        hide_parameters=True, connect_args={"connect_timeout": 5,
            "options": "-c statement_timeout=10000 -c lock_timeout=5000"})


def create_worker(settings: WorkerSettings, *, fetcher=None, parser=None):
    app = Celery("doclens", broker=settings.broker_url.get_secret_value(), set_as_current=False)
    app.conf.update(
        task_default_queue=settings.queue, task_serializer="json", accept_content=["json"],
        task_ignore_result=True, result_backend=None, task_store_errors_even_if_ignored=False,
        task_publish_retry=False, broker_connection_retry=False, broker_connection_retry_on_startup=False,
        broker_connection_timeout=2, broker_pool_limit=0,
        broker_transport_options={"visibility_timeout": 120, "socket_connect_timeout": 2,
                                  "socket_timeout": 2, "retry_on_timeout": False,
                                  "max_retries": 0, "polling_interval": 0.5,
                                  "global_keyprefix": f"doclens:{settings.queue}:"},
        visibility_timeout=120, worker_prefetch_multiplier=1, task_acks_late=True,
        # Reconciliation handles lost workers; do not create a broker poison-task loop.
        task_reject_on_worker_lost=False, task_soft_time_limit=60, task_time_limit=75,
        worker_max_tasks_per_child=10, worker_max_memory_per_child=512000,
        worker_send_task_events=False, task_send_sent_event=False, worker_enable_remote_control=False,
    )
    if settings.broker_url.get_secret_value().startswith("rediss:"):
        app.conf.broker_use_ssl = {"ssl_cert_reqs": ssl.CERT_REQUIRED}

    @app.task(name=TASK_NAME, max_retries=0)
    def ingest(job_id):
        engine = None
        try:
            identifier = UUID(job_id)
            engine = database_engine(settings)
            outcome = run_job(sessionmaker(engine, expire_on_commit=False), ArtifactStore(settings.artifact_root),
                identifier, fetcher=fetcher, parser=parser, lease_seconds=settings.lease_seconds)
            logger.warning("ingestion job=%s outcome=%s", identifier, outcome)
        except Exception:
            # DB downtime leaves durable state for bounded dispatch/lease recovery.
            logger.warning("ingestion outcome=worker_or_database_unavailable")
        finally:
            if engine is not None:
                engine.dispose()

    return app


def sender(app):
    return lambda job_id: app.send_task(TASK_NAME, args=[job_id], retry=False, ignore_result=True)


def start_worker(app, settings):
    """Use Celery's program worker and preserve its actual shutdown status.

    Celery 5.6.3's worker_main() returns None even after a failed startup.
    Worker installs the same lifecycle/signal handling and exposes exitcode.
    """
    worker = app.Worker(loglevel="WARNING", concurrency=1, pool="prefork",
        without_gossip=True, without_mingle=True, without_heartbeat=True,
        hostname=f"doclens-ingestion@{gethostname()}", queues=[settings.queue])
    worker.start()
    return worker.exitcode if worker.exitcode is not None else 0


def main():
    cli = argparse.ArgumentParser(description=__doc__)
    cli.add_argument("command", choices=("worker", "dispatch"))
    cli.add_argument("--env-file", type=Path, default=Path(".env.worker.local"))
    cli.add_argument("--once", action="store_true", help="One bounded dispatch tick.")
    args = cli.parse_args()
    engine = None
    try:
        settings = WorkerSettings(_env_file=args.env_file)
        app = create_worker(settings)
        if args.command == "worker":
            raise SystemExit(start_worker(app, settings))
        else:
            engine = database_engine(settings)
            sessions = sessionmaker(engine, expire_on_commit=False)
            while True:
                try:
                    counts = dispatch_once(sessions, sender(app))
                    if args.once or any(counts.values()):
                        print(counts, flush=True)
                except Exception:
                    print("Dispatch unavailable; committed jobs remain in PostgreSQL.", flush=True)
                    if args.once:
                        raise SystemExit(1) from None
                if args.once:
                    break
                time.sleep(2)
    except (ValidationError, ValueError):
        raise SystemExit("Invalid worker settings; check the selected local env file. Credentials not displayed.") from None
    finally:
        if engine is not None:
            engine.dispose()


if __name__ == "__main__":
    main()
