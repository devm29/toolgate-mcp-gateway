from __future__ import annotations

import json
import uuid
from dataclasses import dataclass
from typing import Any

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from jwt.algorithms import RSAAlgorithm
from sqlalchemy import select, text

from toolgate.auth.models import SigningKey
from toolgate.db import SessionFactory, transaction


@dataclass(frozen=True, slots=True)
class LoadedKey:
    kid: str
    private_key: rsa.RSAPrivateKey

    @property
    def public_jwk(self) -> dict[str, Any]:
        jwk: dict[str, Any] = json.loads(RSAAlgorithm.to_jwk(self.private_key.public_key()))
        return {**jwk, "kid": self.kid, "use": "sig", "alg": "RS256"}


class KeyStore:
    """RS256 signing keys persisted in Postgres so every replica signs and verifies with the same set.

    Production deployments would keep the private half in a KMS; the interface stays the same.
    """

    def __init__(self, sessions: SessionFactory) -> None:
        self._sessions = sessions
        self._keys: dict[str, LoadedKey] = {}
        self._active: LoadedKey | None = None

    async def load(self) -> None:
        async with transaction(self._sessions) as session:
            # Serialize first boot across replicas so exactly one key gets generated.
            await session.execute(text("SELECT pg_advisory_xact_lock(hashtext('toolgate.signing_keys'))"))
            rows = (await session.scalars(select(SigningKey).order_by(SigningKey.created_at))).all()
            if not any(r.active for r in rows):
                private = rsa.generate_private_key(public_exponent=65537, key_size=2048)
                pem = private.private_bytes(
                    serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()
                ).decode()
                record = SigningKey(kid=uuid.uuid4().hex[:16], private_pem=pem, active=True)
                session.add(record)
                rows = [*rows, record]
        self._keys = {}
        for row in rows:
            key = serialization.load_pem_private_key(row.private_pem.encode(), password=None)
            if not isinstance(key, rsa.RSAPrivateKey):
                raise TypeError(f"signing key {row.kid} is not RSA")
            loaded = LoadedKey(row.kid, key)
            self._keys[row.kid] = loaded
            if row.active:
                self._active = loaded

    @property
    def active(self) -> LoadedKey:
        if self._active is None:
            raise RuntimeError("KeyStore.load() has not run")
        return self._active

    def get(self, kid: str) -> LoadedKey | None:
        return self._keys.get(kid)

    def jwks(self) -> dict[str, list[dict[str, Any]]]:
        return {"keys": [k.public_jwk for k in self._keys.values()]}
