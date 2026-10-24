"""Read the curated source manifest."""

import json
from pathlib import Path
from urllib.parse import urlsplit


def load_sources(manifest_path: Path) -> list[dict]:
    """Load and check source records before any downloads begin."""
    text = manifest_path.read_text(encoding="utf-8")
    manifest = json.loads(text)
    if not isinstance(manifest, dict) or not isinstance(manifest.get("sources"), list):
        raise ValueError("Manifest must contain a 'sources' list.")

    sources = manifest["sources"]
    if not sources:
        raise ValueError("Manifest must contain at least one source.")

    required = (
        "source_id", "product", "version", "document_type",
        "url", "local_path", "source_terms_url",
    )
    source_ids = set()
    local_paths = set()
    for index, source in enumerate(sources, start=1):
        if not isinstance(source, dict):
            raise ValueError(f"Source {index} must be an object.")
        for field in required:
            if not isinstance(source.get(field), str) or not source[field].strip():
                raise ValueError(f"Source {index}: '{field}' must be a nonempty string.")

        for field in ("url", "source_terms_url"):
            url = urlsplit(source[field])
            if url.scheme != "https" or not url.hostname or url.fragment:
                raise ValueError(f"Source {index}: '{field}' must be an HTTPS page URL without a fragment.")

        path = Path(source["local_path"])
        if path.is_absolute() or path.parts[:2] != ("data", "raw") or ".." in path.parts or len(path.parts) < 3:
            raise ValueError(f"Source {index}: 'local_path' must be a file under data/raw/.")
        if path.suffix.lower() not in (".html", ".htm", ".xhtml"):
            raise ValueError(f"Source {index}: 'local_path' must name an HTML file.")
        if source["source_id"] in source_ids or path in local_paths:
            raise ValueError(f"Source {index}: duplicate source ID or local path.")
        source_ids.add(source["source_id"])
        local_paths.add(path)

    return sources
