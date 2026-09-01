from datetime import datetime
from zoneinfo import ZoneInfo

from markupsafe import escape

from ._http import fetch_json
from .registry import ConfigField, SlideType, register

# Departure APIs in the wild give a time either as "HH:MM" already or as a
# Unix timestamp in seconds (e.g. dbf.finalrewind.org's ?hafas=... JSON) -
# accept either rather than assuming one. Timestamps are rendered in the
# board's own timezone regardless of the host's, since this is always a
# specific local departure board, not wherever the backend happens to run.
BOARD_TZ = ZoneInfo("Europe/Berlin")


def _format_time(raw) -> str:
    if isinstance(raw, (int, float)):
        return datetime.fromtimestamp(raw, tz=BOARD_TZ).strftime("%H:%M")
    return str(raw or "")


async def is_available(config: dict) -> bool:
    # Deliberately no network call here: render() below already fetches the
    # departures API and renders a friendly "Unable to load departures"
    # error state on failure, so doing a second fetch here too would just
    # double the outbound requests to the API on every rotation step (see
    # #19, same pattern as #17) without adding much real value over this
    # cheap config check.
    if not config.get("api_url"):
        return False
    return True


async def render(config: dict, slide_id: int | None = None) -> str:
    title = config.get("title") or "Departures"
    data = await fetch_json(config["api_url"])
    if not isinstance(data, dict):
        return f'<div class="slide slide-train"><h2>{escape(title)}</h2><p>Unable to load departures.</p></div>'

    departures = data.get("departures", [])
    rows = []
    for dep in departures:
        line = escape(str(dep.get("train", "")))
        destination = escape(str(dep.get("destination", "")))
        time = escape(_format_time(dep.get("time")))
        rows.append(
            f"<tr><td class='line'>{line}</td><td>{destination}</td><td class='time'>{time}</td></tr>"
        )

    table = (
        f"<table class='departures'>{''.join(rows)}</table>" if rows else "<p>No departures found.</p>"
    )
    return f'<div class="slide slide-train"><h2>{escape(title)}</h2>{table}</div>'


register(
    SlideType(
        key="train",
        label="Train departures",
        config_fields=[
            ConfigField(
                name="api_url",
                label="Departures API URL (JSON: {departures:[{train,destination,time}]})",
            ),
            ConfigField(name="title", label="Display title", required=False),
        ],
        is_available=is_available,
        render=render,
    )
)
