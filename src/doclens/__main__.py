"""Report scaffold status without implying that the RAG pipeline exists."""

import argparse

from doclens import __version__


def main() -> None:
    parser = argparse.ArgumentParser(
        description="DocLens project scaffold for a version-aware RAG assistant."
    )
    parser.add_argument("--version", action="version", version=__version__)
    parser.parse_args()
    print("DocLens")
    print("Status: project scaffold; the RAG pipeline is not implemented yet.")
    print("Next milestone: select a versioned corpus and implement ingestion.")
    print("Read README.md and docs/roadmap.md to follow the build.")


if __name__ == "__main__":
    main()
