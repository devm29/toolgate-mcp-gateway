"""Benign: a weather service with deterministic forecasts."""

from __future__ import annotations

import hashlib
from typing import Any

from fixtures.kit import FixtureServer, FixtureTool, schema

CONDITIONS = ["Clear", "Partly cloudy", "Overcast", "Light rain", "Showers", "Fog", "Windy"]


def _seed(*parts: str) -> int:
    return int(hashlib.sha256("|".join(parts).encode()).hexdigest()[:8], 16)


def forecast(args: dict[str, Any]) -> dict[str, Any]:
    city = str(args["city"]).strip()
    days = int(args.get("days", 3))
    if not 1 <= days <= 7:
        raise ValueError("days must be between 1 and 7")
    out = []
    for day in range(days):
        seed = _seed(city.lower(), str(day))
        out.append(
            {
                "day": day,
                "condition": CONDITIONS[seed % len(CONDITIONS)],
                "high_c": 12 + seed % 17,
                "low_c": 4 + seed % 9,
                "precipitation_pct": seed % 80,
            }
        )
    return {"city": city, "days": out}


def alerts(args: dict[str, Any]) -> dict[str, Any]:
    region = str(args["region"])
    active = _seed(region) % 3 == 0
    return {
        "region": region,
        "alerts": [{"severity": "moderate", "headline": f"Wind advisory for {region} until 18:00"}] if active else [],
    }


def server() -> FixtureServer:
    return FixtureServer(
        name="weather",
        tools=[
            FixtureTool(
                name="get_forecast",
                title="Get forecast",
                description=(
                    "Daily forecast for a city: conditions, high and low temperature in Celsius, chance of rain."
                ),
                input_schema=schema(
                    {
                        "city": {"type": "string", "description": "City name, e.g. Lisbon", "minLength": 1},
                        "days": {"type": "integer", "minimum": 1, "maximum": 7, "default": 3},
                    },
                    ["city"],
                ),
                handler=forecast,
                annotations={"readOnlyHint": True, "openWorldHint": True},
            ),
            FixtureTool(
                name="get_alerts",
                title="Get weather alerts",
                description="Active severe-weather alerts for a region.",
                input_schema=schema({"region": {"type": "string", "description": "Region or state code"}}, ["region"]),
                handler=alerts,
                annotations={"readOnlyHint": True},
            ),
        ],
    )


if __name__ == "__main__":
    server().main()
