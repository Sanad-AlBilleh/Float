"""Cookie names, CSRF checks, and redirect safety for browser requests (SRS §9)."""

import hmac
from urllib.parse import urlsplit

from starlette.requests import Request

SESSION_COOKIE = "float_session"
ANON_CSRF_COOKIE = "float_csrf"
UNSAFE_METHODS = frozenset({"POST", "PUT", "PATCH", "DELETE"})


class CsrfError(Exception):
    """The request failed the CSRF token or origin check."""


def same_origin(request: Request) -> bool:
    """Browsers send Origin (or at least Referer) on form posts; both must name this site."""
    expected = f"{request.url.scheme}://{request.url.netloc}"
    origin = request.headers.get("origin")
    if origin is not None:
        return origin == expected
    referer = request.headers.get("referer")
    if referer is not None:
        return referer == expected or referer.startswith(expected + "/")
    return True  # Non-browser clients send neither header; the token check still applies.


def tokens_match(submitted: str | None, expected: str | None) -> bool:
    if not submitted or not expected:
        return False
    return hmac.compare_digest(submitted.encode(), expected.encode())


def safe_next(target: str | None) -> str:
    """Only paths on this site are allowed as post-login redirects; anything else goes home."""
    if not target or not target.startswith("/") or target.startswith("//") or "\\" in target:
        return "/"
    # Like browsers, urlsplit drops tabs and newlines, so "/\t/evil.example" is seen as "//evil.example".
    parts = urlsplit(target)
    return "/" if parts.scheme or parts.netloc else target
