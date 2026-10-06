# Architecture

- **Backend**: FastAPI + Uvicorn (`backend/app.py`), serving:
  - `/` — the admin control UI for adding/editing/reordering/enabling slides,
    a live HDMI-output preview, and basic system stats.
  - `/display` — the kiosk display page (`templates/display.html`), polled by
    the browser every 5s for the current slide's rendered HTML. Only bound
    on the kiosk-internal `127.0.0.1:8081` instance.
  - `/proxy` — a server-side fetch used by slides that need X-Frame-Options/
    CSP bypassed, heavy ad-consent scripts stripped, or (for
    `dbf.finalrewind.org` specifically) a forced dark theme. Accepts either
    `?url=...&cookies=...` directly, or `?slide_id=...` to look both up
    server-side from a stored slide's config (see `backend/app.py` for the
    exact rewriting rules).
  - `/api/slide/current`, `/api/preview.png`, `/api/system/status` — JSON/PNG
    endpoints consumed by the display and admin pages.
- **Rotation** (`backend/rotation.py`): a background asyncio loop that walks
  enabled slides in order, holding each for a configurable interval, and can
  be interrupted immediately by "View now" from the admin UI.
- **Slide types** (`backend/slides/`): pluggable, each with `is_available()`
  and `render()` — `media` (image/video/iframe URL), `webcam` (MJPEG stream
  availability check), `mastodon` (hashtag timeline), `matrix` (room
  messages), `train` (generic departure-board JSON API), `api_status` (a
  JSON field read from an HTTP API or an MQTT topic, shown as a true/false
  label), `rss` (RSS/Atom feed,
  with Mastodon-tag-RSS-specific quirks like author/image extraction), `gpx`
  (a GPS track drawn on a Leaflet map, see [slides.md](slides.md)).
  `render()` fetching is factored through `backend/slides/_http.py`'s shared
  `fetch_json()` helper for the API-backed types.
- **Storage**: SQLite via `aiosqlite` (`signage.db`, gitignored, WAL mode) —
  slides and settings only; no secrets belong in git.
- **Kiosk display**: X11 (no window manager) + Chromium in `--kiosk` mode
  (`deploy/xinitrc`), showing the backend's own `/display` page full-screen.

The backend runs as **four separate uvicorn processes** bound to different
host:port combinations, since a single port can't serve both plain HTTP and
TLS. Only one of them ("the rotation owner" — `backend.service`, set via
`SIGNAGE_ROTATION_OWNER=1`) actually runs the rotation loop; the other three
forward `/api/slide/current` reads and `view-now` writes to it over loopback
HTTP, so every port shows consistent state:

| Service | Bind | Purpose |
|---|---|---|
| `backend.service` | `127.0.0.1:8081` | kiosk-internal only; owns rotation |
| `backend-http.service` | `0.0.0.0:80` | LAN admin access, no port needed |
| `backend-tls.service` | `0.0.0.0:8080` | LAN admin access over HTTPS |
| `backend-tls-443.service` | `0.0.0.0:443` | LAN admin access over HTTPS, no port needed |

## Hardware

- Raspberry Pi 2 Model B, Raspberry Pi OS Lite (Debian 13 "trixie", armv7l)
- HDMI-connected TV
- `dtoverlay=vc4-fkms-v3d` in `/boot/firmware/config.txt` — the older
  "fake KMS" driver. Full KMS (`vc4-kms-v3d`) causes a gray/black-screen
  scanout bug on some TVs; fkms also loses active CEC control but still
  sends a passive CEC wake broadcast on HDMI init, so the TV auto-wakes when
  the Pi boots.
