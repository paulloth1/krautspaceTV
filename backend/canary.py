"""Live listener for a "smart glass canary" - a device that watches for
nearby smart glasses (Meta Ray-Ban, Snap Spectacles, ...) and publishes to
MQTT when one's detected, so the display can show a prominent top-of-screen
alert (see display.html's #canary-overlay).

Expects three topics under a common prefix (default "canary/glasses"):
  - <prefix>/event  - transient, not retained: a display-ready plain-text
    message each time something changes (e.g. "Glasses detected: Meta
    Ray-Ban (-49 dBm)").
  - <prefix>/state  - retained "present"/"clear": the persistent indicator
    should be driven by this, not by `event` alone, so a signage restart
    immediately knows where things stand rather than showing nothing until
    the next event fires.
  - <prefix>/status - retained "online"/"offline", backed by the canary's
    MQTT Last Will. Without watching this, a dead canary (lost power,
    crashed) looks identical to a quiet one: `state` just sits at its last
    value forever and the display would keep implying nothing's detected
    when nothing is actually watching. Expect ~15-25s before "offline"
    appears (broker keepalive), not instant.

Unlike printer.py/the api_status MQTT source (a short connect-read-
disconnect per poll), this keeps one subscription open for the process
lifetime: `event` isn't retained, so a fresh per-poll connection would only
ever catch a message that happened to arrive in that exact instant - an
alert needs someone actually listening the whole time. Runs only in the
rotation-owner process (see app.py), same as rotation.py's rotation_loop().
"""

import asyncio
import logging
from typing import Callable, Coroutine

import aiomqtt

logger = logging.getLogger(__name__)

RECONNECT_DELAY = 5  # seconds, after a dropped/failed connection or while unconfigured


class CanaryState:
    def __init__(self) -> None:
        self.configured = False
        self.online: bool | None = None  # None = no status message seen yet
        self.present: bool | None = None  # None = no state message seen yet
        self.event_text: str = ""
        self._lock = asyncio.Lock()

    async def set_configured(self, configured: bool) -> None:
        async with self._lock:
            self.configured = configured
            if not configured:
                self.online = self.present = None
                self.event_text = ""

    async def set_online(self, online: bool | None) -> None:
        async with self._lock:
            self.online = online

    async def set_present(self, present: bool) -> None:
        async with self._lock:
            self.present = present

    async def set_event(self, text: str) -> None:
        async with self._lock:
            self.event_text = text

    async def snapshot(self) -> dict:
        async with self._lock:
            return {
                "configured": self.configured,
                "online": self.online,
                "present": self.present,
                "event": self.event_text,
            }


STATE = CanaryState()

CanaryConfig = tuple[str, int, str, str, str]  # host, port, event_topic, state_topic, status_topic


def _decode(payload) -> str:
    if isinstance(payload, (bytes, bytearray)):
        return payload.decode("utf-8", errors="replace").strip()
    return str(payload).strip()


async def _listen_once(host: str, port: int, event_topic: str, state_topic: str, status_topic: str) -> None:
    async with aiomqtt.Client(hostname=host, port=port) as client:
        await client.subscribe(event_topic)
        await client.subscribe(state_topic)
        await client.subscribe(status_topic)
        # Connected - but a genuinely offline canary's retained `status` LWT
        # only fires once the broker's keepalive gives up on it (~15-25s), so
        # don't claim "online" ourselves until we've actually heard from it.
        async for message in client.messages:
            topic = str(message.topic)
            text = _decode(message.payload)
            if topic == status_topic:
                await STATE.set_online(text == "online")
            elif topic == state_topic:
                await STATE.set_present(text == "present")
            elif topic == event_topic:
                await STATE.set_event(text)


async def canary_listener_loop(get_config: Callable[[], Coroutine[None, None, CanaryConfig | None]]) -> None:
    """`get_config` is re-awaited on every (re)connect attempt (not read once
    at startup) so a settings change takes effect without a service restart."""
    while True:
        config = await get_config()
        if config is None:
            await STATE.set_configured(False)
            await asyncio.sleep(RECONNECT_DELAY)
            continue
        await STATE.set_configured(True)
        host, port, event_topic, state_topic, status_topic = config
        try:
            await _listen_once(host, port, event_topic, state_topic, status_topic)
        except Exception:
            logger.exception("canary_listener_loop: connection lost, retrying")
            # Can't reach the broker either way, so from the display's
            # perspective this is indistinguishable from "not watching".
            await STATE.set_online(False)
        await asyncio.sleep(RECONNECT_DELAY)
