"""Persisted jobs, dispatch intents and immutable ready source revisions."""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

revision = "0002_ingestion"
down_revision = "0001_workspace_sources"
branch_labels = depends_on = None
S = "doclens_service"


def upgrade():
    op.create_unique_constraint("uq_source_scope", "sources", ["id", "workspace_id"], schema=S)
    op.create_table("ingestion_jobs",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("source_id", sa.Uuid(), nullable=False),
        sa.Column("requested_by", sa.Uuid(), sa.ForeignKey(f"{S}.principals.id"), nullable=False),
        sa.Column("request_key", sa.Uuid(), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("stage", sa.String(16), nullable=False),
        sa.Column("attempts", sa.Integer(), nullable=False),
        sa.Column("available_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("lease_token", sa.Uuid()),
        sa.Column("lease_expires_at", sa.DateTime(timezone=True)),
        sa.Column("error_code", sa.String(32)),
        sa.Column("error_message", sa.String(200)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["source_id", "workspace_id"], [f"{S}.sources.id", f"{S}.sources.workspace_id"]),
        sa.UniqueConstraint("workspace_id", "request_key", name="uq_job_request"),
        sa.UniqueConstraint("id", "source_id", "workspace_id", name="uq_job_scope"),
        sa.CheckConstraint("status IN ('queued', 'running', 'retry_wait', 'succeeded', 'failed')", name="ck_job_status"),
        sa.CheckConstraint("attempts BETWEEN 0 AND 3", name="ck_job_attempts"),
        sa.CheckConstraint("stage IN ('queued', 'fetching', 'parsing', 'publishing', 'complete', 'failed')", name="ck_job_stage"),
        sa.CheckConstraint("(status = 'running') = (lease_token IS NOT NULL AND lease_expires_at IS NOT NULL)", name="ck_job_lease"), schema=S)
    op.create_index("ix_doclens_service_ingestion_jobs_workspace_id", "ingestion_jobs", ["workspace_id"], schema=S)
    op.create_index("uq_job_active_source", "ingestion_jobs", ["source_id"], unique=True, schema=S,
                    postgresql_where=sa.text("status IN ('queued', 'running', 'retry_wait')"))
    op.create_table("dispatch_intents",
        sa.Column("job_id", sa.Uuid(), sa.ForeignKey(f"{S}.ingestion_jobs.id"), primary_key=True),
        sa.Column("next_dispatch_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("deliveries", sa.Integer(), nullable=False),
        sa.Column("last_error_code", sa.String(32)),
        sa.CheckConstraint("deliveries BETWEEN 0 AND 20", name="ck_dispatch_deliveries"), schema=S)
    op.create_index("ix_doclens_service_dispatch_intents_next_dispatch_at", "dispatch_intents", ["next_dispatch_at"], schema=S)
    op.create_table("source_revisions",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("job_id", sa.Uuid(), nullable=False),
        sa.Column("source_id", sa.Uuid(), nullable=False),
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("source_snapshot", JSONB(), nullable=False),
        sa.Column("parser_config", JSONB(), nullable=False),
        sa.Column("final_url", sa.String(2048), nullable=False),
        sa.Column("fetched_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("raw_sha256", sa.String(64), nullable=False),
        sa.Column("parsed_sha256", sa.String(64), nullable=False),
        sa.Column("raw_size", sa.Integer(), nullable=False),
        sa.Column("parsed_size", sa.Integer(), nullable=False),
        sa.Column("raw_key", sa.String(512), nullable=False),
        sa.Column("parsed_key", sa.String(512), nullable=False),
        sa.Column("title", sa.String(512), nullable=False),
        sa.Column("section_count", sa.Integer(), nullable=False),
        sa.Column("block_count", sa.Integer(), nullable=False),
        sa.Column("code_count", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(["job_id", "source_id", "workspace_id"], [f"{S}.ingestion_jobs.id", f"{S}.ingestion_jobs.source_id", f"{S}.ingestion_jobs.workspace_id"]),
        sa.UniqueConstraint("job_id", name="uq_revision_job"),
        sa.UniqueConstraint("id", "source_id", "workspace_id", name="uq_revision_scope"),
        sa.CheckConstraint("raw_size BETWEEN 1 AND 4194304 AND parsed_size BETWEEN 1 AND 8388608", name="ck_revision_sizes"), schema=S)
    op.create_index("ix_doclens_service_source_revisions_workspace_id", "source_revisions", ["workspace_id"], schema=S)
    op.create_table("source_publications",
        sa.Column("source_id", sa.Uuid(), primary_key=True),
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("revision_id", sa.Uuid(), nullable=False),
        sa.ForeignKeyConstraint(["source_id", "workspace_id"], [f"{S}.sources.id", f"{S}.sources.workspace_id"]),
        sa.ForeignKeyConstraint(["revision_id", "source_id", "workspace_id"], [f"{S}.source_revisions.id", f"{S}.source_revisions.source_id", f"{S}.source_revisions.workspace_id"]), schema=S)
    op.execute(f"GRANT USAGE ON SCHEMA {S} TO doclens_worker")
    op.execute(f"GRANT SELECT ON {S}.principals, {S}.workspaces, {S}.memberships, {S}.sources TO doclens_worker")
    tables = ", ".join(f"{S}.{t}" for t in ("ingestion_jobs", "dispatch_intents", "source_revisions", "source_publications"))
    op.execute(f"GRANT SELECT ON {tables} TO doclens_app, doclens_worker")
    op.execute(f"GRANT INSERT ON {S}.ingestion_jobs, {S}.dispatch_intents TO doclens_app")
    op.execute(f"GRANT UPDATE ON {S}.ingestion_jobs, {S}.dispatch_intents TO doclens_worker")
    op.execute(f"GRANT INSERT ON {S}.source_revisions, {S}.source_publications TO doclens_worker")
    op.execute(f"GRANT UPDATE ON {S}.source_publications TO doclens_worker")


def downgrade():
    for table in ("source_publications", "source_revisions", "dispatch_intents", "ingestion_jobs"):
        op.drop_table(table, schema=S)
    op.drop_constraint("uq_source_scope", "sources", schema=S)
