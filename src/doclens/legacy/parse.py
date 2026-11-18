"""Baseline file pipeline: verify a downloaded snapshot and save parsed JSON under data/."""

import hashlib
import json
from pathlib import Path

from doclens.legacy.files import write_atomic
from doclens.sources.python_docs import parse_html


def parse_source(source: dict, *, root: Path) -> dict:
    """Verify a downloaded snapshot, then save its structured representation."""
    root = root.resolve()
    raw_path = (root / source["local_path"]).resolve()
    if not raw_path.is_relative_to(root / "data" / "raw"):
        raise ValueError(f"Source {source['source_id']}: raw file must stay under data/raw/.")
    content = raw_path.read_bytes()
    metadata_path = raw_path.with_name(raw_path.name + ".metadata.json")
    metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    if not isinstance(metadata, dict):
        raise ValueError(f"Source {source['source_id']}: metadata must be an object.")
    if any(metadata.get(field) != value for field, value in source.items()):
        raise ValueError(f"Source {source['source_id']}: metadata differs from the manifest; run fetch again.")
    if (
        metadata.get("sha256") != hashlib.sha256(content).hexdigest()
        or metadata.get("size_bytes") != len(content)
    ):
        raise ValueError(f"Source {source['source_id']}: raw content does not match metadata; run fetch again.")

    document = parse_html(content, source_url=source["url"])
    document["source"] = metadata
    relative_path = raw_path.relative_to(root / "data" / "raw")
    destination = (root / "data" / "parsed" / relative_path).with_name(
        relative_path.name + ".json"
    ).resolve()
    if not destination.is_relative_to(root / "data" / "parsed"):
        raise ValueError("Parsed files must stay under data/parsed/.")
    write_atomic(destination, (json.dumps(document, indent=2, ensure_ascii=False) + "\n").encode("utf-8"))
    return document
