from __future__ import annotations

import hmac
from typing import Annotated

from fastapi import Depends, Header

from toolgate.auth import scopes as scope_utils
from toolgate.auth.tokens import InvalidTokenError
from toolgate.common.principal import Principal
from toolgate.container import Container, get_container
from toolgate.errors import ForbiddenError, UnauthorizedError

ADMIN_KEY_SUBJECT = "admin-key:console"


async def require_admin(
    container: Annotated[Container, Depends(get_container)],
    authorization: Annotated[str | None, Header()] = None,
    x_toolgate_admin_key: Annotated[str | None, Header()] = None,
) -> Principal:
    """The console's server side presents the admin key; humans and scripts can use an admin-scoped JWT instead."""
    if x_toolgate_admin_key is not None:
        expected = container.settings.admin_api_key.get_secret_value()
        if hmac.compare_digest(x_toolgate_admin_key.encode(), expected.encode()):
            return Principal(subject=ADMIN_KEY_SUBJECT, scopes=frozenset({scope_utils.ADMIN}))
        raise UnauthorizedError("Invalid admin key")
    if not authorization or not authorization.lower().startswith("bearer "):
        raise UnauthorizedError("Admin credentials required")
    try:
        principal = await container.tokens.verify(authorization[7:], audience=container.settings.admin_resource)
    except InvalidTokenError as exc:
        raise UnauthorizedError(str(exc)) from exc
    if not principal.has_scope(scope_utils.ADMIN):
        raise ForbiddenError("The toolgate:admin scope is required")
    return principal


AdminPrincipal = Annotated[Principal, Depends(require_admin)]
