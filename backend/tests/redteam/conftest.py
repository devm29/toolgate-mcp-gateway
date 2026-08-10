from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

ATTACKS: list[dict[str, str]] = []
REPORT_PATH = Path(__file__).resolve().parents[3] / "docs" / "attack-blocked.json"


def record_attack(*, attack: str, technique: str, fixture: str, decision: str, detail: str) -> None:
    ATTACKS.append(
        {"attack": attack, "technique": technique, "fixture": fixture, "decision": decision, "detail": detail}
    )


@pytest.fixture
def attacks() -> list[dict[str, str]]:
    return ATTACKS


def pytest_sessionfinish(session: pytest.Session, exitstatus: int) -> None:
    if not ATTACKS or exitstatus != 0 or os.environ.get("TOOLGATE_WRITE_ATTACK_REPORT") != "1":
        return
    REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    REPORT_PATH.write_text(json.dumps(sorted(ATTACKS, key=lambda a: a["attack"]), indent=2))
