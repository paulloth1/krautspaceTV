import asyncio
import ipaddress
import json
import os
import re
import socket
from contextlib import asynccontextmanager
from pathlib import Path
from urllib.parse import urljoin, urlparse

import httpx
from markupsafe import escape
from fastapi import FastAPI, Form, Request
from fastapi.responses import RedirectResponse, Response
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from . import db, system_info
from .preview import get_preview_png
from .rotation import STATE, rotation_loop
from .slides import REGISTRY

BASE_DIR = Path(__file__).parent

# We run four separate uvicorn processes bound to different host:ports (see
# README) since one port can't serve both plain HTTP and TLS. Only one of them
# ("the owner", the kiosk-internal 127.0.0.1:8081 instance that actually drives
# the display) runs the rotation loop; the others forward reads/writes of the
# current-slide state to it over loopback HTTP, so "View now" and "now
# displaying" are consistent no matter which port a client used.
IS_ROTATION_OWNER = os.environ.get("SIGNAGE_ROTATION_OWNER") == "1"
ROTATION_OWNER_URL = os.environ.get("SIGNAGE_ROTATION_OWNER_URL", "http://127.0.0.1:8081")

# Rotation interval should reset to 60s on every actual Pi reboot, but survive
# service restarts within the same boot (e.g. redeploys) so an admin change
# isn't silently undone mid-session. The kernel hands out a fresh random
# boot_id on every boot (and never changes it for the life of that boot), so
# comparing it against the last one we saw (stored in our own settings table)
# distinguishes "first owner startup this boot" from "just restarted" without
# needing write access to anything outside the sqlite DB we already use.
BOOT_ID_PATH = Path("/proc/sys/kernel/random/boot_id")


def _current_boot_id() -> str:
    try:
        return BOOT_ID_PATH.read_text().strip()
    except OSError:
        return ""


async def _forward_to_owner(method: str, path: str, **kwargs) -> httpx.Response | None:
    """Forward a request to the rotation owner process over loopback HTTP.

    Returns the response, or None if the owner is unreachable (connection
    error, timeout, etc.) so callers can apply their own fallback.
    """
    try:
        async with httpx.AsyncClient(timeout=5) as client:
            return await client.request(method, f"{ROTATION_OWNER_URL}{path}", **kwargs)
    except httpx.HTTPError:
        return None

# Third-party ad/consent (IAB TCF) vendor scripts known to hang the Pi's weak
# CPU by synchronously processing hundreds of vendor entries on page load.
# Strip <script> tags loading from these hosts before handing pages to Chromium.
HEAVY_SCRIPT_HOSTS = [
    "opencmp.net",
    "cdntrf.com",
]
SCRIPT_TAG_RE = re.compile(r"<script\b[^>]*src=[\"']([^\"']+)[\"'][^>]*>.*?</script>", re.IGNORECASE | re.DOTALL)

# dbf.finalrewind.org (departure board embeds) picks light/dark CSS via a
# <link id="theme"> tag, defaulting to "light" before its own JS swaps it based
# on localStorage/system preference. Force it straight to dark for the kiosk.
THEME_LINK_RE = re.compile(r'<link\b[^>]*\bid=["\']theme["\'][^>]*>', re.IGNORECASE)
# ...its inline <script> re-checks matchMedia('prefers-color-scheme') on every
# load and overwrites that link again, racing our substitution above. Strip any
# inline (no-src) script mentioning it so our forced dark link always wins.
INLINE_SCRIPT_RE = re.compile(r"<script(?![^>]*\bsrc=)[^>]*>(.*?)</script>", re.IGNORECASE | re.DOTALL)

# The kiosk display has no one to click "accept"/"reject" on a cookie banner, so
# just hide the common ones outright rather than leaving them stuck on screen.
COOKIE_BANNER_CSS = """
<style>
.contao-cookiebar, .cc-window, .cookie-consent, .cookiebar, .cookie-banner,
#cookie-consent, #cookiebar, #CybotCookiebotDialog, .cmpbox, .fc-consent-root {
  display: none !important;
}
</style>
"""

