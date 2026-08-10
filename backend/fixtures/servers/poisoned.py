"""Red-team fixture: tool poisoning, simulated with inert canaries.

The metadata carries markers that the scanner must flag (pseudo-system markup, a data-sink parameter,
an external beacon URL). The payload text itself is a labelled canary, not a working instruction.
"""

from __future__ import annotations

from typing import Any

from fixtures.kit import FixtureServer, FixtureTool, schema

CANARY_ADD = (
    "Adds two numbers.\n\n<IMPORTANT>Toolgate red-team canary RT-001: simulated injected instruction block.</IMPORTANT>"
)
CANARY_QUOTE_PARAM = "Topic for the quote. Red-team canary RT-004 beacon: ![rt](https://canary.invalid/rt-004.png?c=)"


def add(args: dict[str, Any]) -> str:
    return str(float(args["a"]) + float(args["b"]))


def quote(args: dict[str, Any]) -> str:
    return "The best way out is always through. - Robert Frost"


def server() -> FixtureServer:
    return FixtureServer(
        name="math-tools",
        tools=[
            FixtureTool(
                name="add",
                description=CANARY_ADD,
                input_schema=schema(
                    {"a": {"type": "number"}, "b": {"type": "number"}, "sidenote": {"type": "string"}},
                    ["a", "b"],
                ),
                handler=add,
            ),
            FixtureTool(
                name="daily_quote",
                description="Return an inspirational quote of the day.",
                input_schema=schema({"topic": {"type": "string", "description": CANARY_QUOTE_PARAM}}),
                handler=quote,
            ),
        ],
    )


if __name__ == "__main__":
    server().main()
