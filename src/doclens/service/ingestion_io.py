"""One deliberately narrow HTTPS adapter and a bounded local artifact store."""

from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
from ipaddress import ip_address
import os
from pathlib import Path
import socket
from tempfile import NamedTemporaryFile
import time
from urllib.parse import urljoin, urlsplit

import httpx

RAW_LIMIT = 4 * 1024 * 1024
PARSED_LIMIT = 8 * 1024 * 1024
POLICY = "python-sphinx-service-v1"

# Only these application-authored messages may be persisted or returned.
ERRORS = {
    "unsupported_source": "This sync supports versioned Python HTML or the curated pinned repository source only.",
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


def validate_destination(url: str, version: str) -> None:
    try:
        parsed = urlsplit(url)
        valid = (len(url) <= 2048 and parsed.scheme == "https" and parsed.hostname == "docs.python.org"
                 and parsed.port in (None, 443) and not parsed.username and not parsed.password
                 and not parsed.query and not parsed.fragment and version in ("3.12", "3.13")
                 and parsed.path.startswith(f"/{version}/") and parsed.path.endswith(".html")
                 and not any(ord(c) < 33 for c in url) and "%" not in parsed.path
                 and "\\" not in url and all(part not in (".", "..") for part in parsed.path.split("/")))
    except ValueError:
        valid = False
    if not valid:
        raise IngestionError("unsafe_destination")


def validate_source(source: dict) -> None:
    if source["connector_kind"] != "https_html" or source["product"] != "python":
        raise IngestionError("unsupported_source")
    validate_destination(source["url"], source["version"])


def public_addresses(host: str) -> list[str]:
    try:
        addresses = sorted({row[4][0] for row in socket.getaddrinfo(host, 443, type=socket.SOCK_STREAM)},
                           key=lambda address: (":" in address, address))
    except OSError:
        raise IngestionError("network_error", retryable=True) from None
    if not addresses or any(not ip_address(address).is_global for address in addresses):
        raise IngestionError("unsafe_destination")
    return addresses


class PinnedTransport(httpx.BaseTransport):
    """Connect to a checked public IP, retaining the approved Host/TLS identity.

    Pinning avoids a second DNS lookup between validation and connection. The
    HTTPX transport still owns TLS verification, sockets and timeout handling.
    """
    def __init__(self, resolver=public_addresses):
        self.resolver = resolver
        self.transport = httpx.HTTPTransport(retries=0, trust_env=False)

    def handle_request(self, request):
        address = self.resolver(request.url.host)[0]
        pinned = httpx.Request(request.method, request.url.copy_with(host=address),
            headers={**request.headers, "host": request.url.host}, stream=request.stream,
            extensions={**request.extensions, "sni_hostname": request.url.host})
        return self.transport.handle_request(pinned)

    def close(self):
        self.transport.close()


@dataclass(frozen=True)
class Snapshot:
    content: bytes
    final_url: str
    fetched_at: datetime


def fetch_python(source: dict, *, transport=None, clock=time.monotonic) -> Snapshot:
    validate_source(source)
    current = source["url"]
    deadline = clock() + 30
    try:
        with httpx.Client(transport=transport or PinnedTransport(), timeout=httpx.Timeout(5),
                          follow_redirects=False, trust_env=False,
                          headers={"User-Agent": "DocLens/0.1 (curated documentation ingestion)",
                                   "Accept": "text/html", "Accept-Encoding": "identity"}) as client:
            for redirect in range(3):
                validate_destination(current, source["version"])
                if clock() >= deadline:
                    raise IngestionError("network_error", retryable=True)
                with client.stream("GET", current) as response:
                    if response.status_code in (301, 302, 303, 307, 308):
                        if redirect == 2 or "location" not in response.headers:
                            raise IngestionError("unsafe_destination")
                        current = urljoin(current, response.headers["location"])
                        continue  # Validate before connecting or reading a redirect body.
                    if response.status_code == 429 or 500 <= response.status_code < 600:
                        raise IngestionError("http_temporary", retryable=True)
                    if response.status_code != 200:
                        raise IngestionError("http_rejected")
                    if (response.headers.get("content-type", "").split(";")[0].strip().lower() not in
                            ("text/html", "application/xhtml+xml")
                            or response.headers.get("content-encoding", "identity").lower() != "identity"):
                        raise IngestionError("invalid_html")
                    length = response.headers.get("content-length")
                    if length is not None and (not length.isdecimal() or int(length) > RAW_LIMIT):
                        raise IngestionError("size_limit")
                    content = bytearray()
                    for piece in response.iter_raw(chunk_size=64 * 1024):
                        if clock() >= deadline:
                            raise IngestionError("network_error", retryable=True)
                        if len(content) + len(piece) > RAW_LIMIT:
                            raise IngestionError("size_limit")
                        content.extend(piece)
                    if not content.strip():
                        raise IngestionError("invalid_html")
                    return Snapshot(bytes(content), current, datetime.now(timezone.utc))
    except (httpx.HTTPError, OSError):
        # Never expose request URLs, server bodies, headers or exception reprs.
        raise IngestionError("network_error", retryable=True) from None
    raise IngestionError("unsafe_destination")


class ArtifactStore:
    """Trusted local filesystem, immutable hash-named files, no user paths."""
    def __init__(self, root: Path):
        self.root = root.resolve()

    def _path(self, key):
        path = (self.root / key).resolve()
        if not path.is_relative_to(self.root) or path == self.root:
            raise IngestionError("artifact_error")
        return path

    def put(self, prefix: str, content: bytes, kind: str) -> tuple[str, str]:
        limit = RAW_LIMIT if kind == "raw" else PARSED_LIMIT
        if not content or len(content) > limit:
            raise IngestionError("size_limit")
        digest = hashlib.sha256(content).hexdigest()
        key = f"{prefix}/{digest}.{kind}"
        path = self._path(key)
        temporary = None
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            with NamedTemporaryFile(dir=path.parent, delete=False) as stream:
                temporary = Path(stream.name)
                stream.write(content)
                stream.flush()
                os.fsync(stream.fileno())
            try:
                os.link(temporary, path)  # Atomic create, never overwrite an existing snapshot.
            except FileExistsError:
                pass
            self.read(key, digest, len(content), limit=limit)
        except OSError:
            raise IngestionError("artifact_error") from None
        finally:
            if temporary is not None:
                temporary.unlink(missing_ok=True)
        return key, digest

    def read(self, key, digest, size, *, limit=PARSED_LIMIT) -> bytes:
        try:
            path = self._path(key)
            if not 0 < size <= limit or path.stat().st_size != size:
                raise IngestionError("artifact_error")
            with path.open("rb") as stream:
                content = stream.read(limit + 1)
            if len(content) != size or hashlib.sha256(content).hexdigest() != digest:
                raise IngestionError("artifact_error")
            return content
        except OSError:
            raise IngestionError("artifact_error") from None
