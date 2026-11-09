"""A reviewed local issue export, with attributed summaries and honest locations.

No user path, live API request, Markdown execution or public read grant lives here.
"""

from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import stat
from typing import Annotated, Literal

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, model_validator

from doclens.service.ingestion_io import IngestionError, Snapshot

SOURCE_URL = "https://github.com/python/cpython/issues/88221"
TERMS_URL = "https://docs.github.com/en/site-policy/github-terms/github-terms-of-service"
CURATION_PATH = "corpus/expanded/issues/cpython-88221-v1.json"
EXPECTED_SHA256 = "ff463229c78926804125e68a03119674d0059494e7b9a29a4af22408556bc3b8"
EXPORT_LIMIT = 64 * 1024
DEFAULT_EXPORT_ROOT = Path("data/service/issue-exports")
POLICY = "curated-historical-issue-v1"
COMMENT_IDS = frozenset((1093914525, 1093914527, 1093914529))
SHA256 = Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]
REGISTRATION = {
    "name": "Historical Python 3.8 NamedTemporaryFile issue (curated)",
    "connector_kind": "issue_export", "product": "python", "version": "3.8",
    "document_type": "issue_report", "url": SOURCE_URL, "source_terms_url": TERMS_URL,
}


class StrictRecord(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class ExportBlock(StrictRecord):
    kind: Literal["paragraph", "code"]
    text: str = Field(min_length=1, max_length=16000)
    authorship: Literal["curator_summary", "synthetic_fixture"]
    language: str | None = Field(default=None, max_length=32)

    @model_validator(mode="after")
    def code_language(self):
        if self.kind != "code" and self.language is not None:
            raise ValueError("Only code blocks have a language.")
        return self


class ExportEntry(StrictRecord):
    kind: Literal["issue", "comment"]
    comment_id: int | None
    upstream_author: str = Field(min_length=1, max_length=120)
    created_at: AwareDatetime | None
    updated_at: AwareDatetime | None
    timestamp_status: Literal["supplied", "not_supplied"]
    upstream_body_sha256: SHA256
    blocks: list[ExportBlock] = Field(min_length=1, max_length=20)

    @model_validator(mode="after")
    def identity_and_times(self):
        if ((self.kind == "issue" and self.comment_id is not None) or
                (self.kind == "comment" and self.comment_id not in COMMENT_IDS)):
            raise ValueError("Entry identity is outside the reviewed selection.")
        complete = self.created_at is not None and self.updated_at is not None
        if (self.timestamp_status == "supplied") != complete:
            raise ValueError("Timestamp status must describe the supplied data.")
        if complete and self.updated_at < self.created_at:
            raise ValueError("Update time precedes creation.")
        return self


class IssueExport(StrictRecord):
    schema_version: Literal["doclens-curated-issue-export-v1"]
    repository: Literal["python/cpython"]
    issue_number: Literal[88221]
    title: str = Field(min_length=1, max_length=200)
    issue_state: Literal["open", "closed"]
    closed_at: AwareDatetime | None
    product: Literal["python"]
    version: Literal["3.8"]
    reported_versions: list[Literal["3.8"]] = Field(min_length=1, max_length=1)
    applicability: Literal["historical_context_only"]
    observed_at: AwareDatetime
    synthetic: bool
    content_mode: Literal["curator_summaries"]
    curator: str = Field(min_length=1, max_length=120)
    independent_review: Literal[False]
    source_terms_url: Literal["https://docs.github.com/en/site-policy/github-terms/github-terms-of-service"]
    repository_terms_url: str = Field(min_length=1, max_length=2048)
    terms_note: str = Field(min_length=1, max_length=2000)
    selection_note: str = Field(min_length=1, max_length=2000)
    upstream_hash_origin: str = Field(min_length=1, max_length=300)
    entries: list[ExportEntry] = Field(min_length=2, max_length=4)

    @model_validator(mode="after")
    def selection(self):
        if self.entries[0].kind != "issue" or any(e.kind != "comment" for e in self.entries[1:]):
            raise ValueError("Select an issue overview followed by comments.")
        ids = [e.comment_id for e in self.entries[1:]]
        if len(ids) != len(set(ids)):
            raise ValueError("Duplicate comment identity.")
        if self.issue_state == "open" and self.closed_at is not None:
            raise ValueError("Open issue has a closure date.")
        created = self.entries[0].created_at
        if self.closed_at is not None and created is not None and self.closed_at < created:
            raise ValueError("Closure precedes issue creation.")
        times = [t for e in self.entries for t in (e.created_at, e.updated_at) if t is not None]
        if self.closed_at is not None:
            times.append(self.closed_at)
        if any(t > self.observed_at for t in times):
            raise ValueError("Source time is after this observation.")
        if not self.synthetic and any(b.authorship != "curator_summary" for e in self.entries for b in e.blocks):
            raise ValueError("Real curated exports must identify summaries as curator-authored.")
        return self


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("Duplicate JSON key.")
        result[key] = value
    return result


def _reject_constant(value):
    raise ValueError("Nonfinite JSON values are unsupported.")


def load_export(content: bytes) -> IssueExport:
    if not content or len(content) > EXPORT_LIMIT:
        raise IngestionError("issue_export_invalid")
    try:
        # Reject duplicate keys/nonfinite JSON before Pydantic's JSON-mode date parsing.
        value = json.loads(content.decode("utf-8"), object_pairs_hook=_unique_object,
                           parse_constant=_reject_constant)
        return IssueExport.model_validate_json(json.dumps(value), strict=True)
    except (ValueError, TypeError, RecursionError):
        raise IngestionError("issue_export_invalid") from None


def validate_issue_source(source: dict) -> None:
    if any(source.get(k) != v for k, v in REGISTRATION.items() if k != "name"):
        raise IngestionError("unsupported_source")


def fetch_issue_export(source: dict, *, export_root: Path = DEFAULT_EXPORT_ROOT) -> Snapshot:
    validate_issue_source(source)
    path = Path(export_root) / "reviewed" / f"{EXPECTED_SHA256}.raw"
    try:
        # Fixed hash filename; no request-controlled path or symlink/file-type following.
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
        try:
            info = os.fstat(fd)
            if not stat.S_ISREG(info.st_mode) or not 0 < info.st_size <= EXPORT_LIMIT:
                raise IngestionError("issue_export_invalid")
            with os.fdopen(fd, "rb", closefd=False) as stream:
                content = stream.read(EXPORT_LIMIT + 1)
        finally:
            os.close(fd)  # Also close when a directory/device is rejected before wrapping.
        if len(content) > EXPORT_LIMIT or hashlib.sha256(content).hexdigest() != EXPECTED_SHA256:
            raise IngestionError("issue_export_invalid")
        load_export(content)
        return Snapshot(content, SOURCE_URL, datetime.now(timezone.utc))
    except OSError:
        raise IngestionError("issue_export_unavailable") from None


def issue_source_metadata(content: bytes) -> dict:
    value = load_export(content)
    return {"catalog_id": "cpython-88221-curated-v1", "collection_key": "python-file-processing-history",
            "origin": "curated_public_issue" if not value.synthetic else "synthetic_fixture",
            "authority": "curated_historical_issue" if not value.synthetic else "synthetic_test_fixture",
            "synthetic": value.synthetic, "access": "workspace_membership",
            "applicability": value.applicability, "reported_versions": value.reported_versions,
            "repository": value.repository, "issue_number": value.issue_number,
            "issue_state_at_observation": value.issue_state, "closed_at": value.closed_at.isoformat() if value.closed_at else None,
            "upstream_observed_at": value.observed_at.isoformat(), "curator": value.curator,
            "issue_created_at": value.entries[0].created_at.isoformat() if value.entries[0].created_at else None,
            "issue_updated_at": value.entries[0].updated_at.isoformat() if value.entries[0].updated_at else None,
            "independent_review": False, "content_mode": value.content_mode,
            "current_release_guidance": False, "acquisition_policy": "operator-reviewed-issue-export-v1",
            "curation_path": CURATION_PATH, "expected_export_sha256": EXPECTED_SHA256,
            "selected_comment_ids": [e.comment_id for e in value.entries[1:]],
            "comment_timestamps_complete": all(e.timestamp_status == "supplied" for e in value.entries[1:]),
            "repository_terms_url": value.repository_terms_url, "terms_note": value.terms_note,
            "selection_note": value.selection_note, "upstream_hash_origin": value.upstream_hash_origin}


class IssueLocation(StrictRecord):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)
    kind: Literal["issue", "issue_comment"]
    repository: Literal["python/cpython"] = "python/cpython"
    issue_number: Literal[88221] = 88221
    comment_id: int | None
    upstream_body_sha256: SHA256
    created_at: AwareDatetime | None
    updated_at: AwareDatetime | None

    @model_validator(mode="after")
    def identity(self):
        if (self.kind == "issue" and self.comment_id is not None) or (
                self.kind == "issue_comment" and self.comment_id not in COMMENT_IDS):
            raise ValueError("Location identity mismatch.")
        return self

    @property
    def anchor(self):
        return f"issuecomment-{self.comment_id}" if self.comment_id is not None else None

    @property
    def url(self):
        return SOURCE_URL + (f"#{self.anchor}" if self.anchor else "")


