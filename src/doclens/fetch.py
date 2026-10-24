"""Download curated HTML sources and record their provenance."""

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from tempfile import NamedTemporaryFile
from urllib.request import Request, urlopen


def _write_atomic(path: Path, content: bytes) -> None:
    """Replace a file only after its complete contents have been written."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with NamedTemporaryFile(dir=path.parent, delete=False) as temporary:
        temporary_path = Path(temporary.name)
        try:
            temporary.write(content)
            temporary.flush()
        except BaseException:
            temporary_path.unlink(missing_ok=True)
            raise
    try:
        temporary_path.replace(path)
    finally:
        temporary_path.unlink(missing_ok=True)


def fetch_source(source: dict, *, root: Path) -> dict:
    """Save one HTML page and its metadata, returning the metadata record.

    Local paths are resolved relative to the repository root supplied by the
    caller. Repeated downloads replace the same files; they do not append copies.
    """
    root = root.resolve()
    destination = (root / source["local_path"]).resolve()
    if not destination.is_relative_to(root / "data" / "raw"):
        raise ValueError(f"Source {source['source_id']}: destination must stay under data/raw/.")

    request = Request(source["url"], headers={"User-Agent": "DocLens/0.1 (learning project)"})
    with urlopen(request, timeout=30) as response:
        content_type = response.headers.get_content_type()
        if content_type not in ("text/html", "application/xhtml+xml"):
            raise ValueError(f"Source {source['source_id']}: expected HTML, received {content_type}.")
        content = response.read()
        final_url = response.geturl()
        status = response.status

    if not content.strip():
        raise ValueError(f"Source {source['source_id']}: received an empty page.")

    metadata = {
        **source,
        "final_url": final_url,
        "fetched_at": datetime.now(timezone.utc).isoformat(),
        "http_status": status,
        "content_type": content_type,
        "size_bytes": len(content),
        "sha256": hashlib.sha256(content).hexdigest(),
    }
    metadata_path = destination.with_name(destination.name + ".metadata.json")
    metadata_bytes = (json.dumps(metadata, indent=2, ensure_ascii=False) + "\n").encode("utf-8")
    _write_atomic(destination, content)
    _write_atomic(metadata_path, metadata_bytes)
    return metadata
