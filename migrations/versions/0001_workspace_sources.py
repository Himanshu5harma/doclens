"""Explicit workspace ownership; schema is provisioned by the trusted operator.

Revision ID: 0001_workspace_sources
"""

from alembic import op
import sqlalchemy as sa


revision = "0001_workspace_sources"
down_revision = None
branch_labels = None
depends_on = None
SCHEMA = "doclens_service"


def upgrade():
    op.create_table("principals",
        sa.Column("id", sa.Uuid(), nullable=False, primary_key=True),
        sa.Column("issuer", sa.String(2048), nullable=False),
        sa.Column("subject", sa.String(255), nullable=False),
        sa.UniqueConstraint("issuer", "subject", name="uq_principal_identity"), schema=SCHEMA)
    op.create_table("workspaces",
        sa.Column("id", sa.Uuid(), nullable=False, primary_key=True),
        sa.Column("slug", sa.String(64), nullable=False, unique=True),
        sa.Column("name", sa.String(120), nullable=False), schema=SCHEMA)
    op.create_table("memberships",
        sa.Column("workspace_id", sa.Uuid(), sa.ForeignKey(f"{SCHEMA}.workspaces.id"), primary_key=True),
        sa.Column("principal_id", sa.Uuid(), sa.ForeignKey(f"{SCHEMA}.principals.id"), primary_key=True),
        sa.Column("role", sa.String(16), nullable=False),
        sa.CheckConstraint("role IN ('owner', 'editor', 'viewer')", name="ck_membership_role"), schema=SCHEMA)
    op.create_table("sources",
        sa.Column("id", sa.Uuid(), nullable=False, primary_key=True),
        sa.Column("workspace_id", sa.Uuid(), sa.ForeignKey(f"{SCHEMA}.workspaces.id"), nullable=False),
        sa.Column("created_by", sa.Uuid(), sa.ForeignKey(f"{SCHEMA}.principals.id"), nullable=False),
        sa.Column("name", sa.String(120), nullable=False),
        sa.Column("connector_kind", sa.String(32), nullable=False),
        sa.Column("product", sa.String(64), nullable=False),
        sa.Column("version", sa.String(64), nullable=False),
        sa.Column("document_type", sa.String(32), nullable=False),
        sa.Column("url", sa.String(2048), nullable=False),
        sa.Column("source_terms_url", sa.String(2048), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("workspace_id", "url", "product", "version", name="uq_source_identity"),
        sa.CheckConstraint("connector_kind = 'https_html'", name="ck_source_connector"),
        sa.CheckConstraint("document_type IN ('reference', 'release_notes')", name="ck_source_purpose"), schema=SCHEMA)
    op.create_index("ix_doclens_service_sources_workspace_id", "sources", ["workspace_id"], schema=SCHEMA)
    # No DDL, membership administration, update or delete for the API role.
    op.execute(f"GRANT USAGE ON SCHEMA {SCHEMA} TO doclens_app")
    op.execute(f"GRANT SELECT ON {SCHEMA}.principals, {SCHEMA}.workspaces, {SCHEMA}.memberships, {SCHEMA}.sources TO doclens_app")
    op.execute(f"GRANT INSERT ON {SCHEMA}.sources TO doclens_app")


def downgrade():
    for table in ("sources", "memberships", "workspaces", "principals"):
        op.drop_table(table, schema=SCHEMA)
