"""Register the reviewed repository example through the authenticated local API."""

import argparse
import json
import sys

import httpx

from stage1_dev import ALIASES, ROOT, token
from doclens.service.repository import REGISTRATION, source_metadata
from doclens.service.schemas import SourceCreate


def main():
    cli = argparse.ArgumentParser(description=__doc__)
    cli.add_argument("command", choices=("register",))
    cli.add_argument("--workspace", default="atlas", help="An authorized workspace slug.")
    cli.add_argument("--identity", choices=ALIASES, default="atlas-owner")
    args = cli.parse_args()
    try:
        catalog = json.loads((ROOT / "corpus/expanded/sources.json").read_text())["sources"][0]
        body = catalog.pop("registration")
        if catalog != source_metadata() or body != REGISTRATION:
            raise ValueError("Catalog and reviewed adapter policy differ.")
        SourceCreate(**body)
        with httpx.Client(base_url="http://127.0.0.1:18000", timeout=10, follow_redirects=False,
                          trust_env=False, headers={"Authorization": "Bearer " + token(args.identity)}) as client:
            workspaces = client.get("/api/v1/workspaces")
            workspaces.raise_for_status()
            workspace = next(w for w in workspaces.json() if w["slug"] == args.workspace)
            path = f"/api/v1/workspaces/{workspace['id']}/sources"
            response = client.post(path, json=body)
            if response.status_code == 409:
                # A rerun can reuse the existing registration; never resync automatically.
                listing = client.get(path, params={"limit": 100})
                listing.raise_for_status()
                matches = [s for s in listing.json() if all(s[k] == body[k] for k in
                           ("connector_kind", "product", "version", "url", "source_terms_url", "document_type"))]
                if len(matches) != 1:
                    raise ValueError("Inspect source pagination before retrying.")
                result = matches[0]
                print("Existing registration reused; no sync requested.")
            else:
                response.raise_for_status()
                result = response.json()
                print(f"HTTP {response.status_code}; no sync requested.")
            print(json.dumps(result, indent=2))
    except Exception:
        print("Repository registration failed; check the reviewed catalog, services and membership. No credentials displayed.", file=sys.stderr)
        raise SystemExit(1) from None


if __name__ == "__main__":
    main()
