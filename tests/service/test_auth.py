import time

from fastapi.testclient import TestClient
import jwt
from jwt.exceptions import PyJWKClientConnectionError
import pytest

from conftest import FixtureKeys
from doclens.service.app import create_app
from doclens.service.auth import AuthenticationError, IdentityProviderUnavailable, TokenVerifier
from doclens.service.settings import ServiceSettings


def claims(settings):
    now = int(time.time())
    return {"iss": settings.oidc_issuer, "sub": "fixture-subject", "aud": "doclens-api",
            "iat": now, "exp": now + 300, "typ": "Bearer"}


def signed(payload, private, **header):
    return jwt.encode(payload, private, algorithm="RS256", headers={"kid": "fixture-key", **header})


def test_verified_identity_has_no_workspace_permissions(service_settings, rsa_keys):
    private, public = rsa_keys
    client = FixtureKeys(public)
    result = TokenVerifier(service_settings, key_client=client).verify(signed(claims(service_settings), private))
    assert result.issuer == service_settings.oidc_issuer
    assert result.subject == "fixture-subject"
    assert not hasattr(result, "workspace_id")
    assert client.calls == ["fixture-key"]


@pytest.mark.parametrize("field", ["iss", "sub", "aud", "iat", "exp", "typ"])
def test_missing_required_claim_is_rejected(field, service_settings, rsa_keys):
    payload = claims(service_settings); payload.pop(field)
    verifier = TokenVerifier(service_settings, key_client=FixtureKeys(rsa_keys[1]))
    token = signed(payload, rsa_keys[0])
    with pytest.raises(AuthenticationError):
        verifier.verify(token)
    with TestClient(create_app(service_settings, verifier=verifier)) as client:
        assert client.get("/api/v1/workspaces", headers={"Authorization": "Bearer " + token}).status_code == 401


@pytest.mark.parametrize("update", [
    {"iss": "https://other.example.test"}, {"aud": "another-api"},
    {"exp": 1}, {"iat": 9999999999, "exp": 10000000000}, {"typ": "ID"},
    {"sub": ""}, {"sub": 123}, {"exp": True}, {"iat": "1"}, {"nbf": 9999999999},
])
def test_invalid_claims_are_rejected(update, service_settings, rsa_keys):
    payload = claims(service_settings); payload.update(update)
    verifier = TokenVerifier(service_settings, key_client=FixtureKeys(rsa_keys[1]))
    token = signed(payload, rsa_keys[0])
    with pytest.raises(AuthenticationError):
        verifier.verify(token)
    with TestClient(create_app(service_settings, verifier=verifier)) as client:
        assert client.get("/api/v1/workspaces", headers={"Authorization": "Bearer " + token}).status_code == 401


def test_bad_signature_unknown_key_and_token_type(service_settings, rsa_keys):
    from cryptography.hazmat.primitives.asymmetric import rsa
    other = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    verifier = TokenVerifier(service_settings, key_client=FixtureKeys(rsa_keys[1]))
    for token in (signed(claims(service_settings), other),
                  signed(claims(service_settings), rsa_keys[0], kid="unknown"),
                  signed(claims(service_settings), rsa_keys[0], typ="not-a-jwt"), "broken", "x" * 16_385):
        with pytest.raises(AuthenticationError): verifier.verify(token)
        with TestClient(create_app(service_settings, verifier=verifier)) as client:
            assert client.get("/api/v1/workspaces", headers={"Authorization": "Bearer " + token}).status_code == 401


def test_algorithm_and_critical_header_rejected_before_key_lookup(service_settings, rsa_keys):
    keys = FixtureKeys(rsa_keys[1]); verifier = TokenVerifier(service_settings, key_client=keys)
    for token in (jwt.encode(claims(service_settings), "fixture-secret-" * 3, algorithm="HS256", headers={"kid": "fixture-key"}),
                  signed(claims(service_settings), rsa_keys[0], crit=["unhandled"])):
        with pytest.raises(AuthenticationError): verifier.verify(token)
    assert keys.calls == []


