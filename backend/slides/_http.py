"""Small shared helpers for slide types that fetch data over HTTP.

Several slide types (mastodon, matrix, train, ...) independently implement
near-identical "open an httpx client, GET, handle errors" boilerplate for
both is_available() and render(). These two helpers factor out that pattern.
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


async def url_ok(url: str, headers: dict | None = None, timeout: float = 3.0) -> bool:
    """GET url and report whether it responded with HTTP 200. False on any failure."""
    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            resp = await client.get(url, headers=headers or {})
            return resp.status_code == 200
    except httpx.HTTPError:
        return False
