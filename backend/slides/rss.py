import html
import re

import httpx
from defusedxml import ElementTree
from defusedxml.ElementTree import ParseError
from markupsafe import escape

from .registry import ConfigField, SlideType, register

TAG_RE = re.compile(r"<[^>]+>")

# RSS 2.0 uses unprefixed <item>/<title>/<description> tags; Atom uses the
# atom namespace and <entry>/<title>/<summary|content>. Try RSS first, then
# fall back to Atom so both feed flavors work without extra config.
ATOM_NS = "{http://www.w3.org/2005/Atom}"


async def _fetch_text(url: str, timeout: float = 5.0) -> str | None:
    try:
        async with httpx.AsyncClient(timeout=timeout, follow_redirects=True) as client:
            resp = await client.get(url, headers={"User-Agent": "kraut.space-signage/1.0"})
            resp.raise_for_status()
            return resp.text
    except httpx.HTTPError:
        return None


def _strip_html(text: str) -> str:
    text = TAG_RE.sub(" ", text or "")
    text = html.unescape(text)
    return " ".join(text.split())


def _parse_items(xml_text: str, limit: int) -> list[dict] | None:
    try:
        root = ElementTree.fromstring(xml_text)
    except ParseError:
        return None

    items = []

    # RSS 2.0 / RDF: <item> with plain <title>/<description>
    for item in root.iter("item"):
        title = item.findtext("title", "")
        description = item.findtext("description", "")
        items.append({"title": _strip_html(title), "summary": _strip_html(description)})
        if len(items) >= limit:
            return items

    if items:
        return items

    # Atom: <entry> with namespaced <title>/<summary|content>
    for entry in root.iter(f"{ATOM_NS}entry"):
        title = entry.findtext(f"{ATOM_NS}title", "")
        summary = entry.findtext(f"{ATOM_NS}summary") or entry.findtext(f"{ATOM_NS}content") or ""
        items.append({"title": _strip_html(title), "summary": _strip_html(summary)})
        if len(items) >= limit:
            return items

    return items


async def is_available(config: dict) -> bool:
    url = config.get("feed_url", "").strip()
    if not url:
        return False
    text = await _fetch_text(url)
    if text is None:
        return False
    return _parse_items(text, 1) is not None


async def render(config: dict, slide_id: int | None = None) -> str:
    title = config.get("title") or "RSS feed"
    url = config.get("feed_url", "").strip()
    try:
        limit = max(1, int(config.get("item_count") or 5))
    except ValueError:
        limit = 5

    text = await _fetch_text(url)
    if text is None:
        return f'<div class="slide slide-rss"><h2>{escape(title)}</h2><p>Unable to load feed.</p></div>'

    items = _parse_items(text, limit)
    if not items:
        return f'<div class="slide slide-rss"><h2>{escape(title)}</h2><p>Unable to parse feed.</p></div>'

    rows = []
    for entry in items:
        summary = entry["summary"]
        if len(summary) > 200:
            summary = summary[:200].rsplit(" ", 1)[0] + "…"
        summary_html = f'<span class="summary">{escape(summary)}</span>' if summary else ""
        rows.append(f'<li><span class="headline">{escape(entry["title"])}</span>{summary_html}</li>')

    return f'<div class="slide slide-rss"><h2>{escape(title)}</h2><ul class="rss-items">{"".join(rows)}</ul></div>'


register(
    SlideType(
        key="rss",
        label="RSS / Atom feed",
        config_fields=[
            ConfigField(name="feed_url", label="Feed URL"),
            ConfigField(name="title", label="Display title", required=False),
            ConfigField(
                name="item_count",
                label="Number of items to show",
                type="number",
                required=False,
                default="5",
            ),
        ],
        is_available=is_available,
        render=render,
    )
)
