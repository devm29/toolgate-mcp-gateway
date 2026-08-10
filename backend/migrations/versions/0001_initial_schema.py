"""initial schema: oauth, registry, policies, append-only audit log

Revision ID: 0001
Revises:
Create Date: 2026-10-04 14:45:20.987587
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "audit_events",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("request_id", sa.String(length=64), nullable=False),
        sa.Column("principal", sa.String(length=160), nullable=False),
        sa.Column("client_id", sa.String(length=96), nullable=True),
        sa.Column("tool_name", sa.String(length=160), nullable=False),
        sa.Column("upstream", sa.String(length=48), nullable=True),
        sa.Column("upstream_tool", sa.String(length=256), nullable=True),
        sa.Column("decision", sa.String(length=24), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("arguments", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("latency_ms", sa.Float(), nullable=False),
        sa.Column("is_error", sa.Boolean(), nullable=False),
        sa.Column("trace_id", sa.String(length=32), nullable=True),
        sa.Column("span_id", sa.String(length=16), nullable=True),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_audit_events")),
    )
    op.create_index(op.f("ix_audit_events_decision"), "audit_events", ["decision"], unique=False)
    op.create_index("ix_audit_events_occurred_at", "audit_events", ["occurred_at"], unique=False)
    op.create_index(op.f("ix_audit_events_principal"), "audit_events", ["principal"], unique=False)
    op.create_index("ix_audit_events_tool_occurred", "audit_events", ["tool_name", "occurred_at"], unique=False)
    op.create_table(
        "oauth_clients",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("client_id", sa.String(length=96), nullable=False),
        sa.Column("client_secret_hash", sa.String(length=128), nullable=True),
        sa.Column("client_name", sa.String(length=200), nullable=False),
        sa.Column("redirect_uris", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("grant_types", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("token_endpoint_auth_method", sa.String(length=32), nullable=False),
        sa.Column("scope", sa.Text(), nullable=False),
        sa.Column("metadata", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_oauth_clients")),
        sa.UniqueConstraint("client_id", name=op.f("uq_oauth_clients_client_id")),
    )
    op.create_table(
        "policies",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("rules", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_policies")),
        sa.UniqueConstraint("name", name=op.f("uq_policies_name")),
    )
    op.create_table(
        "signing_keys",
        sa.Column("kid", sa.String(length=64), nullable=False),
        sa.Column("algorithm", sa.String(length=16), nullable=False),
        sa.Column("private_pem", sa.Text(), nullable=False),
        sa.Column("active", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("kid", name=op.f("pk_signing_keys")),
    )
    op.create_table(
        "upstreams",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(length=48), nullable=False),
        sa.Column("display_name", sa.String(length=120), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column(
            "transport",
            sa.Enum("stdio", "streamable_http", name="transport", native_enum=False, length=32),
            nullable=False,
        ),
        sa.Column("command", sa.Text(), nullable=True),
        sa.Column("args", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("env", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("cwd", sa.Text(), nullable=True),
        sa.Column("url", sa.Text(), nullable=True),
        sa.Column("headers", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column(
            "status",
            sa.Enum(
                "pending", "connected", "degraded", "disabled", name="upstream_status", native_enum=False, length=32
            ),
            nullable=False,
        ),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("last_synced_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_upstreams")),
        sa.UniqueConstraint("name", name=op.f("uq_upstreams_name")),
    )
    op.create_table(
        "users",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("username", sa.String(length=64), nullable=False),
        sa.Column("display_name", sa.String(length=128), nullable=False),
        sa.Column("password_hash", sa.String(length=256), nullable=False),
        sa.Column("is_admin", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_users")),
        sa.UniqueConstraint("username", name=op.f("uq_users_username")),
    )
    op.create_table(
        "authorization_codes",
        sa.Column("code_hash", sa.String(length=64), nullable=False),
        sa.Column("client_id", sa.String(length=96), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("redirect_uri", sa.Text(), nullable=False),
        sa.Column("scope", sa.Text(), nullable=False),
        sa.Column("resource", sa.Text(), nullable=False),
        sa.Column("code_challenge", sa.String(length=128), nullable=False),
        sa.Column("token_family", sa.Uuid(), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("consumed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["client_id"],
            ["oauth_clients.client_id"],
            name=op.f("fk_authorization_codes_client_id_oauth_clients"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], name=op.f("fk_authorization_codes_user_id_users"), ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("code_hash", name=op.f("pk_authorization_codes")),
    )
    op.create_table(
        "refresh_tokens",
        sa.Column("token_hash", sa.String(length=64), nullable=False),
        sa.Column("family_id", sa.Uuid(), nullable=False),
        sa.Column("client_id", sa.String(length=96), nullable=False),
        sa.Column("subject", sa.String(length=160), nullable=False),
        sa.Column("scope", sa.Text(), nullable=False),
        sa.Column("resource", sa.Text(), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("rotated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["client_id"],
            ["oauth_clients.client_id"],
            name=op.f("fk_refresh_tokens_client_id_oauth_clients"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("token_hash", name=op.f("pk_refresh_tokens")),
    )
    op.create_index(op.f("ix_refresh_tokens_family_id"), "refresh_tokens", ["family_id"], unique=False)
    op.create_table(
        "tools",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("upstream_id", sa.Uuid(), nullable=False),
        sa.Column("upstream_tool_name", sa.String(length=256), nullable=False),
        sa.Column("exposed_name", sa.String(length=128), nullable=False),
        sa.Column(
            "status",
            sa.Enum("pending", "approved", "quarantined", "rejected", name="tool_status", native_enum=False, length=32),
            nullable=False,
        ),
        sa.Column("current_hash", sa.String(length=64), nullable=False),
        sa.Column("current_definition", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("approved_hash", sa.String(length=64), nullable=True),
        sa.Column("approved_definition", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("risk_score", sa.Integer(), nullable=False),
        sa.Column("risk_level", sa.String(length=16), nullable=False),
        sa.Column("scan_report", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("approved_by", sa.String(length=160), nullable=True),
        sa.Column("approved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("first_seen_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("status_changed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("removed_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(
            ["upstream_id"], ["upstreams.id"], name=op.f("fk_tools_upstream_id_upstreams"), ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_tools")),
        sa.UniqueConstraint("exposed_name", name=op.f("uq_tools_exposed_name")),
        sa.UniqueConstraint("upstream_id", "upstream_tool_name", name=op.f("uq_tools_upstream_id")),
    )
    op.create_index(op.f("ix_tools_status"), "tools", ["status"], unique=False)
    op.create_index(op.f("ix_tools_upstream_id"), "tools", ["upstream_id"], unique=False)
    op.create_table(
        "tool_changes",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("tool_id", sa.Uuid(), nullable=False),
        sa.Column(
            "kind",
            sa.Enum("new", "changed", "removed", name="change_kind", native_enum=False, length=32),
            nullable=False,
        ),
        sa.Column("previous_hash", sa.String(length=64), nullable=True),
        sa.Column("new_hash", sa.String(length=64), nullable=False),
        sa.Column("previous_definition", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("new_definition", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("detected_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "resolution",
            sa.Enum(
                "approved", "rejected", "superseded", "reverted", name="change_resolution", native_enum=False, length=32
            ),
            nullable=True,
        ),
        sa.Column("resolved_by", sa.String(length=160), nullable=True),
        sa.ForeignKeyConstraint(
            ["tool_id"], ["tools.id"], name=op.f("fk_tool_changes_tool_id_tools"), ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_tool_changes")),
    )
    op.create_index(op.f("ix_tool_changes_tool_id"), "tool_changes", ["tool_id"], unique=False)
    op.create_table(
        "tool_pins",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("tool_id", sa.Uuid(), nullable=False),
        sa.Column("sha256", sa.String(length=64), nullable=False),
        sa.Column("definition", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("approved_by", sa.String(length=160), nullable=False),
        sa.Column("note", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["tool_id"], ["tools.id"], name=op.f("fk_tool_pins_tool_id_tools"), ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_tool_pins")),
    )
    op.create_index(op.f("ix_tool_pins_tool_id"), "tool_pins", ["tool_id"], unique=False)

    # The audit log is evidence. Updates, deletes and truncation are refused at the database layer, which
    # stops application bugs and SQL injection from rewriting history. A role that owns the table can still
    # drop these triggers, so production runs the app as a separate role (see 0002) with INSERT/SELECT only.
    op.execute(
        """
        CREATE FUNCTION audit_events_append_only() RETURNS trigger AS $$
        BEGIN
          RAISE EXCEPTION 'audit_events is append-only (% blocked)', TG_OP;
        END;
        $$ LANGUAGE plpgsql
        """
    )
    op.execute(
        "CREATE TRIGGER audit_events_no_mutation BEFORE UPDATE OR DELETE ON audit_events "
        "FOR EACH ROW EXECUTE FUNCTION audit_events_append_only()"
    )
    op.execute(
        "CREATE TRIGGER audit_events_no_truncate BEFORE TRUNCATE ON audit_events "
        "FOR EACH STATEMENT EXECUTE FUNCTION audit_events_append_only()"
    )


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS audit_events_no_truncate ON audit_events")
    op.execute("DROP TRIGGER IF EXISTS audit_events_no_mutation ON audit_events")
    op.execute("DROP FUNCTION IF EXISTS audit_events_append_only()")
    op.drop_index(op.f("ix_tool_pins_tool_id"), table_name="tool_pins")
    op.drop_table("tool_pins")
    op.drop_index(op.f("ix_tool_changes_tool_id"), table_name="tool_changes")
    op.drop_table("tool_changes")
    op.drop_index(op.f("ix_tools_upstream_id"), table_name="tools")
    op.drop_index(op.f("ix_tools_status"), table_name="tools")
    op.drop_table("tools")
    op.drop_index(op.f("ix_refresh_tokens_family_id"), table_name="refresh_tokens")
    op.drop_table("refresh_tokens")
    op.drop_table("authorization_codes")
    op.drop_table("users")
    op.drop_table("upstreams")
    op.drop_table("signing_keys")
    op.drop_table("policies")
    op.drop_table("oauth_clients")
    op.drop_index("ix_audit_events_tool_occurred", table_name="audit_events")
    op.drop_index(op.f("ix_audit_events_principal"), table_name="audit_events")
    op.drop_index("ix_audit_events_occurred_at", table_name="audit_events")
    op.drop_index(op.f("ix_audit_events_decision"), table_name="audit_events")
    op.drop_table("audit_events")
