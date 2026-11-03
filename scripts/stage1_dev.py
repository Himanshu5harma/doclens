"""Local-only provisioning/request helpers. Never print access tokens or DSNs.

Workspaces and membership are bootstrapped here with operator credentials, not
through an API which would let a caller assign themselves privileges.
"""

import argparse
import json
import os
from pathlib import Path
import secrets
import sys
import time
from uuid import NAMESPACE_URL, uuid5

ROOT = Path(__file__).resolve().parents[1]
DEV = ROOT / "data" / "service" / "dev"
ISSUER = "http://127.0.0.1:18080/realms/doclens-dev"
ALIASES = ("atlas-owner", "atlas-editor", "atlas-viewer", "boreal-owner", "dual-member", "outsider")


def private_write(path, content):
    path.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as stream:
        stream.write(content)
    path.chmod(0o600)


def credentials():
    return json.loads((DEV / "credentials.json").read_text())


def database_url(user, database="doclens_service"):
    from sqlalchemy import URL
    creds = credentials()
    return URL.create("postgresql+psycopg", username=user, password=creds[user],
                      host="127.0.0.1", port=15432, database=database)


def settings():
    from doclens.service.settings import ServiceSettings
    return ServiceSettings(_env_file=ROOT / ".env.service.local")


def prepare():
    DEV.mkdir(parents=True, exist_ok=True)
    path = DEV / "credentials.json"
    if not path.exists():
        creds = {name: secrets.token_hex(24) for name in
                 ("doclens_dev_admin", "doclens_owner", "doclens_app", *ALIASES)}
        private_write(path, json.dumps(creds, indent=2) + "\n")
    creds = credentials()
    private_write(DEV / "postgres-admin.txt", creds["doclens_dev_admin"] + "\n")
    private_write(ROOT / ".env.stage1.idp.local", "".join(
        f"{alias.upper().replace('-', '_')}_SECRET={creds[alias]}\n" for alias in ALIASES))
    clients = []
    for alias in ALIASES:
        clients.append({
            "clientId": alias, "enabled": True, "protocol": "openid-connect",
            "publicClient": False, "serviceAccountsEnabled": True,
            "standardFlowEnabled": False, "directAccessGrantsEnabled": False,
            "secret": "${" + alias.upper().replace("-", "_") + "_SECRET}",
            "protocolMappers": [{
                "name": "doclens-api-audience", "protocol": "openid-connect",
                "protocolMapper": "oidc-audience-mapper", "consentRequired": False,
                "config": {"included.custom.audience": "doclens-api",
                           "access.token.claim": "true", "id.token.claim": "false"},
            }],
        })
    # Realm file has placeholders only, so the container can read it without
    # making its generated client secrets world-readable on the host.
    realm = {"realm": "doclens-dev", "enabled": True, "sslRequired": "none",
             "registrationAllowed": False, "accessTokenLifespan": 300, "clients": clients}
    (DEV / "realm.json").write_text(json.dumps(realm, indent=2) + "\n")
    (DEV / "realm.json").chmod(0o644)
    private_write(ROOT / ".env.service.local", "\n".join([
        "DOCLENS_DATABASE_URL=" + database_url("doclens_app").render_as_string(hide_password=False),
        "DOCLENS_OIDC_ISSUER=" + ISSUER,
        "DOCLENS_OIDC_JWKS_URL=" + ISSUER + "/protocol/openid-connect/certs",
        "DOCLENS_OIDC_AUDIENCE=doclens-api", "DOCLENS_ALLOW_LOCAL_HTTP=true", "",
    ]))
    print("Prepared ignored local configuration and generated credentials (not displayed).")


def token(alias):
    import httpx
    if alias not in ALIASES:
        raise ValueError("Unknown demonstration identity.")
    with httpx.Client(timeout=5, follow_redirects=False, trust_env=False) as client:
        response = client.post(ISSUER + "/protocol/openid-connect/token", data={
            "grant_type": "client_credentials", "client_id": alias,
            "client_secret": credentials()[alias],
        })
        response.raise_for_status()
        value = response.json().get("access_token")
        if not isinstance(value, str):
            raise ValueError("Identity provider did not return an access token.")
        return value


def wait_for_services():
    import httpx
    from sqlalchemy import create_engine, text
    engine = create_engine(database_url("doclens_dev_admin"), connect_args={"connect_timeout": 2},
                           hide_parameters=True)
    try:
        for _ in range(90):
            try:
                with engine.connect() as connection:
                    connection.execute(text("SELECT 1"))
                with httpx.Client(timeout=2, follow_redirects=False, trust_env=False) as client:
                    response = client.get(ISSUER + "/.well-known/openid-configuration")
                    response.raise_for_status()
                    if response.json()["issuer"] != ISSUER:
                        raise ValueError("Unexpected development issuer.")
                return
            except Exception:
                time.sleep(1)
    finally:
        engine.dispose()
    raise RuntimeError("Local PostgreSQL/Keycloak readiness timed out.")


