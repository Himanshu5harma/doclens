"""Offline crypto fixtures and opt-in real PostgreSQL/Keycloak integration.

Integration uses a newly created disposable DB, not the baseline SQLite index
or the persistent service demonstration database.
"""

import importlib.util
import os
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa
from pydantic import SecretStr
from sqlalchemy import create_engine
from psycopg import sql

from doclens.service.settings import ServiceSettings


@pytest.fixture(scope="session")
def rsa_keys():
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    return key, key.public_key()


@pytest.fixture
def service_settings():
    return ServiceSettings(
        database_url="postgresql+psycopg://unavailable:dummy@127.0.0.1:1/test",
        oidc_issuer="https://idp.example.test/realms/test",
        oidc_jwks_url="https://idp.example.test/realms/test/certs",
        oidc_audience="doclens-api",
    )


class FixtureKeys:
    def __init__(self, public):
        self.public = public
        self.calls = []

    def get_signing_key(self, kid):
        self.calls.append(kid)
        if kid != "fixture-key":
            raise jwt.PyJWKClientError("Fixture key not found")
        return SimpleNamespace(key=self.public)


@pytest.fixture(scope="session")
def dev():
    spec = importlib.util.spec_from_file_location("stage1_dev", Path(__file__).resolve().parents[2] / "scripts/stage1_dev.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="session")
def real_services(dev):
    if os.environ.get("DOCLENS_RUN_INTEGRATION") != "1":
        pytest.skip("Set DOCLENS_RUN_INTEGRATION=1 with the isolated Stage 1 services running.")
    if not (dev.DEV / "credentials.json").exists():
        pytest.fail("Prepare and start the Stage 1 development services first.")
    name = "doclens_stage1_test_" + uuid4().hex
    admin = create_engine(dev.database_url("doclens_dev_admin"), isolation_level="AUTOCOMMIT", hide_parameters=True)
    with admin.connect() as con:
        con.connection.driver_connection.execute(sql.SQL("CREATE DATABASE {} OWNER doclens_dev_admin").format(sql.Identifier(name)))
    owner = runtime = None
    try:
        dev.provision_database(name)
        owner = create_engine(dev.database_url("doclens_owner", name), hide_parameters=True)
        runtime = create_engine(dev.database_url("doclens_app", name), hide_parameters=True, pool_size=1, max_overflow=0)
        workspaces = dev.seed(owner)  # Real issued tokens + real JWKS verification.
        settings = dev.settings().model_copy(update={
            "database_url": SecretStr(dev.database_url("doclens_app", name).render_as_string(hide_password=False))})
        yield SimpleNamespace(owner=owner, runtime=runtime, workspaces=workspaces, settings=settings, dev=dev)
    finally:
        if runtime is not None:
            runtime.dispose()
        if owner is not None:
            owner.dispose()
        with admin.connect() as con:
            # The name was generated here; never drop a configured user DB.
            con.connection.driver_connection.execute(sql.SQL("DROP DATABASE {} WITH (FORCE)").format(sql.Identifier(name)))
        admin.dispose()


@pytest.fixture
def api(real_services):
    from fastapi.testclient import TestClient
    from doclens.service.app import create_app
    with TestClient(create_app(real_services.settings)) as client:
        yield client


@pytest.fixture
def headers(real_services):
    return lambda alias: {"Authorization": "Bearer " + real_services.dev.token(alias)}
