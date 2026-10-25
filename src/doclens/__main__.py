"""Run DocLens commands and report the current implementation status."""

import argparse
from pathlib import Path

from doclens import __version__
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
    args = parser.parse_args()

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
    print("Status: source downloading and parsing available; retrieval and answers are not implemented yet.")
    print("Run from the repository root: doclens ingest")
    print("Read README.md and docs/roadmap.md to follow the build.")


if __name__ == "__main__":
    main()
