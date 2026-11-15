"""Stage 4 dev-set retrieval on PostgreSQL/pgvector, compared with the SQLite baseline.

    uv run --extra retrieval --extra service python scripts/stage4_eval.py

What it does (development split only; evals/heldout.json is never opened):
1. Creates a disposable PostgreSQL database (Stage 1 dev services), provisions
   roles + pgvector, migrates to head.
2. Bootstraps one synthetic evaluator workspace/principal with operator
   credentials and registers the 20 manifest pages as `https_html` sources.
3. Runs the real ingestion job code for each page, but the "fetch" reads the
   local raw HTML snapshot from data/raw (no network), so both stores see the
   same bytes. Then indexes with the pinned local model through the service
   indexer (worker role).
4. Proves chunk parity: every service chunk equals the baseline chunker's chunk
   (same ordinal, same text hash) for that page.
5. Evaluates dev with the unchanged scorer twice: once through the scoped
   pgvector search (app role, membership checked in SQL) and once through the
   SQLite baseline, then writes a per-question ranking comparison.

The frozen dataset pins raw-page hashes. With --derive-refetched-dataset the
script writes a clearly labeled copy under outputs/ whose ONLY change is the
source/manifest hashes (labels and quotes unchanged; quotes are still verified
against the new snapshot). It never edits evals/.
"""

import argparse
from dataclasses import asdict
import hashlib
import importlib.util
import json
from datetime import datetime, timezone
from pathlib import Path
import sys
from uuid import UUID, uuid4

from psycopg import sql
from sqlalchemy import create_engine, insert
from sqlalchemy.orm import sessionmaker

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from doclens.chunk import ChunkPolicy, chunk_document  # noqa: E402
from doclens.embeddings import LocalEncoder, load_embedding_config  # noqa: E402
from doclens.evaluation import load_catalog, run_evaluation  # noqa: E402
from doclens.manifest import load_sources  # noqa: E402
from doclens.records import SearchResponse, SearchResult, Source, document_from_dict  # noqa: E402
from doclens.retrieval import search_index  # noqa: E402
from doclens.service.indexer import run as run_indexer  # noqa: E402
from doclens.service.ingestion import run_job  # noqa: E402
from doclens.service.ingestion_io import ArtifactStore, Snapshot  # noqa: E402
from doclens.service.models import (DispatchIntent, IngestionJob, Membership, Principal,  # noqa: E402
                                    RegisteredSource, RetrievalChunk, Workspace)
from doclens.service.retrieval_index import RetrievalConfig, search_scope  # noqa: E402

ISSUER, SUBJECT = "urn:doclens:stage4-eval", "synthetic-evaluator"