# kraut.space/chat/ (the Candy XMPP webchat client) connects anonymously but
# still prompts for a nickname via a #login-form before it'll join the room -
# there's no one at the kiosk to type one in, so auto-fill and submit that
# form (and any "nickname already taken" #nickname-conflict-form retry) with
# a fixed nickname via injected JS instead. Candy already loads jQuery, which
# this relies on being present by the time the script runs (placed at the end
# of body, after Candy's own scripts).
KRAUT_CHAT_NICKNAME = "krautspaceTV"
CANDY_AUTOJOIN_SCRIPT = f"""
<script>
(function() {{
  var NICKNAME = {json.dumps(KRAUT_CHAT_NICKNAME)};
  function trySubmit() {{
    if (typeof jQuery === 'undefined') return;
    var $login = jQuery('#login-form');
    if ($login.length) {{
      jQuery('#username').val(NICKNAME);
      $login.trigger('submit');
      return;
    }}
    var $conflict = jQuery('#nickname-conflict-form');
    if ($conflict.length) {{
      jQuery('#nickname').val(NICKNAME + '-' + Math.floor(Math.random() * 1000));
      $conflict.trigger('submit');
    }}
  }}
  setInterval(trySubmit, 500);
}})();
</script>
"""

# The kiosk wants the message list only, not Candy's full multi-room chat UI
# (room tabs, user roster sidebar, the message-compose box - nobody's typing
# from the TV). #chat-tabs/.roster-pane/.message-form-wrapper's own CSS
# (res/default.css) reserves space for them via margins on
# .message-pane-wrapper, so hiding them alone would leave that space blank -
# zero the margin out too so the message list fills the screen.
CANDY_TRIM_CSS = """
<style>
#chat-tabs, .roster-pane, .message-form-wrapper, #mobile-roster-icon, #chat-toolbar {
  display: none !important;
}
.message-pane-wrapper {
  margin: 0 !important;
}
</style>
"""


@asynccontextmanager
async def lifespan(app: FastAPI):
    await db.init_db()
    if IS_ROTATION_OWNER:
        boot_id = _current_boot_id()
        if boot_id and boot_id != await db.get_setting("last_boot_id"):
            await db.set_setting("rotation_interval_seconds", "60")
            await db.set_setting("last_boot_id", boot_id)
    task = asyncio.create_task(rotation_loop()) if IS_ROTATION_OWNER else None
    yield
    if task:
        task.cancel()


app = FastAPI(lifespan=lifespan)
app.mount("/static", StaticFiles(directory=BASE_DIR / "static"), name="static")
templates = Jinja2Templates(directory=BASE_DIR / "templates")


@app.middleware("http")
async def static_no_cache(request: Request, call_next):
    # Static files (CSS/JS) had no Cache-Control at all, so browsers fell back
    # to heuristic caching and could keep serving a stale copy indefinitely
    # (and independently per http/https origin) after an update. Force
    # revalidation on every load instead — still fast (ETag/Last-Modified
    # already set by StaticFiles give a cheap 304), but never silently stale.
    response = await call_next(request)
    if request.url.path.startswith("/static/"):
        response.headers["Cache-Control"] = "no-cache"
    return response


@app.get("/display")
async def display(request: Request):
    return templates.TemplateResponse(request, "display.html", {})


@app.get("/api/slide/current")
async def slide_current():
    if IS_ROTATION_OWNER:
        return await STATE.snapshot()
    resp = await _forward_to_owner("GET", "/api/slide/current")
    if resp is not None:
        return resp.json()
    return {
        "id": None,
        "html": '<div class="slide slide-empty"><h2>Rotation owner unreachable</h2></div>',
        "forced": False,
        "seconds_remaining": None,
    }


@app.get("/api/slide/visible")
async def slide_visible():
    if IS_ROTATION_OWNER:
        return await STATE.visible_snapshot()
    resp = await _forward_to_owner("GET", "/api/slide/visible")
    if resp is not None:
        return resp.json()
    return {"id": None, "forced": False}


