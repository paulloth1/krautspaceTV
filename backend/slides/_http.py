"""Small shared helper for slide types that fetch data over HTTP.

Several slide types (mastodon, matrix, train, ...) are backed by a remote API
and independently implement near-identical "open an httpx client, GET, parse
JSON, handle errors" boilerplate in render(). fetch_json() factors out that
pattern so each slide type's render() can just await it instead of hand-rolling
its own httpx client/try/except.
"""

import httpx


async def fetch_json(url: str, headers: dict | None = None, timeout: float = 3.0):
    """GET url, raise_for_status, and parse JSON. Returns None on any failure."""
    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            resp = await client.get(url, headers=headers or {})
            resp.raise_for_status()
            return resp.json()
    except (httpx.HTTPError, ValueError):
        return None
