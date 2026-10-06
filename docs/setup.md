# Setup

## 1. OS and dependencies

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

## 2. Self-signed TLS certificate (for the HTTPS admin services)

```sh
mkdir -p ~/signage/certs
openssl req -x509 -newkey rsa:2048 \
  -keyout ~/signage/certs/key.pem -out ~/signage/certs/cert.pem \
  -days 3650 -nodes -subj '/CN=krautspaceTV' \
  -addext 'subjectAltName=DNS:krautspaceTV,DNS:krautspaceTV.local,DNS:localhost,IP:127.0.0.1'
```

## 3. systemd services

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

## 4. Quiet boot with a custom splash screen (optional)

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
