"""A persistent SQLite dense baseline: version filter first, exact cosine next."""

import hashlib
import json
import sqlite3
import struct
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
from tempfile import NamedTemporaryFile

from doclens.chunk import ChunkPolicy, chunk_source
from doclens.embeddings import EmbeddingConfig, Encoder, LocalEncoder, unit_vector
from doclens.manifest import load_sources
from doclens.records import Chunk, SearchResponse, SearchResult, Source, content_digest


def collect_chunks(root: Path, manifest: Path, policy: ChunkPolicy) -> list[Chunk]:
    """Refresh verified chunk bundles for the active manifest, excluding stale caches."""
    chunks = []
    for source in load_sources(manifest):
        _, source_chunks = chunk_source(source, root=root, policy=policy)
        chunks.extend(source_chunks)
    return chunks


def build_index(
    chunks: list[Chunk], *, path: Path, encoder: Encoder,
    manifest_hash: str, policy: ChunkPolicy,
) -> dict:
    """Build a complete replacement off to the side; failures preserve the old DB."""
    if not chunks or len({chunk.chunk_id for chunk in chunks}) != len(chunks):
        raise ValueError("Index inputs must contain nonempty, unique chunk IDs.")
    if any(chunk.policy_id != policy.policy_id for chunk in chunks):
        raise ValueError("All index chunks must match the recorded chunking policy.")
    texts = [chunk.text for chunk in chunks]
    counts = encoder.token_counts(texts)
    if len(counts) != len(chunks) or any(type(count) is not int or count <= 0 for count in counts):
        raise ValueError("Encoder returned invalid token counts.")
    for chunk, count in zip(chunks, counts):
        if count > encoder.config.max_tokens:
            raise ValueError(
                f"Chunk {chunk.chunk_id} ({chunk.source.source_id}) needs {count} tokens; "
                f"model limit is {encoder.config.max_tokens}. No text was truncated."
            )
    vectors = encoder.encode(texts)
    if len(vectors) != len(chunks):
        raise ValueError("Encoder returned the wrong number of document vectors.")
    vectors = [unit_vector(vector, encoder.config.dimensions) for vector in vectors]
    metadata = {
        "schema_version": 1, "embedding": asdict(encoder.config), "runtime": encoder.runtime,
        "policy": policy.to_dict(), "policy_id": policy.policy_id,
        "manifest_sha256": manifest_hash, "chunks": len(chunks),
        "sources": len({chunk.source.source_id for chunk in chunks}),
        "max_document_tokens": max(counts), "built_at": datetime.now(timezone.utc).isoformat(),
        "chunk_set_hash": content_digest([
            {"id": c.chunk_id, "text_hash": c.content_hash, "source_hash": c.source.content_hash,
             "document_hash": c.document_content_hash}
            for c in sorted(chunks, key=lambda chunk: chunk.chunk_id)
        ]),
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path = None
    try:
        with NamedTemporaryFile(dir=path.parent, suffix=".sqlite3", delete=False) as temporary:
            temporary_path = Path(temporary.name)
        connection = sqlite3.connect(temporary_path)
        try:
            with connection:
                connection.executescript("""
                    CREATE TABLE metadata (key TEXT PRIMARY KEY, value TEXT NOT NULL);
                    CREATE TABLE chunks (
                        chunk_id TEXT PRIMARY KEY, product TEXT NOT NULL, version TEXT NOT NULL,
                        source_id TEXT NOT NULL, payload TEXT NOT NULL, embedding BLOB NOT NULL
                    );
                    CREATE INDEX chunks_by_version ON chunks(product, version);
                """)
                connection.executemany(
                    "INSERT INTO metadata VALUES (?, ?)",
                    [(key, json.dumps(value)) for key, value in metadata.items()],
                )
                connection.executemany(
                    "INSERT INTO chunks VALUES (?, ?, ?, ?, ?, ?)",
                    [(
                        chunk.chunk_id, chunk.source.product, chunk.source.version, chunk.source.source_id,
                        json.dumps(asdict(chunk), ensure_ascii=False),
                        struct.pack(f"<{encoder.config.dimensions}f", *vector),
                    ) for chunk, vector in zip(chunks, vectors)],
                )
        finally:
            connection.close()
        temporary_path.replace(path)
    finally:
        if temporary_path is not None:
            temporary_path.unlink(missing_ok=True)
    return metadata


def search_index(
    path: Path, query: str, *, version: str, root: Path, product: str = "python",
    top_k: int = 5, encoder: Encoder | None = None,
) -> SearchResponse:
    """Search only the requested version in a read-only index snapshot."""
    if not isinstance(query, str) or not query.strip():
        raise ValueError("Query must be nonempty.")
    if not isinstance(version, str) or not version.strip():
        raise ValueError("An explicit version is required.")
    if type(top_k) is not int or top_k <= 0:
        raise ValueError("top_k must be a positive integer.")
    connection = sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True)
    try:
        metadata = {key: json.loads(value) for key, value in connection.execute("SELECT key, value FROM metadata")}
        if metadata.get("schema_version") != 1:
            raise ValueError("Unsupported search index schema; rebuild the index.")
        config = EmbeddingConfig.from_dict(metadata.get("embedding"))
        # Apply product/version constraints BEFORE selecting candidates to score.
        rows = connection.execute(
            "SELECT chunk_id, payload, embedding FROM chunks WHERE product = ? AND version = ? ORDER BY chunk_id",
            (product, version),
        ).fetchall()
        if not rows:
            raise ValueError(f"No indexed chunks for product {product!r}, version {version!r}.")
    finally:
        connection.close()

    if encoder is None:
        encoder = LocalEncoder(config, cache=root / "data" / "models", offline=True)
    if encoder.config != config:
        raise ValueError("Query encoder configuration does not match the index.")
    encoded = encoder.encode([query], query=True)
    if len(encoded) != 1:
        raise ValueError("Encoder must return exactly one query vector.")
    query_vector = unit_vector(encoded[0], config.dimensions)
    scored = []
    for chunk_id, payload, blob in rows:
        if len(blob) != config.dimensions * 4:
            raise ValueError(f"Invalid stored vector size for {chunk_id}; rebuild the index.")
        vector = unit_vector(struct.unpack(f"<{config.dimensions}f", blob), config.dimensions)
        score = sum(left * right for left, right in zip(query_vector, vector))
        scored.append((score, chunk_id, payload))
    scored.sort(key=lambda row: (-row[0], row[1]))
    results = []
    for rank, (score, chunk_id, payload) in enumerate(scored[:top_k], start=1):
        try:
            chunk = json.loads(payload)
            source = Source(**chunk["source"])
            if source.product != product or source.version != version or chunk["chunk_id"] != chunk_id:
                raise ValueError("Indexed payload does not match its version/ID columns.")
            if hashlib.sha256(chunk["text"].encode()).hexdigest() != chunk["content_hash"]:
                raise ValueError("Indexed text does not match its hash.")
            results.append(SearchResult(
                rank=rank, score=score, chunk_id=chunk_id, source=source,
                document_title=chunk["document_title"], heading_path=tuple(chunk["heading_path"]),
                url=chunk["url"], text=chunk["text"], content_hash=chunk["content_hash"],
                oversized=chunk["oversized"],
            ))
        except (KeyError, TypeError) as error:
            raise ValueError("Malformed indexed chunk payload; rebuild the index.") from error
    return SearchResponse(query, product, version, len(rows), config.model_id, config.revision, tuple(results))
