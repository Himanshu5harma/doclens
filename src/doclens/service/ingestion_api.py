"""Scoped job/revision/artifact endpoints; HTTP requests never fetch or enqueue."""

from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, HTTPException, Query, Request, Response
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from doclens.service.app import AccessDep, SessionDep
from doclens.service.ingestion import source_snapshot
from doclens.service.ingestion_io import IngestionError
from doclens.service.source_adapters import validate_source
from doclens.service.models import DispatchIntent, IngestionJob, RegisteredSource, SourcePublication, SourceRevision
from doclens.service.schemas import JobRead, RevisionRead, SyncCreate

router = APIRouter(prefix="/api/v1/workspaces/{workspace_id}")


def scoped_source(session, access, source_id):
    source = session.scalar(select(RegisteredSource).where(
        RegisteredSource.id == source_id, RegisteredSource.workspace_id == access.workspace_id))
    if source is None:
        raise HTTPException(404, "Resource not found.")
    return source


def job_read(session, job):
    result = JobRead.model_validate(job)
    result.revision_id = session.scalar(select(SourceRevision.id).where(
        SourceRevision.job_id == job.id, SourceRevision.workspace_id == job.workspace_id))
    intent = session.get(DispatchIntent, job.id)
    if intent is not None:
        result.delivery_attempts = intent.deliveries
        if job.status in ("queued", "retry_wait", "running"):
            result.next_dispatch_at = max(intent.next_dispatch_at, job.available_at,
                                          *([job.lease_expires_at] if job.status == "running" else []))
            result.dispatch_error_code = intent.last_error_code
            if intent.last_error_code == "broker_unavailable":
                result.dispatch_error_message = "Broker unavailable; the durable job will be retried within its delivery limit."
    return result


def revision_read(revision):
    result = RevisionRead.model_validate(revision)
    prefix = (f"/api/v1/workspaces/{revision.workspace_id}/sources/{revision.source_id}"
              f"/revisions/{revision.id}/artifacts")
    result.raw_artifact_url = prefix + "/raw"
    result.parsed_artifact_url = prefix + "/parsed"
    return result


def scoped_revision(session, access, source_id, revision_id):
    revision = session.scalar(select(SourceRevision).where(
        SourceRevision.id == revision_id, SourceRevision.source_id == source_id,
        SourceRevision.workspace_id == access.workspace_id))
    if revision is None:
        raise HTTPException(404, "Resource not found.")
    return revision


@router.post("/sources/{source_id}/sync", response_model=JobRead, status_code=202)
def sync_source(source_id: UUID, body: SyncCreate, access: AccessDep, session: SessionDep):
    source = scoped_source(session, access, source_id)
    if access.role not in ("owner", "editor"):
        raise HTTPException(403, "Source sync requires owner or editor membership.")
    existing = session.scalar(select(IngestionJob).where(
        IngestionJob.workspace_id == access.workspace_id, IngestionJob.request_key == body.request_key))
    if existing is not None:
        if existing.source_id != source_id:
            raise HTTPException(409, "Request key belongs to a different source.")
        return job_read(session, existing)
    try:
        validate_source(source_snapshot(source))
    except IngestionError as error:
        raise HTTPException(422, str(error)) from None
    job = IngestionJob(workspace_id=access.workspace_id, source_id=source_id,
                       requested_by=access.principal_id, request_key=body.request_key)
    try:
        session.add(job)
        session.flush()
        session.add(DispatchIntent(job_id=job.id))
        session.commit()  # Job and delivery intent are one transaction, no broker dependency.
    except IntegrityError:
        session.rollback()
        existing = session.scalar(select(IngestionJob).where(
            IngestionJob.workspace_id == access.workspace_id, IngestionJob.request_key == body.request_key,
            IngestionJob.source_id == source_id))
        if existing is not None:
            return job_read(session, existing)
        raise HTTPException(409, "Source has an active sync or this request key conflicts.") from None
    return job_read(session, job)


@router.get("/sources/{source_id}/jobs", response_model=list[JobRead])
def list_jobs(source_id: UUID, access: AccessDep, session: SessionDep,
              limit: Annotated[int, Query(ge=1, le=100)] = 50,
              offset: Annotated[int, Query(ge=0, le=100_000)] = 0):
    scoped_source(session, access, source_id)
    jobs = session.scalars(select(IngestionJob).where(
        IngestionJob.workspace_id == access.workspace_id, IngestionJob.source_id == source_id)
        .order_by(IngestionJob.created_at.desc(), IngestionJob.id).limit(limit).offset(offset)).all()
    return [job_read(session, job) for job in jobs]


@router.get("/jobs/{job_id}", response_model=JobRead)
def get_job(job_id: UUID, access: AccessDep, session: SessionDep):
    job = session.scalar(select(IngestionJob).where(
        IngestionJob.id == job_id, IngestionJob.workspace_id == access.workspace_id))
    if job is None:
        raise HTTPException(404, "Resource not found.")
    return job_read(session, job)


@router.get("/sources/{source_id}/revision", response_model=RevisionRead)
def current_revision(source_id: UUID, access: AccessDep, session: SessionDep):
    revision = session.scalar(select(SourceRevision).join(SourcePublication,
        SourcePublication.revision_id == SourceRevision.id).where(
            SourcePublication.source_id == source_id, SourcePublication.workspace_id == access.workspace_id,
            SourceRevision.source_id == source_id, SourceRevision.workspace_id == access.workspace_id))
    if revision is None:
        raise HTTPException(404, "Resource not found.")
    return revision_read(revision)


@router.get("/sources/{source_id}/revisions/{revision_id}", response_model=RevisionRead)
def get_revision(source_id: UUID, revision_id: UUID, access: AccessDep, session: SessionDep):
    return revision_read(scoped_revision(session, access, source_id, revision_id))


@router.get("/sources/{source_id}/revisions/{revision_id}/artifacts/{kind}")
def get_artifact(source_id: UUID, revision_id: UUID, kind: Literal["raw", "parsed"],
                 request: Request, access: AccessDep, session: SessionDep):
    revision = scoped_revision(session, access, source_id, revision_id)
    try:
        content = request.app.state.artifacts.read(getattr(revision, f"{kind}_key"),
            getattr(revision, f"{kind}_sha256"), getattr(revision, f"{kind}_size"))
    except IngestionError:
        raise HTTPException(503, "Source artifact unavailable or failed integrity verification.") from None
    return Response(content, media_type="application/octet-stream" if kind == "raw" else "application/json",
                    headers={"Content-Disposition": f'attachment; filename="{revision.id}.{kind}"',
                             "X-Content-Type-Options": "nosniff", "Cache-Control": "no-store"})
