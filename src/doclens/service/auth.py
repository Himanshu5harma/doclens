"""Verify Keycloak access tokens; permissions are deliberately absent here."""

from dataclasses import dataclass

import jwt
from jwt import PyJWKClient
from jwt.exceptions import PyJWKClientConnectionError

from doclens.service.settings import ServiceSettings


@dataclass(frozen=True)
class Identity:
    issuer: str
    subject: str


class AuthenticationError(Exception):
    pass


class IdentityProviderUnavailable(Exception):
    pass


class TokenVerifier:
    def __init__(self, settings: ServiceSettings, *, key_client=None):
        self.settings = settings
        # This URL comes only from server configuration. Token jku/x5u are ignored.
        self.key_client = key_client or PyJWKClient(
            settings.oidc_jwks_url, timeout=settings.jwks_timeout_seconds,
            lifespan=settings.jwks_cache_seconds, cache_keys=False,
        )

    def verify(self, token: str) -> Identity:
        if not token or len(token) > 16_384:
            raise AuthenticationError()
        try:
            header = jwt.get_unverified_header(token)
            if (header.get("alg") != "RS256" or header.get("typ") != "JWT"
                    or not isinstance(header.get("kid"), str) or not 1 <= len(header["kid"]) <= 200
                    or header.get("crit")):
                raise AuthenticationError()
            key = self.key_client.get_signing_key(header["kid"]).key
            claims = jwt.decode(
                token, key, algorithms=["RS256"], issuer=self.settings.oidc_issuer,
                audience=self.settings.oidc_audience,
                options={"require": ["iss", "sub", "aud", "exp", "iat", "typ"]},
            )
            # Keycloak's access-token profile differs from its ID-token profile.
            if (claims["typ"] != "Bearer" or not isinstance(claims["sub"], str)
                    or not 1 <= len(claims["sub"]) <= 255
                    or type(claims["exp"]) is not int or type(claims["iat"]) is not int
                    or claims["exp"] <= claims["iat"]):
                raise AuthenticationError()
            return Identity(self.settings.oidc_issuer, claims["sub"])
        except PyJWKClientConnectionError:
            raise IdentityProviderUnavailable() from None
        except (jwt.PyJWTError, ValueError, TypeError, KeyError):
            raise AuthenticationError() from None
