"""Run DocLens commands and report the current implementation status."""

import argparse
from pathlib import Path

from doclens import __version__
from doclens.fetch import fetch_source
from doclens.manifest import load_sources


def main() -> None:
    parser = argparse.ArgumentParser(
        description="DocLens: a version-aware RAG assistant, currently building ingestion."
    )
    parser.add_argument("--version", action="version", version=__version__)
    commands = parser.add_subparsers(dest="command")
    fetch_parser = commands.add_parser("fetch", help="Download HTML pages listed in the source manifest.")
    fetch_parser.add_argument("--manifest", type=Path, default=Path("corpus/sources.json"))
    args = parser.parse_args()

    if args.command == "fetch":
        try:
            sources = load_sources(args.manifest)
            for source in sources:
                metadata = fetch_source(source, root=Path.cwd())
                print(
                    f"Saved {metadata['source_id']} -> {metadata['local_path']} "
                    f"({metadata['size_bytes']} bytes, sha256={metadata['sha256'][:12]})"
                )
        except (OSError, ValueError) as error:
            parser.exit(1, f"Fetch failed: {error}\n")
        print(f"Downloaded {len(sources)} sources with provenance metadata.")
        return

    print("DocLens")
    print("Status: source downloader available; parsing and RAG are not implemented yet.")
    print("Run from the repository root: doclens fetch")
    print("Read README.md and docs/roadmap.md to follow the build.")


if __name__ == "__main__":
    main()
