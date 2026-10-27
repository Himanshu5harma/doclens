"""Typed records at the boundary between parsed documents and retrieval inputs."""

import hashlib
import json
import re
from dataclasses import asdict, dataclass
from enum import StrEnum
from urllib.parse import quote


def content_digest(value: object) -> str:
    """Fingerprint structured content without depending on dictionary order."""
    encoded = json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def citation_url(page_url: str, anchor: str | None) -> str:
    return f"{page_url}#{quote(anchor)}" if anchor else page_url


class BlockKind(StrEnum):
    PARAGRAPH = "paragraph"
    CODE = "code"
    SIGNATURE = "signature"
    LIST_ITEM = "list_item"
    TABLE_ROW = "table_row"


@dataclass(frozen=True)
class Source:
    source_id: str
    product: str
    version: str
    document_type: str
    url: str
    content_hash: str  # SHA-256 of the original HTML bytes.
    fetched_at: str
    source_terms_url: str


@dataclass(frozen=True)
class Block:
    kind: BlockKind
    text: str
    anchor: str | None
    url: str


@dataclass(frozen=True)
class Section:
    heading: str
    level: int
    heading_path: tuple[str, ...]
    anchor: str | None
    url: str
    blocks: tuple[Block, ...]


@dataclass(frozen=True)
class Document:
    source: Source
    title: str
    sections: tuple[Section, ...]
    content_hash: str  # Parsed title/sections, excluding fetch metadata.


@dataclass(frozen=True)
class ChunkPiece:
    kind: BlockKind
    text: str
    anchor: str | None
    url: str
    block_index: int
    start_char: int  # Half-open offsets into the original block's text.
    end_char: int


@dataclass(frozen=True)
class Chunk:
    chunk_id: str
    source: Source
    document_title: str
    document_content_hash: str
    policy_id: str
    section_index: int
    section_anchor: str | None
    heading_path: tuple[str, ...]
    anchor: str | None
    url: str
    pieces: tuple[ChunkPiece, ...]
    text: str
    content_hash: str  # SHA-256 of rendered text, including heading context.
    oversized: bool


@dataclass(frozen=True)
class SearchResult:
    rank: int
    score: float
    chunk_id: str
    source: Source
    document_title: str
    heading_path: tuple[str, ...]
    url: str
    text: str
    content_hash: str
    oversized: bool


@dataclass(frozen=True)
class SearchResponse:
    query: str
    product: str
    version: str
    candidate_count: int
    model_id: str
    model_revision: str
    results: tuple[SearchResult, ...]


def _object(value: object, label: str) -> dict:
    if not isinstance(value, dict):
        raise ValueError(f"{label} must be an object.")
    return value


def _text(value: object, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{label} must be a nonempty string.")
    return value


def _list(value: object, label: str) -> list:
    if not isinstance(value, list):
        raise ValueError(f"{label} must be a list.")
    return value


def _location(record: dict, page_url: str) -> tuple[str | None, str]:
    anchor = record.get("anchor")
    if anchor is not None:
        anchor = _text(anchor, "anchor")
    url = _text(record.get("url"), "citation URL")
    if url != citation_url(page_url, anchor):
        raise ValueError("Section/block citation URL must match the source page and anchor.")
    return anchor, url


def document_from_dict(value: object) -> Document:
    """Validate existing parsed JSON, then construct immutable typed records.

    Type annotations alone do not validate JSON. Keep these checks at the file
    boundary; the pure chunker can then work with known record shapes.
    """
    data = _object(value, "Document")
    if type(data.get("schema_version")) is not int or data["schema_version"] != 1:
        raise ValueError("Unsupported parsed document schema; expected version 1.")
    raw_source = _object(data.get("source"), "source")
    source_fields = {
        field: _text(raw_source.get(field), f"source.{field}")
        for field in (
            "source_id", "product", "version", "document_type", "url",
            "fetched_at", "source_terms_url",
        )
    }
    raw_hash = _text(raw_source.get("sha256"), "source.sha256")
    if not re.fullmatch(r"[0-9a-f]{64}", raw_hash):
        raise ValueError("source.sha256 must be a lowercase SHA-256 digest.")
    source = Source(**source_fields, content_hash=raw_hash)
    title = _text(data.get("title"), "title")
    sections = []
    for raw_section in _list(data.get("sections"), "sections"):
        section = _object(raw_section, "section")
        heading = _text(section.get("heading"), "heading")
        level = section.get("level")
        if type(level) is not int or not 1 <= level <= 6:
            raise ValueError("Heading level must be an integer from 1 to 6.")
        path = tuple(_text(part, "heading_path entry") for part in _list(section.get("heading_path"), "heading_path"))
        if not path or path[-1] != heading:
            raise ValueError("heading_path must end with the section heading.")
        anchor, url = _location(section, source.url)
        blocks = []
        for raw_block in _list(section.get("blocks"), "blocks"):
            block = _object(raw_block, "block")
            block_anchor, block_url = _location(block, source.url)
            blocks.append(Block(
                kind=BlockKind(block.get("kind")),
                text=_text(block.get("text"), "block.text"),
                anchor=block_anchor, url=block_url,
            ))
        sections.append(Section(heading, level, path, anchor, url, tuple(blocks)))
    if not any(section.blocks for section in sections):
        raise ValueError("Document must contain at least one content block.")
    section_records = tuple(sections)
    parsed_hash = content_digest({"title": title, "sections": [asdict(section) for section in section_records]})
    return Document(source, title, section_records, parsed_hash)
