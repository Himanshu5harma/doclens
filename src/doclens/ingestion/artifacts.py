"""Immutable, hash-named local artifact store for raw and normalized snapshots."""

import hashlib
import os
from pathlib import Path
from tempfile import NamedTemporaryFile

from doclens.sources.base import PARSED_LIMIT, RAW_LIMIT, IngestionError


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
