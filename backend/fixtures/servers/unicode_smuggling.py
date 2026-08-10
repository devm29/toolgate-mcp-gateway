"""Red-team fixture: invisible Unicode. Tag characters encode a canary string a reviewer cannot see."""

from __future__ import annotations

from typing import Any

from fixtures.kit import FixtureServer, FixtureTool, schema

HIDDEN_CANARY = "RT-005 hidden canary"


def encode_tags(text: str) -> str:
    return "".join(chr(0xE0000 + ord(c)) for c in text)


DESCRIPTION = f"Translate text between languages.{encode_tags(HIDDEN_CANARY)} Supports 40 languages.​​"


def translate(args: dict[str, Any]) -> str:
    return f"[{args['target']}] {args['text']}"


def server() -> FixtureServer:
    return FixtureServer(
        name="translator",
        tools=[
            FixtureTool(
                name="translate",
                description=DESCRIPTION,
                input_schema=schema(
                    {
                        "text": {"type": "string", "maxLength": 5000},
                        "target": {"type": "string", "pattern": "^[a-z]{2}$"},
                    },
                    ["text", "target"],
                ),
                handler=translate,
            )
        ],
    )


if __name__ == "__main__":
    server().main()
