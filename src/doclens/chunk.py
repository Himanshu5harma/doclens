"""An inspectable, section/anchor-aware character chunking baseline."""

import hashlib
import json
from collections import Counter
from dataclasses import asdict, dataclass
from pathlib import Path

from doclens.files import write_atomic
from doclens.records import (
    Block, BlockKind, Chunk, ChunkPiece, Document,
    citation_url, content_digest, document_from_dict,
)


@dataclass(frozen=True)
class ChunkPolicy:
    max_chars: int = 2000

    def __post_init__(self) -> None:
        if type(self.max_chars) is not int or self.max_chars <= 0:
            raise ValueError("max_chars must be a positive integer.")

    def to_dict(self) -> dict:
        return {
            "name": "section-anchor-v1", "max_chars": self.max_chars,
            "size_unit": "unicode_characters", "overlap": 0,
            "oversized_prose": "split_at_whitespace_then_characters",
            "oversized_structured_blocks": "keep_whole_and_flag",
        }

    @property
    def policy_id(self) -> str:
        return content_digest(self.to_dict())

    @property
    def directory(self) -> str:
        return f"section-anchor-v1-{self.max_chars}"


def _pieces(block: Block, block_index: int, capacity: int) -> list[ChunkPiece]:
    """Split only prose, preserving exact text via contiguous source offsets."""
    pieces = []
    start = 0
    while start < len(block.text):
        end = len(block.text)
        if block.kind in (BlockKind.PARAGRAPH, BlockKind.LIST_ITEM) and end - start > capacity:
            end = start + capacity
            # Include the whitespace in the preceding piece so no characters
            # are stripped or duplicated. A long word falls back to a hard cut.
            boundary = next((i + 1 for i in range(end - 1, start - 1, -1) if block.text[i].isspace()), None)
            if boundary is not None:
                end = boundary
        pieces.append(ChunkPiece(
            kind=block.kind, text=block.text[start:end], anchor=block.anchor, url=block.url,
            block_index=block_index, start_char=start, end_char=end,
        ))
        start = end
    return pieces


def chunk_document(document: Document, policy: ChunkPolicy = ChunkPolicy()) -> list[Chunk]:
    """Greedily pack blocks without crossing section or effective-anchor groups."""
    chunks = []
    occurrences = Counter()
    policy_id = policy.policy_id
    for section_index, section in enumerate(document.sections):
        pending = []
        current_anchor = None
        prefix = ""
        size = 0

        def flush() -> None:
            nonlocal pending, size
            if not pending:
                return
            text = prefix + "\n\n".join(piece.text for piece in pending)
            text_hash = hashlib.sha256(text.encode("utf-8")).hexdigest()
            identity = content_digest({
                "product": document.source.product, "version": document.source.version,
                "source_id": document.source.source_id, "source_url": document.source.url,
                "policy_id": policy_id, "heading_path": section.heading_path,
                "anchor": current_anchor, "content_hash": text_hash,
                "pieces": [{"kind": p.kind, "text": p.text, "anchor": p.anchor, "url": p.url} for p in pending],
            })
            # Distinguish identical repeated passages without making every ID
            # depend on document-wide offsets or the raw HTML snapshot hash.
            occurrence = occurrences[identity]
            occurrences[identity] += 1
            chunk_id = "chunk-" + content_digest({"identity": identity, "occurrence": occurrence})
            chunks.append(Chunk(
                chunk_id=chunk_id, source=document.source, document_title=document.title,
                document_content_hash=document.content_hash, policy_id=policy_id,
                section_index=section_index, section_anchor=section.anchor,
                heading_path=section.heading_path, anchor=current_anchor,
                url=citation_url(document.source.url, current_anchor),
                pieces=tuple(pending), text=text, content_hash=text_hash,
                oversized=len(text) > policy.max_chars,
            ))
            pending = []
            size = len(prefix)

        for block_index, block in enumerate(section.blocks):
            anchor = block.anchor or section.anchor
            if not pending or anchor != current_anchor:
                flush()
                current_anchor = anchor
                headings = section.heading_path
                if headings[0] != document.title:
                    headings = (document.title, *headings)
                context = " > ".join(headings)
                if anchor and anchor != section.anchor:
                    context += "\n" + anchor
                prefix = context + "\n\n"
                size = len(prefix)
                if size >= policy.max_chars:
                    raise ValueError(
                        f"Source {document.source.source_id}: heading/anchor context uses "
                        f"{size} characters; increase max_chars above {size}."
                    )
            for piece in _pieces(block, block_index, policy.max_chars - len(prefix)):
                addition = len(piece.text) + (2 if pending else 0)
                if pending and size + addition > policy.max_chars:
                    flush()
                    addition = len(piece.text)
                pending.append(piece)
                size += addition
                if size > policy.max_chars:
                    flush()  # Oversized code/signature/row is always alone.
        flush()
    return chunks


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
