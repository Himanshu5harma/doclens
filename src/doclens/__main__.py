"""Run DocLens commands and report the current implementation status."""

import argparse
import hashlib
import json
import sqlite3
from dataclasses import asdict
from pathlib import Path

from doclens import __version__
from doclens.chunk import ChunkPolicy, chunk_source
from doclens.embeddings import LocalEncoder, load_embedding_config
from doclens.fetch import fetch_source
from doclens.manifest import load_sources
from doclens.parse import parse_source
from doclens.retrieval import build_index, collect_chunks, search_index


def main() -> None:
    parser = argparse.ArgumentParser(
        description="DocLens: version-aware retrieval for technical documentation."
    )
    parser.add_argument("--version", action="version", version=__version__)
    commands = parser.add_subparsers(dest="command")
    for command, help_text in (
        ("fetch", "Download HTML pages listed in the source manifest."),
        ("parse", "Parse downloaded pages into structured JSON sections."),
        ("ingest", "Download and parse each manifest source in one command."),
    ):
        command_parser = commands.add_parser(command, help=help_text)
        command_parser.add_argument("--manifest", type=Path, default=Path("corpus/sources.json"))
    chunk_parser = commands.add_parser("chunk", help="Build inspectable chunks from verified local parsed documents.")
    chunk_parser.add_argument("--manifest", type=Path, default=Path("corpus/sources.json"))
    chunk_parser.add_argument("--max-chars", type=int, default=2000, help="Character target including heading/anchor context (default: 2000).")
    chunk_parser.add_argument("--source-id", help="Process only this manifest source ID.")
    index_parser = commands.add_parser("index", help="Build a local dense search index from verified chunks.")
    index_parser.add_argument("--manifest", type=Path, default=Path("corpus/sources.json"))
    index_parser.add_argument("--config", type=Path, default=Path("configs/retrieval.json"))
    index_parser.add_argument("--index", type=Path, default=Path("data/indexes/baseline.sqlite3"))
    index_parser.add_argument("--max-chars", type=int, default=2000)
    search_parser = commands.add_parser("search", help="Retrieve inspectable passages from an explicit version.")
    search_parser.add_argument("query")
    search_parser.add_argument("--version", required=True, help="Document release line, e.g. 3.13.")
    search_parser.add_argument("--product", default="python")
    search_parser.add_argument("--top-k", type=int, default=5)
    search_parser.add_argument("--index", type=Path, default=Path("data/indexes/baseline.sqlite3"))
    search_parser.add_argument("--json", action="store_true", dest="json_output")
    args = parser.parse_args()

    if args.command == "index":
        try:
            policy = ChunkPolicy(args.max_chars)
            manifest_bytes = args.manifest.read_bytes()
            chunks = collect_chunks(Path.cwd(), args.manifest, policy)
            if args.manifest.read_bytes() != manifest_bytes:
                raise ValueError("Manifest changed while collecting chunks; retry indexing.")
            config = load_embedding_config(args.config)
            encoder = LocalEncoder(config, cache=Path.cwd() / "data" / "models")
            metadata = build_index(
                chunks, path=args.index, encoder=encoder, policy=policy,
                manifest_hash=hashlib.sha256(manifest_bytes).hexdigest(),
            )
        except (OSError, ValueError, sqlite3.Error) as error:
            parser.exit(1, f"Index failed: {error}\n")
        print(f"Indexed {metadata['chunks']} chunks from {metadata['sources']} sources -> {args.index}")
        print(f"Model: {config.model_id}@{config.revision}; dimensions={config.dimensions}")
        print(f"Largest document input: {metadata['max_document_tokens']}/{config.max_tokens} tokens (no truncation)")
        return

    if args.command == "search":
        try:
            response = search_index(
                args.index, args.query, version=args.version, root=Path.cwd(),
                product=args.product, top_k=args.top_k,
            )
        except (OSError, ValueError, sqlite3.Error) as error:
            parser.exit(1, f"Search failed: {error}\n")
        if args.json_output:
            print(json.dumps(asdict(response), indent=2, ensure_ascii=False))
        else:
            print(f"Version {response.version}: ranked {response.candidate_count} filtered candidates")
            for result in response.results:
                print(f"\n[{result.rank}] score={result.score:.4f} {result.source.source_id}")
                print(result.url)
                print(result.text)
        return

    if args.command == "chunk":
        try:
            policy = ChunkPolicy(args.max_chars)
            sources = load_sources(args.manifest)
            if args.source_id:
                sources = [source for source in sources if source["source_id"] == args.source_id]
                if not sources:
                    raise ValueError(f"Unknown source ID: {args.source_id}")
            total, oversized = 0, 0
            for source in sources:
                path, chunks = chunk_source(source, root=Path.cwd(), policy=policy)
                count = sum(chunk.oversized for chunk in chunks)
                total += len(chunks)
                oversized += count
                print(
                    f"Chunked {source['source_id']}: {len(chunks)} chunks, {count} oversized "
                    f"-> {path.relative_to(Path.cwd().resolve())}"
                )
        except (OSError, ValueError) as error:
            parser.exit(1, f"Chunk failed: {error}\n")
        print(f"Wrote {total} chunks from {len(sources)} sources ({oversized} oversized).")
        return

    if args.command in ("fetch", "parse", "ingest"):
        try:
            sources = load_sources(args.manifest)
            for source in sources:
                if args.command in ("fetch", "ingest"):
                    metadata = fetch_source(source, root=Path.cwd())
                    print(
                        f"Saved {metadata['source_id']} -> {metadata['local_path']} "
                        f"({metadata['size_bytes']} bytes, sha256={metadata['sha256'][:12]})"
                    )
                if args.command in ("parse", "ingest"):
                    document = parse_source(source, root=Path.cwd())
                    sections = document["sections"]
                    block_count = sum(len(section["blocks"]) for section in sections)
                    print(f"Parsed {source['source_id']}: {len(sections)} sections, {block_count} blocks")
        except (OSError, ValueError) as error:
            parser.exit(1, f"{args.command.capitalize()} failed: {error}\n")
        if args.command == "fetch":
            print(f"Downloaded {len(sources)} sources with provenance metadata.")
        elif args.command == "parse":
            print(f"Parsed {len(sources)} sources into data/parsed/.")
        else:
            print(f"Ingested {len(sources)} sources: raw HTML, provenance, and parsed documents.")
        return

    print("DocLens")
    print("Status: ingestion, chunking, and local dense retrieval available; answer generation is planned.")
    print("Run: doclens ingest, then doclens index; doclens search requires an explicit --version.")
    print("Read README.md and docs/roadmap.md to follow the build.")


if __name__ == "__main__":
    main()
