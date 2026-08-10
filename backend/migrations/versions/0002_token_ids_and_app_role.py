"""track access token ids for revocation; least-privilege grants for the app role

Revision ID: 0002
Revises: 0001
Create Date: 2026-10-04 20:10:00.000000
"""

import os
import re
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0002"
down_revision: str | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_ROLE = re.compile(r"^[a-z_][a-z0-9_]{0,62}$")


def _app_role() -> str | None:
    """Migrations run as the schema owner; TOOLGATE_DB_APP_ROLE names the role the API connects as."""
    role = os.environ.get("TOOLGATE_DB_APP_ROLE", "").strip()
    if not role:
        return None
    if not _ROLE.match(role):
        raise ValueError(f"TOOLGATE_DB_APP_ROLE {role!r} is not a plain lowercase role name")
    return role


def upgrade() -> None:
    op.add_column("authorization_codes", sa.Column("access_token_jti", sa.String(length=64), nullable=True))
    op.add_column("refresh_tokens", sa.Column("access_token_jti", sa.String(length=64), nullable=True))

    role = _app_role()
    if role is not None:
        op.execute(f'GRANT USAGE ON SCHEMA public TO "{role}"')
        op.execute(f'GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO "{role}"')
        op.execute(f'GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO "{role}"')
        # The audit log stays append-only even for the app itself, independent of the triggers.
        op.execute(f'REVOKE UPDATE, DELETE, TRUNCATE ON audit_events FROM "{role}"')


def downgrade() -> None:
    op.drop_column("refresh_tokens", "access_token_jti")
    op.drop_column("authorization_codes", "access_token_jti")