def test_token_cannot_select_a_key_url(service_settings, rsa_keys):
    keys = FixtureKeys(rsa_keys[1])
    TokenVerifier(service_settings, key_client=keys).verify(signed(
        claims(service_settings), rsa_keys[0], jku="http://127.0.0.1/attacker", x5u="https://untrusted.example"))
    assert keys.calls == ["fixture-key"]


def test_provider_failure_is_503_and_never_echoes_secret(service_settings, rsa_keys, caplog):
    secret = "fixture-provider-secret-never-display"
    class Unavailable:
        def get_signing_key(self, kid): raise PyJWKClientConnectionError(secret)
    verifier = TokenVerifier(service_settings, key_client=Unavailable())
    token = signed(claims(service_settings), rsa_keys[0])
    with pytest.raises(IdentityProviderUnavailable): verifier.verify(token)
    with TestClient(create_app(service_settings, verifier=verifier)) as client:
        response = client.get("/api/v1/workspaces", headers={"Authorization": "Bearer " + token})
        assert response.status_code == 503
        assert secret not in response.text + caplog.text
        assert token not in response.text + caplog.text


@pytest.mark.parametrize("authorization", [None, "Basic ignored", "Bearer broken"])
def test_invalid_auth_is_401_before_database_access(authorization, service_settings, caplog):
    with TestClient(create_app(service_settings)) as client:
        response = client.get("/api/v1/workspaces", headers={"Authorization": authorization} if authorization else {})
        assert response.status_code == 401
        assert response.headers["www-authenticate"] == "Bearer"
        assert "unavailable:dummy" not in response.text + caplog.text


def test_missing_settings_redact_input_and_local_http_is_explicit(monkeypatch):
    monkeypatch.delenv("DOCLENS_DATABASE_URL", raising=False)
    with pytest.raises(ValueError, match="Invalid DocLens service settings"):
        create_app()
    from pydantic import ValidationError
    with pytest.raises(ValidationError):
        ServiceSettings(database_url="sqlite:///baseline.sqlite3", oidc_issuer="https://issuer.test", oidc_jwks_url="https://issuer.test/keys")
    with pytest.raises(ValidationError):
        ServiceSettings(database_url="postgresql+psycopg://user:password@localhost/test", oidc_issuer="http://127.0.0.1/realm", oidc_jwks_url="http://127.0.0.1/keys")


def test_invalid_request_does_not_echo_rejected_values(service_settings, rsa_keys, caplog):
    # Missing auth prevents a DB call; request validation is separately checked
    # through authenticated real-DB requests in the integration tests.
    verifier = TokenVerifier(service_settings, key_client=FixtureKeys(rsa_keys[1]))
    with TestClient(create_app(service_settings, verifier=verifier)) as client:
        response = client.get("/api/v1/workspaces", headers={"Authorization": "Bearer invalid-secret"})
        assert response.status_code == 401
        assert "invalid-secret" not in response.text + caplog.text


def test_database_failure_is_readable_and_does_not_echo_dsn(service_settings, rsa_keys, caplog):
    verifier = TokenVerifier(service_settings, key_client=FixtureKeys(rsa_keys[1]))
    token = signed(claims(service_settings), rsa_keys[0])
    with TestClient(create_app(service_settings, verifier=verifier)) as client:
        response = client.get("/api/v1/workspaces", headers={"Authorization": "Bearer " + token})
        assert response.status_code == 503
        assert response.json() == {"detail": "Source service database unavailable."}
        assert "unavailable:dummy" not in response.text + caplog.text
        assert token not in response.text + caplog.text


def test_application_log_uses_route_template_not_input(service_settings, caplog):
    import logging
    caplog.set_level(logging.INFO, logger="doclens.service")
    with TestClient(create_app(service_settings)) as client:
        assert client.get("/api/v1/workspaces?access_token=fixture-secret").status_code == 401
    messages = "\n".join(r.message for r in caplog.records if r.name == "doclens.service")
    assert "route=/api/v1/workspaces status=401" in messages
    assert "fixture-secret" not in messages
