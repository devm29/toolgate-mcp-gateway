from __future__ import annotations

from toolgate.audit.redaction import REDACTED, redact_arguments


def test_secret_keys_redacted() -> None:
    out = redact_arguments({"password": "hunter2", "api_key": "x", "note": "fine"})
    assert out["password"] == REDACTED
    assert out["api_key"] == REDACTED
    assert out["note"] == "fine"


def test_jwt_value_redacted() -> None:
    token = "eyJhbGciOi.eyJzdWIiOiAxMjN9.abcDEFghiJKL"
    out = redact_arguments({"body": f"Authorization: Bearer {token}"})
    assert token not in out["body"]


def test_valid_card_redacted_invalid_kept() -> None:
    out = redact_arguments({"valid": "4242 4242 4242 4242", "invalid": "1234 5678 9012 3456"})
    assert out["valid"] == REDACTED
    assert out["invalid"] == "1234 5678 9012 3456"


def test_nested_depth_limited() -> None:
    nested: dict = {}
    cur = nested
    for _ in range(10):
        cur["child"] = {}
        cur = cur["child"]
    out = redact_arguments({"root": nested})
    assert out  # does not raise


def test_long_string_truncated() -> None:
    out = redact_arguments({"blob": "a" * 2000})
    assert out["blob"].endswith("chars)")
