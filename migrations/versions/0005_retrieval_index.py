"""Stage 4: persistent chunk vectors for published revisions (exact pgvector search).

The trusted operator installs the `vector` extension (it needs database
superuser rights); this migration only verifies it, so the owner role keeps
no extension/administrative privileges. No ANN index is created: search is an
exact scan of rows that already passed workspace/product/version filters.
"""

from alembic import op
import sqlalchemy as sa
from pgvector.sqlalchemy import Vector
from sqlalchemy.dialects.postgresql import JSONB

revision = "0005_retrieval_index"
down_revision = "0004_issue_export"
branch_labels = depends_on = None
S = "doclens_service"


def upgrade():
    if not op.get_bind().scalar(sa.text("SELECT 1 FROM pg_extension WHERE extname = 'vector'")):
        raise RuntimeError("The pgvector extension is not installed in this database. A trusted operator must "
                           "run CREATE EXTENSION vector first (scripts/stage1_dev.py bootstrap does this).")
    op.create_table("revision_indexes",
        sa.Column("revision_id", sa.Uuid(), primary_key=True),
        sa.Column("index_id", sa.String(64), primary_key=True),
        sa.Column("source_id", sa.Uuid(), nullable=False),
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("document_schema", sa.String(64), nullable=False),
        sa.Column("config", JSONB(), nullable=False),
        sa.Column("runtime", JSONB(), nullable=False),
        sa.Column("chunk_count", sa.Integer(), nullable=False),
        sa.Column("max_tokens", sa.Integer(), nullable=False),
        sa.Column("chunk_set_hash", sa.String(64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["revision_id", "source_id", "workspace_id"],
                                [f"{S}.source_revisions.id", f"{S}.source_revisions.source_id", f"{S}.source_revisions.workspace_id"]),
        sa.UniqueConstraint("revision_id", "index_id", "source_id", "workspace_id", name="uq_revision_index_scope"),
        sa.CheckConstraint("chunk_count >= 1 AND max_tokens >= 1", name="ck_revision_index_counts"), schema=S)
    op.create_index("ix_doclens_service_revision_indexes_workspace_id", "revision_indexes", ["workspace_id"], schema=S)
    op.create_table("retrieval_chunks",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("revision_id", sa.Uuid(), nullable=False),
        sa.Column("index_id", sa.String(64), nullable=False),
        sa.Column("source_id", sa.Uuid(), nullable=False),
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("product", sa.String(64), nullable=False),
        sa.Column("version", sa.String(64), nullable=False),
        sa.Column("document_type", sa.String(32), nullable=False),
        sa.Column("ordinal", sa.Integer(), nullable=False),
        sa.Column("chunk_key", sa.String(80), nullable=False),
        sa.Column("section_index", sa.Integer(), nullable=False),
        sa.Column("heading_path", JSONB(), nullable=False),
        sa.Column("anchor", sa.String(512)),
        sa.Column("url", sa.String(2048), nullable=False),
        sa.Column("location", JSONB(), nullable=False),
        sa.Column("document_title", sa.String(512), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("content_hash", sa.String(64), nullable=False),
        sa.Column("oversized", sa.Boolean(), nullable=False),
        sa.Column("token_count", sa.Integer(), nullable=False),
        sa.Column("embedding", Vector(768), nullable=False),
        sa.ForeignKeyConstraint(["revision_id", "index_id", "source_id", "workspace_id"],
                                [f"{S}.revision_indexes.revision_id", f"{S}.revision_indexes.index_id",
                                 f"{S}.revision_indexes.source_id", f"{S}.revision_indexes.workspace_id"]),
        sa.UniqueConstraint("revision_id", "index_id", "chunk_key", name="uq_chunk_identity"),
        sa.UniqueConstraint("revision_id", "index_id", "ordinal", name="uq_chunk_ordinal"),
        sa.CheckConstraint("ordinal >= 0 AND section_index >= 0 AND token_count >= 1", name="ck_chunk_counts"), schema=S)
    op.create_index("ix_retrieval_chunks_scope", "retrieval_chunks",
                    ["workspace_id", "product", "version", "index_id"], schema=S)
    tables = f"{S}.revision_indexes, {S}.retrieval_chunks"
    # API reads only; the indexer (worker credentials) inserts complete sets. Nobody updates vectors in place.
    op.execute(f"GRANT SELECT ON {tables} TO doclens_app, doclens_worker")
    op.execute(f"GRANT INSERT ON {tables} TO doclens_worker")


def downgrade():
    op.drop_table("retrieval_chunks", schema=S)
    op.drop_table("revision_indexes", schema=S)
