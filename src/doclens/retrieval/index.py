"""Stage 4: index ready service revisions and search them with exact, scoped pgvector cosine.

Flow: published revision -> verified parsed artifact -> typed service document
(HTML v1 / repository v2 / issue v3) -> unchanged `section-anchor-v1` chunker ->
token preflight (no truncation) -> local encoder -> one transaction that writes
the revision's complete chunk set. Search applies membership, workspace,
current publication, product/version and index configuration in SQL *before*
ordering by distance; there is no approximate index and no post-filtering.
"""

from dataclasses import asdict, dataclass
import hashlib
import json
from uuid import NAMESPACE_URL, UUID, uuid5

from sqlalchemy import exists, func, select
from sqlalchemy.dialects.postgresql import insert

from doclens.domain.chunking import ChunkPolicy, chunk_document
from doclens.retrieval.embeddings import EmbeddingConfig, unit_vector
from doclens.retrieval.ports import Encoder
from doclens.domain.records import (
    Block, BlockKind, Chunk, Document, Section, Source, _list, _location, _object, _text, content_digest,
)
from doclens.db.models import (
    EMBEDDING_DIMENSIONS, Membership, Principal, RegisteredSource, RetrievalChunk, RevisionIndex,
    SourcePublication, SourceRevision,
)

INDEX_SCHEMA = "doclens-service-retrieval-v1"
DOCUMENT_SCHEMAS = ("doclens-service-document-v1", "doclens-service-document-v2", "doclens-service-document-v3")
LOCATION_KINDS = {"doclens-service-document-v2": ("repository_lines",),
                  "doclens-service-document-v3": ("issue", "issue_comment")}


class IndexingError(ValueError):
    """A revision cannot be indexed as-is; nothing was written."""


@dataclass(frozen=True)
class RetrievalConfig:
    embedding: EmbeddingConfig
    policy: ChunkPolicy = ChunkPolicy()

    def __post_init__(self):
        if self.embedding.dimensions != EMBEDDING_DIMENSIONS:
            raise ValueError(f"Schema stores vector({EMBEDDING_DIMENSIONS}); a different model needs a new migration.")

    def to_dict(self) -> dict:
        return {"schema": INDEX_SCHEMA, "embedding": asdict(self.embedding),
                "chunk_policy": self.policy.to_dict(), "chunk_policy_id": self.policy.policy_id,
                "similarity": "cosine", "search": "exact"}

    @property
    def index_id(self) -> str:
        # Any model/prefix/policy change yields a separate, non-mixing index.
        return content_digest(self.to_dict())


@dataclass(frozen=True)
class ServiceDocument:
    schema: str
    document: Document
    section_locations: tuple[dict, ...]


