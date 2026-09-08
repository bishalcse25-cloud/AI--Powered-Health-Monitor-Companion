"""
Shared SlowAPI limiter.

One `Limiter` instance, imported by both main.py (to register the error
handler and expose it on app.state) and the routers that decorate endpoints
with `@limiter.limit(...)`.

Storage is in-process memory, which is correct for a single Uvicorn worker.
Run more than one worker / process and you must point SlowAPI at Redis
(`storage_uri="redis://..."`) or each worker will keep its own separate
counter and the effective limit multiplies by the worker count.
"""

from slowapi import Limiter
from slowapi.util import get_remote_address


def _client_key(request) -> str:
    """
    Rate-limit key = client IP. Behind a reverse proxy the real client IP is
    in X-Forwarded-For; trust it only because a proxy is expected in front of
    this service in every deployed environment. Locally it falls back to the
    socket address.
    """
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return get_remote_address(request)


limiter = Limiter(key_func=_client_key)
