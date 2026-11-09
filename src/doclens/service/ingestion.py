"""PostgreSQL owns ingestion state; Celery delivery may repeat or disappear."""

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import json
from uuid import NAMESPACE_URL, UUID, uuid4, uuid5

from sqlalchemy import and_, or_, select
from sqlalchemy.dialects.postgresql import insert

from doclens.service.ingestion_io import ArtifactStore, ERRORS, IngestionError
from doclens.service.source_adapters import adapter_for, normalized_source, acquisition_metadata
from doclens.service.issue_export import DEFAULT_EXPORT_ROOT
from doclens.service.models import (DispatchIntent, IngestionJob, Membership, RegisteredSource,
                                    SourcePublication, SourceRevision)

MAX_ATTEMPTS = 3
MAX_DELIVERIES = 20
ACTIVE = ("queued", "running", "retry_wait")
SOURCE_FIELDS = ("id", "workspace_id", "name", "connector_kind", "product", "version",
                 "document_type", "url", "source_terms_url")


def utcnow():
    return datetime.now(timezone.utc)


def source_snapshot(source):
    return {field: str(value) if isinstance(value, UUID) else value
            for field in SOURCE_FIELDS if (value := getattr(source, field)) is not None}


def can_sync(session, job):
    return session.scalar(select(Membership.role).where(
        Membership.workspace_id == job.workspace_id,
        Membership.principal_id == job.requested_by)) in ("owner", "editor")


def fail(job, code, *, now, retryable=False):
    retry = retryable and job.attempts < MAX_ATTEMPTS
    job.status = "retry_wait" if retry else "failed"
    job.stage = "queued" if retry else "failed"
    job.lease_token = job.lease_expires_at = None
    job.error_code, job.error_message = code, ERRORS[code]
    job.available_at = now + timedelta(seconds=5 * 2 ** max(0, job.attempts - 1)) if retry else now
    job.updated_at = now


@dataclass(frozen=True)
class Claim:
    job_id: UUID
    token: UUID
    source: dict


class LostClaim(Exception):
    """A stale execution must not publish or alter a replacement's state."""


def claim_job(sessions, job_id: UUID, *, lease_seconds=120, now=None) -> Claim | None:
    now = now or utcnow()
    with sessions.begin() as session:
        job = session.scalar(select(IngestionJob).where(IngestionJob.id == job_id).with_for_update())
        if job is None or job.status not in ACTIVE or job.available_at > now:
            return None
        if job.status == "running" and job.lease_expires_at > now:
            return None
        if not can_sync(session, job):
            fail(job, "access_revoked", now=now)
            return None
        if job.attempts >= MAX_ATTEMPTS:
            fail(job, "worker_lost", now=now)
            return None
        source = session.scalar(select(RegisteredSource).where(
            RegisteredSource.id == job.source_id, RegisteredSource.workspace_id == job.workspace_id))
        job.status, job.stage = "running", "fetching"
        job.attempts += 1
        job.lease_token = uuid4()
        job.lease_expires_at = now + timedelta(seconds=lease_seconds)
        job.updated_at = now
        job.error_code = job.error_message = None
        return Claim(job.id, job.lease_token, source_snapshot(source))


def current_claim(session, claim, now):
    job = session.scalar(select(IngestionJob).where(IngestionJob.id == claim.job_id).with_for_update())
    if (job is None or job.status != "running" or job.lease_token != claim.token
            or job.lease_expires_at <= now):
        raise LostClaim
    return job


def progress(sessions, claim, stage):
    with sessions.begin() as session:
        job = current_claim(session, claim, utcnow())
        job.stage, job.updated_at = stage, utcnow()


def publish_revision(sessions, claim, revision):
    with sessions.begin() as session:
        job = current_claim(session, claim, utcnow())
        # Queueing does not freeze an old authorization decision.
        if not can_sync(session, job):
            fail(job, "access_revoked", now=utcnow())
            return False
        session.add(revision)
        session.flush()
        statement = insert(SourcePublication).values(
            source_id=job.source_id, workspace_id=job.workspace_id, revision_id=revision.id)
        session.execute(statement.on_conflict_do_update(
            index_elements=[SourcePublication.source_id], set_={"revision_id": revision.id}))
        job.status, job.stage = "succeeded", "complete"
        job.lease_token = job.lease_expires_at = None
        job.error_code = job.error_message = None
        job.updated_at = utcnow()
        # Revision + ready pointer + success commit together, after both files exist.
    return True


