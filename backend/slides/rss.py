import html
import re

import httpx
from defusedxml import ElementTree
from defusedxml.ElementTree import ParseError
from markupsafe import escape

from .registry import ConfigField, SlideType, register

TAG_RE = re.compile(r"<[^>]+>")
MD_BOLD_RE = re.compile(r"\*\*(.+?)\*\*")

# RSS 2.0 uses unprefixed <item>/<title>/<description> tags; Atom uses the
# atom namespace and <entry>/<title>/<summary|content>. Try RSS first, then
# fall back to Atom so both feed flavors work without extra config.
ATOM_NS = "{http://www.w3.org/2005/Atom}"
DC_NS = "{http://purl.org/dc/elements/1.1/}"
CONTENT_NS = "{http://purl.org/rss/1.0/modules/content/}"

MASTODON_AUTHOR_RE = re.compile(r"/@([^/]+)/")


def _guess_author(item, author: str) -> str:
    if author:
        return _strip_html(author)
    # Mastodon (and similar ActivityPub) feeds carry no <author>/<dc:creator>
    # but their item/entry link is always .../@username/<id> — pull the
    # username out of that as a fallback so posts aren't left unattributed.
    for tag in ("link", "guid"):
        value = item.findtext(tag, "")
        match = MASTODON_AUTHOR_RE.search(value)
        if match:
            return "@" + match.group(1)
    return ""


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
    text = MD_BOLD_RE.sub(r"\1", text)
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
        # content:encoded (full post body) is preferred over <description>,
        # which some generators (e.g. GoToSocial) wrap in boilerplate like
        # "X made a new post: ..." instead of just the post text.
        description = item.findtext(f"{CONTENT_NS}encoded") or item.findtext("description", "")
        author = item.findtext("author", "") or item.findtext(f"{DC_NS}creator", "")
        items.append({
            "title": _strip_html(title),
            "summary": _strip_html(description),
            "author": _guess_author(item, author),
        })
        if len(items) >= limit:
            return items

    if items:
        return items

    # Atom: <entry> with namespaced <title>/<summary|content>
    for entry in root.iter(f"{ATOM_NS}entry"):
        title = entry.findtext(f"{ATOM_NS}title", "")
        summary = entry.findtext(f"{ATOM_NS}summary") or entry.findtext(f"{ATOM_NS}content") or ""
        author = entry.findtext(f"{ATOM_NS}author/{ATOM_NS}name", "")
        items.append({
            "title": _strip_html(title),
            "summary": _strip_html(summary),
            "author": _guess_author(entry, author),
        })
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
        headline = entry["title"]
        summary = entry["summary"]
        if not headline:
            # Some feeds (e.g. Mastodon tag RSS) omit <title> entirely and
            # only carry the post body in <description> — use the start of
            # that as the headline instead of leaving it blank.
            cutoff = summary[:80].rsplit(" ", 1)[0] or summary[:80]
            headline, summary = cutoff, summary[len(cutoff):].lstrip()
        if len(summary) > 200:
            summary = summary[:200].rsplit(" ", 1)[0] + "…"
        author_html = f'<span class="sender">{escape(entry["author"])}</span> ' if entry["author"] else ""
        summary_html = f'<span class="summary">{escape(summary)}</span>' if summary else ""
        rows.append(f'<li>{author_html}<span class="headline">{escape(headline)}</span>{summary_html}</li>')

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
