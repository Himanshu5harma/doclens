"""Allow one curated issue-export connector without rewriting old records."""

from alembic import op

revision = "0004_issue_export"
down_revision = "0003_repository_source"
branch_labels = depends_on = None
S = "doclens_service"


def _constraints(connector, purpose):
    op.drop_constraint("ck_source_connector", "sources", schema=S, type_="check")
    op.drop_constraint("ck_source_purpose", "sources", schema=S, type_="check")
    op.create_check_constraint("ck_source_connector", "sources", connector, schema=S)
    op.create_check_constraint("ck_source_purpose", "sources", purpose, schema=S)


def upgrade():
    _constraints("connector_kind IN ('https_html', 'github_file', 'issue_export')",
                 "document_type IN ('reference', 'release_notes', 'test_code', 'issue_report')")


def downgrade():
    # Refuse incompatible existing rows, rather than silently deleting source history.
    _constraints("connector_kind IN ('https_html', 'github_file')",
                 "document_type IN ('reference', 'release_notes', 'test_code')")