def provision_database(database="doclens_service"):
    """Trusted setup only; the API cannot create roles or memberships."""
    from psycopg import sql
    from sqlalchemy import create_engine, text
    engine = create_engine(database_url("doclens_dev_admin", database), hide_parameters=True)
    try:
        with engine.begin() as con:
            for role in ("doclens_owner", "doclens_app"):
                if not con.scalar(text("SELECT 1 FROM pg_roles WHERE rolname = :role"), {"role": role}):
                    # psycopg quotes both identifier and password as SQL values.
                    raw = con.connection.driver_connection
                    raw.execute(sql.SQL("CREATE ROLE {} LOGIN PASSWORD {} NOSUPERUSER NOCREATEDB NOCREATEROLE NOBYPASSRLS")
                                .format(sql.Identifier(role), sql.Literal(credentials()[role])))
            raw = con.connection.driver_connection
            raw.execute(sql.SQL("REVOKE ALL ON DATABASE {} FROM PUBLIC").format(sql.Identifier(database)))
            raw.execute(sql.SQL("GRANT CONNECT ON DATABASE {} TO doclens_owner, doclens_app")
                        .format(sql.Identifier(database)))
            con.execute(text("REVOKE CREATE ON SCHEMA public FROM PUBLIC"))
            con.execute(text("CREATE SCHEMA IF NOT EXISTS doclens_service AUTHORIZATION doclens_owner"))
    finally:
        engine.dispose()
    migrate(database)


def migrate(database="doclens_service"):
    from alembic import command
    from alembic.config import Config
    previous = os.environ.get("DOCLENS_MIGRATION_DATABASE_URL")
    os.environ["DOCLENS_MIGRATION_DATABASE_URL"] = database_url("doclens_owner", database).render_as_string(hide_password=False)
    try:
        command.upgrade(Config(str(ROOT / "alembic.ini")), "head")
    finally:
        if previous is None:
            os.environ.pop("DOCLENS_MIGRATION_DATABASE_URL", None)
        else:
            os.environ["DOCLENS_MIGRATION_DATABASE_URL"] = previous


def seed(engine):
    from sqlalchemy import select
    from sqlalchemy.orm import Session
    from doclens.service.auth import TokenVerifier
    from doclens.service.models import Membership, Principal, Workspace
    verifier = TokenVerifier(settings())
    identities = {alias: verifier.verify(token(alias)) for alias in ALIASES}
    workspaces = {name: uuid5(NAMESPACE_URL, "doclens-stage1-demo/" + name) for name in ("atlas", "boreal")}
    grants = {"atlas-owner": [("atlas", "owner")], "atlas-editor": [("atlas", "editor")],
              "atlas-viewer": [("atlas", "viewer")], "boreal-owner": [("boreal", "owner")],
              "dual-member": [("atlas", "viewer"), ("boreal", "editor")], "outsider": []}
    with Session(engine) as session, session.begin():
        for name, wid in workspaces.items():
            if session.get(Workspace, wid) is None:
                session.add(Workspace(id=wid, slug=name, name=name.title() + " demonstration"))
        session.flush()
        for alias, identity in identities.items():
            principal = session.scalar(select(Principal).where(
                Principal.issuer == identity.issuer, Principal.subject == identity.subject))
            if principal is None:
                principal = Principal(issuer=identity.issuer, subject=identity.subject)
                session.add(principal)
                session.flush()
            for name, role in grants[alias]:
                if session.get(Membership, (workspaces[name], principal.id)) is None:
                    session.add(Membership(workspace_id=workspaces[name], principal_id=principal.id, role=role))
    return workspaces


def bootstrap():
    from sqlalchemy import create_engine
    wait_for_services()
    provision_database()
    engine = create_engine(database_url("doclens_owner"), hide_parameters=True)
    try:
        workspaces = seed(engine)
        print(json.dumps({"workspaces": {k: str(v) for k, v in workspaces.items()},
                          "identity_provider": "real local Keycloak access tokens verified against JWKS"}, indent=2))
    finally:
        engine.dispose()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("prepare")
    commands.add_parser("bootstrap")
    request = commands.add_parser("request")
    request.add_argument("path")
    request.add_argument("--identity", choices=ALIASES, default="atlas-owner")
    request.add_argument("--method", choices=("GET", "POST"), default="GET")
    request.add_argument("--body", type=Path)
    args = parser.parse_args()
    try:
        if args.command == "prepare":
            prepare()
        elif args.command == "bootstrap":
            bootstrap()
        else:
            import httpx
            if not args.path.startswith("/api/v1/") or "?" in args.path or "#" in args.path:
                raise ValueError("Request path must be a local API path.")
            with httpx.Client(timeout=10, follow_redirects=False, trust_env=False) as client:
                response = client.request(args.method, "http://127.0.0.1:18000" + args.path,
                    headers={"Authorization": "Bearer " + token(args.identity)},
                    json=json.loads(args.body.read_text()) if args.body else None)
            print(f"HTTP {response.status_code}")
            print(json.dumps(response.json(), indent=2))
    except Exception:
        # Driver/HTTP exceptions may include URLs, secrets or provider bodies.
        print("Stage 1 development command failed; check local services/configuration. No credentials displayed.", file=sys.stderr)
        raise SystemExit(1) from None


if __name__ == "__main__":
    main()