def stage1():
    spec = importlib.util.spec_from_file_location("stage1_dev", ROOT / "scripts/stage1_dev.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def derive_dataset(dataset: Path, catalog, manifest: Path, out: Path) -> Path:
    data = json.loads(dataset.read_text(encoding="utf-8"))
    actual = {sid: source["content_hash"] for sid, source in catalog.sources.items()}
    changed = sorted(sid for sid, digest in data["source_hashes"].items() if actual.get(sid) != digest)
    data["derived_from"] = {"dataset": str(dataset.relative_to(ROOT)), "dataset_sha256": sha256(dataset),
                            "change": "source_hashes/corpus_manifest_sha256 replaced for a re-fetched snapshot; "
                                      "questions, labels and quotes unchanged",
                            "changed_sources": changed,
                            "frozen_corpus_manifest_sha256": data.get("corpus_manifest_sha256")}
    data["source_hashes"] = actual
    data["corpus_manifest_sha256"] = catalog.metadata.get("manifest_sha256")
    out.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return out


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--dataset", type=Path, default=ROOT / "evals/dev.json")
    parser.add_argument("--sqlite", type=Path, default=ROOT / "data/indexes/baseline.sqlite3")
    parser.add_argument("--manifest", type=Path, default=ROOT / "corpus/sources.json")
    parser.add_argument("--out", type=Path, default=ROOT / "outputs/stage4")
    parser.add_argument("--top-k", type=int, default=5)
    parser.add_argument("--derive-refetched-dataset", action="store_true")
    parser.add_argument("--keep-database", action="store_true")
    args = parser.parse_args(argv)
    if "heldout" in args.dataset.name:
        raise SystemExit("Stage 4 evaluates the development split only.")
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    out = args.out / stamp
    out.mkdir(parents=True)
    dev = stage1()
    config = RetrievalConfig(load_embedding_config(ROOT / "configs/retrieval.json"), ChunkPolicy())
    catalog = load_catalog(args.sqlite)
    if catalog.metadata["embedding"] != asdict(config.embedding) or catalog.metadata["policy_id"] != config.policy.policy_id:
        raise SystemExit("SQLite index was built with a different model/policy; comparison would not be like-for-like.")
    dataset = args.dataset
    if args.derive_refetched_dataset:
        dataset = derive_dataset(args.dataset, catalog, args.manifest, out / "dev-refetched-snapshot.json")
    encoder = LocalEncoder(config.embedding, cache=ROOT / "data/models", offline=True)

    name = "doclens_stage4_eval_" + uuid4().hex[:12]
    admin = create_engine(dev.database_url("doclens_dev_admin"), isolation_level="AUTOCOMMIT", hide_parameters=True)
    with admin.connect() as con:
        con.connection.driver_connection.execute(sql.SQL("CREATE DATABASE {} OWNER doclens_dev_admin").format(sql.Identifier(name)))
    engines = []
    try:
        dev.provision_database(name)
        owner, runtime, worker = (create_engine(dev.database_url(role, name), hide_parameters=True)
                                  for role in ("doclens_owner", "doclens_app", "doclens_worker"))
        engines += [owner, runtime, worker]
        workspace_id, principal_id = uuid4(), uuid4()
        sources = load_sources(args.manifest)
        with owner.begin() as con:  # Trusted operator bootstrap, as in Stage 1.
            con.execute(insert(Workspace).values(id=workspace_id, slug="stage4-eval", name="Stage 4 evaluation (synthetic principal)"))
            con.execute(insert(Principal).values(id=principal_id, issuer=ISSUER, subject=SUBJECT))
            con.execute(insert(Membership).values(workspace_id=workspace_id, principal_id=principal_id, role="owner"))
            service_ids, jobs = {}, []
            for source in sources:
                service_ids[source["source_id"]] = sid = uuid4()
                con.execute(insert(RegisteredSource).values(
                    id=sid, workspace_id=workspace_id, created_by=principal_id, name=source["source_id"],
                    connector_kind="https_html", product=source["product"], version=source["version"],
                    document_type=source["document_type"], url=source["url"], source_terms_url=source["source_terms_url"]))
                job = uuid4()
                con.execute(insert(IngestionJob).values(id=job, workspace_id=workspace_id, source_id=sid,
                    requested_by=principal_id, request_key=uuid4(), status="queued", stage="queued", attempts=0))
                con.execute(insert(DispatchIntent).values(job_id=job, deliveries=0))
                jobs.append((source, job))
        store = ArtifactStore(ROOT / "data/service/stage4-eval-artifacts" / name)
        worker_sessions = sessionmaker(worker, expire_on_commit=False)
        for source, job in jobs:
            raw = ROOT / source["local_path"]
            metadata = json.loads(raw.with_name(raw.name + ".metadata.json").read_text(encoding="utf-8"))
            fetched = datetime.fromisoformat(metadata["fetched_at"])
            status = run_job(worker_sessions, store, job,
                             fetcher=lambda s, raw=raw, fetched=fetched: Snapshot(raw.read_bytes(), s["url"], fetched))
            if status != "finished":
                raise SystemExit(f"Service ingestion of {source['source_id']} returned {status}.")
        indexing = run_indexer(worker_sessions, store, config, encoder)
        if any(v != "indexed" for v in indexing["revisions"].values()) or len(indexing["revisions"]) != len(sources):
            raise SystemExit(f"Indexing incomplete: {indexing}")

        # Chunk parity: service chunks must equal baseline chunks for the same snapshot.
        key_map, mismatches = {}, []
        by_name = {v: k for k, v in service_ids.items()}
        with sessionmaker(owner)() as session:
            rows = session.query(RetrievalChunk.source_id, RetrievalChunk.ordinal, RetrievalChunk.content_hash).all()
        stored = {(by_name[r.source_id], r.ordinal): r.content_hash for r in rows}
        baseline_count = 0
        for source in sources:
            raw = ROOT / source["local_path"]
            parsed = ROOT / "data/parsed" / raw.relative_to(ROOT / "data/raw")
            parsed = parsed.with_name(parsed.name + ".json")
            chunks = chunk_document(document_from_dict(json.loads(parsed.read_text(encoding="utf-8"))), config.policy)
            baseline_count += len(chunks)
            for ordinal, chunk in enumerate(chunks):
                if stored.get((source["source_id"], ordinal)) != chunk.content_hash or chunk.chunk_id not in catalog.chunk_regions:
                    mismatches.append([source["source_id"], ordinal])
                key_map[(service_ids[source["source_id"]], ordinal)] = chunk.chunk_id
        parity = {"service_chunks": len(rows), "baseline_chunks": baseline_count,
                  "sqlite_chunks": catalog.metadata["chunks"], "mismatches": mismatches}
        if mismatches or len(rows) != baseline_count:
            raise SystemExit(f"Chunk parity failed: {parity}")

        runtime_sessions = sessionmaker(runtime)

        def pg_searcher(index, query, *, version, root, product, top_k, encoder):
            vector = encoder.encode([query], query=True)[0]
            with runtime_sessions() as session:
                count, hits = search_scope(session, workspace_id=workspace_id, issuer=ISSUER, subject=SUBJECT,
                                           query_vector=vector, product=product, version=version,
                                           top_k=top_k, index_id=config.index_id)
            results = []
            for hit in hits:
                chunk_id = key_map[(hit.row.source_id, hit.row.ordinal)]
                results.append(SearchResult(
                    rank=hit.rank, score=hit.score, chunk_id=chunk_id, source=Source(**catalog.chunk_sources[chunk_id]),
                    document_title=hit.row.document_title, heading_path=tuple(hit.row.heading_path), url=hit.row.url,
                    text=hit.row.text, content_hash=hit.row.content_hash, oversized=hit.row.oversized))
            return SearchResponse(query, product, version, count, config.embedding.model_id,
                                  config.embedding.revision, tuple(results))

        reports = {}
        for label, searcher in (("pgvector", pg_searcher), ("sqlite", search_index)):
            reports[label] = run_evaluation(dataset, args.sqlite, root=ROOT, split="dev", top_k=args.top_k,
                                            output=out / f"dev-k{args.top_k}-{label}.json", encoder=encoder,
                                            searcher=searcher)
        comparison = []
        for pg_case, sq_case in zip(reports["pgvector"]["cases"], reports["sqlite"]["cases"]):
            for version in pg_case["versions"]:
                pg_ids = [r["chunk_id"] for r in pg_case["retrieved"][version]]
                sq_ids = [r["chunk_id"] for r in sq_case["retrieved"][version]]
                diffs = [abs(a["score"] - b["score"]) for a, b in zip(pg_case["retrieved"][version], sq_case["retrieved"][version])]
                comparison.append({"id": pg_case["id"], "version": version, "same_order": pg_ids == sq_ids,
                                   "same_set": set(pg_ids) == set(sq_ids), "max_score_abs_diff": max(diffs, default=0.0),
                                   "candidates": [pg_case["candidate_counts"][version], sq_case["candidate_counts"][version]]})
        summary = {
            "created_at": stamp, "dataset": str(dataset.relative_to(ROOT)), "dataset_sha256": sha256(dataset),
            "sqlite_index_sha256": sha256(args.sqlite), "index_id": config.index_id, "parity": parity,
            "indexing": indexing, "split": "dev", "top_k": args.top_k, "heldout_opened": False,
            "metrics": {label: {group: {k: report[group][k] for k in ("evidence_recall_at_k", "mrr_at_k",
                                                                      "evidence_group_recall_at_k", "wrong_version_chunks",
                                                                      "retrieved_chunks")}
                                for group in ("single_release", "comparison", "overall")}
                        for label, report in reports.items()},
            "retrieval_seconds_total": {label: report["retrieval_seconds_total"] for label, report in reports.items()},
            "ranking_comparison": {"calls": len(comparison), "same_order": sum(c["same_order"] for c in comparison),
                                   "same_set": sum(c["same_set"] for c in comparison),
                                   "max_score_abs_diff": max(c["max_score_abs_diff"] for c in comparison),
                                   "calls_detail": comparison},
            "database": name if args.keep_database else "dropped",
        }
        (out / "summary.json").write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
        print(json.dumps({k: v for k, v in summary.items() if k not in ("indexing",)} | {
            "ranking_comparison": {k: v for k, v in summary["ranking_comparison"].items() if k != "calls_detail"}}, indent=2))
        print(f"Reports: {out}")
        return 0
    finally:
        for engine in engines:
            engine.dispose()
        if not args.keep_database:
            with admin.connect() as con:  # Only the database generated above.
                con.connection.driver_connection.execute(sql.SQL("DROP DATABASE IF EXISTS {} WITH (FORCE)").format(sql.Identifier(name)))
        admin.dispose()


if __name__ == "__main__":
    raise SystemExit(main())
