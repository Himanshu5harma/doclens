"""Run DocLens commands and report the current implementation status."""

import argparse
import hashlib
import json
import sqlite3
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path

from doclens import __version__
from doclens.answer_evaluation import run_answer_sample
from doclens.answers import answer_question, display_answer, prepare_question
from doclens.chunk import ChunkPolicy, chunk_source
from doclens.embeddings import LocalEncoder, load_embedding_config
from doclens.evaluation import run_evaluation
from doclens.fetch import fetch_source
from doclens.generation import GenerationError, load_generation_config
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
    ask_parser = commands.add_parser("ask", help="Generate and validate an answer from version-scoped evidence.")
    ask_parser.add_argument("question")
    ask_parser.add_argument("--version", required=True)
    ask_parser.add_argument("--product", default="python")
    ask_parser.add_argument("--top-k", type=int, default=5)
    ask_parser.add_argument("--index", type=Path, default=Path("data/indexes/baseline.sqlite3"))
    ask_parser.add_argument("--config", type=Path, default=Path("configs/generation.json"))
    ask_parser.add_argument("--model", help="Override with one explicit :free ID; current zero pricing is checked before generation.")
    ask_parser.add_argument("--inspect-prompt", action="store_true", help="Print exact messages, evidence map, and settings; no provider API call or key needed.")
    ask_parser.add_argument("--json", action="store_true", dest="json_output")
    answer_eval_parser = commands.add_parser("evaluate-answers", help="Run the fixed four-case development generation sample; never reads held-out labels.")
    answer_eval_parser.add_argument("--index", type=Path, default=Path("data/indexes/baseline.sqlite3"))
    answer_eval_parser.add_argument("--config", type=Path, default=Path("configs/generation.json"))
    answer_eval_parser.add_argument("--output", type=Path, help="New report under outputs/answers/ (default: timestamped).")
    answer_eval_parser.add_argument("--inspect-prompt", action="store_true", help="Save prepared prompts only; no provider API calls.")
    eval_parser = commands.add_parser("evaluate", help="Measure one labeled retrieval split without changing the index.")
    eval_parser.add_argument("--split", choices=("dev", "heldout"), default="dev")
    eval_parser.add_argument("--dataset", type=Path, help="Defaults to evals/<split>.json.")
    eval_parser.add_argument("--index", type=Path, default=Path("data/indexes/baseline.sqlite3"))
    eval_parser.add_argument("--top-k", type=int, default=5, help="Results per requested version.")
    eval_parser.add_argument("--output", type=Path, help="Defaults to outputs/evals/<split>-k<k>.json.")
    args = parser.parse_args()

    if args.command in ("ask", "evaluate-answers"):
        try:
            config = load_generation_config(args.config)
            if args.command == "evaluate-answers":
                stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
                output = args.output or Path("outputs/answers") / f"dev-{stamp}.json"
                report = run_answer_sample(args.index, root=Path.cwd(), config=config,
                                           output=output, inspect_only=args.inspect_prompt)
                print(f"Saved four-case dev {'prompts' if args.inspect_prompt else 'generation run'} -> {output}")
                for case in report["cases"]:
                    print(f"{case['id']}: {case['outcome']}")
                if any(case["outcome"] == "error" for case in report["cases"]):
                    error = next(case["error"] for case in report["cases"] if case["outcome"] == "error")
                    parser.exit(1, f"Answer evaluation stopped ({error['kind']}): {error['message']}\n")
                return
            if args.model:
                from dataclasses import replace
                config = replace(config, model_id=args.model)
            prepared = prepare_question(args.index, args.question, version=args.version,
                                        product=args.product, top_k=args.top_k, root=Path.cwd(), config=config)
            if args.inspect_prompt:
                print(json.dumps({"mode": "prompt_only", "settings": asdict(config),
                                  "prepared": asdict(prepared)}, ensure_ascii=False, indent=2))
                return
            result = answer_question(prepared, config)
            print(json.dumps(asdict(result), ensure_ascii=False, indent=2) if args.json_output else display_answer(result))
        except GenerationError as error:
            parser.exit(1, f"Answer failed ({error.kind}): {error}\n")
        except (OSError, ValueError, sqlite3.Error) as error:
            parser.exit(1, f"Answer failed: {error}\n")
        except KeyboardInterrupt:
            parser.exit(1, "Answer request interrupted; no automatic retry was made.\n")
        return

    if args.command == "evaluate":
        try:
            dataset = args.dataset or Path("evals") / f"{args.split}.json"
            output = args.output or Path("outputs/evals") / f"{args.split}-k{args.top_k}.json"
            report = run_evaluation(dataset, args.index, root=Path.cwd(), split=args.split, top_k=args.top_k, output=output)
        except (OSError, ValueError, sqlite3.Error) as error:
            parser.exit(1, f"Evaluation failed: {error}\n")
        for label in ("single_release", "comparison"):
            metrics = report[label]
            if metrics["answerable_questions"]:
                print(
                    f"{label}: {metrics['answerable_questions']} answerable; "
                    f"evidence_recall@{args.top_k}={metrics['evidence_recall_at_k']:.4f}, "
                    f"MRR@{args.top_k}={metrics['mrr_at_k']:.4f}, "
                    f"evidence_group_recall@{args.top_k}={metrics['evidence_group_recall_at_k']:.4f}"
                )
        overall = report["overall"]
        print(f"Wrong-version chunks: {overall['wrong_version_chunks']}/{overall['retrieved_chunks']}")
        print(f"Saved {args.split} report -> {output}")
        return

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
    print("Status: ingestion, chunking, retrieval, evaluation, and direct RAG commands implemented.")
    print("Run: doclens ask QUESTION --version 3.13; add --inspect-prompt for offline evidence inspection.")
    print("Read README.md and docs/roadmap.md to follow the build.")


if __name__ == "__main__":
    main()
