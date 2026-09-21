#!/bin/sh
# Resumes kiosk.service once an AirPlay session ends - after a grace
# period with no reconnect, not immediately. Does NOT stop the kiosk on
# connect - see below.
#
# History: this used to also *stop* the kiosk reactively, the moment
# UxPlay logged the first sign of an incoming connection, to free the DRM
# device before UxPlay's kmssink output tried to grab it (Xorg and
# kmssink can't both hold DRM master at once on this hardware). Extensive
# live testing found that race is not reliably winnable on this Pi 2:
# even triggering on the earliest possible log line and replacing a plain
# `systemctl stop` with a direct SIGTERM to Xorg (measured ~50ms to
# actually free the display), UxPlay still reached kmssink first often
# enough - sometimes within ~150ms - to fail on nearly every attempt in a
# row, not just occasionally. Chasing tighter reaction times kept
# narrowing the miss without closing it.
#
# The reliable fix is to not race at all: stop kiosk.service manually
# *before* connecting (`sudo systemctl stop kiosk.service` on the Pi -
# see the AirPlay section of README.md), which gives the display as much
# lead time as you want instead of a few hundred milliseconds. This
# script still auto-resumes the kiosk once the session ends, so you don't
# have to remember to do that part.
#
# Disconnect is detected via "raop_rtp_mirror->running is no longer true"
# / "Connection closed for socket" - the lines actually observed at the
# end of both a failed and a successful real session (not the
# "Destroying connection"/"Disconnecting on software request" strings
# this script originally guessed from the binary, which never appeared in
# practice). Known gap, hit live: "Connection closed for socket" isn't
# necessarily the mirror's own socket - a stray probe connection closing
# during an active mirror matches it too, starting a resume countdown
# during a still-ongoing session. Rather than try to identify the right
# socket from the log text alone (not reliably possible without UxPlay's
# actual source), the grace-period expiry below double-checks reality
# instead of trusting the log: it only starts the kiosk if the DRM device
# is actually free at that moment. If UxPlay still holds it - a real
# ongoing session - the resume is dropped rather than fought over; kiosk
# stays off, unattempted, until the session's real end fires its own
# disconnect trigger and a fresh countdown. Without this check, a
# spurious countdown would otherwise crash-loop kiosk.service every
# RestartSec against a device it can never win while streaming is
# actually still active - harmless to the loop itself, but pointless
# churn against the same DRM/CMA allocation path that caused real memory
# fragmentation problems earlier (see the CMA exhaustion incident in git
# history around this feature's development).
#
# The resume isn't immediate: a mirroring session can drop and reconnect
# within a second or two (Wi-Fi hiccup, the client renegotiating, etc.),
# and resuming the kiosk immediately on every such blip would mean
# constantly flickering the display back and forth during what's really
# one continuous viewing session. Instead, a disconnect starts a
# RESUME_GRACE_SECONDS countdown (background, doesn't block the log
# loop); a fresh connection arriving before it elapses cancels the
# pending resume via the token check below, rather than the kiosk
# starting up only to be immediately stopped again moments later.
set -eu

PENDING=/run/uxplay-switcher.pending-resume
STUCK_THRESHOLD=15
RESUME_GRACE_SECONDS=10

stuck_count=0

journalctl -u uxplay.service -f -o cat -n0 | while IFS= read -r line; do
    case "$line" in
        *"Accepted IPv"*)
            stuck_count=0
            rm -f "$PENDING"
            ;;
        *"invalid ntp_time"*)
            if ! systemctl is-active --quiet kiosk.service; then
                stuck_count=$((stuck_count + 1))
                if [ "$stuck_count" -ge "$STUCK_THRESHOLD" ]; then
                    stuck_count=0
                    rm -f "$PENDING"
                    systemctl restart uxplay.service || true
                    systemctl start kiosk.service || true
                fi
            fi
            ;;
        *"raop_rtp_mirror->running is no longer true"*|*"Connection closed for socket"*)
            stuck_count=0
            token=$(date +%s%N)
            echo "$token" > "$PENDING"
            (
                sleep "$RESUME_GRACE_SECONDS"
                if [ -f "$PENDING" ] && [ "$(cat "$PENDING" 2>/dev/null)" = "$token" ]; then
                    rm -f "$PENDING"
                    if ! fuser -s /dev/dri/card0 2>/dev/null; then
                        systemctl start kiosk.service || true
                    fi
                fi
            ) &
            ;;
    esac
done
