import html
import re
from urllib.parse import quote

from markupsafe import escape

import httpx

from .registry import ConfigField, SlideType, register

TAG_RE = re.compile(r"<[^>]+>")


def _timeline_url(config: dict, limit: int) -> str:
    instance = config.get("instance", "").strip().rstrip("/")
    tag = quote(config.get("hashtag", "").strip().lstrip("#"))
    return f"https://{instance}/api/v1/timelines/tag/{tag}?limit={limit}"


def _strip_html(content: str) -> str:
    text = TAG_RE.sub(" ", content)
    text = html.unescape(text)
    return " ".join(text.split())


def _headers(config: dict) -> dict:
    token = config.get("access_token", "")
    return {"Authorization": f"Bearer {token}"} if token else {}


async def is_available(config: dict) -> bool:
    if not config.get("instance") or not config.get("hashtag"):
        return False
    try:
        async with httpx.AsyncClient(timeout=3.0) as client:
            resp = await client.get(_timeline_url(config, 1), headers=_headers(config))
            return resp.status_code == 200
    except httpx.HTTPError:
        return False


async def render(config: dict, slide_id: int | None = None) -> str:
    hashtag = config.get("hashtag", "").strip().lstrip("#")
    title = config.get("title") or f"#{hashtag}"
    try:
        async with httpx.AsyncClient(timeout=3.0) as client:
            resp = await client.get(_timeline_url(config, 10), headers=_headers(config))
            resp.raise_for_status()
            statuses = resp.json()
    except (httpx.HTTPError, ValueError):
        return f'<div class="slide slide-mastodon"><h2>{escape(title)}</h2><p>Unable to load posts.</p></div>'

    items = []
    for status in statuses:
        account = status.get("account", {})
        sender = account.get("display_name") or account.get("acct", "")
        body = _strip_html(status.get("content", ""))
        items.append(
            f'<li><span class="sender">{escape(sender)}</span>: {escape(body)}</li>'
        )

    body_html = f'<ul class="mastodon-posts">{"".join(items)}</ul>' if items else "<p>No recent posts.</p>"
    return f'<div class="slide slide-mastodon"><h2>{escape(title)}</h2>{body_html}</div>'


register(
    SlideType(
        key="mastodon",
        label="Mastodon hashtag",
        config_fields=[
            ConfigField(name="instance", label="Instance domain (e.g. mastodon.social)"),
            ConfigField(name="hashtag", label="Hashtag (without #)"),
            ConfigField(
                name="access_token",
                label="Access token (only needed if the instance requires auth for public timelines)",
                type="password",
                required=False,
            ),
            ConfigField(name="title", label="Display title", required=False),
        ],
        is_available=is_available,
        render=render,
    )
)
