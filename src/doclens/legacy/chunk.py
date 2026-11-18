"""Baseline file pipeline: check local provenance and write chunk bundles under data/."""

import hashlib
import json
from dataclasses import asdict
from pathlib import Path

from doclens.domain.chunking import ChunkPolicy, chunk_document
from doclens.domain.records import (
    Chunk,
    document_from_dict,
)
from doclens.legacy.files import write_atomic


def chunk_source(source: dict, *, root: Path, policy: ChunkPolicy = ChunkPolicy()) -> tuple[Path, list[Chunk]]:
    """Check local provenance, load typed records, and atomically write chunks."""
    root = root.resolve()
    raw_path = (root / source["local_path"]).resolve()
    if not raw_path.is_relative_to(root / "data" / "raw"):
        raise ValueError("Raw source path must stay under data/raw/.")
    relative_path = raw_path.relative_to(root / "data" / "raw")
    parsed_path = (root / "data" / "parsed" / relative_path).with_name(relative_path.name + ".json").resolve()
    if not parsed_path.is_relative_to(root / "data" / "parsed"):
        raise ValueError("Parsed source path must stay under data/parsed/.")
    parsed_bytes = parsed_path.read_bytes()
    parsed = json.loads(parsed_bytes)
    document = document_from_dict(parsed)
    metadata_path = raw_path.with_name(raw_path.name + ".metadata.json")
    metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    if (
        not isinstance(metadata, dict)
        or parsed["source"] != metadata
        or any(metadata.get(field) != value for field, value in source.items())
    ):
        raise ValueError(f"Source {source['source_id']}: parsed provenance is stale or mismatched; run ingest again.")
    raw = raw_path.read_bytes()
    if metadata.get("sha256") != hashlib.sha256(raw).hexdigest() or metadata.get("size_bytes") != len(raw):
        raise ValueError(f"Source {source['source_id']}: raw content does not match metadata; run ingest again.")

    chunks = chunk_document(document, policy)
    destination = (root / "data" / "chunks" / policy.directory / relative_path).with_name(relative_path.name + ".json").resolve()
    if not destination.is_relative_to(root / "data" / "chunks" / policy.directory):
        raise ValueError("Chunk outputs must stay under the policy's data/chunks/ directory.")
    bundle = {
        "schema_version": 1, "policy": policy.to_dict(), "policy_id": policy.policy_id,
        "parsed_file_sha256": hashlib.sha256(parsed_bytes).hexdigest(),
        "chunks": [asdict(chunk) for chunk in chunks],
    }
    write_atomic(destination, (json.dumps(bundle, indent=2, ensure_ascii=False) + "\n").encode("utf-8"))
    return destination, chunks
