from __future__ import annotations

from pydantic import BaseModel, ConfigDict


class Principal(BaseModel):
    """The authenticated caller behind a gateway request, derived from a validated access token."""

    model_config = ConfigDict(frozen=True)

    subject: str
    client_id: str | None = None
    scopes: frozenset[str] = frozenset()
    token_id: str | None = None

    @property
    def identities(self) -> tuple[str, ...]:
        ids = [self.subject]
        if self.client_id and f"client:{self.client_id}" != self.subject:
            ids.append(f"client:{self.client_id}")
        return tuple(ids)

    def has_scope(self, scope: str) -> bool:
        return scope in self.scopes