def run_job(sessions, store: ArtifactStore, job_id: UUID, *, fetcher=None,
            parser=None, lease_seconds=120, export_root=DEFAULT_EXPORT_ROOT):
    claim = claim_job(sessions, job_id, lease_seconds=lease_seconds)
    if claim is None:
        return "ignored"
    try:
        adapter = adapter_for(claim.source, export_root=export_root)
        snapshot = (fetcher or adapter.fetch)(claim.source)
        source = normalized_source(claim.source, adapter, snapshot.content)
        prefix = f"{claim.source['workspace_id']}/{claim.source['id']}/{claim.job_id}/{claim.token}"
        raw_key, raw_hash = store.put(prefix, snapshot.content, "raw")
        progress(sessions, claim, "parsing")
        try:
            document = (parser or adapter.parse)(snapshot.content, source_url=source["url"])
        except (ValueError, TypeError, KeyError):
            raise IngestionError("parse_error") from None
        revision_id = uuid5(NAMESPACE_URL, f"doclens-service-v1/revision/{claim.job_id}")
        normalized = {
            "schema_version": adapter.document_schema, "processing_policy": adapter.policy,
            "revision_id": str(revision_id), "source": source,
            "provenance": {"final_url": snapshot.final_url, "fetched_at": snapshot.fetched_at.isoformat(),
                           "raw_sha256": raw_hash, "size_bytes": len(snapshot.content),
                           **acquisition_metadata(snapshot.content, adapter)},
            "document": {key: document[key] for key in ("parser", "title", "sections")},
        }
        encoded = (json.dumps(normalized, ensure_ascii=False, sort_keys=True, indent=2) + "\n").encode()
        parsed_key, parsed_hash = store.put(prefix, encoded, "parsed")
        # Verify both staged artifacts immediately before the publication transaction.
        store.read(raw_key, raw_hash, len(snapshot.content))
        store.read(parsed_key, parsed_hash, len(encoded))
        progress(sessions, claim, "publishing")
        blocks = [block for section in document["sections"] for block in section["blocks"]]
        revision = SourceRevision(
            id=revision_id, job_id=claim.job_id, workspace_id=UUID(claim.source["workspace_id"]),
            source_id=UUID(claim.source["id"]), source_snapshot=source,
            parser_config={**document["parser"], "processing_policy": adapter.policy},
            final_url=snapshot.final_url, fetched_at=snapshot.fetched_at,
            raw_sha256=raw_hash, parsed_sha256=parsed_hash, raw_size=len(snapshot.content),
            parsed_size=len(encoded), raw_key=raw_key, parsed_key=parsed_key,
            title=document["title"], section_count=len(document["sections"]), block_count=len(blocks),
            code_count=sum(block["kind"] == "code" for block in blocks),
        )
        return "finished" if publish_revision(sessions, claim, revision) else "access_revoked"
    except LostClaim:
        return "stale"
    except Exception as error:
        # Includes parser/storage surprises; never save the raw exception string.
        failure = error if isinstance(error, IngestionError) else IngestionError("internal_error", retryable=True)
        with sessions.begin() as session:
            try:
                job = current_claim(session, claim, utcnow())
            except LostClaim:
                return "stale"
            now = utcnow()
            fail(job, failure.code, now=now, retryable=failure.retryable)
            intent = session.get(DispatchIntent, job.id)
            intent.next_dispatch_at = job.available_at
        return failure.code


@dataclass(frozen=True)
class DeliveryReservation:
    job_id: UUID
    generation: int
    expires_at: datetime


def _reserve_deliveries(sessions, *, limit, now):
    """Commit due delivery attempts before any broker I/O or worker execution."""
    reservations = []
    outcomes = {"sent": 0, "broker_errors": 0, "expired": 0, "failed": 0}
    with sessions.begin() as session:
        jobs = session.scalars(select(IngestionJob).join(DispatchIntent)
            .where(DispatchIntent.next_dispatch_at <= now, IngestionJob.available_at <= now,
                   or_(IngestionJob.status.in_(("queued", "retry_wait")),
                       and_(IngestionJob.status == "running", IngestionJob.lease_expires_at <= now)))
            .order_by(IngestionJob.created_at).limit(limit)
            .with_for_update(of=IngestionJob, skip_locked=True)).all()
        for job in jobs:
            intent = session.get(DispatchIntent, job.id)
            if not can_sync(session, job):
                fail(job, "access_revoked", now=now)
                outcomes["failed"] += 1
                continue
            if job.status == "running":
                outcomes["expired"] += 1
                if job.attempts >= MAX_ATTEMPTS:
                    fail(job, "worker_lost", now=now)
                    outcomes["failed"] += 1
                    continue
                job.status, job.stage = "retry_wait", "queued"
                job.lease_token = job.lease_expires_at = None
                job.error_code, job.error_message = "worker_lost", ERRORS["worker_lost"]
                job.updated_at = now
            if intent.deliveries >= MAX_DELIVERIES:
                fail(job, "dispatch_exhausted", now=now)
                outcomes["failed"] += 1
                continue
            intent.deliveries += 1
            intent.next_dispatch_at = now + timedelta(seconds=30)
            reservations.append(DeliveryReservation(job.id, intent.deliveries, intent.next_dispatch_at))
    return reservations, outcomes  # The context has committed and released every job lock.


def _record_delivery(sessions, reservation, *, failed, now):
    """A slow publisher must not overwrite a newer delivery or worker retry."""
    with sessions.begin() as session:
        job = session.scalar(select(IngestionJob).where(
            IngestionJob.id == reservation.job_id).with_for_update())
        if job is None:
            return
        intent = session.get(DispatchIntent, job.id)
        if intent is None or intent.deliveries != reservation.generation:
            return
        if not failed:
            intent.last_error_code = None
            # Leave the reserved replay time, or a worker's newer retry time, alone.
        elif (job.status in ("queued", "retry_wait")
              and intent.next_dispatch_at == reservation.expires_at):
            intent.last_error_code = "broker_unavailable"
            intent.next_dispatch_at = max(now + timedelta(seconds=5), job.available_at)


def dispatch_once(sessions, send, *, limit=10, now=None):
    """Bounded relay/recovery with durable reservations and unlocked broker I/O.

    A crash after reserving or publishing leaves a replayable intent. Delivery
    count fences late results; processing state remains protected by job claims.
    """
    reservations, outcomes = _reserve_deliveries(sessions, limit=limit, now=now or utcnow())
    for reservation in reservations:
        try:
            send(str(reservation.job_id))  # Only the job UUID crosses the broker.
        except Exception:
            failed = True
            outcomes["broker_errors"] += 1
        else:
            failed = False
            outcomes["sent"] += 1
        _record_delivery(sessions, reservation, failed=failed, now=now or utcnow())
    return outcomes
