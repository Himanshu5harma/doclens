"""Actual API + PostgreSQL + Keycloak checks; no fake identity dependency."""

from uuid import uuid4

import pytest
from sqlalchemy import delete, func, insert, select, text
from sqlalchemy.exc import IntegrityError, ProgrammingError

from doclens.service.models import Membership, Principal, RegisteredSource, Workspace


def body(name=None):
    name = name or uuid4().hex
    return {"name": name, "product": "python", "version": "3.13", "document_type": "reference",
            "url": f"https://docs.python.org/3.13/library/{name}.html",
            "source_terms_url": "https://docs.python.org/3.13/license.html"}


def sources_path(real_services, name):
    return f"/api/v1/workspaces/{real_services.workspaces[name]}/sources"


def test_real_keycloak_token_and_membership_scoped_workspaces(api, headers, real_services):
    response = api.get("/api/v1/workspaces", headers=headers("atlas-owner"))
    assert response.status_code == 200
    assert [(w["slug"], w["role"]) for w in response.json()] == [("atlas", "owner")]
    both = api.get("/api/v1/workspaces", headers=headers("dual-member")).json()
    assert {(w["slug"], w["role"]) for w in both} == {("atlas", "viewer"), ("boreal", "editor")}
    assert api.get("/api/v1/workspaces", headers=headers("outsider")).json() == []


def test_registration_persists_metadata_and_trusted_creator(api, headers, real_services):
    payload = body(); path = sources_path(real_services, "atlas")
    response = api.post(path, headers=headers("atlas-owner"), json=payload)
    assert response.status_code == 201
    value = response.json()
    assert value["schema_version"] == "doclens-service-v1"
    assert value["workspace_id"] == str(real_services.workspaces["atlas"])
    assert {k: value[k] for k in payload} == payload
    assert value["connector_kind"] == "https_html" and value["created_at"]
    with real_services.runtime.connect() as con:
        row = con.execute(select(RegisteredSource.__table__).where(RegisteredSource.id == value["id"])).one()
        assert str(row.created_by) == value["created_by"]
    assert api.get(path + "/" + value["id"], headers=headers("atlas-viewer")).json() == value
    assert any(s["id"] == value["id"] for s in api.get(path, headers=headers("atlas-viewer")).json())


@pytest.mark.parametrize("alias,workspace,expected", [
    ("atlas-editor", "atlas", 201), ("atlas-viewer", "atlas", 403),
    ("atlas-owner", "boreal", 404), ("boreal-owner", "atlas", 404),
    ("outsider", "atlas", 404), ("dual-member", "atlas", 403), ("dual-member", "boreal", 201),
])
def test_registration_roles_and_cross_workspace_denial(alias, workspace, expected, api, headers, real_services):
    payload = body()
    response = api.post(sources_path(real_services, workspace), headers=headers(alias), json=payload)
    assert response.status_code == expected
    with real_services.runtime.connect() as con:
        count = con.scalar(select(func.count()).select_from(RegisteredSource).where(RegisteredSource.url == payload["url"]))
    assert count == (1 if expected == 201 else 0)


def test_foreign_source_id_cannot_be_smuggled_into_allowed_workspace(api, headers, real_services):
    boreal = sources_path(real_services, "boreal"); atlas = sources_path(real_services, "atlas")
    value = api.post(boreal, headers=headers("boreal-owner"), json=body("boreal-canary-" + uuid4().hex)).json()
    auth = headers("atlas-owner")
    for path in (boreal, boreal + "/" + value["id"], atlas + "/" + value["id"],
                 f"/api/v1/workspaces/{uuid4()}/sources", atlas + "/" + str(uuid4())):
        response = api.get(path, headers=auth)
        assert response.status_code == 404
        assert response.json() == {"detail": "Resource not found."}
        assert value["name"] not in response.text
    visible = api.get(atlas, headers=auth).json()
    assert all(s["workspace_id"] == str(real_services.workspaces["atlas"]) for s in visible)
    assert value["id"] not in {s["id"] for s in visible}


@pytest.mark.parametrize("extra", ["workspace_id", "created_by", "owner", "tenant_id", "role"])
def test_request_body_cannot_override_scope(extra, api, headers, real_services):
    payload = {**body(), extra: str(real_services.workspaces["boreal"])}
    response = api.post(sources_path(real_services, "atlas"), headers=headers("atlas-owner"), json=payload)
    assert response.status_code == 422
    with real_services.runtime.connect() as con:
        assert con.scalar(select(func.count()).select_from(RegisteredSource).where(RegisteredSource.url == payload["url"])) == 0


def test_duplicate_rolls_back_and_next_request_still_works(api, headers, real_services):
    path = sources_path(real_services, "atlas"); payload = body(); auth = headers("atlas-owner")
    assert api.post(path, headers=auth, json=payload).status_code == 201
    conflict = api.post(path, headers=auth, json=payload)
    assert conflict.status_code == 409
    assert payload["url"] not in conflict.text
    assert api.post(path, headers=auth, json=body()).status_code == 201
    # The same public URL is a separate owned registration in another workspace.
    assert api.post(sources_path(real_services, "boreal"), headers=headers("boreal-owner"), json=payload).status_code == 201


