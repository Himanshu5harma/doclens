"""Authorized exact search over the caller's workspace. Requests never write content or vectors."""

from threading import Lock

from fastapi import APIRouter, HTTPException, Request

from doclens.embeddings import load_embedding_config
from doclens.service.app import AccessDep, IdentityDep, SessionDep
from doclens.service.retrieval_index import RetrievalConfig, search_scope
from doclens.service.schemas import SearchCreate, SearchHitRead, SearchRead

router = APIRouter(prefix="/api/v1/workspaces/{workspace_id}")
_lock = Lock()


class EncoderUnavailable(Exception):
    pass


def query_encoder(app):
    """Load the pinned local model once, from cache only; tests may pre-set app.state.query_encoder."""
    with _lock:
        encoder = getattr(app.state, "query_encoder", None)
        if encoder is None:
            settings = app.state.settings
            try:
                from doclens.embeddings import LocalEncoder
                config = load_embedding_config(settings.embedding_config)
                encoder = LocalEncoder(config, cache=settings.model_cache, offline=True)
            except (OSError, ValueError):
                raise EncoderUnavailable from None
            app.state.query_encoder = encoder
        return encoder


@router.post("/search", response_model=SearchRead)
def search(body: SearchCreate, request: Request, access: AccessDep, identity: IdentityDep, session: SessionDep):
    # `def` (not async): FastAPI runs it in a worker thread, so CPU-bound query
    # encoding does not block the event loop. Membership was checked by AccessDep
    # and is checked again inside the ranking statement.
    try:
        encoder = query_encoder(request.app)
    except EncoderUnavailable:
        raise HTTPException(503, "Retrieval model unavailable.") from None
    config = RetrievalConfig(encoder.config)
    try:
        with _lock:  # One local CPU model; serialize inference rather than oversubscribing threads.
            vectors = encoder.encode([body.query], query=True)
    except ValueError:
        raise HTTPException(422, "Query cannot be encoded within the model limit.") from None
    count, hits = search_scope(
        session, workspace_id=access.workspace_id, issuer=identity.issuer, subject=identity.subject,
        query_vector=vectors[0], product=body.product, version=body.version, top_k=body.top_k,
        index_id=config.index_id, document_types=tuple(body.document_types) if body.document_types else None)
    return SearchRead(
        query=body.query, product=body.product, version=body.version, candidate_count=count,
        index_id=config.index_id, model_id=config.embedding.model_id, model_revision=config.embedding.revision,
        results=[SearchHitRead(
            rank=hit.rank, score=hit.score, chunk_id=hit.row.id, chunk_key=hit.row.chunk_key,
            source_id=hit.row.source_id, source_name=hit.source_name, revision_id=hit.row.revision_id,
            document_type=hit.row.document_type, document_title=hit.row.document_title,
            heading_path=hit.row.heading_path, anchor=hit.row.anchor, url=hit.row.url,
            location=hit.row.location, text=hit.row.text, content_hash=hit.row.content_hash,
            oversized=hit.row.oversized, token_count=hit.row.token_count) for hit in hits])
