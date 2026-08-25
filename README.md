# krautspaceTV

Digital Signage im Krautspace — a Raspberry Pi 2 Model B driving a TV in the
hackerspace, rotating between the 3D printer webcam, Matrix/Mastodon feeds,
train departure boards, weather, and other web content, with a web-based
admin UI for managing slides.

## Using it

- Admin UI: `http://krautspaceTV/` (or `https://` on port 443/8080 —
  self-signed cert, browser will warn once). It's intentionally open to
  anyone on the network — the point is to let people add their own content.
- The kiosk display itself lives at `/display`, served only on the
  kiosk-internal `127.0.0.1:8081` binding — you won't normally load this
  directly.
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
  consent on every load. It's looked up server-side via the slide's id
  (`/proxy?slide_id=...`) rather than appearing in the iframe's URL.
- The dark-theme/script-stripping rewrites above only apply to
  `dbf.finalrewind.org`; kraut.space's own XMPP webchat (`/chat/`) gets its
  own rewrites instead (auto-filling its nickname prompt, trimming it down
  to just the message list, and dark-theming it) — `/proxy` otherwise passes
  pages through with just the generic ad-script stripping and cookie-banner
  hiding.
- `no_reset: yes` opts an iframe out of the display's periodic 30s reload
  (normally there to fix scroll drift on embeds it can't control directly).
  Needed for embeds whose own load/login flow takes longer than that to
  finish — the periodic reset would otherwise restart them before they ever
  get there. Used by the kraut.space chat slide, since its XMPP handshake
  can take longer than 30s on the Pi's weak CPU.

## Notes on the `gpx` (GPS track map) slide type

Draws a device's recent track on a [Leaflet](https://leafletjs.com) map,
fetched from a Protegear-backed GPX API (`GET /v1/devices/{imei}/gpx`).

- Configure the API base URL, the device IMEI, and — if that API was started
  with `-auth-token` — the token. The token is only ever sent from the backend
  as an `Authorization: Bearer` header; it never reaches the browser and never
  appears in a URL.
- `hours` is the look-back window (fractional allowed). Anything above the
  API's own `-max-window` (720h by default) is clamped rather than turned into
  an error.
- `gap` splits the track into separate lines after a pause that long (`30m` by
  default, `-1s` to never split), so a device that sat still overnight doesn't
  get a straight line drawn across the map.
- Alarm events (SOS, crash, fall) come back as GPX waypoints and are drawn as
  labelled yellow markers. Turn them off with the `waypoints` field.
- `refresh_seconds` re-fetches the track in place, without reloading the page
  (0 loads it once). The slide's iframe is marked `no_reset` for the same
  reason the chat slide is: the display's periodic 30s iframe reload would
  restart the map for nothing.
- Tiles come from OpenStreetMap by default; `tile_url`/`tile_attribution`
  point it at another provider (e.g. a dark-themed one).

Leaflet itself is vendored under `backend/static/vendor/leaflet/` rather than
loaded from a CDN, so the map does not depend on a third party being reachable.

The map lives in its own page (`/gpx/<slide-id>`, iframed by the slide) because
the display injects slide HTML with `innerHTML`, which never executes
`<script>`. That page reads pre-parsed JSON from `/api/slide/<id>/track`: the
GPX is parsed and thinned to at most 2000 points server-side, since the Pi 2
stalls visibly on DOM-parsing a multi-thousand-point GPX file.

## Printer status overlay

- If a "3D printer host" is set in "Rotation settings", the display polls a
  Creality K1-family printer's local status websocket (`ws://<host>:9999`)
  every 15s and shows a small "Printing: ..." bar in a corner, on top of
  whatever slide is currently showing — independent of slide rotation, and
  only visible while a print is actually running. Leave the field blank to
  disable it.
- This talks to Creality's own websocket protocol (not Moonraker, despite
  the K1C's Klipper-based firmware); field/state-code meanings come from the
  community-reverse-engineered
  [ha-creality-lan](https://github.com/rathlinus/ha-creality-lan) Home
  Assistant integration.

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
  messages), `train` (generic departure-board JSON API), `api_status` (JSON
  field read from an API, shown as a true/false label), `rss` (RSS/Atom feed,
  with Mastodon-tag-RSS-specific quirks like author/image extraction), `gpx`
  (a GPS track drawn on a Leaflet map, see below).
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

</details>

<details>
<summary><h2>Setup</h2></summary>

### 1. OS and dependencies

Dependencies are managed with [uv](https://docs.astral.sh/uv/): `pyproject.toml`
declares them, `uv.lock` pins the exact resolved versions, and `uv sync` builds
the project-local `.venv` the systemd units run from.

On the Pi (as the `admin` user):

```sh
sudo apt install chromium xinit x11-xserver-utils unclutter scrot
curl -LsSf https://astral.sh/uv/install.sh | sh
git clone https://github.com/paulloth1/krautspaceTV.git ~/signage
cd ~/signage
uv sync --frozen --no-dev
```

`--frozen` installs exactly what `uv.lock` pins and fails rather than silently
re-resolving; `--no-dev` skips pytest, which the Pi has no use for. Re-run the
same command after every `git pull` that touches `pyproject.toml` or `uv.lock`.

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
(`http://127.0.0.1:8081/display`). It waits for the backend to respond
before starting X (see `ExecStartPre` in `deploy/kiosk.service`).

### 4. Quiet boot with a custom splash screen (optional)

By default the Pi prints kernel/systemd boot text to the HDMI output before
the kiosk takes over. To replace that with a plain "krautspace" splash
(`deploy/plymouth-krautspace/`):

```sh
sudo apt install plymouth plymouth-themes
sudo mkdir -p /usr/share/plymouth/themes/krautspace
sudo cp deploy/plymouth-krautspace/* /usr/share/plymouth/themes/krautspace/
sudo /usr/sbin/plymouth-set-default-theme krautspace
sudo update-initramfs -u
```

Use `plymouth-set-default-theme` specifically, not `update-alternatives` —
the initramfs-tools hook that decides which theme/plugin to bundle reads
`/etc/plymouth/plymouthd.conf`'s `Theme=` line (which is what
`plymouth-set-default-theme` writes), not the `default.plymouth`
alternatives symlink. Pointing only the symlink leaves the theme
unresolved at build time, and the hook silently falls back to bundling the
built-in text-mode "details" theme instead — which is what shows up as
scrolling green-on-black boot text despite `quiet`/`splash`. Verify with
`lsinitramfs /boot/firmware/initramfs7 | grep krautspace` (swap `7` for
whichever kernel variant `uname -r` reports) before trusting a reboot.

Then append to `/boot/firmware/cmdline.txt` (same line, space-separated, no
newlines):

```
quiet splash loglevel=0 vt.global_cursor_default=0 logo.nologo plymouth.ignore-serial-consoles
```

Two things end the splash cleanly rather than blanking the screen:

- `kiosk.service`'s `ExecStartPre` runs `plymouth quit --retain-splash`
  before Xorg starts (not from `xinitrc`, which only runs once Xorg is
  already up and would have to contend with plymouthd for the display).
- systemd's own `plymouth-quit.service` (`WantedBy=multi-user.target`) fires
  independently, often earlier than kiosk.service, and its default action
  is a plain `plymouth quit` with no `--retain-splash` — install the
  override so it doesn't blank the screen first:

  ```sh
  sudo mkdir -p /etc/systemd/system/plymouth-quit.service.d
  sudo cp deploy/plymouth-quit-retain-splash.conf \
          /etc/systemd/system/plymouth-quit.service.d/override.conf
  sudo systemctl daemon-reload
  ```

Either way, `--retain-splash` just keeps the last frame drawn (not an
active daemon), so display.html's own `#boot-splash` overlay (shown from
first paint) can paint over it without a flash once Chromium starts.

