from __future__ import annotations

import base64
import hashlib

from toolgate.auth.pkce import is_valid_challenge, verify_s256

VERIFIER = "dBjftJeZ4CVP-mB92K27uhbUJU1p1r_wW1gWFrnjzK8xfoo0abc123DEF456"


def challenge_for(verifier: str) -> str:
    return base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()


def test_valid_pair() -> None:
    assert verify_s256(VERIFIER, challenge_for(VERIFIER))


def test_wrong_verifier_rejected() -> None:
    assert not verify_s256(VERIFIER, challenge_for("different-verifier-" + VERIFIER))


def test_short_verifier_rejected() -> None:
    assert not verify_s256("tooshort", challenge_for("tooshort"))


def test_challenge_format() -> None:
    assert is_valid_challenge(challenge_for(VERIFIER))
    assert not is_valid_challenge("not-a-valid-challenge")
