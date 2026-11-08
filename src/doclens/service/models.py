"""Service-owned schema. This does not reinterpret baseline document schema 1."""

from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import (CheckConstraint, DateTime, ForeignKey, ForeignKeyConstraint, Index,
                        Integer, MetaData, String, UniqueConstraint, func, text)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


SCHEMA = "doclens_service"


class Base(DeclarativeBase):
    metadata = MetaData(schema=SCHEMA)


class Principal(Base):
    __tablename__ = "principals"
    __table_args__ = (UniqueConstraint("issuer", "subject", name="uq_principal_identity"),)

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    issuer: Mapped[str] = mapped_column(String(2048))
    subject: Mapped[str] = mapped_column(String(255))


class Workspace(Base):
    __tablename__ = "workspaces"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    slug: Mapped[str] = mapped_column(String(64), unique=True)
    name: Mapped[str] = mapped_column(String(120))


class Membership(Base):
    __tablename__ = "memberships"
    __table_args__ = (CheckConstraint("role IN ('owner', 'editor', 'viewer')", name="ck_membership_role"),)

    workspace_id: Mapped[UUID] = mapped_column(ForeignKey(f"{SCHEMA}.workspaces.id"), primary_key=True)
    principal_id: Mapped[UUID] = mapped_column(ForeignKey(f"{SCHEMA}.principals.id"), primary_key=True)
    role: Mapped[str] = mapped_column(String(16))


class RegisteredSource(Base):
    __tablename__ = "sources"
    __table_args__ = (
        UniqueConstraint("workspace_id", "url", "product", "version", name="uq_source_identity"),
        UniqueConstraint("id", "workspace_id", name="uq_source_scope"),
        CheckConstraint("connector_kind IN ('https_html', 'github_file')", name="ck_source_connector"),
        CheckConstraint("document_type IN ('reference', 'release_notes', 'test_code')", name="ck_source_purpose"),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    workspace_id: Mapped[UUID] = mapped_column(ForeignKey(f"{SCHEMA}.workspaces.id"), index=True)
    created_by: Mapped[UUID] = mapped_column(ForeignKey(f"{SCHEMA}.principals.id"))
    name: Mapped[str] = mapped_column(String(120))
    connector_kind: Mapped[str] = mapped_column(String(32))
    product: Mapped[str] = mapped_column(String(64))
    version: Mapped[str] = mapped_column(String(64))
    document_type: Mapped[str] = mapped_column(String(32))
    url: Mapped[str] = mapped_column(String(2048))
    source_terms_url: Mapped[str] = mapped_column(String(2048))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class IngestionJob(Base):
    __tablename__ = "ingestion_jobs"
    __table_args__ = (
        ForeignKeyConstraint(["source_id", "workspace_id"], [f"{SCHEMA}.sources.id", f"{SCHEMA}.sources.workspace_id"]),
        UniqueConstraint("workspace_id", "request_key", name="uq_job_request"),
        UniqueConstraint("id", "source_id", "workspace_id", name="uq_job_scope"),
        CheckConstraint("status IN ('queued', 'running', 'retry_wait', 'succeeded', 'failed')", name="ck_job_status"),
        CheckConstraint("attempts BETWEEN 0 AND 3", name="ck_job_attempts"),
        CheckConstraint("stage IN ('queued', 'fetching', 'parsing', 'publishing', 'complete', 'failed')", name="ck_job_stage"),
        CheckConstraint("(status = 'running') = (lease_token IS NOT NULL AND lease_expires_at IS NOT NULL)", name="ck_job_lease"),
        Index("uq_job_active_source", "source_id", unique=True,
              postgresql_where=text("status IN ('queued', 'running', 'retry_wait')")),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    workspace_id: Mapped[UUID] = mapped_column(index=True)
    source_id: Mapped[UUID]
    requested_by: Mapped[UUID] = mapped_column(ForeignKey(f"{SCHEMA}.principals.id"))
    request_key: Mapped[UUID]
    status: Mapped[str] = mapped_column(String(16), default="queued")
    stage: Mapped[str] = mapped_column(String(16), default="queued")
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    available_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    lease_token: Mapped[UUID | None]
    lease_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    error_code: Mapped[str | None] = mapped_column(String(32))
    error_message: Mapped[str | None] = mapped_column(String(200))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class DispatchIntent(Base):
    __tablename__ = "dispatch_intents"
    __table_args__ = (CheckConstraint("deliveries BETWEEN 0 AND 20", name="ck_dispatch_deliveries"),)

    job_id: Mapped[UUID] = mapped_column(ForeignKey(f"{SCHEMA}.ingestion_jobs.id"), primary_key=True)
    next_dispatch_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), index=True)
    deliveries: Mapped[int] = mapped_column(Integer, default=0)
    last_error_code: Mapped[str | None] = mapped_column(String(32))


class SourceRevision(Base):
    __tablename__ = "source_revisions"
    __table_args__ = (
        ForeignKeyConstraint(["job_id", "source_id", "workspace_id"],
                             [f"{SCHEMA}.ingestion_jobs.id", f"{SCHEMA}.ingestion_jobs.source_id", f"{SCHEMA}.ingestion_jobs.workspace_id"]),
        UniqueConstraint("job_id", name="uq_revision_job"),
        UniqueConstraint("id", "source_id", "workspace_id", name="uq_revision_scope"),
        CheckConstraint("raw_size BETWEEN 1 AND 4194304 AND parsed_size BETWEEN 1 AND 8388608", name="ck_revision_sizes"),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True)
    job_id: Mapped[UUID]
    source_id: Mapped[UUID]
    workspace_id: Mapped[UUID] = mapped_column(index=True)
    source_snapshot: Mapped[dict] = mapped_column(JSONB)
    parser_config: Mapped[dict] = mapped_column(JSONB)
    final_url: Mapped[str] = mapped_column(String(2048))
    fetched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    raw_sha256: Mapped[str] = mapped_column(String(64))
    parsed_sha256: Mapped[str] = mapped_column(String(64))
    raw_size: Mapped[int]
    parsed_size: Mapped[int]
    raw_key: Mapped[str] = mapped_column(String(512))
    parsed_key: Mapped[str] = mapped_column(String(512))
    title: Mapped[str] = mapped_column(String(512))
    section_count: Mapped[int]
    block_count: Mapped[int]
    code_count: Mapped[int]


class SourcePublication(Base):
    """One ready document pointer; not a vector-index/public-reader publication."""
    __tablename__ = "source_publications"
    __table_args__ = (
        ForeignKeyConstraint(["source_id", "workspace_id"], [f"{SCHEMA}.sources.id", f"{SCHEMA}.sources.workspace_id"]),
        ForeignKeyConstraint(["revision_id", "source_id", "workspace_id"],
                             [f"{SCHEMA}.source_revisions.id", f"{SCHEMA}.source_revisions.source_id", f"{SCHEMA}.source_revisions.workspace_id"]),
    )
    source_id: Mapped[UUID] = mapped_column(primary_key=True)
    workspace_id: Mapped[UUID]
    revision_id: Mapped[UUID]
