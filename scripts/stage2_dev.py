"""Prepare Stage 2 local credentials or inspect the authenticated ingestion API."""

import argparse
import json
from pathlib import Path
import secrets
import sys
from uuid import uuid4

from stage1_dev import ALIASES, DEV, ROOT, credentials, database_url, prepare as prepare_stage1, private_write, token


def prepare():
    prepare_stage1()
    creds = credentials()
    if "redis" not in creds:
        creds["redis"] = secrets.token_hex(24)
        private_write(DEV / "credentials.json", json.dumps(creds, indent=2) + "\n")
    # This bind-mounted development config must be readable by the container's
    # redis user. Host directory stays private; do not copy it into an image.
    (DEV / "redis.conf").write_text("\n".join([
        "bind 0.0.0.0", "protected-mode yes", "port 6379", "dir /data", "appendonly yes",
        "appendfsync everysec", "maxmemory 128mb", "maxmemory-policy noeviction",
        "requirepass " + creds["redis"], "",
    ]))
    (DEV / "redis.conf").chmod(0o644)
    DEV.chmod(0o700)
    private_write(ROOT / ".env.worker.local", "\n".join([
        "DOCLENS_DATABASE_URL=" + database_url("doclens_worker").render_as_string(hide_password=False),
        f"DOCLENS_BROKER_URL=redis://:{creds['redis']}@127.0.0.1:16379/0",
        "DOCLENS_ARTIFACT_ROOT=" + str(ROOT / "data/service/artifacts"), "",
    ]))
    print("Prepared ignored broker/worker configuration; existing credentials preserved.")


def main():
    cli = argparse.ArgumentParser(description=__doc__)
    commands = cli.add_subparsers(dest="command", required=True)
    commands.add_parser("prepare")
    request = commands.add_parser("request")
    request.add_argument("path")
    request.add_argument("--identity", choices=ALIASES, default="atlas-owner")
    request.add_argument("--sync", action="store_true", help="POST a sync; prints its request key for repeat inspection.")
    request.add_argument("--request-key", help="Reuse a previously printed UUID for an idempotent sync request.")
    request.add_argument("--output", type=Path, help="Save an artifact instead of printing its bytes.")
    args = cli.parse_args()
    try:
        if args.command == "prepare":
            prepare()
            return
        import httpx
        if not args.path.startswith("/api/v1/") or any(c in args.path for c in ("?", "#")):
            raise ValueError
        key = args.request_key or str(uuid4())
        with httpx.Client(timeout=10, follow_redirects=False, trust_env=False) as client:
            response = client.request("POST" if args.sync else "GET", "http://127.0.0.1:18000" + args.path,
                headers={"Authorization": "Bearer " + token(args.identity)},
                json={"request_key": key} if args.sync else None)
        print(f"HTTP {response.status_code}")
        if args.output and response.is_success:
            if args.output.exists():
                raise ValueError("Refusing to overwrite an existing output.")
            # Inspection downloads must stay in separate ignored service outputs.
            destination = args.output.resolve()
            if not destination.is_relative_to(ROOT / "outputs/service"):
                raise ValueError
            destination.parent.mkdir(parents=True, exist_ok=True)
            with destination.open("xb") as stream:
                stream.write(response.content)
            print(f"Saved {len(response.content)} bytes to {destination}")
        else:
            print(json.dumps(response.json(), indent=2))
    except Exception:
        print("Stage 2 command failed; check services, permission and separate output path. No credentials displayed.", file=sys.stderr)
        raise SystemExit(1) from None


if __name__ == "__main__":
    main()
