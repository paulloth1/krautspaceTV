import asyncio
import json
import os
import re
from contextlib import asynccontextmanager
from pathlib import Path
from urllib.parse import urlparse

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


@asynccontextmanager
async def lifespan(app: FastAPI):
    await db.init_db()
    task = asyncio.create_task(rotation_loop()) if IS_ROTATION_OWNER else None
    yield
    if task:
        task.cancel()


app = FastAPI(lifespan=lifespan)
app.mount("/static", StaticFiles(directory=BASE_DIR / "static"), name="static")
templates = Jinja2Templates(directory=BASE_DIR / "templates")


@app.get("/display")
async def display(request: Request):
    return templates.TemplateResponse(request, "display.html", {})


@app.get("/api/slide/current")
async def slide_current():
    if IS_ROTATION_OWNER:
        return await STATE.snapshot()
    try:
        async with httpx.AsyncClient(timeout=5) as client:
            resp = await client.get(f"{ROTATION_OWNER_URL}/api/slide/current")
            return resp.json()
    except httpx.HTTPError:
        return {
            "id": None,
            "html": '<div class="slide slide-empty"><h2>Rotation owner unreachable</h2></div>',
            "forced": False,
            "seconds_remaining": None,
        }


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

    is_finalrewind = urlparse(url).hostname == "dbf.finalrewind.org"
    headers = {"Cookie": cookies} if cookies else {}
    try:
        async with httpx.AsyncClient(follow_redirects=True, timeout=15) as client:
            resp = await client.get(url, headers=headers)
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

    new_body, count = re.subn(
        r"(?i)<head[^>]*>", lambda m: m.group(0) + base_tag + COOKIE_BANNER_CSS, body, count=1
    )
    body = new_body if count else base_tag + COOKIE_BANNER_CSS + body

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
        try:
            async with httpx.AsyncClient(timeout=5) as client:
                await client.post(f"{ROTATION_OWNER_URL}/admin/slides/{slide_id}/view-now")
        except httpx.HTTPError:
            pass  # rotation owner unreachable; still redirect back rather than 500
    return RedirectResponse("/", status_code=303)


@app.post("/admin/slides/{slide_id}/move")
async def move_slide(slide_id: int, direction: str = Form(...)):
    await db.move_slide(slide_id, direction)
    return RedirectResponse("/", status_code=303)


@app.post("/admin/settings")
async def update_settings(rotation_interval_seconds: str = Form(...)):
    try:
        value = int(rotation_interval_seconds)
    except ValueError:
        value = None
    if value is not None and value > 0:
        await db.set_setting("rotation_interval_seconds", str(value))
    return RedirectResponse("/", status_code=303)
