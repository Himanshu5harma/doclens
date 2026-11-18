"""Source adapter port, acquisition snapshot and the fixed, safe ingestion error vocabulary."""

from dataclasses import dataclass
from datetime import datetime
from typing import Callable

RAW_LIMIT = 4 * 1024 * 1024
PARSED_LIMIT = 8 * 1024 * 1024

# Only these application-authored messages may be persisted or returned.
ERRORS = {
    "unsupported_source": "This sync supports versioned Python HTML, the curated repository file or the curated issue export only.",
    "unsafe_destination": "The source or redirect is outside the permitted versioned destination.",
    "network_error": "The document request was interrupted or timed out.",
    "http_temporary": "The document server is temporarily unavailable or rate limited.",
    "http_rejected": "The document server did not return a successful response.",
    "invalid_html": "The response is not a supported nonempty HTML document.",
    "size_limit": "The document exceeds the configured artifact size limit.",
    "parse_error": "The document does not match the supported Python/Sphinx structure.",
    "repository_invalid": "The repository response did not match the pinned commit, path or file content.",
    "repository_parse": "The Python file could not be parsed or the selected class was missing.",
    "repository_rate_limit": "GitHub access is rate limited; this job stopped. Wait before requesting a new sync.",
    "issue_export_invalid": "The issue export is malformed or does not match the reviewed identity, scope or hash.",
    "issue_export_unavailable": "The reviewed issue export is unavailable; prepare the operator-owned frozen export first.",
    "artifact_error": "A local artifact could not be saved or verified.",
    "worker_lost": "The worker claim expired before completion.",
    "dispatch_exhausted": "Task delivery attempts were exhausted; request a new sync to retry.",
    "access_revoked": "The requesting principal no longer has source-sync permission.",
    "internal_error": "Ingestion could not complete; no partial revision was published.",
}


class IngestionError(Exception):
    def __init__(self, code: str, *, retryable: bool = False):
        self.code = code
        self.retryable = retryable
        super().__init__(ERRORS[code])


@dataclass(frozen=True)
class Snapshot:
    content: bytes
    final_url: str
    fetched_at: datetime


@dataclass(frozen=True)
class SourceAdapter:
    fetch: Callable
    parse: Callable
    document_schema: str
    policy: str
    metadata: Callable[[bytes], dict] = lambda content: {}
    provenance: Callable[[bytes], dict] = lambda content: {}
