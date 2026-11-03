"""Optional shared secret for the web app, REST API and MCP HTTP endpoint.

Unset LOCAL_LINEAR_TOKEN means no login (the default for local, single-user use). When set, every
request must carry it as ``Authorization: Bearer <token>`` or, for browsers, as the cookie that
``/login?token=<token>`` sets.
"""

import hmac
import os

COOKIE = "ll_token"


def token() -> str:
    return os.getenv("LOCAL_LINEAR_TOKEN", "")


def token_ok(authorization: str, cookie: str) -> bool:
    """True if no token is configured, or the Authorization header / cookie carries it."""
    want = token()
    if not want:
        return True
    given = authorization.removeprefix("Bearer ").strip() if authorization.startswith("Bearer ") else cookie
    return hmac.compare_digest(given.encode(), want.encode())