@app.post("/api/slide/visible")
async def report_slide_visible(id: int | None = None, forced: bool = False):
    if IS_ROTATION_OWNER:
        await STATE.report_visible(id, forced)
    else:
        params = {"forced": forced}
        if id is not None:
            params["id"] = id
        await _forward_to_owner("POST", "/api/slide/visible", params=params)
    return {"ok": True}


def _resolve_hostname_ips(hostname: str) -> list[ipaddress.IPv4Address | ipaddress.IPv6Address]:
    """Resolve `hostname` to the IP address(es) it currently points to. A bare
    IP literal resolves to itself without touching DNS; anything else goes
    through getaddrinfo (which may return multiple/mixed v4+v6 records)."""
    try:
        return [ipaddress.ip_address(hostname)]
    except ValueError:
        pass
    try:
        infos = socket.getaddrinfo(hostname, None)
    except socket.gaierror:
        return []
    ips = []
    for info in infos:
        try:
            ips.append(ipaddress.ip_address(info[4][0]))
        except ValueError:
            continue
    return ips


def _is_internal_address(ip: ipaddress.IPv4Address | ipaddress.IPv6Address) -> bool:
    return (
        ip.is_private
        or ip.is_loopback
        or ip.is_link_local
        or ip.is_multicast
        or ip.is_reserved
        or ip.is_unspecified
    )


def ssrf_check(url: str) -> str | None:
    """SSRF guard for GET /proxy's untrusted `?url=` param: returns an error
    message if `url` is unsafe for this server to fetch on a stranger's
    request, or None if it looks safe.

    The server listens on 0.0.0.0:80/443 with no auth, so anyone on the
    internet can ask it to fetch an arbitrary URL. Without this check they
    could use it as an open proxy to probe/reach services on the local LAN
    (or loopback on the Pi itself) that were never meant to be internet-
    reachable - e.g. http://192.168.x.x/... or http://127.0.0.1:.../admin.
    A hostname's DNS can point anywhere (including changing between checks,
    aka DNS rebinding), so this resolves and checks the actual IP(s) rather
    than trusting the hostname string. Do NOT remove this thinking it's
    unnecessary - it's the whole fix for GH issue #16.

    This must only be applied to the raw `url` query-param path. It is
    intentionally NOT applied when the URL instead comes from a stored
    slide's config (`slide_id` given) - that's admin-controlled server-side
    data, not attacker-controlled per-request input, and an admin may
    legitimately want to embed something on the LAN (e.g. a local device's
    web UI) in a slide.
    """
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https"):
        return "URL scheme must be http or https"
    hostname = parsed.hostname
    if not hostname:
        return "Missing hostname"
    ips = _resolve_hostname_ips(hostname)
    if not ips:
        return "Could not resolve hostname"
    for ip in ips:
        if _is_internal_address(ip):
            return "URL resolves to a private/internal address"
    return None


