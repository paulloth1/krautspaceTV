from markupsafe import escape

from .registry import ConfigField, SlideType, register


async def is_available(config: dict) -> bool:
    # Deliberately no network call (same reasoning as api_status/#19): the map
    # page fetches the track itself and shows its own error state, so probing
    # the API here would just double the outbound requests every rotation.
    return bool(config.get("base_url") and config.get("imei"))


async def render(config: dict, slide_id: int | None = None) -> str:
    # The map has to run Leaflet, and display.html injects slide HTML with
    # innerHTML — which never executes <script>. So the slide is an iframe onto
    # a real page instead, which also keeps the API token server-side: the page
    # is addressed by slide id and looks its config up itself.
    if slide_id is None:
        return (
            '<div class="slide slide-gpx-error"><h2>Track map</h2>'
            "<p>This slide has to be saved before its map can be shown.</p></div>"
        )
    # data-no-reset: the display's periodic 30s iframe reload would restart the
    # map (re-fetch, re-fit, flash) for no reason — the page refreshes its own
    # track data in place instead, see gpx_map.html.
    return (
        f'<div class="slide slide-gpx">'
        f'<iframe src="/gpx/{escape(slide_id)}" data-no-reset></iframe>'
        f"</div>"
    )


register(
    SlideType(
        key="gpx",
        label="GPS track map (GPX on Leaflet)",
        config_fields=[
            ConfigField(name="base_url", label="Track API base URL (e.g. https://tracker.example.org)"),
            ConfigField(name="imei", label="Device IMEI"),
            ConfigField(
                name="token",
                label="API token (only if the track API was started with -auth-token)",
                type="password",
                required=False,
            ),
            ConfigField(
                name="hours",
                label="Look-back window in hours (fractional allowed, max 720)",
                type="number",
                required=False,
                default="24",
            ),
            ConfigField(
                name="title",
                label="Heading shown on the slide (leave empty to use the track's own name)",
                required=False,
            ),
            ConfigField(
                name="track_name",
                label="Track name to request from the API (leave empty for the device name)",
                required=False,
            ),
            ConfigField(
                name="gap",
                label="Split the track after a pause this long, e.g. '30m' ('-1s' to never split)",
                required=False,
                default="30m",
            ),
            ConfigField(
                name="waypoints",
                label="Show alarm events (SOS, crash, fall) as markers",
                type="select",
                options=["yes", "no"],
                required=False,
                default="yes",
            ),
            ConfigField(
                name="refresh_seconds",
                label="How often the map re-fetches the track (0 to load it once)",
                type="number",
                required=False,
                default="60",
            ),
            ConfigField(
                name="tile_url",
                label="Map tile URL template (leave empty for OpenStreetMap)",
                required=False,
            ),
            ConfigField(
                name="tile_attribution",
                label="Attribution text for a custom tile URL",
                required=False,
            ),
        ],
        is_available=is_available,
        render=render,
    )
)
