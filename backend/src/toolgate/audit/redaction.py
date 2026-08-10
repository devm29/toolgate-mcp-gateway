from __future__ import annotations

import re
from typing import Any

REDACTED = "[REDACTED]"
MAX_STRING = 512
MAX_ITEMS = 50
MAX_DEPTH = 6

_SECRET_KEY = re.compile(
    r"(pass(word|wd|phrase)?|secret|token|api[_-]?key|authorization|auth|cookie|session|credential|private[_-]?key|"
    r"ssn|card[_-]?number|cvv|pin)$",
    re.IGNORECASE,
)
_SECRET_VALUE = (
    re.compile(r"\beyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\b"),
    re.compile(r"\b(sk|pk|rk)[-_](live|test|ant|proj)?[-_]?[A-Za-z0-9_-]{16,}\b"),
    re.compile(r"\bAKIA[0-9A-Z]{16}\b"),
    re.compile(r"\bgh[pousr]_[A-Za-z0-9]{30,}\b"),
    re.compile(r"\bxox[abpr]-[A-Za-z0-9-]{10,}\b"),
    re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----.*?-----END [A-Z ]*PRIVATE KEY-----", re.DOTALL),
    re.compile(r"(?i)\bbearer\s+[A-Za-z0-9._~+/-]{16,}=*"),
)


_CARD_CANDIDATE = re.compile(r"\b\d(?:[ -]?\d){12,18}\b")


def _luhn_valid(digits: str) -> bool:
    total = 0
    for index, char in enumerate(reversed(digits)):
        n = int(char)
        if index % 2 == 1:
            n = n * 2 - 9 if n > 4 else n * 2
        total += n
    return total % 10 == 0


def _mask_card(match: re.Match[str]) -> str:
    digits = re.sub(r"\D", "", match.group(0))
    return REDACTED if _luhn_valid(digits) else match.group(0)


def _scrub(text: str) -> str:
    for pattern in _SECRET_VALUE:
        text = pattern.sub(REDACTED, text)
    text = _CARD_CANDIDATE.sub(_mask_card, text)
    if len(text) > MAX_STRING:
        text = f"{text[:MAX_STRING]}… (+{len(text) - MAX_STRING} chars)"
    return text


def redact(value: Any, *, depth: int = 0) -> Any:
    """Audit logs must be useful to investigators without becoming a second copy of everyone's secrets."""
    if depth >= MAX_DEPTH:
        return "…"
    if isinstance(value, dict):
        out: dict[str, Any] = {}
        for index, (key, item) in enumerate(value.items()):
            if index >= MAX_ITEMS:
                out["…"] = f"+{len(value) - MAX_ITEMS} keys"
                break
            name = str(key)
            out[name] = REDACTED if _SECRET_KEY.search(name) else redact(item, depth=depth + 1)
        return out
    if isinstance(value, list | tuple):
        items = [redact(v, depth=depth + 1) for v in list(value)[:MAX_ITEMS]]
        if len(value) > MAX_ITEMS:
            items.append(f"… +{len(value) - MAX_ITEMS} items")
        return items
    if isinstance(value, str):
        return _scrub(value)
    if value is None or isinstance(value, bool | int | float):
        return value
    return _scrub(str(value))


def _secret_values(value: Any, *, depth: int = 0) -> list[str]:
    if depth >= MAX_DEPTH:
        return []
    found: list[str] = []
    if isinstance(value, dict):
        for key, item in value.items():
            if _SECRET_KEY.search(str(key)) and isinstance(item, str | int | float) and len(str(item)) >= 4:
                found.append(str(item))
            else:
                found.extend(_secret_values(item, depth=depth + 1))
    elif isinstance(value, list | tuple):
        for item in value:
            found.extend(_secret_values(item, depth=depth + 1))
    return found


def redact_text(text: str, arguments: dict[str, Any] | None = None) -> str:
    """Free text that may quote arguments (error messages, reasons) gets the same masking as the arguments."""
    for secret in sorted(set(_secret_values(arguments or {})), key=len, reverse=True):
        text = text.replace(secret, REDACTED)
    return _scrub(text)


def redact_arguments(arguments: dict[str, Any] | None) -> dict[str, Any]:
    result = redact(arguments or {})
    return result if isinstance(result, dict) else {}
