"""Run DocLens commands and report the current implementation status."""

import argparse
from pathlib import Path

from doclens import __version__
from doclens.chunk import ChunkPolicy, chunk_source
from doclens.fetch import fetch_source
from doclens.manifest import load_sources
from doclens.parse import parse_source


def main() -> None:
    parser = argparse.ArgumentParser(
        description="DocLens: a version-aware RAG assistant, currently building ingestion."
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
    args = parser.parse_args()

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
    print("Status: ingestion and baseline chunking available; retrieval and answers are not implemented yet.")
    print("Run from the repository root: doclens ingest, then doclens chunk")
    print("Read README.md and docs/roadmap.md to follow the build.")


if __name__ == "__main__":
    main()
