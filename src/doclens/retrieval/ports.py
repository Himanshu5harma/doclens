"""Retrieval ports: interfaces the indexing/search code depends on."""

from typing import Protocol

from doclens.retrieval.embeddings import EmbeddingConfig


class Encoder(Protocol):
    config: EmbeddingConfig
    runtime: dict

    def token_counts(self, texts: list[str], *, query: bool = False) -> list[int]: ...
    def encode(self, texts: list[str], *, query: bool = False) -> list[tuple[float, ...]]: ...
