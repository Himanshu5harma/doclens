"""Index currently published revisions into pgvector. Run explicitly, like the dispatcher.

    uv run --extra retrieval --extra service python -m doclens.service.indexer --env-file .env.worker.local

Uses the restricted worker DB role (SELECT revisions, INSERT chunk sets). The
model is loaded from the local cache only unless --allow-download is given.
Repeating the command is safe: complete sets are skipped, never appended.
"""

import argparse
import json
import logging
import sys
from uuid import UUID

from pydantic import ValidationError
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import NullPool

from doclens.embeddings import load_embedding_config
from doclens.service.ingestion_io import ArtifactStore, IngestionError
from doclens.service.retrieval_index import IndexingError, RetrievalConfig, index_revision, pending_revisions
from doclens.service.settings import IndexerSettings

logger = logging.getLogger("doclens.indexer")


def run(sessions, store, config: RetrievalConfig, encoder, *, revision_ids=None, limit=100) -> dict:
    if revision_ids is None:
        with sessions() as session:
            revision_ids = [revision.id for revision in pending_revisions(session, config.index_id, limit=limit)]
    outcomes = {}
    for revision_id in revision_ids:
        try:
            outcomes[str(revision_id)] = index_revision(sessions, store, revision_id, config, encoder)
        except (IndexingError, IngestionError) as error:
            # Bounded, application-authored messages only; continue with other revisions.
            outcomes[str(revision_id)] = f"failed: {error}"
    return {"index_id": config.index_id, "revisions": outcomes}


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--env-file", default=".env.worker.local")
    parser.add_argument("--revision", type=UUID, action="append", help="Index only these revision IDs.")
    parser.add_argument("--limit", type=int, default=100)
    parser.add_argument("--allow-download", action="store_true", help="Permit fetching the pinned model files.")
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s %(message)s")
    try:
        settings = IndexerSettings(_env_file=args.env_file)
    except ValidationError:
        print("Invalid indexer settings; set DOCLENS_DATABASE_URL (worker role).", file=sys.stderr)
        return 2
    from doclens.embeddings import LocalEncoder
    config = RetrievalConfig(load_embedding_config(settings.embedding_config))
    encoder = LocalEncoder(config.embedding, cache=settings.model_cache, offline=not args.allow_download)
    engine = create_engine(settings.database_url.get_secret_value(), poolclass=NullPool, hide_parameters=True,
                           connect_args={"connect_timeout": 5, "options": "-c statement_timeout=60000 -c lock_timeout=5000"})
    try:
        report = run(sessionmaker(engine, expire_on_commit=False), ArtifactStore(settings.artifact_root),
                     config, encoder, revision_ids=args.revision, limit=args.limit)
    finally:
        engine.dispose()
    print(json.dumps(report, indent=2))
    return 1 if any(v.startswith("failed") for v in report["revisions"].values()) else 0


if __name__ == "__main__":
    raise SystemExit(main())