def service_document(parsed: dict, revision: SourceRevision) -> ServiceDocument:
    """Validate a parsed service artifact against its DB revision; build typed records.

    This is an explicit adapter for the service schemas, not a reinterpretation
    of baseline schema 1: the source identity is the service source UUID and
    the content hash is the revision's raw SHA-256.
    """
    data = _object(parsed, "Parsed artifact")
    schema = data.get("schema_version")
    if schema not in DOCUMENT_SCHEMAS:
        raise IndexingError("Unsupported service document schema.")
    snapshot = _object(data.get("source"), "source")
    provenance = _object(data.get("provenance"), "provenance")
    if (data.get("revision_id") != str(revision.id) or snapshot.get("id") != str(revision.source_id)
            or snapshot.get("workspace_id") != str(revision.workspace_id)
            or provenance.get("raw_sha256") != revision.raw_sha256
            or any(snapshot.get(k) != revision.source_snapshot.get(k)
                   for k in ("product", "version", "document_type", "url", "source_terms_url"))):
        raise IndexingError("Parsed artifact does not match its revision record.")
    source = Source(
        source_id=str(revision.source_id), product=_text(snapshot.get("product"), "product"),
        version=_text(snapshot.get("version"), "version"),
        document_type=_text(snapshot.get("document_type"), "document_type"),
        url=_text(snapshot.get("url"), "url"), content_hash=revision.raw_sha256,
        fetched_at=_text(provenance.get("fetched_at"), "fetched_at"),
        source_terms_url=_text(snapshot.get("source_terms_url"), "source_terms_url"))
    body = _object(data.get("document"), "document")
    title = _text(body.get("title"), "title")
    sections, locations = [], []
    for raw_section in _list(body.get("sections"), "sections"):
        section = _object(raw_section, "section")
        heading = _text(section.get("heading"), "heading")
        level = section.get("level")
        if type(level) is not int or not 1 <= level <= 6:
            raise IndexingError("Heading level must be an integer from 1 to 6.")
        path = tuple(_text(part, "heading_path entry") for part in _list(section.get("heading_path"), "heading_path"))
        if not path or path[-1] != heading:
            raise IndexingError("heading_path must end with the section heading.")
        anchor, url = _location(section, source.url)
        location = section.get("location")
        if schema == "doclens-service-document-v1":
            if location is not None:
                raise IndexingError("HTML sections carry page anchors, not typed locations.")
            location = {"kind": "page_anchor", "anchor": anchor, "url": url}
        elif not isinstance(location, dict) or location.get("kind") not in LOCATION_KINDS[schema]:
            raise IndexingError("Repository/issue sections need their trusted typed location.")
        blocks = []
        for raw_block in _list(section.get("blocks"), "blocks"):
            block = _object(raw_block, "block")
            block_anchor, block_url = _location(block, source.url)
            text = _text(block.get("text"), "block.text")
            if block.get("location", location) != location:
                raise IndexingError("Block location differs from its section location.")
            digest = block.get("content_sha256")
            if digest is not None and digest != hashlib.sha256(text.encode("utf-8")).hexdigest():
                raise IndexingError("Block text does not match its recorded hash.")
            blocks.append(Block(BlockKind(block.get("kind")), text, block_anchor, block_url))
        sections.append(Section(heading, level, path, anchor, url, tuple(blocks)))
        locations.append(location)
    if not any(section.blocks for section in sections):
        raise IndexingError("Document must contain at least one content block.")
    records = tuple(sections)
    parsed_hash = content_digest({"title": title, "sections": [asdict(section) for section in records]})
    return ServiceDocument(schema, Document(source, title, records, parsed_hash), tuple(locations))


def chunk_set_hash(chunks: list[Chunk]) -> str:
    return content_digest([{"id": c.chunk_id, "text_hash": c.content_hash} for c in chunks])


def prepare_revision(parsed: dict, revision: SourceRevision, config: RetrievalConfig,
                     encoder: Encoder) -> tuple[RevisionIndex, list[RetrievalChunk]]:
    """Pure CPU work, done outside any DB transaction. Refuses (never truncates) long inputs."""
    if encoder.config != config.embedding:
        raise IndexingError("Encoder configuration does not match the retrieval configuration.")
    service = service_document(parsed, revision)
    chunks = chunk_document(service.document, config.policy)
    if not chunks:
        raise IndexingError("Revision produced no chunks.")
    texts = [chunk.text for chunk in chunks]
    counts = encoder.token_counts(texts)
    if len(counts) != len(chunks) or any(type(c) is not int or c <= 0 for c in counts):
        raise IndexingError("Encoder returned invalid token counts.")
    if max(counts) > config.embedding.max_tokens:
        raise IndexingError(f"A chunk needs {max(counts)} tokens; limit is {config.embedding.max_tokens}. "
                            "No text was truncated and nothing was indexed.")
    vectors = encoder.encode(texts)
    if len(vectors) != len(chunks):
        raise IndexingError("Encoder returned the wrong number of vectors.")
    index_id = config.index_id
    marker = RevisionIndex(
        revision_id=revision.id, index_id=index_id, source_id=revision.source_id,
        workspace_id=revision.workspace_id, document_schema=service.schema, config=config.to_dict(),
        runtime=dict(encoder.runtime), chunk_count=len(chunks), max_tokens=max(counts),
        chunk_set_hash=chunk_set_hash(chunks))
    rows = []
    for ordinal, (chunk, count, vector) in enumerate(zip(chunks, counts, vectors)):
        rows.append(RetrievalChunk(
            id=uuid5(NAMESPACE_URL, f"{INDEX_SCHEMA}/{revision.id}/{index_id}/{ordinal}"),
            revision_id=revision.id, index_id=index_id, source_id=revision.source_id,
            workspace_id=revision.workspace_id, product=chunk.source.product, version=chunk.source.version,
            document_type=chunk.source.document_type, ordinal=ordinal, chunk_key=chunk.chunk_id,
            section_index=chunk.section_index, heading_path=list(chunk.heading_path), anchor=chunk.anchor,
            url=chunk.url, location=service.section_locations[chunk.section_index],
            document_title=chunk.document_title, text=chunk.text, content_hash=chunk.content_hash,
            oversized=chunk.oversized, token_count=count,
            embedding=list(unit_vector(vector, config.embedding.dimensions))))
    return marker, rows