def test_pagination_and_connection_reuse_do_not_carry_identity(api, headers, real_services):
    dual = headers("dual-member"); atlas = sources_path(real_services, "atlas")
    for alias in ("atlas-owner", "boreal-owner", "outsider", "atlas-viewer", "atlas-owner"):
        values = api.get("/api/v1/workspaces?limit=1&offset=0", headers=headers(alias)).json()
        assert len(values) == (0 if alias == "outsider" else 1)
        if values: assert values[0]["slug"] == ("boreal" if alias == "boreal-owner" else "atlas")
    assert len(api.get("/api/v1/workspaces?limit=1&offset=1", headers=dual).json()) == 1
    assert api.get("/api/v1/workspaces?limit=1&offset=2", headers=dual).json() == []
    page = api.get(atlas + "?limit=1&offset=0", headers=dual).json()
    assert len(page) <= 1
    assert all(s["workspace_id"] == str(real_services.workspaces["atlas"]) for s in page)
    assert api.get("/api/v1/workspaces?limit=101", headers=dual).status_code == 422


def test_current_membership_is_checked_even_for_an_existing_valid_token(api, headers, real_services):
    auth = headers("atlas-viewer"); wid = real_services.workspaces["atlas"]
    path = sources_path(real_services, "atlas")
    assert api.get(path, headers=auth).status_code == 200
    with real_services.owner.begin() as con:
        identity = api.app.state.verifier.verify(auth["Authorization"].removeprefix("Bearer "))
        pid = con.scalar(select(Principal.id).where(Principal.issuer == identity.issuer, Principal.subject == identity.subject))
        con.execute(delete(Membership).where(Membership.workspace_id == wid, Membership.principal_id == pid))
    try:
        assert api.get(path, headers=auth).status_code == 404
    finally:
        with real_services.owner.begin() as con:
            con.execute(insert(Membership).values(workspace_id=wid, principal_id=pid, role="viewer"))


def test_runtime_role_has_no_admin_ddl_or_membership_write_privileges(real_services):
    with real_services.runtime.connect() as con:
        role = con.execute(text("SELECT current_user, rolsuper, rolcreatedb, rolcreaterole, rolbypassrls FROM pg_roles WHERE rolname=current_user")).one()
        assert tuple(role) == ("doclens_app", False, False, False, False)
        assert con.scalar(text("SELECT tableowner FROM pg_tables WHERE schemaname='doclens_service' AND tablename='sources'")) == "doclens_owner"
    for statement in ("CREATE TABLE doclens_service.unauthorized_test (id int)",
                      "DELETE FROM doclens_service.memberships", "UPDATE doclens_service.memberships SET role='owner'",
                      "INSERT INTO doclens_service.workspaces (id, slug, name) VALUES (gen_random_uuid(), 'forbidden', 'forbidden')"):
        with pytest.raises(ProgrammingError) as error:
            with real_services.runtime.begin() as con: con.execute(text(statement))
        assert error.value.orig.sqlstate == "42501"


def test_real_database_constraints_and_transactions(real_services):
    wid = real_services.workspaces["atlas"]
    with real_services.owner.connect() as con:
        membership = con.execute(select(Membership.__table__).where(Membership.workspace_id == wid)).first()
    for values in ({"workspace_id": wid, "principal_id": membership.principal_id, "role": membership.role},
                   {"workspace_id": uuid4(), "principal_id": membership.principal_id, "role": "owner"},
                   {"workspace_id": real_services.workspaces["boreal"], "principal_id": membership.principal_id, "role": "administrator"}):
        with pytest.raises(IntegrityError):
            with real_services.owner.begin() as con: con.execute(insert(Membership).values(**values))
    with pytest.raises(RuntimeError):
        with real_services.owner.begin() as con:
            con.execute(insert(Workspace).values(id=uuid4(), slug="rolled-back", name="rolled-back"))
            raise RuntimeError("Controlled transaction failure")
    with real_services.owner.connect() as con:
        assert con.scalar(select(func.count()).select_from(Workspace).where(Workspace.slug == "rolled-back")) == 0


@pytest.mark.parametrize("url", ["http://docs.example.test/page", "https://user:fixture-secret@example.test/page",
    "https://docs.example.test/page?key=fixture-secret", "https://127.0.0.1/page", "https://localhost/page",
    "https://docs.python.org/3.12/library/pathlib.html"])
def test_invalid_registration_redacts_rejected_input(url, api, headers, real_services, caplog):
    payload = {**body(), "url": url}
    response = api.post(sources_path(real_services, "atlas"), headers=headers("atlas-owner"), json=payload)
    assert response.status_code == 422
    assert response.json() == {"detail": "Invalid request."}
    assert "fixture-secret" not in response.text + caplog.text


def test_schema_is_migrated_and_no_rls_claim_is_made(real_services):
    with real_services.owner.connect() as con:
        assert con.scalar(text("SELECT version_num FROM doclens_service.alembic_version")) == "0001_workspace_sources"
        assert con.scalar(text("SELECT count(*) FROM pg_tables WHERE schemaname='doclens_service' AND rowsecurity")) == 0
