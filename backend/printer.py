"""Status polling for a Creality K1-family 3D printer, for the display's
"printer is running" overlay.

These printers push a full status snapshot immediately on connecting to
their local status websocket (ws://<host>:9999), then keep streaming partial
updates - we only need the one initial snapshot per poll, so each call opens
a short-lived connection, reads the first message, and closes rather than
holding a persistent connection open.

Field meanings (state especially) aren't officially documented; taken from
the community-reverse-engineered Home Assistant integration at
https://github.com/rathlinus/ha-creality-lan.
"""

import asyncio
import json
import re

import websockets

# 0=idle, 1=printing, 2=complete, 3=failed, 4=abort, 5=paused, 6=pausing,
# 7=stopping, 8=restoring - only these count as "actively running" for the
# overlay; idle/complete/failed/etc should leave the display alone.
ACTIVE_STATES = {1, 5, 6}

_TIME_SUFFIX_RE = re.compile(r"_[A-Za-z]+_\d+h\d+m\d+s$")


def _clean_filename(raw: str | None) -> str | None:
    if not raw:
        return None
    name = raw.rsplit("/", 1)[-1]
    if name.endswith(".gcode"):
        name = name[: -len(".gcode")]
    # Creality's slicer appends "_<material>_<estimated time>" to the
    # original filename (e.g. "..._PETG_1h6m24s") - strip it for display.
    name = _TIME_SUFFIX_RE.sub("", name)
    if "." in name:
        name = name.rsplit(".", 1)[0]  # drop the original model extension too
    return name


def _parse_temp(raw) -> float | None:
    try:
        return round(float(raw), 1)
    except (TypeError, ValueError):
        return None


async def get_printer_status(host: str, timeout: float = 3.0) -> dict | None:
    """Connect to the printer's status websocket, read one snapshot, and
    return a small summary dict - or None if unreachable/times out/unparsable."""
    if not host:
        return None
    uri = f"ws://{host}:9999"
    try:
        async with websockets.connect(uri, open_timeout=timeout, close_timeout=1) as ws:
            raw = await asyncio.wait_for(ws.recv(), timeout=timeout)
    except (OSError, asyncio.TimeoutError, websockets.exceptions.WebSocketException):
        return None
    try:
        data = json.loads(raw)
    except ValueError:
        return None

    state = data.get("state")
    return {
        "printing": state in ACTIVE_STATES,
        "progress": data.get("printProgress"),
        "file": _clean_filename(data.get("printFileName")),
        "layer": data.get("layer"),
        "total_layer": data.get("TotalLayer"),
        "left_time": data.get("printLeftTime"),
        "nozzle_temp": _parse_temp(data.get("nozzleTemp")),
        "bed_temp": _parse_temp(data.get("bedTemp0")),
    }
