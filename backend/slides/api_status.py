from markupsafe import escape

from ._http import fetch_json
from .registry import ConfigField, SlideType, register


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
    # API and renders a friendly "Unable to load status" error state on
    # failure, so doing a second fetch here too would just double the
    # outbound requests to the API on every rotation step (see #19, same
    # pattern as #17) without adding much real value over this cheap config
    # check.
    if not config.get("api_url"):
        return False
    return True


async def render(config: dict, slide_id: int | None = None) -> str:
    title = config.get("title") or "Status"
    field_path = (config.get("json_field") or "").strip()
    true_label = config.get("true_label") or "Open"
    false_label = config.get("false_label") or "Closed"

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
        label="API status (JSON field)",
        config_fields=[
            ConfigField(name="api_url", label="API URL (returns JSON)"),
            ConfigField(
                name="json_field",
                label="JSON field to read (dot path, e.g. 'door.open'; leave empty to use the whole response)",
                required=False,
            ),
            ConfigField(name="title", label="Display title", required=False, default="Status"),
            ConfigField(name="true_label", label="Label when truthy", required=False, default="Open"),
            ConfigField(name="false_label", label="Label when falsy", required=False, default="Closed"),
            ConfigField(
                name="access_token",
                label="Bearer token (only if the API requires auth)",
                type="password",
                required=False,
            ),
        ],
        is_available=is_available,
        render=render,
    )
)
