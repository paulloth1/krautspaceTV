# Slide types and overlays

## The `media` (URL) slide type

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

## The `gpx` (GPS track map) slide type

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

## Canary (smart-glasses detector) alert overlay

- If a "Canary MQTT broker host" is set in "Rotation settings", the display
  shows a banner across the top of the screen — independent of slide
  rotation, on top of whatever slide is showing — driven by a live MQTT
  subscription the backend keeps open for the process lifetime (see
  `backend/canary.py`), not a per-poll fetch like the printer overlay
  above. Leave the field blank to disable it.
- Expects three topics under a configurable prefix (default
  `canary/glasses`):
  - `<prefix>/event` — transient, not retained: a display-ready plain-text
    message each time something changes (e.g. `Glasses detected: Meta
    Ray-Ban (-49 dBm)`). Shown verbatim, budget ~60 characters.
  - `<prefix>/state` — retained `present`/`clear`. Drives whether the
    banner shows at all: `present` shows a pulsing red alert (using the
    latest `event` text, or a generic fallback if none has arrived yet
    this run); `clear` hides the banner entirely, same as the printer
    overlay staying hidden when nothing's printing.
  - `<prefix>/status` — retained `online`/`offline`, expected to be backed
    by the canary's own MQTT Last Will so the broker announces `offline`
    on its own if the canary loses power or crashes (allow ~15–25s for
    this, per the broker's keepalive). Anything other than a confirmed
    `online` — including right at startup, before a status message has
    arrived at all — shows a muted grey "CANARY OFFLINE" banner instead of
    silently doing nothing, since a quiet canary and a dead, unheard-from
    one must never look the same on screen.
- A local broker for this (and for the `api_status` slide's MQTT source,
  see above) can be set up with `deploy/mosquitto-krautspace.conf` —
  anonymous and LAN-reachable, the same "intentionally open" call as the
  admin UI itself:
  ```sh
  sudo apt install mosquitto mosquitto-clients
  sudo cp deploy/mosquitto-krautspace.conf /etc/mosquitto/conf.d/krautspace.conf
  sudo systemctl restart mosquitto
  ```

## Known limitations

- Pi 2's weak CPU + 900MB RAM means any sufficiently JS-heavy embedded page
  (ad tech, chat widgets) risks freezing the whole kiosk tab; the `/proxy`
  stripping above mitigates known offenders, but new ones may need the same
  treatment.
- No active CEC control (power on/off, input switching) under `vc4-fkms-v3d`
  — only the passive wake-on-HDMI-init behavior works.
