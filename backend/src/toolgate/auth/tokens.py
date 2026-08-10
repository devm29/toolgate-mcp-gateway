from __future__ import annotations

import time
import uuid
from dataclasses import dataclass

import jwt
from pydantic import BaseModel, ValidationError
from redis.asyncio import Redis

from toolgate.auth import scopes as scope_utils
from toolgate.auth.keys import KeyStore
from toolgate.common.principal import Principal

ACCESS_TOKEN_TYPE = "at+jwt"
LEEWAY_SECONDS = 30


class InvalidTokenError(Exception):
    pass


class AccessTokenClaims(BaseModel):
    iss: str
    sub: str
    aud: str
    exp: int
    iat: int
    nbf: int
    jti: str
    scope: str
    client_id: str


@dataclass(frozen=True, slots=True)
class IssuedToken:
    token: str
    expires_in: int
    jti: str


class TokenService:
    """Issues and validates RFC 9068 JWT access tokens bound to a single resource (audience)."""

    def __init__(self, keys: KeyStore, redis: Redis, *, issuer: str, ttl_seconds: int) -> None:
        self._keys = keys
        self._redis = redis
        self._issuer = issuer
        self._ttl = ttl_seconds

    def issue(self, *, subject: str, client_id: str, scopes: list[str], resource: str) -> IssuedToken:
        now = int(time.time())
        jti = uuid.uuid4().hex
        claims = AccessTokenClaims(
            iss=self._issuer,
            sub=subject,
            aud=resource,
            exp=now + self._ttl,
            iat=now,
            nbf=now,
            jti=jti,
            scope=scope_utils.render(scopes),
            client_id=client_id,
        )
        key = self._keys.active
        token = jwt.encode(
            claims.model_dump(),
            key.private_key,
            algorithm="RS256",
            headers={"kid": key.kid, "typ": ACCESS_TOKEN_TYPE},
        )
        return IssuedToken(token=token, expires_in=self._ttl, jti=jti)

    def decode(self, token: str, *, audience: str) -> AccessTokenClaims:
        try:
            header = jwt.get_unverified_header(token)
        except jwt.PyJWTError as exc:
            raise InvalidTokenError("Malformed access token") from exc
        if header.get("typ") != ACCESS_TOKEN_TYPE or header.get("alg") != "RS256":
            raise InvalidTokenError("Unsupported token type")
        key = self._keys.get(str(header.get("kid", "")))
        if key is None:
            raise InvalidTokenError("Unknown signing key")
        try:
            payload = jwt.decode(
                token,
                key.private_key.public_key(),
                algorithms=["RS256"],
                audience=audience,
                issuer=self._issuer,
                leeway=LEEWAY_SECONDS,
                options={"require": ["exp", "iat", "nbf", "iss", "aud", "sub", "jti"]},
            )
        except jwt.ExpiredSignatureError as exc:
            raise InvalidTokenError("Access token expired") from exc
        except jwt.InvalidAudienceError as exc:
            raise InvalidTokenError("Access token was issued for a different resource") from exc
        except jwt.PyJWTError as exc:
            raise InvalidTokenError("Access token is invalid") from exc
        try:
            return AccessTokenClaims.model_validate(payload)
        except ValidationError as exc:
            raise InvalidTokenError("Access token claims are incomplete") from exc

    async def verify(self, token: str, *, audience: str) -> Principal:
        claims = self.decode(token, audience=audience)
        if await self._redis.exists(self._revocation_key(claims.jti)):
            raise InvalidTokenError("Access token was revoked")
        return Principal(
            subject=claims.sub,
            client_id=claims.client_id,
            scopes=frozenset(scope_utils.parse(claims.scope)),
            token_id=claims.jti,
        )

    async def revoke(self, claims: AccessTokenClaims) -> None:
        ttl = max(1, claims.exp - int(time.time()) + LEEWAY_SECONDS)
        await self._redis.set(self._revocation_key(claims.jti), "1", ex=ttl)

    async def revoke_ids(self, jtis: list[str]) -> None:
        """Revoke tokens known only by id; the entry outlives any token this service could have issued."""
        if not jtis:
            return
        async with self._redis.pipeline(transaction=False) as pipe:
            for jti in jtis:
                pipe.set(self._revocation_key(jti), "1", ex=self._ttl + LEEWAY_SECONDS)
            await pipe.execute()

    @staticmethod
    def _revocation_key(jti: str) -> str:
        return f"revoked:jti:{jti}"
