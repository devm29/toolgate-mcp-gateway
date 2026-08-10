"""Benign: transactional email. It is the target that the shadowing fixture tries to hijack."""

from __future__ import annotations

import itertools
from typing import Any

from fixtures.kit import FixtureServer, FixtureTool, schema

_ids = itertools.count(1001)


def send_email(args: dict[str, Any]) -> dict[str, Any]:
    return {"message_id": f"msg_{next(_ids)}", "to": args["to"], "bcc": args.get("bcc", []), "status": "queued"}


def list_inbox(args: dict[str, Any]) -> dict[str, Any]:
    limit = int(args.get("limit", 5))
    messages = [
        {"from": "ops@acme.dev", "subject": "Weekly on-call handoff"},
        {"from": "billing@acme.dev", "subject": "Invoice INV-2291 paid"},
        {"from": "security@acme.dev", "subject": "Quarterly access review"},
    ]
    return {"messages": messages[:limit]}


def server() -> FixtureServer:
    return FixtureServer(
        name="mailer",
        tools=[
            FixtureTool(
                name="send_email",
                title="Send email",
                description="Send a plain-text email from the team mailbox.",
                input_schema=schema(
                    {
                        "to": {"type": "string", "format": "email"},
                        "subject": {"type": "string", "maxLength": 200},
                        "body": {"type": "string", "maxLength": 20000},
                        "bcc": {"type": "array", "items": {"type": "string", "format": "email"}, "maxItems": 5},
                    },
                    ["to", "subject", "body"],
                ),
                handler=send_email,
            ),
            FixtureTool(
                name="list_inbox",
                title="List inbox",
                description="Most recent messages in the team inbox.",
                input_schema=schema({"limit": {"type": "integer", "minimum": 1, "maximum": 50, "default": 5}}),
                handler=list_inbox,
                annotations={"readOnlyHint": True},
            ),
        ],
    )


if __name__ == "__main__":
    server().main()
