"""Download curated HTML sources and record their provenance."""

import hashlib
import json
from datetime import datetime, timezone
from http.client import HTTPException
from pathlib import Path
from urllib.parse import urlsplit
from urllib.request import Request, urlopen

from doclens.files import write_atomic


def _validate_final_url(source: dict, final_url: str) -> None:
    """Keep a redirect on the source host and, for Python, its release line."""
    requested = urlsplit(source["url"])
    final = urlsplit(final_url)
    if (
        final.scheme != "https"
        or final.hostname != requested.hostname
        or (final.port or 443) != (requested.port or 443)
        or final.username is not None
        or final.password is not None
    ):
        raise ValueError(
            f"Source {source['source_id']}: final URL must stay on the source's HTTPS host: {final_url}"
        )
    if source["product"] == "python" and not final.path.startswith(f"/{source['version']}/"):
        raise ValueError(
            f"Source {source['source_id']}: final URL must retain Python version "
            f"{source['version']}: {final_url}"
        )


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
    try:
        with urlopen(request, timeout=30) as response:
            final_url = response.geturl()
            _validate_final_url(source, final_url)
            content_type = response.headers.get_content_type()
            if content_type not in ("text/html", "application/xhtml+xml"):
                raise ValueError(f"Source {source['source_id']}: expected HTML, received {content_type}.")
            content = response.read()
            status = response.status
    except HTTPException as error:
        # The CLI already handles OSError. Give protocol failures the same
        # readable failure path, with the source that needs to be retried.
        raise OSError(f"Source {source['source_id']}: HTTP response failed: {error}") from error

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
    write_atomic(destination, content)
    write_atomic(metadata_path, metadata_bytes)
    return metadata
