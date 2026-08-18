from urllib.parse import quote

from markupsafe import escape

from .registry import ConfigField, SlideType, register


async def is_available(config: dict) -> bool:
    return bool(config.get("src"))


def _parse_scale(config: dict) -> float:
    try:
        scale = float(config.get("scale") or 1)
    except ValueError:
        scale = 1
    return scale if scale > 0 else 1


async def render(config: dict, slide_id: int | None = None) -> str:
    kind = config.get("kind", "image")
    src = config.get("src", "")
    scale = _parse_scale(config)

    if kind == "video":
        body = f'<video src="{escape(src)}" autoplay muted loop playsinline></video>'
    elif kind == "url":
        bypass_csp = str(config.get("bypass_csp") or "").lower() in ("1", "true", "yes", "on")
        if bypass_csp and slide_id is not None:
            # Look the cookie value up server-side via slide_id instead of
            # passing it through the query string, where it would leak into
            # the DOM and access logs.
            iframe_src = f"/proxy?slide_id={slide_id}"
        elif bypass_csp:
            cookies = (config.get("cookies") or "").strip()
            iframe_src = f"/proxy?url={quote(src, safe='')}"
            if cookies:
                iframe_src += f"&cookies={quote(cookies, safe='')}"
        else:
            iframe_src = src
        no_reset = str(config.get("no_reset") or "").lower() in ("1", "true", "yes", "on")
        no_reset_attr = " data-no-reset" if no_reset else ""
        if scale != 1:
            inv = 100 / scale
            style = (
                f"width:{inv}%;height:{inv}%;border:none;overflow:hidden;"
                f"transform:scale({scale});transform-origin:top left;"
            )
            body = f'<iframe src="{escape(iframe_src)}" style="{style}"{no_reset_attr}></iframe>'
        else:
            body = f'<iframe src="{escape(iframe_src)}" style="overflow:hidden;"{no_reset_attr}></iframe>'
    else:
        body = f'<img src="{escape(src)}" alt="media">'
    return f'<div class="slide slide-media slide-media-{escape(kind)}">{body}</div>'


register(
    SlideType(
        key="media",
        label="Other media (image / video / URL)",
        config_fields=[
            ConfigField(
                name="kind", label="Kind", type="select", options=["image", "video", "url"], default="image"
            ),
            ConfigField(name="src", label="Source (file path or URL)"),
            ConfigField(
                name="scale",
                label="Zoom scale for URL embeds (e.g. 3 for a small widget that won't fill the screen)",
                type="number",
                required=False,
                default="1",
            ),
            ConfigField(
                name="bypass_csp",
                label="Bypass frame-block headers (X-Frame-Options/CSP) for URL embeds",
                type="select",
                options=["no", "yes"],
                required=False,
                default="no",
            ),
            ConfigField(
                name="cookies",
                label="Cookies to send (only used with bypass CSP) — paste 'name=value; name2=value2' "
                "captured from a real browser after accepting/rejecting the site's cookie banner once, "
                "so it isn't re-shown (and its heavy consent JS isn't re-run) on every load",
                type="textarea",
                required=False,
            ),
            ConfigField(
                name="no_reset",
                label="Skip periodic iframe reset (for URL embeds) — the display normally reloads iframes "
                "every 30s to fix scroll drift on embeds it can't control directly; turn this on for an "
                "embed whose own load/login flow takes longer than that, so it isn't perpetually restarted "
                "before it finishes",
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