def parse_issue_export(content: bytes, *, source_url: str) -> dict:
    if source_url != SOURCE_URL:
        raise IngestionError("issue_export_invalid")
    value = load_export(content)
    sections = []
    for entry in value.entries:
        location = IssueLocation(kind="issue" if entry.kind == "issue" else "issue_comment",
            comment_id=entry.comment_id, upstream_body_sha256=entry.upstream_body_sha256,
            created_at=entry.created_at, updated_at=entry.updated_at)
        heading = "Issue overview" if entry.kind == "issue" else f"Comment {entry.comment_id} by {entry.upstream_author}"
        blocks = [{**block.model_dump(exclude_none=True), "anchor": location.anchor, "url": location.url,
                   "location": location.model_dump(mode="json"),
                   "content_sha256": hashlib.sha256(block.text.encode("utf-8")).hexdigest()}
                  for block in entry.blocks]
        sections.append({"heading": heading, "level": 1,
                         "heading_path": ["Historical Python 3.8 issue", value.title, heading],
                         "anchor": location.anchor, "url": location.url,
                         "location": location.model_dump(mode="json"), "blocks": blocks})
    return {"parser": {"name": "curated-issue-json", "version": 1, "export_schema": value.schema_version,
                       "content_mode": value.content_mode, "selected_comment_count": len(value.entries) - 1},
            "title": f"Historical Python 3.8 issue #88221: {value.title}", "sections": sections}