@app.get("/proxy")
async def proxy(url: str = "", cookies: str = "", slide_id: int | None = None):
    """Fetch a page server-side and strip framing-blocker headers so it can be
    embedded in the kiosk's iframe slides. Only the top-level document needs this
    (frame-ancestors/X-Frame-Options only apply to the framed document itself);
    sub-resources (css/js/images) are left to load directly from the origin, so
    we just inject a <base> tag pointing back at the real page URL.

    `cookies` is an optional raw "name=value; name2=value2" header, pre-captured
    from a real browser after manually accepting/rejecting a site's cookie banner
    once, so the site sees existing consent and skips its (often very heavy)
    consent-management JS entirely instead of rendering the banner every load.

    If `slide_id` is given, `url`/`cookies` are looked up server-side from the
    stored slide's config instead, so a cookie value never needs to appear in
    the URL (visible in the DOM / access logs). The `url`/`cookies` query
    params remain supported directly, for any caller with no stored slide."""
    if slide_id is not None:
        slide = await db.get_slide(slide_id)
        if slide is None:
            return Response(content="Slide not found", status_code=404)
        config = slide["config"]
        url = config.get("src", "")
        cookies = config.get("cookies", "") or ""

    if not urlparse(url).scheme:
        return Response(content="Missing or invalid 'url'", status_code=400)

    # SSRF guard: only for the raw `url` param path. `slide_id`-driven URLs
    # come from trusted, admin-configured slide data, not the request, so
    # they're deliberately exempt (see ssrf_check's docstring).
    untrusted_url = slide_id is None
    if untrusted_url:
        err = ssrf_check(url)
        if err:
            return Response(content=f"Rejected 'url': {err}", status_code=400)

    parsed_url = urlparse(url)
    is_finalrewind = parsed_url.hostname == "dbf.finalrewind.org"
    is_kraut_chat = parsed_url.hostname == "kraut.space" and parsed_url.path.rstrip("/") == "/chat"
    headers = {"Cookie": cookies} if cookies else {}
    try:
        # We follow redirects manually (rather than httpx's
        # follow_redirects=True) so that, for the untrusted url-param path,
        # every redirect hop can be re-checked by ssrf_check too - a public
        # URL could otherwise redirect straight to an internal address.
        async with httpx.AsyncClient(follow_redirects=False, timeout=15) as client:
            current_url = url
            for _ in range(20):
                resp = await client.get(current_url, headers=headers)
                if resp.status_code not in (301, 302, 303, 307, 308):
                    break
                location = resp.headers.get("location")
                if not location:
                    break
                current_url = urljoin(current_url, location)
                if untrusted_url:
                    err = ssrf_check(current_url)
                    if err:
                        return Response(content=f"Rejected redirect: {err}", status_code=400)
            else:
                return Response(content="Too many redirects", status_code=502)
    except httpx.HTTPError:
        return Response(content="Upstream fetch failed", status_code=502)

    content_type = resp.headers.get("content-type", "text/html")
    if "text/html" not in content_type:
        return Response(content=resp.content, media_type=content_type)

    final = urlparse(str(resp.url))
    base_url = f"{final.scheme}://{final.netloc}{final.path.rsplit('/', 1)[0]}/"
    base_tag = f'<base href="{escape(base_url)}">'

    body = resp.text

    def _strip_heavy_script(m: re.Match) -> str:
        src = m.group(1)
        return "" if any(host in src for host in HEAVY_SCRIPT_HOSTS) else m.group(0)

    body = SCRIPT_TAG_RE.sub(_strip_heavy_script, body)
    if is_finalrewind:
        body = THEME_LINK_RE.sub(lambda m: m.group(0).replace("light.min.css", "dark.min.css"), body)
        body = INLINE_SCRIPT_RE.sub(
            lambda m: "" if "prefers-color-scheme" in m.group(1) else m.group(0), body
        )

    head_extras = base_tag + COOKIE_BANNER_CSS + (CANDY_TRIM_CSS if is_kraut_chat else "")
    new_body, count = re.subn(r"(?i)<head[^>]*>", lambda m: m.group(0) + head_extras, body, count=1)
    body = new_body if count else head_extras + body

    if is_kraut_chat:
        new_body, count = re.subn(r"(?i)</body>", lambda m: CANDY_AUTOJOIN_SCRIPT + m.group(0), body, count=1)
        body = new_body if count else body + CANDY_AUTOJOIN_SCRIPT

    return Response(content=body, media_type=content_type)


@app.get("/api/system/status")
async def system_status():
    return await system_info.get_stats()


@app.get("/api/preview.png")
async def preview_png():
    data = await get_preview_png()
    if data is None:
        return Response(status_code=503, content="preview unavailable")
    return Response(content=data, media_type="image/png")


