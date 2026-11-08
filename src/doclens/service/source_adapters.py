"""Select acquisition/normalization policy without changing job recovery logic."""

from dataclasses import dataclass
from typing import Callable

from doclens.parse import parse_html
from doclens.service.ingestion_io import IngestionError, POLICY, fetch_python, validate_source as validate_html
from doclens.service.repository import (POLICY as REPOSITORY_POLICY, fetch_repository, git_blob_sha,
                                       parse_repository, source_metadata, validate_repository_source)


@dataclass(frozen=True)
class SourceAdapter:
    fetch: Callable
    parse: Callable
    document_schema: str
    policy: str


HTML = SourceAdapter(fetch_python, parse_html, "doclens-service-document-v1", POLICY)
REPOSITORY = SourceAdapter(fetch_repository, parse_repository, "doclens-service-document-v2", REPOSITORY_POLICY)


def adapter_for(source: dict) -> SourceAdapter:
    if source.get("connector_kind") == "https_html":
        validate_html(source)
        return HTML
    if source.get("connector_kind") == "github_file":
        validate_repository_source(source)
        return REPOSITORY
    raise IngestionError("unsupported_source")


def validate_source(source: dict) -> None:
    adapter_for(source)


def normalized_source(source: dict, adapter: SourceAdapter) -> dict:
    return {**source, **source_metadata()} if adapter is REPOSITORY else source


def acquisition_metadata(content: bytes, adapter: SourceAdapter) -> dict:
    return {"git_blob_sha1": git_blob_sha(content)} if adapter is REPOSITORY else {}
