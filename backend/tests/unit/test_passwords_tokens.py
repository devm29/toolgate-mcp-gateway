from __future__ import annotations

from toolgate.auth.passwords import hash_password, hash_token, verify_password


def test_password_roundtrip() -> None:
    encoded = hash_password("correct horse")
    assert verify_password("correct horse", encoded)
    assert not verify_password("wrong", encoded)


def test_password_salted() -> None:
    assert hash_password("same") != hash_password("same")


def test_token_hash_deterministic() -> None:
    assert hash_token("abc") == hash_token("abc")
    assert len(hash_token("abc")) == 64
