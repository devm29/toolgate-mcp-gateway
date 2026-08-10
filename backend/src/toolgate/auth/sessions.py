from __future__ import annotations

import hashlib
import hmac
import secrets
import time
import uuid

import jwt

COOKIE_NAME = "toolgate_session"
LOGIN_NONCE_COOKIE = "toolgate_login_nonce"
LOGIN_NONCE_TTL_SECONDS = 15 * 60


class LoginSessions:
    """Signed, short-lived cookie that remembers the resource owner between the login and consent steps."""

    def __init__(self, secret: str, *, ttl_seconds: int, secure: bool) -> None:
        self._secret = secret
        self._ttl = ttl_seconds
        self.secure = secure

    @property
    def ttl(self) -> int:
        return self._ttl

    def issue(self, user_id: uuid.UUID) -> str:
        now = int(time.time())
        return jwt.encode(
            {"sub": str(user_id), "iat": now, "exp": now + self._ttl, "sid": uuid.uuid4().hex},
            self._secret,
            algorithm="HS256",
        )

    def read(self, cookie: str | None) -> uuid.UUID | None:
        if not cookie:
            return None
        try:
            claims = jwt.decode(cookie, self._secret, algorithms=["HS256"], options={"require": ["exp", "sub"]})
            return uuid.UUID(str(claims["sub"]))
        except (jwt.PyJWTError, ValueError):
            return None

    @staticmethod
    def new_login_nonce() -> str:
        return secrets.token_urlsafe(24)

    def login_csrf(self, nonce: str, return_to: str) -> str:
        """Binds the login form to a pre-session cookie so another site cannot sign a victim into its account."""
        return self.csrf_token(f"login:{nonce}", return_to)

    def check_login_csrf(self, token: str, nonce: str | None, return_to: str) -> bool:
        return bool(nonce) and hmac.compare_digest(token, self.login_csrf(nonce or "", return_to))

    def csrf_token(self, cookie: str, *parts: str) -> str:
        message = "\x1f".join((cookie, *parts)).encode()
        return hmac.new(self._secret.encode(), message, hashlib.sha256).hexdigest()

    def check_csrf(self, token: str, cookie: str, *parts: str) -> bool:
        return hmac.compare_digest(token, self.csrf_token(cookie, *parts))
