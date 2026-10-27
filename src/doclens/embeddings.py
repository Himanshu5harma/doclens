"""A local dense encoder with explicit configuration and no silent truncation."""

import json
import math
import re
from dataclasses import dataclass
from importlib.metadata import version
from pathlib import Path
from typing import Protocol, Sequence


@dataclass(frozen=True)
class EmbeddingConfig:
    model_id: str
    revision: str
    dimensions: int
    max_tokens: int
    document_prefix: str
    query_prefix: str
    batch_size: int = 8
    cpu_threads: int = 4

    def __post_init__(self):
        if not isinstance(self.model_id, str) or not self.model_id.strip():
            raise ValueError("Embedding model_id must be a nonempty string.")
        if not isinstance(self.revision, str) or not re.fullmatch(r"[0-9a-f]{40}", self.revision):
            raise ValueError("Pin the embedding revision to a full model commit SHA.")
        for name in ("dimensions", "max_tokens", "batch_size", "cpu_threads"):
            value = getattr(self, name)
            if type(value) is not int or value <= 0:
                raise ValueError(f"Embedding {name} must be a positive integer.")
        for prefix in (self.document_prefix, self.query_prefix):
            if not isinstance(prefix, str):
                raise ValueError("Embedding prefixes must be strings.")

    @classmethod
    def from_dict(cls, data: object) -> "EmbeddingConfig":
        if not isinstance(data, dict):
            raise ValueError("Embedding configuration must be an object.")
        try:
            return cls(**data)
        except TypeError as error:
            raise ValueError(f"Invalid embedding configuration: {error}") from error


def load_embedding_config(path: Path) -> EmbeddingConfig:
    return EmbeddingConfig.from_dict(json.loads(path.read_text(encoding="utf-8")))


def unit_vector(values: Sequence[float], dimensions: int) -> tuple[float, ...]:
    if len(values) != dimensions:
        raise ValueError(f"Expected {dimensions} vector dimensions, received {len(values)}.")
    try:
        vector = tuple(float(value) for value in values)
    except (ValueError, TypeError) as error:
        raise ValueError("Embedding vector must contain finite numbers.") from error
    if not all(math.isfinite(value) for value in vector):
        raise ValueError("Embedding vector must contain finite numbers.")
    norm = math.sqrt(sum(value * value for value in vector))
    if not math.isfinite(norm) or norm == 0:
        raise ValueError("Embedding vector must have finite, nonzero length.")
    return tuple(value / norm for value in vector)


class Encoder(Protocol):
    config: EmbeddingConfig
    runtime: dict

    def token_counts(self, texts: list[str], *, query: bool = False) -> list[int]: ...
    def encode(self, texts: list[str], *, query: bool = False) -> list[tuple[float, ...]]: ...


class LocalEncoder:
    """Load a pinned public model; queries can require cached files only.

    Heavy imports stay here so ingestion and the offline tests do not require
    the optional retrieval dependencies or a model download.
    """

    def __init__(self, config: EmbeddingConfig, *, cache: Path, offline: bool = False):
        try:
            import torch
            from sentence_transformers import SentenceTransformer
        except ImportError as error:
            raise ValueError("Install local retrieval dependencies: uv sync --extra retrieval") from error
        torch.set_num_threads(config.cpu_threads)
        self.config = config
        try:
            self.model = SentenceTransformer(
                config.model_id, revision=config.revision, device="cpu",
                cache_folder=str(cache), trust_remote_code=False, local_files_only=offline,
            )
        except Exception as error:
            raise ValueError(f"Cannot load the pinned local embedding model: {error}") from error
        dimension_method = getattr(self.model, "get_embedding_dimension", None)
        dimensions = dimension_method() if dimension_method else self.model.get_sentence_embedding_dimension()
        if dimensions != config.dimensions:
            raise ValueError("Configured dimensions do not match the embedding model.")
        if config.max_tokens > self.model.max_seq_length:
            raise ValueError("Configured token limit exceeds the model's actual sequence limit.")
        self.runtime = {
            package: version(package) for package in ("sentence-transformers", "transformers", "torch")
        }
        self.runtime.update(device="cpu", normalization="l2", similarity="cosine")

    def _inputs(self, texts: list[str], query: bool) -> list[str]:
        prefix = self.config.query_prefix if query else self.config.document_prefix
        return [prefix + text for text in texts]

    def token_counts(self, texts: list[str], *, query: bool = False) -> list[int]:
        return [
            len(self.model.tokenizer.encode(text, add_special_tokens=True, truncation=False))
            for text in self._inputs(texts, query)
        ]

    def encode(self, texts: list[str], *, query: bool = False) -> list[tuple[float, ...]]:
        counts = self.token_counts(texts, query=query)
        if any(count > self.config.max_tokens for count in counts):
            raise ValueError("Embedding input exceeds the token limit; refusing to truncate it.")
        try:
            vectors = self.model.encode(
                self._inputs(texts, query), batch_size=self.config.batch_size,
                prompt="",  # Prefixes are explicit above, not library defaults.
                normalize_embeddings=True, convert_to_numpy=True, show_progress_bar=len(texts) > 1,
            )
        except RuntimeError as error:
            raise ValueError(f"Local embedding inference failed: {error}") from error
        return [unit_vector(vector, self.config.dimensions) for vector in vectors]