@app.get("/")
async def admin(request: Request):
    slides = await db.list_slides()
    interval = await db.get_setting("rotation_interval_seconds", "60")
    slide_names = {slide["id"]: slide["name"] for slide in slides}
    return templates.TemplateResponse(
        request,
        "admin.html",
        {
            "slides": slides,
            "registry": REGISTRY,
            "rotation_interval": interval,
            "slide_names_json": json.dumps(slide_names),
        },
    )


@app.get("/admin/slides/new")
async def new_slide_form(request: Request, type: str):
    slide_type = REGISTRY.get(type)
    if slide_type is None:
        return RedirectResponse("/", status_code=303)
    return templates.TemplateResponse(
        request,
        "slide_form.html",
        {"slide_type": slide_type, "slide": None, "action": "/admin/slides"},
    )


@app.post("/admin/slides")
async def create_slide(request: Request):
    form = await request.form()
    slide_type_key = form.get("_type")
    name = form.get("_name") or slide_type_key
    slide_type = REGISTRY.get(slide_type_key)
    if slide_type is None:
        return RedirectResponse("/", status_code=303)
    config = {f.name: form.get(f.name, "") for f in slide_type.config_fields}
    await db.add_slide(slide_type_key, name, config)
    return RedirectResponse("/", status_code=303)


@app.get("/admin/slides/{slide_id}/edit")
async def edit_slide_form(request: Request, slide_id: int):
    slide = await db.get_slide(slide_id)
    if slide is None:
        return RedirectResponse("/", status_code=303)
    slide_type = REGISTRY.get(slide["type"])
    if slide_type is None:
        return RedirectResponse("/", status_code=303)
    return templates.TemplateResponse(
        request,
        "slide_form.html",
        {"slide_type": slide_type, "slide": slide, "action": f"/admin/slides/{slide_id}/update"},
    )


@app.post("/admin/slides/{slide_id}/update")
async def update_slide(request: Request, slide_id: int):
    form = await request.form()
    slide = await db.get_slide(slide_id)
    if slide is None:
        return RedirectResponse("/", status_code=303)
    slide_type = REGISTRY.get(slide["type"])
    if slide_type is None:
        return RedirectResponse("/", status_code=303)
    name = form.get("_name") or slide["name"]
    config = {f.name: form.get(f.name, "") for f in slide_type.config_fields}
    await db.update_slide(slide_id, name, config)
    return RedirectResponse("/", status_code=303)


@app.post("/admin/slides/{slide_id}/delete")
async def delete_slide(slide_id: int):
    await db.delete_slide(slide_id)
    return RedirectResponse("/", status_code=303)


@app.post("/admin/slides/{slide_id}/toggle")
async def toggle_slide(slide_id: int):
    await db.toggle_slide(slide_id)
    return RedirectResponse("/", status_code=303)


@app.post("/admin/slides/{slide_id}/view-now")
async def view_now(slide_id: int):
    if IS_ROTATION_OWNER:
        await STATE.request_forced(slide_id)
    else:
        # rotation owner unreachable; still redirect back rather than 500
        await _forward_to_owner("POST", f"/admin/slides/{slide_id}/view-now")
    return RedirectResponse("/", status_code=303)


@app.post("/admin/slides/{slide_id}/move")
async def move_slide(slide_id: int, direction: str = Form(...)):
    await db.move_slide(slide_id, direction)
    return RedirectResponse("/", status_code=303)


# display.html waits up to IFRAME_SETTLE_MS (10s) after an iframe's "load"
# event before swapping it in, on top of however long the page itself takes to
# load. An interval at or below that leaves iframe slides perpetually
# superseded by the next poll before they finish settling, so the display
# never completes a swap and freezes on its "Loading..." placeholder forever.
MIN_ROTATION_INTERVAL_SECONDS = 20


@app.post("/admin/settings")
async def update_settings(rotation_interval_seconds: str = Form(...)):
    try:
        value = int(rotation_interval_seconds)
    except ValueError:
        value = None
    if value is not None and value >= MIN_ROTATION_INTERVAL_SECONDS:
        await db.set_setting("rotation_interval_seconds", str(value))
    return RedirectResponse("/", status_code=303)
