"""One curated public repository file: bounded acquisition, no checkout/execution.

The allowlist is application policy, rather than caller-controlled authority,
version labels or paths. The matching registration example lives in corpus/.
"""

import ast
from datetime import datetime, timezone
import hashlib
import io
import sys
import time
from typing import Literal

import httpx
from pydantic import BaseModel, ConfigDict, Field, model_validator

from doclens.service.ingestion_io import IngestionError, PinnedTransport, Snapshot

REPOSITORY = "python/cpython"
COMMIT = "60403a5409ff2c3f3b07dd2ca91a7a3e096839c7"
FILE_PATH = "Lib/test/test_tempfile.py"
SYMBOL = "TestNamedTemporaryFile"
SOURCE_URL = f"https://github.com/{REPOSITORY}/blob/{COMMIT}/{FILE_PATH}"
TERMS_URL = f"https://github.com/{REPOSITORY}/blob/{COMMIT}/LICENSE"
RAW_URL = f"https://raw.githubusercontent.com/{REPOSITORY}/{COMMIT}/{FILE_PATH}"
EXPECTED_SHA256 = "08f33f84addf1cb7a99747857d093246973a49f238a63eeb64fe395205bd2c36"
EXPECTED_BLOB_SHA1 = "a5e182cef23dc54f534fe04dcc2aafcf0e35fe6a"
FILE_LIMIT = 256 * 1024
POLICY = "cpython-selected-class-v1"

REGISTRATION = {
    "name": "CPython 3.13.0 NamedTemporaryFile tests",
    "connector_kind": "github_file", "product": "python", "version": "3.13",
    "document_type": "test_code", "url": SOURCE_URL, "source_terms_url": TERMS_URL,
}


def validate_repository_source(source: dict) -> None:
    # Changing the reviewed release/path requires a new curation decision.
    if any(source.get(key) != value for key, value in REGISTRATION.items() if key != "name"):
        raise IngestionError("unsupported_source")


def source_metadata() -> dict:
    return {"catalog_id": "cpython-3.13.0-tempfile-tests",
            "collection_key": "python-file-processing",
            "origin": "public_repository", "authority": "official_test_code",
            "synthetic": False, "access": "workspace_membership",
            "source_release": "3.13.0", "repository": REPOSITORY,
            "commit": COMMIT, "path": FILE_PATH, "selected_symbols": [SYMBOL],
            "tests_executed": False, "acquisition_policy": "github-curated-raw-sha256-v1",
            "raw_url": RAW_URL, "expected_raw_sha256": EXPECTED_SHA256,
            "expected_git_blob_sha1": EXPECTED_BLOB_SHA1}


def git_blob_sha(content: bytes) -> str:
    return hashlib.sha1(b"blob " + str(len(content)).encode("ascii") + b"\0" + content).hexdigest()


def fetch_repository(source: dict, *, transport=None, clock=time.monotonic) -> Snapshot:
    validate_repository_source(source)
    deadline = clock() + 30
    try:
        with httpx.Client(transport=transport or PinnedTransport(), timeout=httpx.Timeout(5),
                          follow_redirects=False, trust_env=False,
                          headers={"User-Agent": "DocLens/0.1 (curated repository ingestion)",
                                   "Accept": "text/plain", "Accept-Encoding": "identity"}) as client:
            if clock() >= deadline:
                raise IngestionError("network_error", retryable=True)
            # The URL and expected hashes are reviewed policy, never response/caller paths.
            with client.stream("GET", RAW_URL) as response:
                if response.status_code == 429 or (response.status_code == 403 and
                        (response.headers.get("x-ratelimit-remaining") == "0" or "retry-after" in response.headers)):
                    raise IngestionError("repository_rate_limit")
                if 500 <= response.status_code < 600:
                    raise IngestionError("http_temporary", retryable=True)
                if response.status_code != 200:  # No redirects, fallback or automatic 4xx retry.
                    raise IngestionError("http_rejected")
                if (response.headers.get("content-type", "").split(";")[0].strip().lower()
                        not in ("text/plain", "text/x-python", "application/octet-stream")
                        or response.headers.get("content-encoding", "identity").lower() != "identity"):
                    raise IngestionError("repository_invalid")
                length = response.headers.get("content-length")
                if length is not None and (not length.isdecimal() or int(length) > FILE_LIMIT):
                    raise IngestionError("size_limit")
                content = bytearray()
                for piece in response.iter_raw(chunk_size=64 * 1024):
                    if clock() >= deadline:
                        raise IngestionError("network_error", retryable=True)
                    if len(content) + len(piece) > FILE_LIMIT:
                        raise IngestionError("size_limit")
                    content.extend(piece)
                content = bytes(content)
                if (hashlib.sha256(content).hexdigest() != EXPECTED_SHA256
                        or git_blob_sha(content) != EXPECTED_BLOB_SHA1):
                    raise IngestionError("repository_invalid")
                return Snapshot(content, RAW_URL, datetime.now(timezone.utc))
    except (httpx.HTTPError, OSError):
        raise IngestionError("network_error", retryable=True) from None
    except (ValueError, TypeError):
        raise IngestionError("repository_invalid") from None


