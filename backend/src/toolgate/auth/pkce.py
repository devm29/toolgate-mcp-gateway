from __future__ import annotations

import hmac
import re

from authlib.oauth2.rfc7636 import create_s256_code_challenge

# RFC 7636 section 4.1: 43-128 characters from the unreserved set.
_VERIFIER = re.compile(r"^[A-Za-z0-9\-._~]{43,128}$")
_CHALLENGE = re.compile(r"^[A-Za-z0-9\-_]{43}$")


def is_valid_challenge(challenge: str) -> bool:
    return bool(_CHALLENGE.match(challenge))


def verify_s256(verifier: str, challenge: str) -> bool:
    if not _VERIFIER.match(verifier):
        return False
    computed: str = create_s256_code_challenge(verifier)
    return hmac.compare_digest(computed, challenge)
