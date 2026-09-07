import asyncio
import json
import ssl

import aiomqtt
from markupsafe import escape

from ._http import fetch_json
from .registry import ConfigField, SlideType, register


async def _fetch_mqtt(config: dict, timeout: float = 5.0):
    """Connect to a broker, subscribe, and return the first message's
    payload - JSON-decoded if it parses as JSON, otherwise the raw string.

    Meant for a topic a broker retains the last value of (the usual pattern
    for a status/state topic), so the retained message arrives immediately
    on subscribe rather than waiting for a fresh publish. A short-lived
    connection per poll, same reasoning as printer.py's websocket: this is
    polled once per rotation step, not something worth holding a persistent
    connection open for.
    """
    host = (config.get("mqtt_host") or "").strip()
    topic = (config.get("mqtt_topic") or "").strip()
    if not host or not topic:
        return None
    try:
        port = int(config.get("mqtt_port") or 1883)
    except ValueError:
        port = 1883
    tls = str(config.get("mqtt_tls") or "").lower() in ("1", "true", "yes", "on")

    async def _read_one():
        async with aiomqtt.Client(
            hostname=host,
            port=port,
            username=config.get("mqtt_username") or None,
            password=config.get("mqtt_password") or None,
            tls_context=ssl.create_default_context() if tls else None,
        ) as client:
            await client.subscribe(topic)
            async for message in client.messages:
                return message.payload

    try:
        raw = await asyncio.wait_for(_read_one(), timeout=timeout)
    except (aiomqtt.MqttError, asyncio.TimeoutError, OSError):
        return None
    if raw is None:
        return None
    if isinstance(raw, (bytes, bytearray)):
        raw = raw.decode("utf-8", errors="replace")
    try:
        return json.loads(raw)
    except ValueError:
        return raw  # not JSON - _extract()/_is_truthy() below handle a bare string too


def _extract(data, path: str):
    """Pull a value out of parsed JSON via a dot path, e.g. 'door.open'.
    Empty path means "use the whole response" (for APIs that just return a
    bare bool/string/number)."""
    current = data
    if not path:
        return current
    for part in path.split("."):
        if isinstance(current, dict):
            current = current.get(part)
        else:
            return None
    return current


def _is_truthy(value) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    if isinstance(value, str):
        return value.strip().lower() in ("true", "1", "yes", "open", "on")
    return bool(value)


def _headers(config: dict) -> dict:
    token = config.get("access_token", "")
    return {"Authorization": f"Bearer {token}"} if token else {}


async def is_available(config: dict) -> bool:
    # Deliberately no network call here: render() below already fetches the
    # status and renders a friendly "Unable to load status" error state on
    # failure, so doing a second fetch here too would just double the
    # outbound requests on every rotation step (see #19, same pattern as
    # #17) without adding much real value over this cheap config check.
    if (config.get("source") or "http") == "mqtt":
        return bool(config.get("mqtt_host")) and bool(config.get("mqtt_topic"))
    return bool(config.get("api_url"))


async def render(config: dict, slide_id: int | None = None) -> str:
    title = config.get("title") or "Status"
    field_path = (config.get("json_field") or "").strip()
    true_label = config.get("true_label") or "Open"
    false_label = config.get("false_label") or "Closed"

    if (config.get("source") or "http") == "mqtt":
        data = await _fetch_mqtt(config)
    else:
        data = await fetch_json(config.get("api_url", ""), headers=_headers(config))
    if data is None:
        return (
            f'<div class="slide slide-api-status"><h2>{escape(title)}</h2>'
            f'<p class="api-status-value">Unable to load status.</p></div>'
        )

    value = _extract(data, field_path)
    truthy = _is_truthy(value)
    label = true_label if truthy else false_label
    state_class = "api-status-true" if truthy else "api-status-false"

    return (
        f'<div class="slide slide-api-status {state_class}">'
        f'<h2>{escape(title)}</h2>'
        f'<p class="api-status-value">{escape(str(label))}</p>'
        f'</div>'
    )


register(
    SlideType(
        key="api_status",
        label="API/MQTT status (JSON field)",
        config_fields=[
            ConfigField(
                name="source",
                label="Source",
                type="select",
                options=["http", "mqtt"],
                required=False,
                default="http",
            ),
            ConfigField(
                name="api_url", label="API URL (returns JSON; source=http)", required=False
            ),
            ConfigField(
                name="access_token",
                label="Bearer token (only if the API requires auth; source=http)",
                type="password",
                required=False,
            ),
            ConfigField(name="mqtt_host", label="Broker host (source=mqtt)", required=False),
            ConfigField(
                name="mqtt_port", label="Broker port", type="number", required=False, default="1883"
            ),
            ConfigField(name="mqtt_topic", label="Topic to subscribe to (source=mqtt)", required=False),
            ConfigField(name="mqtt_username", label="Broker username", required=False),
            ConfigField(name="mqtt_password", label="Broker password", type="password", required=False),
            ConfigField(
                name="mqtt_tls",
                label="Connect over TLS",
                type="select",
                options=["no", "yes"],
                required=False,
                default="no",
            ),
            ConfigField(
                name="json_field",
                label="JSON field to read (dot path, e.g. 'door.open'; leave empty to use the whole "
                "message/response as-is)",
                required=False,
            ),
            ConfigField(name="title", label="Display title", required=False, default="Status"),
            ConfigField(name="true_label", label="Label when truthy", required=False, default="Open"),
            ConfigField(name="false_label", label="Label when falsy", required=False, default="Closed"),
        ],
        is_available=is_available,
        render=render,
    )
)
