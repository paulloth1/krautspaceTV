# krautspaceTV

Digital Signage im Krautspace — a Raspberry Pi 2 Model B driving a TV in the
hackerspace, rotating between the 3D printer webcam, Matrix/Mastodon feeds,
train departure boards, weather, and other web content, with a web-based
admin UI for managing slides.

## Using it

- Admin UI: `http://krautspaceTV/admin` (or `https://` on port 443/8080
  — self-signed cert, browser will warn once).
- Add slides via "Add slide", pick a type, fill in its fields, save.
- "View now" force-pushes a slide to the display immediately, without
  waiting for rotation.
- Rotation interval is configurable in "Rotation settings" — keep it above
  roughly 20–25s, since the display's own load/fade buffering takes that
  long for iframe-heavy slides.

### Notes on the `media` (URL) slide type

- `scale` zooms a small embedded widget to fill more of the screen.
- `bypass_csp: yes` routes the iframe through `/proxy`, which:
  - strips `X-Frame-Options`/`CSP` so sites that block framing can still be
    embedded,
  - strips known heavy ad/consent-management scripts (`opencmp.net`,
    `cdntrf.com`) that can peg the Pi 2's CPU hard enough to freeze the
    entire kiosk browser,
  - hides common cookie-consent banners via injected CSS (the kiosk has no
    one to click "accept"),
  - forces `dbf.finalrewind.org` departure boards to dark theme.
- `cookies` (only used with `bypass_csp`) lets you paste a raw
  `name=value; name2=value2` header captured from a real browser after
  accepting/rejecting a site's cookie banner once, so the site sees existing
  consent on every load.

## Known limitations

- Pi 2's weak CPU + 900MB RAM means any sufficiently JS-heavy embedded page
  (ad tech, chat widgets) risks freezing the whole kiosk tab; the `/proxy`
  stripping above mitigates known offenders, but new ones may need the same
  treatment.
- No active CEC control (power on/off, input switching) under `vc4-fkms-v3d`
  — only the passive wake-on-HDMI-init behavior works.

<details>
<summary><h2>Architecture</h2></summary>

- **Backend**: FastAPI + Uvicorn (`backend/app.py`), serving:
  - `/` — the kiosk display page (`templates/display.html`), polled by the
    browser every 5s for the current slide's rendered HTML.
  - `/admin` — the control UI for adding/editing/reordering/enabling slides,
    a live HDMI-output preview, and basic system stats.
  - `/proxy` — a server-side fetch used by slides that need X-Frame-Options/
    CSP bypassed, heavy ad-consent scripts stripped, or a forced dark theme
    (see `backend/app.py` for the exact rewriting rules).
  - `/api/slide/current`, `/api/preview.png`, `/api/system/status` — JSON/PNG
    endpoints consumed by the display and admin pages.
- **Rotation** (`backend/rotation.py`): a background asyncio loop that walks
  enabled slides in order, holding each for a configurable interval, and can
  be interrupted immediately by "View now" from the admin UI.
- **Slide types** (`backend/slides/`): pluggable, each with `is_available()`
  and `render()` — `media` (image/video/iframe URL), `webcam` (MJPEG stream
  availability check), `mastodon` (hashtag timeline), `matrix` (room
  messages), `train` (generic departure-board JSON API).
- **Storage**: SQLite via `aiosqlite` (`signage.db`, gitignored) — slides and
  settings only; no secrets belong in git.
- **Kiosk display**: X11 (no window manager) + Chromium in `--kiosk` mode
  (`deploy/xinitrc`), showing the backend's own display page full-screen.

The backend runs as **four separate uvicorn processes** bound to different
host:port combinations, since a single port can't serve both plain HTTP and
TLS:

| Service | Bind | Purpose |
|---|---|---|
| `backend.service` | `127.0.0.1:8081` | kiosk-internal only, plain HTTP |
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

</details>

<details>
<summary><h2>Setup</h2></summary>

### 1. OS and dependencies

On the Pi (as the `admin` user):

```sh
sudo apt install python3-venv chromium xinit x11-xserver-utils unclutter scrot
git clone https://github.com/paulloth1/krautspaceTV.git ~/signage
cd ~/signage
python3 -m venv ~/signage-venv
~/signage-venv/bin/pip install -r requirements.txt
```

### 2. Self-signed TLS certificate (for the HTTPS admin services)

```sh
mkdir -p ~/signage/certs
openssl req -x509 -newkey rsa:2048 \
  -keyout ~/signage/certs/key.pem -out ~/signage/certs/cert.pem \
  -days 3650 -nodes -subj '/CN=krautspaceTV' \
  -addext 'subjectAltName=DNS:krautspaceTV,DNS:krautspaceTV.local,DNS:localhost,IP:127.0.0.1'
```

### 3. systemd services

```sh
sudo cp deploy/backend.service deploy/backend-http.service \
        deploy/backend-tls.service deploy/backend-tls-443.service \
        deploy/kiosk.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now backend.service backend-http.service \
        backend-tls.service backend-tls-443.service kiosk.service
```

`kiosk.service` starts an X session on `tty1` via `deploy/xinitrc` and
launches Chromium in kiosk mode pointed at the internal backend
(`http://127.0.0.1:8081/`). It waits for the backend to respond before
starting X (see `ExecStartPre` in `deploy/kiosk.service`).

</details>
