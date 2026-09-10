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

DEFAULT_MAX_ROWS = 12

# A HAFAS response mixes two very different kinds of entry in `messages`:
# per-trip amenity attributes ("Fahrkartenautomat im Zug", "Laptop-
# Steckdosen", ...) which are `type: "A"` with `is_him` unset, and actual
# disruption/incident text from the HAFAS Information Manager, flagged
# `is_him: true`. Only the latter belongs on a wall board.
def _disruption_texts(messages) -> list[str]:
    if not isinstance(messages, list):
        return []
    out: list[str] = []
    for m in messages:
        if not isinstance(m, dict):
            continue
        if not m.get("is_him"):
            continue
        text = str(m.get("text") or "").strip()
        if text and text not in out:
            out.append(text)
    return out


def _product_class(line: str) -> str:
    """Coarse vehicle class from the line label, for colour-coding the pill.
    Deliberately loose - unknown prefixes just get no extra class."""
    head = line.strip().split(" ", 1)[0].upper().rstrip("0123456789")  # "RB28" -> "RB"
    if head == "BUS":
        return "bus"
    if head in ("STR", "TRAM", "M", "T"):
        return "tram"
    if head in ("S", "RB", "RE", "IRE", "IC", "ICE", "EC", "D", "TGV"):
        return "rail"
    return ""


def _int_or_none(raw) -> int | None:
    try:
        return int(raw)
    except (TypeError, ValueError):
        return None


def _format_time(raw) -> str:
    if isinstance(raw, (int, float)):
        return datetime.fromtimestamp(raw, tz=BOARD_TZ).strftime("%H:%M")
    return str(raw or "")


def _max_rows(config: dict) -> int:
    value = _int_or_none(config.get("max_rows"))
    return value if value and value > 0 else DEFAULT_MAX_ROWS


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


def _render_row(dep: dict) -> str:
    line = str(dep.get("train", ""))
    destination = str(dep.get("destination", ""))
    cancelled = bool(dep.get("isCancelled"))
    delay = _int_or_none(dep.get("delay"))

    # `time` is the real, delay-adjusted departure (already computed by the
    # API); `scheduledTime` is the timetabled one. Show the actual time as
    # the figure you read - no mental "+N" arithmetic - and keep the
    # scheduled time struck through beneath it when they differ, so which is
    # which is never in doubt. Either field alone is fine for a minimal API.
    actual = _format_time(dep.get("time") if dep.get("time") is not None else dep.get("scheduledTime"))
    sched = _format_time(dep.get("scheduledTime") if dep.get("scheduledTime") is not None else dep.get("time"))

    platform = str(dep.get("platform") or "").strip()
    sched_platform = str(dep.get("scheduledPlatform") or "").strip()
    platform_changed = bool(platform and sched_platform and platform != sched_platform)

    via = dep.get("via")
    via_stops = [str(v).strip() for v in via if str(v).strip()] if isinstance(via, list) else []
    disruptions = _disruption_texts(dep.get("messages"))

    row_classes = ["dep"]
    if cancelled:
        row_classes.append("dep-cancelled")
    elif delay and delay >= 5:
        row_classes.append("dep-late-major")
    elif delay and delay >= 1:
        row_classes.append("dep-late")

    if cancelled:
        time_cell = f'<span class="sched">{escape(sched)}</span>'
    elif delay and delay >= 1:
        time_cell = (
            f'<span class="actual">{escape(actual)}</span>'
            f'<span class="delay">+{delay}</span>'
            f'<span class="sched-was">{escape(sched)}</span>'
        )
    else:
        time_cell = f'<span class="sched">{escape(actual)}</span>'

    dest_cell = f'<span class="dest">{escape(destination)}</span>'
    if via_stops:
        dest_cell += f'<span class="via">über {escape(" · ".join(via_stops))}</span>'
    if cancelled:
        dest_cell += '<span class="cancel-flag">Fällt aus</span>'
    for text in disruptions:
        dest_cell += f'<span class="disruption">{escape(text)}</span>'

    pill_class = _product_class(line)
    line_cell = f'<span class="line-pill {("line-" + pill_class) if pill_class else ""}">{escape(line)}</span>'

    plat_cell = ""
    if platform_changed:
        plat_cell = f'<s>{escape(sched_platform)}</s> {escape(platform)}'
    elif platform:
        plat_cell = escape(platform)
    plat_td_class = "dep-platform" + (" changed" if platform_changed else "")

    return (
        f'<tr class="{" ".join(row_classes)}">'
        f'<td class="dep-time">{time_cell}</td>'
        f'<td class="dep-line">{line_cell}</td>'
        f'<td class="dep-dest">{dest_cell}</td>'
        f'<td class="{plat_td_class}">{plat_cell}</td>'
        f"</tr>"
    )


async def render(config: dict, slide_id: int | None = None) -> str:
    title = config.get("title") or "Departures"
    data = await fetch_json(config["api_url"])
    if not isinstance(data, dict):
        return f'<div class="slide slide-train"><h2>{escape(title)}</h2><p>Unable to load departures.</p></div>'

    departures = data.get("departures", [])
    rows = [_render_row(dep) for dep in departures[: _max_rows(config)] if isinstance(dep, dict)]

    if rows:
        body = (
            '<table class="departures">'
            "<thead><tr>"
            '<th class="dep-time">Zeit</th><th class="dep-line">Linie</th>'
            '<th class="dep-dest">Ziel</th><th class="dep-platform">Steig</th>'
            "</tr></thead>"
            f"<tbody>{''.join(rows)}</tbody>"
            "</table>"
        )
    else:
        body = "<p>No departures found.</p>"
    return f'<div class="slide slide-train"><h2>{escape(title)}</h2>{body}</div>'


register(
    SlideType(
        key="train",
        label="Train departures",
        config_fields=[
            ConfigField(
                name="api_url",
                label="Departures API URL (HAFAS-style JSON: {departures:[{train, destination, "
                "scheduledTime, delay, isCancelled, platform, ...}]})",
            ),
            ConfigField(name="title", label="Display title", required=False),
            ConfigField(
                name="max_rows",
                label="Max departures to show",
                type="number",
                required=False,
                default=str(DEFAULT_MAX_ROWS),
            ),
        ],
        is_available=is_available,
        render=render,
    )
)
