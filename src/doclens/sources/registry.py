"""Choose the adapter for a registered source; job recovery logic stays adapter-agnostic."""

from dataclasses import replace
from functools import partial

from doclens.sources.base import IngestionError, SourceAdapter
from doclens.sources.issue_export import (
    DEFAULT_EXPORT_ROOT,
    POLICY as ISSUE_POLICY,
    fetch_issue_export,
    issue_source_metadata,
    parse_issue_export,
    validate_issue_source,
)
from doclens.sources.python_docs import POLICY, fetch_python, parse_html, validate_source as validate_html
from doclens.sources.repository import (
    POLICY as REPOSITORY_POLICY,
    fetch_repository,
    git_blob_sha,
    parse_repository,
    source_metadata,
    validate_repository_source,
)

HTML = SourceAdapter(fetch_python, parse_html, "doclens-service-document-v1", POLICY)
REPOSITORY = SourceAdapter(fetch_repository, parse_repository, "doclens-service-document-v2", REPOSITORY_POLICY,
                           lambda content: source_metadata(), lambda content: {"git_blob_sha1": git_blob_sha(content)})
ISSUE = SourceAdapter(fetch_issue_export, parse_issue_export, "doclens-service-document-v3", ISSUE_POLICY,
                      lambda content: issue_source_metadata(content))


def adapter_for(source: dict, *, export_root=DEFAULT_EXPORT_ROOT) -> SourceAdapter:
    if source.get("connector_kind") == "https_html":
        validate_html(source)
        return HTML
    if source.get("connector_kind") == "github_file":
        validate_repository_source(source)
        return REPOSITORY
    if source.get("connector_kind") == "issue_export":
        validate_issue_source(source)
        return replace(ISSUE, fetch=partial(fetch_issue_export, export_root=export_root))
    raise IngestionError("unsupported_source")


def validate_source(source: dict) -> None:
    adapter_for(source)


def normalized_source(source: dict, adapter: SourceAdapter, content: bytes) -> dict:
    return {**source, **adapter.metadata(content)}


def acquisition_metadata(content: bytes, adapter: SourceAdapter) -> dict:
    return adapter.provenance(content)
