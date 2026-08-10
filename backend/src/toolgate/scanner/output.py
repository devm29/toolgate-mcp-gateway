from __future__ import annotations

from collections.abc import Sequence

from toolgate.scanner.models import Severity
from toolgate.scanner.rules import HIDDEN_INSTRUCTION_PATTERNS
from toolgate.scanner.unicode import classify_invisibles

MAX_SCANNED_CHARS = 64_000
_FLAGGED_SEVERITIES = frozenset({Severity.CRITICAL, Severity.HIGH})


def scan_result(texts: Sequence[str]) -> list[str]:
    """Cheap checks for prompt injection in tool output: invisible characters and high-severity steering text."""
    flags: list[str] = []
    for text in texts:
        sample = text[:MAX_SCANNED_CHARS]
        for run in classify_invisibles(sample):
            flags.append(f"{run.count} invisible {run.kind} code point(s)")
        for pattern in HIDDEN_INSTRUCTION_PATTERNS:
            if pattern.severity in _FLAGGED_SEVERITIES and pattern.regex.search(sample):
                flags.append(pattern.title)
    return sorted(set(flags))
