"""Runtime validation for the registration API, with no caller-owned scope fields."""

from datetime import datetime
from ipaddress import ip_address
from typing import Literal
from urllib.parse import urlsplit
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class SourceFields(BaseModel):
    """Shared metadata shape, including previously stored valid records."""
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    name: str = Field(min_length=1, max_length=120)
    connector_kind: Literal["https_html", "github_file"] = "https_html"
    product: str = Field(pattern=r"^[a-z][a-z0-9._-]{0,63}$")
    version: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9._+-]{0,63}$")
    document_type: Literal["reference", "release_notes", "test_code"] = "reference"
    url: str = Field(min_length=1, max_length=2048)
    source_terms_url: str = Field(min_length=1, max_length=2048)

    @field_validator("url", "source_terms_url")
    @classmethod
    def public_https_page(cls, value: str) -> str:
        try:
            url = urlsplit(value)
            port = url.port
        except ValueError:
            raise ValueError("Expected a public HTTPS page URL.") from None
        if (url.scheme != "https" or not url.hostname or url.username or url.password
                or url.query or url.fragment or port not in (None, 443)
                or any(ord(c) < 33 for c in value)
                or url.hostname.lower() == "localhost" or url.hostname.lower().endswith(".localhost")):
            raise ValueError("Expected a public HTTPS page URL without credentials, query or fragment.")
        try:
            address = ip_address(url.hostname)
        except ValueError:
            pass  # Registration does not resolve DNS or fetch the page.
        else:
            if not address.is_global:
                raise ValueError("Expected a public HTTPS page URL.")
        return value

    @model_validator(mode="after")
    def python_release_url(self):
        url = urlsplit(self.url)
        if self.product == "python" and url.hostname == "docs.python.org":
            if not url.path.startswith(f"/{self.version}/"):
                raise ValueError("Python documentation URL must retain the requested release.")
        return self


class SourceCreate(SourceFields):
    @model_validator(mode="after")
    def curated_repository(self):
        if self.connector_kind == "github_file":
            from doclens.service.ingestion_io import IngestionError
            from doclens.service.repository import validate_repository_source
            try:
                validate_repository_source(self.model_dump())
            except IngestionError:
                raise ValueError("Use the reviewed pinned repository registration from the source catalog.") from None
        elif self.document_type == "test_code":
            raise ValueError("Test code requires the curated repository connector.")
        return self

    @field_validator("url", "source_terms_url")
    @classmethod
    def bounded_url_bytes(cls, value: str) -> str:
        # PostgreSQL's unique URL index has a byte budget, not a character budget.
        # 2 KiB leaves room for workspace/product/version and tuple overhead.
        if len(value.encode("utf-8")) > 2048:
            raise ValueError("New source URLs must be at most 2048 UTF-8 bytes.")
        return value


class WorkspaceRead(BaseModel):
    id: UUID
    slug: str
    name: str
    role: Literal["owner", "editor", "viewer"]


class SourceRead(SourceFields):
    model_config = ConfigDict(from_attributes=True, extra="forbid")

    schema_version: Literal["doclens-service-v1"] = "doclens-service-v1"
    id: UUID
    workspace_id: UUID
    created_by: UUID
    created_at: datetime


class SyncCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    request_key: UUID


class JobRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    schema_version: Literal["doclens-ingestion-job-v1"] = "doclens-ingestion-job-v1"
    id: UUID
    workspace_id: UUID
    source_id: UUID
    requested_by: UUID
    request_key: UUID
    status: Literal["queued", "running", "retry_wait", "succeeded", "failed"]
    stage: Literal["queued", "fetching", "parsing", "publishing", "complete", "failed"]
    attempts: int
    max_attempts: Literal[3] = 3
    available_at: datetime
    error_code: str | None
    error_message: str | None
    created_at: datetime
    updated_at: datetime
    revision_id: UUID | None = None
    delivery_attempts: int = 0
    max_delivery_attempts: Literal[20] = 20
    next_dispatch_at: datetime | None = None
    dispatch_error_code: str | None = None
    dispatch_error_message: str | None = None


class RevisionRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    schema_version: Literal["doclens-source-revision-v1"] = "doclens-source-revision-v1"
    id: UUID
    job_id: UUID
    source_id: UUID
    workspace_id: UUID
    source_snapshot: dict
    parser_config: dict
    final_url: str
    fetched_at: datetime
    raw_sha256: str
    parsed_sha256: str
    raw_size: int
    parsed_size: int
    title: str
    section_count: int
    block_count: int
    code_count: int
    raw_artifact_url: str = ""
    parsed_artifact_url: str = ""
