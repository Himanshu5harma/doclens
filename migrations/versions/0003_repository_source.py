"""Allow the curated repository source without rewriting prior revisions."""

from alembic import op

revision = "0003_repository_source"
down_revision = "0002_ingestion"
branch_labels = depends_on = None
S = "doclens_service"


def _constraints(connector, purpose):
    op.drop_constraint("ck_source_connector", "sources", schema=S, type_="check")
    op.drop_constraint("ck_source_purpose", "sources", schema=S, type_="check")
    op.create_check_constraint("ck_source_connector", "sources", connector, schema=S)
    op.create_check_constraint("ck_source_purpose", "sources", purpose, schema=S)


def upgrade():
    _constraints("connector_kind IN ('https_html', 'github_file')",
                 "document_type IN ('reference', 'release_notes', 'test_code')")


def downgrade():
    # PostgreSQL rejects this downgrade if repository rows still exist. Never delete
    # sources/revisions automatically just to make an older application schema fit.
    _constraints("connector_kind = 'https_html'", "document_type IN ('reference', 'release_notes')")
