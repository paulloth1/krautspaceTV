from urllib.parse import quote

from markupsafe import escape

from ._http import fetch_json, url_ok
from .registry import ConfigField, SlideType, register


def _messages_url(config: dict, limit: int) -> str:
    homeserver = config.get("homeserver", "").rstrip("/")
    room_id = quote(config.get("room_id", ""), safe="")
    return f"{homeserver}/_matrix/client/v3/rooms/{room_id}/messages?dir=b&limit={limit}"


def _headers(config: dict) -> dict:
    token = config.get("access_token", "")
    return {"Authorization": f"Bearer {token}"}


async def is_available(config: dict) -> bool:
    if not config.get("homeserver") or not config.get("room_id") or not config.get("access_token"):
        return False
    return await url_ok(_messages_url(config, 1), headers=_headers(config))


async def render(config: dict) -> str:
    room_name = config.get("room_name") or "Matrix chat"
    data = await fetch_json(_messages_url(config, 15), headers=_headers(config))
    if data is None:
        return f'<div class="slide slide-matrix"><h2>{escape(room_name)}</h2><p>Unable to load messages.</p></div>'

    events = [
        e for e in data.get("chunk", [])
        if e.get("type") == "m.room.message" and e.get("content", {}).get("body")
    ]
    events.reverse()  # oldest first for natural reading order

    items = []
    for event in events:
        sender = event.get("sender", "").split(":")[0].lstrip("@")
        body = event.get("content", {}).get("body", "")
        items.append(f'<li><span class="sender">{escape(sender)}</span>: {escape(body)}</li>')

    body_html = f'<ul class="matrix-messages">{"".join(items)}</ul>' if items else "<p>No recent messages.</p>"
    return f'<div class="slide slide-matrix"><h2>{escape(room_name)}</h2>{body_html}</div>'


register(
    SlideType(
        key="matrix",
        label="Matrix chat room",
        config_fields=[
            ConfigField(name="homeserver", label="Homeserver URL (e.g. https://matrix.org)"),
            ConfigField(name="room_id", label="Room ID (e.g. !abc123:matrix.org)"),
            ConfigField(name="access_token", label="Access token", type="password"),
            ConfigField(name="room_name", label="Display name", required=False),
        ],
        is_available=is_available,
        render=render,
    )
)
