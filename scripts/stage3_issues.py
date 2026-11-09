"""Inspect, freeze or register the reviewed historical issue export; no live crawl."""

import argparse
import hashlib
import json
import sys

import httpx

from stage1_dev import ALIASES, ROOT, token
from doclens.service.issue_export import (CURATION_PATH, EXPECTED_SHA256, REGISTRATION,
    SOURCE_URL, issue_source_metadata, load_export, parse_issue_export)
from doclens.service.ingestion_io import ArtifactStore
from doclens.service.schemas import SourceCreate
from doclens.service.settings import WorkerSettings


def reviewed_bytes():
    content = (ROOT / CURATION_PATH).read_bytes()
    if hashlib.sha256(content).hexdigest() != EXPECTED_SHA256:
        raise ValueError("Review changes before updating the pinned export policy.")
    load_export(content)
    return content


def main():
    cli = argparse.ArgumentParser(description=__doc__)
    cli.add_argument("command", choices=("inspect", "prepare", "register"))
    cli.add_argument("--workspace", default="atlas")
    cli.add_argument("--identity", choices=ALIASES, default="atlas-owner")
    args = cli.parse_args()
    try:
        content = reviewed_bytes()
        if args.command == "inspect":
            print(json.dumps({"source": {**REGISTRATION, **issue_source_metadata(content)},
                              "export_sha256": EXPECTED_SHA256,
                              "document": parse_issue_export(content, source_url=SOURCE_URL)}, indent=2))
        elif args.command == "prepare":
            settings = WorkerSettings(_env_file=ROOT / ".env.worker.local")
            root = settings.issue_export_root or settings.artifact_root.parent / "issue-exports"
            key, digest = ArtifactStore(root).put("reviewed", content, "raw")
            print(f"Verified frozen export: {root / key}")
            print(f"SHA-256: {digest}; bytes: {len(content)}; no sync requested.")
        else:
            catalog = json.loads((ROOT / "corpus/expanded/sources.json").read_text())
            entry = next(s for s in catalog["sources"] if s["catalog_id"] == "cpython-88221-curated-v1")
            body = entry.pop("registration")
            if entry != issue_source_metadata(content) or body != REGISTRATION:
                raise ValueError("Catalog differs from reviewed source policy.")
            SourceCreate(**body)
            with httpx.Client(base_url="http://127.0.0.1:18000", timeout=10, follow_redirects=False,
                              trust_env=False, headers={"Authorization": "Bearer " + token(args.identity)}) as client:
                listing = client.get("/api/v1/workspaces")
                listing.raise_for_status()
                workspace = next(w for w in listing.json() if w["slug"] == args.workspace)
                path = f"/api/v1/workspaces/{workspace['id']}/sources"
                response = client.post(path, json=body)
                if response.status_code == 409:
                    listing = client.get(path, params={"limit": 100})
                    listing.raise_for_status()
                    matches = [s for s in listing.json() if all(s[k] == body[k] for k in
                        ("connector_kind", "product", "version", "url", "document_type", "source_terms_url"))]
                    if len(matches) != 1:
                        raise ValueError("Inspect pagination before retrying.")
                    value = matches[0]
                    print("Existing registration reused; no sync requested.")
                else:
                    response.raise_for_status()
                    value = response.json()
                    print(f"HTTP {response.status_code}; no sync requested.")
                print(json.dumps(value, indent=2))
    except Exception:
        print("Issue-export command failed; check the reviewed file, worker settings, services and membership. No credentials displayed.", file=sys.stderr)
        raise SystemExit(1) from None


if __name__ == "__main__":
    main()