To use your own logo instead, swap in a differently drawn
`deploy/plymouth-krautspace/splash.png` (1920x1080, PNG) and rerun the
`update-initramfs -u` step — and update `#boot-splash`'s markup in
`backend/templates/display.html` / styles in `backend/static/display.css`
to match, since that overlay is real HTML/CSS, not the same image file.

### Development

With [devenv](https://devenv.sh) (`devenv shell`, or `direnv allow` if you use
direnv), everything below is already on `PATH`:

| Command | Does |
|---|---|
| `serve` | run the backend on `127.0.0.1:8081` with autoreload |
| `check` | `ruff check` followed by the full test suite |
| `lint` / `fmt` | lint only / autofix and format |
| `version` | print the semver, or bump it: `version patch\|minor\|major` |
| `certs` | generate the self-signed TLS cert |
| `devenv up` | run the backend as a supervised process |
| `devenv test` | what CI would run (`check`) |

The shell pins Python 3.13 (matching the Pi's Debian 13), syncs the venv from
`uv.lock` on entry, and installs git hooks that run `ruff` before each commit.
`SIGNAGE_DB_PATH` points at `signage-dev.db` there, so local runs can never
touch a real `signage.db`.

Without devenv, uv alone is enough:

```sh
uv sync            # creates .venv from uv.lock, including dev dependencies
uv run pytest
```

### Building with Nix

`flake.nix` builds the backend from the same `uv.lock` the Pi installs from, so
the Nix build and `uv sync` resolve to identical dependency versions.

```sh
nix build                     # -> ./result/bin/krautspacetv-backend
nix run . -- --port 8081      # run it; extra args go straight to uvicorn
nix flake check               # builds the package, runs ruff and the test suite
nix develop                   # plain dev shell, if you are not using devenv
```

The built wrapper puts `scrot` on `PATH` (needed by the admin UI's HDMI
preview) and defaults `SIGNAGE_DB_PATH` to `signage.db` in the working
directory, since the package tree itself is read-only in the Nix store.

`nix flake check` deselects `test_ssrf_check_accepts_public_hostname`: it
resolves `example.com` for real, and the Nix sandbox has no network. `check`
and `devenv test` still run it.

The Pi is Debian, not NixOS — it installs via `uv sync` and the systemd units in
`deploy/`. The flake is for building and testing on a workstation.

### Versioning

The project follows [semantic versioning](https://semver.org); the version
lives in `pyproject.toml` and is bumped as part of the change that warrants it
(see `CLAUDE.md` for which kind of change maps to which bump).

</details>
