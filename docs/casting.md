# Casting and audio receivers (optional)

Four optional receivers let visitors put audio or video on the TV. Only
AirPlay mirroring touches the display; the rest are audio-only and leave the
kiosk running.

| Receiver | Sender | Plays | Display | State on the deployed Pi |
|---|---|---|---|---|
| [AirPlay](#airplay-mirroring) (UxPlay) | Apple devices | screen mirroring + audio | takes it over, kiosk must be stopped first | enabled |
| [Spotify Connect](#spotify-connect) (raspotify) | Spotify app, any OS | audio | untouched | enabled |
| [DLNA/UPnP](#dlnaupnp) (Rygel) | Android "Cast", Windows "Cast to Device", VLC (Playback → Renderer) | audio only | untouched | enabled |
| [Bluetooth speaker](#bluetooth-speaker) | any Bluetooth device | audio | untouched | **disabled** (dropouts) |

Chromecast-protocol mirroring and Miracast were investigated and ruled out:
Chromecast mirroring requires a device-auth certificate chain only Google
issues, and Android has been dropping Miracast sender support.

## AirPlay mirroring

```sh
sudo apt install uxplay
sudo cp deploy/uxplay.service deploy/uxplay-switcher.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now uxplay.service uxplay-switcher.service
```

`uxplay.service` runs the receiver continuously, so the Pi is always
discoverable over mDNS as "KrautspaceTV". It uses hardware H.264 *decode*
(`-v4l2 -vd v4l2h264dec`), capped to 720p. It never uses the hardware
*encoder*: an early test of it wedged the shared `bcm2835-codec` subsystem
and hung the whole Pi until the watchdog rebooted it. See the comments in
`deploy/uxplay.service` before adding any flag.

**To mirror: run `sudo systemctl stop kiosk.service` on the Pi first, then
connect from the Apple device.** Xorg and UxPlay's direct-KMS video output
cannot both hold DRM master, and stopping the kiosk in reaction to the
incoming connection loses the race on this hardware (UxPlay reaches its
video sink faster than the kiosk can release the display). Stopping it
beforehand removes the race.

`uxplay-switcher.service` restarts `kiosk.service` after the session ends,
once `RESUME_GRACE_SECONDS` (default 10s) passes with no reconnect, so a
brief drop doesn't flicker the display. `deploy/uxplay-switcher.sh` has the
history of what was tried before landing on this design.

Known rough edges:

- The first connection after the receiver has been idle sometimes fails;
  connecting again a few seconds later works.
- The screen can flash black with terminal text behind it while the display
  changes hands. Cosmetic, left as is. Don't try to fix it by removing
  `console=tty1` from `/boot/firmware/cmdline.txt`: doing that was followed
  by a kernel panic on every boot, and restoring it fixed boot.
- Full KMS (`vc4-kms-v3d`) is not an alternative. It blanks the screen on
  this TV (tried and reverted twice). `kmssink` works under the current
  `vc4-fkms-v3d` driver because GStreamer's KMS sink talks to DRM/KMS
  directly.

## Spotify Connect

Via [raspotify](https://github.com/dtcooper/raspotify), a packaged
[librespot](https://github.com/librespot-org/librespot):

```sh
curl -sSL https://dtcooper.github.io/raspotify/key.asc | sudo tee /usr/share/keyrings/raspotify_key.asc >/dev/null
sudo chmod 644 /usr/share/keyrings/raspotify_key.asc
echo 'deb [signed-by=/usr/share/keyrings/raspotify_key.asc] https://dtcooper.github.io/raspotify raspotify main' | sudo tee /etc/apt/sources.list.d/raspotify.list
sudo apt update && sudo apt install -y raspotify
```

No config needed. It installs and enables `raspotify.service` and appears in
Spotify's device picker under the Pi's hostname, "krautspaceTV".

## DLNA/UPnP

Via [Rygel](https://gitlab.gnome.org/GNOME/rygel). The sender needs nothing
installed on Android or Windows; on Linux use VLC's renderer menu.

```sh
sudo apt install rygel rygel-playbin
sudo cp deploy/rygel.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now rygel.service
```

`rygel-playbin` is a separate package; without it Rygel finds no plugins
and exits after 5 seconds. `deploy/rygel.service` runs Rygel under
`dbus-run-session` because it needs a D-Bus *session* bus and the Pi has no
desktop login (the comments in that file cover why it isn't Rygel's own
`wrap-dbus` example).

It is audio-only on purpose. `/etc/rygel.conf` sets the `[Playbin]`
renderer's `video-sink=fakesink`, so a cast video plays its audio and
discards the picture, and disables the `MediaExport`, `Tracker` and
`Tracker3` plugins (serving files *from* the Pi isn't wanted). A real video
sink would hit the same Xorg/kmssink conflict as AirPlay.

## Bluetooth speaker

**Currently disabled on the deployed Pi.** Playback had frequent dropouts.
The likely cause is radio contention: the Pi's Bluetooth and WiFi share one
2.4GHz radio, and the Pi is WiFi-only. The codec (plain SBC) and playback
buffer (500ms) were ruled out. Plugging the Pi into ethernet is the most
likely fix if you want to retry.

To turn it back on:

```sh
sudo apt install bluez-alsa-utils bluez-tools
sudo cp deploy/bluetooth-audio-setup.service deploy/bt-agent.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now bluetooth bluealsa bluealsa-aplay bluetooth-audio-setup bt-agent
```

Also uncomment `DiscoverableTimeout = 0` and `PairableTimeout = 0` in
`/etc/bluetooth/main.conf` (commented out, the adapter stays discoverable
for only 180s) and restart `bluetooth.service`.

`bluetooth-audio-setup.service` powers the adapter on and keeps it
discoverable and pairable. `bt-agent.service` auto-accepts pairing ("Just
Works", no PIN), fine for a public hackerspace speaker and not for anything
sensitive. The A2DP sink itself is `bluealsa.service` +
`bluealsa-aplay.service` from `bluez-alsa-utils`, with nothing custom.
