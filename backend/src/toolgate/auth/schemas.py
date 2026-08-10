from __future__ import annotations

import ipaddress
from typing import Literal
from urllib.parse import urlsplit

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

AuthMethod = Literal["none", "client_secret_post", "client_secret_basic"]
GrantType = Literal["authorization_code", "refresh_token", "client_credentials"]

_FORBIDDEN_SCHEMES = {"javascript", "data", "file", "vbscript", "about", "blob"}


def _is_loopback(host: str) -> bool:
    if host == "localhost":
        return True
    try:
        return ipaddress.ip_address(host.strip("[]")).is_loopback
    except ValueError:
        return False


def validate_redirect_uri(uri: str) -> str:
    """OAuth 2.1 section 2.3: https, loopback http for native apps, or a private-use scheme. No fragments."""
    parts = urlsplit(uri)
    scheme = parts.scheme.lower()
    if not scheme or scheme in _FORBIDDEN_SCHEMES:
        raise ValueError(f"redirect_uri scheme '{scheme}' is not allowed")
    if parts.fragment:
        raise ValueError("redirect_uri must not contain a fragment")
    if scheme == "http" and not _is_loopback(parts.hostname or ""):
        raise ValueError("plain http redirect URIs are only allowed for loopback addresses")
    if scheme in {"http", "https"} and not parts.hostname:
        raise ValueError("redirect_uri needs a host")
    return uri


def _default_grant_types() -> list[GrantType]:
    return ["authorization_code", "refresh_token"]


def _default_response_types() -> list[Literal["code"]]:
    return ["code"]


class ClientRegistrationRequest(BaseModel):
    """RFC 7591 client metadata. Unknown fields are ignored as the RFC requires."""

    model_config = ConfigDict(extra="ignore")

    redirect_uris: list[str] = Field(default_factory=list, max_length=10)
    client_name: str = Field(default="Unnamed client", min_length=1, max_length=200)
    token_endpoint_auth_method: AuthMethod = "none"
    grant_types: list[GrantType] = Field(default_factory=_default_grant_types)
    response_types: list[Literal["code"]] = Field(default_factory=_default_response_types)
    scope: str | None = Field(default=None, max_length=500)
    client_uri: str | None = Field(default=None, max_length=500)
    logo_uri: str | None = Field(default=None, max_length=500)
    software_id: str | None = Field(default=None, max_length=200)
    software_version: str | None = Field(default=None, max_length=100)

    @field_validator("redirect_uris")
    @classmethod
    def _valid_redirects(cls, uris: list[str]) -> list[str]:
        return [validate_redirect_uri(u) for u in uris]

    @model_validator(mode="after")
    def _consistent(self) -> ClientRegistrationRequest:
        if "authorization_code" in self.grant_types and not self.redirect_uris:
            raise ValueError("authorization_code clients must register at least one redirect_uri")
        if "client_credentials" in self.grant_types and self.token_endpoint_auth_method == "none":
            raise ValueError("client_credentials requires a confidential client (client_secret_post or _basic)")
        if "refresh_token" in self.grant_types and "authorization_code" not in self.grant_types:
            raise ValueError("refresh_token is only issued alongside authorization_code")
        return self


class ClientRegistrationResponse(BaseModel):
    client_id: str
    client_secret: str | None = None
    client_id_issued_at: int
    client_secret_expires_at: int | None = None
    client_name: str
    redirect_uris: list[str]
    grant_types: list[str]
    response_types: list[str]
    token_endpoint_auth_method: str
    scope: str


class TokenResponse(BaseModel):
    access_token: str
    token_type: Literal["Bearer"] = "Bearer"
    expires_in: int
    scope: str
    refresh_token: str | None = None


class AuthorizationRequest(BaseModel):
    model_config = ConfigDict(extra="ignore")

    response_type: str
    client_id: str
    redirect_uri: str | None = None
    code_challenge: str | None = None
    code_challenge_method: str | None = None
    state: str | None = Field(default=None, max_length=500)
    scope: str | None = None
    resource: str | None = None


class ClientOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    client_id: str
    client_name: str
    redirect_uris: list[str]
    grant_types: list[str]
    token_endpoint_auth_method: str
    scope: str
    is_active: bool