class RepositoryLocation(BaseModel):
    """Line locations are constructed from approved metadata, not model output."""
    model_config = ConfigDict(frozen=True, extra="forbid")
    kind: Literal["repository_lines"] = "repository_lines"
    repository: Literal["python/cpython"] = REPOSITORY
    commit: Literal["60403a5409ff2c3f3b07dd2ca91a7a3e096839c7"] = COMMIT
    path: Literal["Lib/test/test_tempfile.py"] = FILE_PATH
    start_line: int = Field(ge=1)
    end_line: int = Field(ge=1)

    @model_validator(mode="after")
    def ordered(self):
        if self.end_line < self.start_line:
            raise ValueError("Line range must be ordered.")
        return self

    @property
    def anchor(self):
        return f"L{self.start_line}-L{self.end_line}"

    @property
    def url(self):
        return f"{SOURCE_URL}#{self.anchor}"


def parse_repository(content: bytes, *, source_url: str) -> dict:
    if source_url != SOURCE_URL or not content or len(content) > FILE_LIMIT:
        raise IngestionError("repository_parse")
    try:
        text = content.decode("utf-8")  # Deliberate supported encoding; no lossy replacement.
        module = ast.parse(text, filename=FILE_PATH)
        classes = [node for node in module.body if isinstance(node, ast.ClassDef) and node.name == SYMBOL]
        if len(classes) != 1:
            raise ValueError
        selected = classes[0]
        start = min([selected.lineno] + [node.lineno for node in selected.decorator_list])
        end = selected.end_lineno
        location = RepositoryLocation(start_line=start, end_line=end)
        # Keep whole original lines, including decorators, comments, indentation and CRLF.
        # Universal source newlines only: str.splitlines also splits inside e.g.
        # U+2028 string literals, which would invalidate Python's line numbers.
        code = "".join(io.StringIO(text, newline="").readlines()[start - 1:end])
    except (ValueError, TypeError, SyntaxError, RecursionError):
        raise IngestionError("repository_parse") from None
    return {
        "parser": {"name": "python-ast-selected-class", "version": 1,
                   "grammar": f"{sys.version_info.major}.{sys.version_info.minor}",
                   "selection": [SYMBOL], "selection_scope": "whole_class", "executes_code": False},
        "title": f"CPython 3.13.0: {FILE_PATH} / {SYMBOL}",
        "sections": [{"heading": SYMBOL, "level": 1, "heading_path": [FILE_PATH, SYMBOL],
                      "anchor": location.anchor, "url": location.url,
                      "location": location.model_dump(),
                      "blocks": [{"kind": "code", "language": "python", "text": code,
                                  "anchor": location.anchor, "url": location.url,
                                  "location": location.model_dump(),
                                  "content_sha256": hashlib.sha256(code.encode("utf-8")).hexdigest()}]}],
    }
