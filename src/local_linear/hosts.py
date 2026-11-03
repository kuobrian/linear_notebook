"""Host names the web app and the MCP server answer to.

There is no login, so a page on another site could drive the API through DNS rebinding (its own
domain resolved to 127.0.0.1) unless requests with a foreign Host header are refused. Set
LOCAL_LINEAR_ALLOWED_HOSTS (comma separated) to reach the app under another name, e.g. a LAN address.
"""

import os
import re


def allowed_hosts() -> list[str]:
    extra = [h.strip().lower() for h in os.getenv("LOCAL_LINEAR_ALLOWED_HOSTS", "").split(",") if h.strip()]
    return ["127.0.0.1", "localhost", "[::1]", *extra]


def host_allowed(header: str) -> bool:
    """True if a Host header ("localhost:8000", "[::1]:8000", "127.0.0.1") names an allowed host."""
    return re.sub(r":\d+$", "", header.strip().lower()) in allowed_hosts()