def pending_revisions(session, index_id: str, *, limit: int = 100) -> list[SourceRevision]:
    """Currently published revisions without a complete index for this configuration."""
    done = exists().where(RevisionIndex.revision_id == SourceRevision.id, RevisionIndex.index_id == index_id)
    return list(session.scalars(
        select(SourceRevision).join(SourcePublication, (SourcePublication.revision_id == SourceRevision.id)
                                    & (SourcePublication.workspace_id == SourceRevision.workspace_id))
        .where(~done).order_by(SourceRevision.id).limit(limit)))


def index_revision(sessions, store, revision_id: UUID, config: RetrievalConfig, encoder: Encoder) -> str:
    """Idempotent: returns 'indexed', 'exists' or 'missing'. Duplicate runs cannot mix chunk sets."""
    with sessions() as session:
        revision = session.get(SourceRevision, revision_id)
        if revision is None:
            return "missing"
        if session.get(RevisionIndex, (revision_id, config.index_id)) is not None:
            return "exists"
        session.expunge(revision)
    parsed = json.loads(store.read(revision.parsed_key, revision.parsed_sha256, revision.parsed_size))
    marker, rows = prepare_revision(parsed, revision, config, encoder)
    with sessions.begin() as session:
        claimed = session.execute(
            insert(RevisionIndex).values({c.key: getattr(marker, c.key) for c in RevisionIndex.__table__.columns
                                          if c.key != "created_at"})
            .on_conflict_do_nothing().returning(RevisionIndex.revision_id)).first()
        if claimed is None:
            return "exists"  # A concurrent indexer committed the same complete set first.
        session.add_all(rows)
    return "indexed"


@dataclass(frozen=True)
class ScopedHit:
    rank: int
    score: float
    row: RetrievalChunk
    source_name: str


def search_scope(session, *, workspace_id: UUID, issuer: str, subject: str, query_vector, product: str,
                 version: str, top_k: int, index_id: str,
                 document_types: tuple[str, ...] | None = None) -> tuple[int, list[ScopedHit]]:
    """One statement = one snapshot: authorization, scope filters, candidate count and exact ranking.

    Membership is rechecked here (not only in the HTTP dependency), so a
    revocation committed before this statement is honoured without re-embedding.
    """
    if type(top_k) is not int or not 1 <= top_k <= 50:
        raise ValueError("top_k must be an integer from 1 to 50.")
    vector = list(unit_vector(query_vector, EMBEDDING_DIMENSIONS))
    member = exists().where(
        Membership.workspace_id == RetrievalChunk.workspace_id, Membership.principal_id == Principal.id,
        Principal.issuer == issuer, Principal.subject == subject)
    distance = RetrievalChunk.embedding.cosine_distance(vector).label("distance")
    statement = (
        select(RetrievalChunk, RegisteredSource.name, distance, func.count().over().label("candidates"))
        .join(SourcePublication, (SourcePublication.revision_id == RetrievalChunk.revision_id)
              & (SourcePublication.source_id == RetrievalChunk.source_id)
              & (SourcePublication.workspace_id == RetrievalChunk.workspace_id))
        .join(RegisteredSource, (RegisteredSource.id == RetrievalChunk.source_id)
              & (RegisteredSource.workspace_id == RetrievalChunk.workspace_id))
        .where(RetrievalChunk.workspace_id == workspace_id, RetrievalChunk.product == product,
               RetrievalChunk.version == version, RetrievalChunk.index_id == index_id, member)
        .order_by(distance, RetrievalChunk.source_id, RetrievalChunk.ordinal)
        .limit(top_k))
    if document_types:
        statement = statement.where(RetrievalChunk.document_type.in_(document_types))
    rows = session.execute(statement).all()
    hits = [ScopedHit(rank, 1.0 - float(row.distance), row.RetrievalChunk, row.name)
            for rank, row in enumerate(rows, start=1)]
    for hit in hits:  # Defence in depth against a mis-scoped row ever leaving the service.
        chunk = hit.row
        if (chunk.workspace_id, chunk.product, chunk.version, chunk.index_id) != (workspace_id, product, version, index_id):
            raise RuntimeError("Retrieved chunk is outside the requested scope.")
        if hashlib.sha256(chunk.text.encode("utf-8")).hexdigest() != chunk.content_hash:
            raise RuntimeError("Stored chunk text does not match its hash.")
    return (rows[0].candidates if rows else 0), hits
