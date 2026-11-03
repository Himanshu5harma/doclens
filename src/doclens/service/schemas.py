"""Runtime validation for the registration API, with no caller-owned scope fields."""

from datetime import datetime
from ipaddress import ip_address
from typing import Literal
from urllib.parse import urlsplit
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class SourceCreate(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    name: str = Field(min_length=1, max_length=120)
    connector_kind: Literal["https_html"] = "https_html"
    product: str = Field(pattern=r"^[a-z][a-z0-9._-]{0,63}$")
    version: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9._+-]{0,63}$")
    document_type: Literal["reference", "release_notes"] = "reference"
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


class WorkspaceRead(BaseModel):
    id: UUID
    slug: str
    name: str
    role: Literal["owner", "editor", "viewer"]


class SourceRead(SourceCreate):
    model_config = ConfigDict(from_attributes=True, extra="forbid")

    schema_version: Literal["doclens-service-v1"] = "doclens-service-v1"
    id: UUID
    workspace_id: UUID
    created_by: UUID
    created_at: datetime
