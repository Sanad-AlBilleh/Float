"""Signed access tokens shared by both services (Assignment 2, ADR-6).

The personal service signs a token when someone registers or logs in. The households service checks
the signature and expiry itself, with the same TOKEN_SECRET, so it keeps working while the personal
service is down: it never has to ask "who is this?" over the network.

Format: ``f1.<user_id>.<expires_unix>.<nonce>.<signature>``, where the signature is HMAC-SHA256 of
everything before it, base64url without padding. The nonce makes every token unique, so the personal
service can still store a hash of it and revoke it on logout. Revocation is not seen by the households
service until the token expires; ADR-6 records that trade-off.
"""

import base64
import hashlib
import hmac
import secrets
from datetime import UTC, datetime

PREFIX = "f1"


def _signature(secret: str, message: str) -> str:
    digest = hmac.new(secret.encode(), message.encode(), hashlib.sha256).digest()
    return base64.urlsafe_b64encode(digest).rstrip(b"=").decode()


def sign(secret: str, *, user_id: int, expires_at: datetime) -> str:
    if not secret:
        raise ValueError("TOKEN_SECRET is empty")
    message = f"{PREFIX}.{user_id}.{int(expires_at.timestamp())}.{secrets.token_urlsafe(24)}"
    return f"{message}.{_signature(secret, message)}"


def verify(secret: str, token: str | None, *, now: datetime) -> int | None:
    """The user ID in a valid, unexpired token, or None. Never raises on bad input."""
    if not token or not secret:
        return None
    parts = token.split(".")
    if len(parts) != 5 or parts[0] != PREFIX:
        return None
    message, signature = ".".join(parts[:4]), parts[4]
    # Bytes: compare_digest raises TypeError on str with non-ASCII characters (a forged token would 500).
    if not hmac.compare_digest(signature.encode(), _signature(secret, message).encode()):
        return None
    try:
        user_id, expires = int(parts[1]), int(parts[2])
    except ValueError:
        return None
    if user_id < 1 or datetime.fromtimestamp(expires, UTC) <= now:
        return None
    return user_id


def bearer(header: str | None) -> str | None:
    """The token from an ``Authorization: Bearer <token>`` header."""
    if not header:
        return None
    scheme, _, value = header.partition(" ")
    return value.strip() or None if scheme.lower() == "bearer" else None
