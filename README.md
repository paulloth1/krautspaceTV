# krautspaceTV

Digital Signage im Krautspace: a Raspberry Pi driving a TV in the hackerspace,
rotating between the 3D printer webcam, feeds, train departure boards, weather
and other web content, with a web admin UI for managing slides.

## Using it

- Admin UI: `http://krautspaceTV/` (or `https://`, self-signed cert). It is
  open to anyone on the network on purpose, so people can add their own content.
- "Add slide", pick a type, fill in its fields, save. "View now" pushes a slide
  to the display immediately.
- Rotation interval is under "Rotation settings"; keep it above ~25s.

## Setup

On the Pi, as `admin` (details and the optional boot splash in
[docs/setup.md](docs/setup.md)):

```sh
sudo apt install chromium xinit x11-xserver-utils unclutter scrot
curl -LsSf https://astral.sh/uv/install.sh | sh
git clone https://github.com/paulloth1/krautspaceTV.git ~/signage && cd ~/signage
uv sync --frozen --no-dev
# create the self-signed TLS cert first (docs/setup.md), then:
sudo cp deploy/backend*.service deploy/kiosk.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now backend.service backend-http.service \
        backend-tls.service backend-tls-443.service kiosk.service
```

## Development

`devenv shell`, then `check` (lint + tests) and `serve`. Without devenv:
`uv sync && uv run pytest`. Version bumps follow [CLAUDE.md](CLAUDE.md).

## More

- [docs/architecture.md](docs/architecture.md): how the backend, rotation and
  kiosk fit together, and the hardware
- [docs/slides.md](docs/slides.md): slide types, overlays, known limitations
- [docs/setup.md](docs/setup.md): full setup
- [docs/casting.md](docs/casting.md): optional AirPlay, Spotify Connect, DLNA
  and Bluetooth receivers
- [docs/development.md](docs/development.md): devenv, Nix, versioning
