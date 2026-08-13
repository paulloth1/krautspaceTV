import html
import re

import httpx
from defusedxml import ElementTree
from defusedxml.ElementTree import ParseError
from markupsafe import escape

from .registry import ConfigField, SlideType, register

TAG_RE = re.compile(r"<[^>]+>")
MD_BOLD_RE = re.compile(r"\*\*(.+?)\*\*")
LIST_ITEM_RE = re.compile(r"(?i)<li[^>]*>")
BLOCK_BREAK_RE = re.compile(r"(?i)</(?:p|li|div|h[1-6])>|<br\s*/?>")

# RSS 2.0 uses unprefixed <item>/<title>/<description> tags; Atom uses the
# atom namespace and <entry>/<title>/<summary|content>. Try RSS first, then
# fall back to Atom so both feed flavors work without extra config.
ATOM_NS = "{http://www.w3.org/2005/Atom}"
DC_NS = "{http://purl.org/dc/elements/1.1/}"
CONTENT_NS = "{http://purl.org/rss/1.0/modules/content/}"
MEDIA_NS = "{http://search.yahoo.com/mrss/}"

MASTODON_AUTHOR_RE = re.compile(r"https?://([^/]+)/@([^/]+)/")


RSS_AUTHOR_EMAIL_RE = re.compile(r"^\S+@\S+\s*\((.+)\)$")


def _guess_author(item, author: str) -> str:
    if author:
        author = _strip_html(author)
        # RSS 2.0's <author> is "email (Display Name)" per spec — the email
        # itself isn't useful on a TV, so show just the display name.
        match = RSS_AUTHOR_EMAIL_RE.match(author)
        return match.group(1) if match else author
    # Mastodon (and similar ActivityPub) feeds carry no <author>/<dc:creator>
    # but their item/entry link is always https://instance/@username/<id> —
    # pull instance + username out of that as a fallback, giving the full
    # @username@instance handle rather than just the bare username.
    for tag in ("link", "guid"):
        value = item.findtext(tag, "")
        match = MASTODON_AUTHOR_RE.search(value)
        if match:
            instance, username = match.groups()
            return f"@{username}@{instance}"
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


def _html_to_lines(raw_html: str) -> list[str]:
    """Turn a fragment of post-body HTML into plain-text lines, treating
    <p>/<li>/<div>/<br> as line breaks instead of collapsing everything
    (as _strip_html does) into one run-on line."""
    text = LIST_ITEM_RE.sub("\n• ", raw_html or "")
    text = BLOCK_BREAK_RE.sub("\n", text)
    text = TAG_RE.sub("", text)
    text = html.unescape(text)
    text = MD_BOLD_RE.sub(r"\1", text)
    lines = (" ".join(line.split()) for line in text.split("\n"))
    return [line for line in lines if line]


def _first_image_url(item) -> str:
    # media:content is how Mastodon/ActivityPub-style feeds (and Media RSS in
    # general) attach post images; grab the first one so it can be shown as a
    # thumbnail alongside the text.
    for media in item.findall(f"{MEDIA_NS}content"):
        media_type = media.get("type", "")
        url = media.get("url", "")
        if url and (media_type.startswith("image/") or media.get("medium") == "image"):
            return url
    return ""


def _pick_headline(title: str, lines: list[str]) -> tuple[str, list[str]]:
    title = title.strip()
    # Some generators (e.g. GoToSocial) truncate <title> to a fixed length
    # and mark it with a trailing ellipsis, while still providing the full,
    # untruncated text in the body — prefer that over a cut-off title.
    truncated = title.endswith("...") or title.endswith("…")
    if title and not truncated:
        return title, lines
    if lines:
        return lines[0], lines[1:]
    return title, lines


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
        headline, lines = _pick_headline(_strip_html(title), _html_to_lines(description))
        items.append({
            "title": headline,
            "lines": lines,
            "author": _guess_author(item, author),
            "image_url": _first_image_url(item),
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
        headline, lines = _pick_headline(_strip_html(title), _html_to_lines(summary))
        items.append({
            "title": headline,
            "lines": lines,
            "author": _guess_author(entry, author),
            "image_url": "",
        })
        if len(items) >= limit:
            return items

    return items


def _join_lines(lines: list[str], budget: int) -> str:
    out = []
    used = 0
    for line in lines:
        if used + len(line) > budget:
            remaining = budget - used
            if remaining > 20:
                out.append(line[:remaining].rsplit(" ", 1)[0] + "…")
            break
        out.append(line)
        used += len(line)
    return "\n".join(out)


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
    show_images = config.get("show_images") == "yes"
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

    # More items on screen at once means less room for each one's body text
    # before it starts pushing later items off the bottom of the slide.
    summary_budget = max(200, 900 // len(items))

    rows = []
    for entry in items:
        summary = _join_lines(entry["lines"], summary_budget)
        author_html = f'<span class="sender">{escape(entry["author"])}</span> ' if entry["author"] else ""
        summary_html = f'<span class="summary">{escape(summary)}</span>' if summary else ""
        text_html = f'<div class="rss-text">{author_html}<span class="headline">{escape(entry["title"])}</span>{summary_html}</div>'
        if show_images and entry["image_url"]:
            image_html = f'<img class="rss-thumb" src="{escape(entry["image_url"])}" loading="lazy" alt="">'
            rows.append(f'<li class="has-image">{image_html}{text_html}</li>')
        else:
            rows.append(f'<li>{text_html}</li>')

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
            ConfigField(
                name="show_images",
                label="Show post images (if the feed includes any)",
                type="select",
                options=["no", "yes"],
                required=False,
                default="no",
            ),
        ],
        is_available=is_available,
        render=render,
    )
)
