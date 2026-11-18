"""Synthetic test encoder and artifact builders for Stage 4 tests.

`HashingEncoder` is a deterministic bag-of-words hash, NOT the real model; it
lets offline and DB tests check plumbing/scope/ordering without a 596 MB
download. Real-model behavior is measured separately by scripts/stage4_eval.py.
"""

import hashlib
import math
import re
from pathlib import Path
from types import SimpleNamespace
from uuid import UUID, uuid4, uuid5, NAMESPACE_URL

from doclens.retrieval.embeddings import load_embedding_config

ROOT = Path(__file__).resolve().parents[2]
CONFIG = load_embedding_config(ROOT / "configs/retrieval.json")


class HashingEncoder:
    def __init__(self, config=CONFIG, *, token_limit=None):
        self.config = config
        self.runtime = {"encoder": "synthetic-hashing-test-encoder"}
        self.token_limit = token_limit
        self.encoded = 0

    def token_counts(self, texts, *, query=False):
        return [len(re.findall(r"\w+", text)) + 2 for text in texts]

    def encode(self, texts, *, query=False):
        self.encoded += len(texts)
        vectors = []
        for text in texts:
            vector = [0.0] * self.config.dimensions
            for word in re.findall(r"\w+", text.lower()):
                slot = int.from_bytes(hashlib.sha256(word.encode()).digest()[:4], "big") % self.config.dimensions
                vector[slot] += 1.0
            vector[0] += 1e-3  # Never a zero vector.
            norm = math.sqrt(sum(v * v for v in vector))
            vectors.append(tuple(v / norm for v in vector))
        return vectors


def revision_for(document: dict, source: dict, *, schema: str, raw_sha256: str = "a" * 64,
                 revision_id: UUID | None = None):
    """Build the parsed artifact exactly as run_job lays it out, plus a matching revision record."""
    revision_id = revision_id or uuid4()
    source = {"id": str(uuid4()), "workspace_id": str(uuid4()), **source}
    parsed = {"schema_version": schema, "processing_policy": "test", "revision_id": str(revision_id),
              "source": source, "provenance": {"final_url": source["url"], "fetched_at": "2026-11-15T00:00:00+00:00",
                                               "raw_sha256": raw_sha256, "size_bytes": 1},
              "document": {key: document[key] for key in ("parser", "title", "sections")}}
    revision = SimpleNamespace(id=revision_id, source_id=UUID(source["id"]), workspace_id=UUID(source["workspace_id"]),
                               raw_sha256=raw_sha256, source_snapshot=source)
    return parsed, revision
