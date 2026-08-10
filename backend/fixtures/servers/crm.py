"""Benign: CRM lookups. Served over Streamable HTTP in the demo to show the second transport."""

from __future__ import annotations

import itertools
from typing import Any

from fixtures.kit import FixtureServer, FixtureTool, schema

CUSTOMERS = {
    "dana@northwind.io": {"id": "cus_8812", "name": "Dana Whitfield", "plan": "Enterprise", "mrr_usd": 4200},
    "li@contoso.app": {"id": "cus_4410", "name": "Li Chen", "plan": "Team", "mrr_usd": 390},
}
_tickets = itertools.count(7301)


def lookup_customer(args: dict[str, Any]) -> dict[str, Any]:
    email = str(args["email"]).lower()
    customer = CUSTOMERS.get(email)
    return {"found": customer is not None, "customer": customer}


def create_ticket(args: dict[str, Any]) -> dict[str, Any]:
    return {
        "ticket": f"T-{next(_tickets)}",
        "customer_id": args["customer_id"],
        "priority": args.get("priority", "normal"),
    }


def server() -> FixtureServer:
    return FixtureServer(
        name="crm",
        tools=[
            FixtureTool(
                name="lookup_customer",
                title="Look up customer",
                description="Find a customer account by email address.",
                input_schema=schema({"email": {"type": "string", "format": "email"}}, ["email"]),
                handler=lookup_customer,
                annotations={"readOnlyHint": True},
            ),
            FixtureTool(
                name="create_ticket",
                title="Create support ticket",
                description="Open a support ticket for a customer.",
                input_schema=schema(
                    {
                        "customer_id": {"type": "string", "pattern": "^cus_[0-9]+$"},
                        "summary": {"type": "string", "maxLength": 500},
                        "priority": {"type": "string", "enum": ["low", "normal", "high", "urgent"]},
                    },
                    ["customer_id", "summary"],
                ),
                handler=create_ticket,
            ),
        ],
    )


if __name__ == "__main__":
    server().main()
