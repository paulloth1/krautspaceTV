import httpx
import pytest

from backend.gpx import (
    DEFAULT_HOURS,
    MAX_HOURS,
    MAX_POINTS,
    _decimate,
    _upstream_error,
    build_request,
    fetch_track,
    parse_gpx,
)
from backend.slides.gpx import is_available, render

GPX_NS = 'xmlns="http://www.topografix.com/GPX/1/1"'


def _gpx(body: str, ns: str = GPX_NS) -> str:
    return f'<?xml version="1.0" encoding="UTF-8"?><gpx version="1.1" {ns}>{body}</gpx>'


def _trkseg(points) -> str:
    pts = "".join(f'<trkpt lat="{lat}" lon="{lon}"></trkpt>' for lat, lon in points)
    return f"<trkseg>{pts}</trkseg>"


# --- parse_gpx -------------------------------------------------------------


def test_parse_gpx_reads_segments_and_name():
    track = parse_gpx(
        _gpx(f"<trk><name>Ilmenau run</name>{_trkseg([(50.68, 10.91), (50.69, 10.92)])}</trk>")
    )
    assert track["name"] == "Ilmenau run"
    assert track["segments"] == [[[50.68, 10.91], [50.69, 10.92]]]
    assert track["point_count"] == 2


def test_parse_gpx_keeps_segments_separate():
    body = f"<trk>{_trkseg([(50.0, 10.0), (50.1, 10.1)])}{_trkseg([(51.0, 11.0), (51.1, 11.1)])}</trk>"
    track = parse_gpx(_gpx(body))
    assert len(track["segments"]) == 2
    # start/end span the whole track, not just one segment.
    assert track["start"] == [50.0, 10.0]
    assert track["end"] == [51.1, 11.1]


def test_parse_gpx_prefers_metadata_name_over_track_name():
    body = f"<metadata><name>From metadata</name></metadata><trk><name>From trk</name>{_trkseg([(1.0, 2.0), (1.1, 2.1)])}</trk>"
    assert parse_gpx(_gpx(body))["name"] == "From metadata"


def test_parse_gpx_falls_back_to_track_name():
    body = f"<metadata></metadata><trk><name>From trk</name>{_trkseg([(1.0, 2.0), (1.1, 2.1)])}</trk>"
    assert parse_gpx(_gpx(body))["name"] == "From trk"


def test_parse_gpx_handles_gpx_10_namespace():
    body = f"<trk><name>Old</name>{_trkseg([(50.0, 10.0), (50.1, 10.1)])}</trk>"
    track = parse_gpx(_gpx(body, ns='xmlns="http://www.topografix.com/GPX/1/0"'))
    assert track["segments"] == [[[50.0, 10.0], [50.1, 10.1]]]


def test_parse_gpx_handles_missing_namespace():
    body = f"<trk>{_trkseg([(50.0, 10.0), (50.1, 10.1)])}</trk>"
    assert parse_gpx(_gpx(body, ns=""))["point_count"] == 2


def test_parse_gpx_reads_waypoints():
    body = (
        f"<trk>{_trkseg([(50.0, 10.0), (50.1, 10.1)])}</trk>"
        '<wpt lat="50.05" lon="10.05"><name>SOS</name><time>2026-08-22T10:00:00Z</time></wpt>'
    )
    track = parse_gpx(_gpx(body))
    assert track["waypoints"] == [
        {"lat": 50.05, "lon": 10.05, "name": "SOS", "time": "2026-08-22T10:00:00Z"}
    ]


def test_parse_gpx_waypoint_falls_back_to_sym_when_unnamed():
    body = '<wpt lat="50.0" lon="10.0"><sym>Danger</sym></wpt>'
    assert parse_gpx(_gpx(body))["waypoints"][0]["name"] == "Danger"


def test_parse_gpx_reads_last_fix_time():
    body = (
        "<trk><trkseg>"
        '<trkpt lat="50.0" lon="10.0"><time>2026-08-22T09:00:00Z</time></trkpt>'
        '<trkpt lat="50.1" lon="10.1"><time>2026-08-22T11:30:00Z</time></trkpt>'
        "</trkseg></trk>"
    )
    assert parse_gpx(_gpx(body))["last_fix"] == "2026-08-22T11:30:00Z"


def test_parse_gpx_computes_bounds_over_points_and_waypoints():
    body = f"<trk>{_trkseg([(50.0, 10.0), (50.5, 10.5)])}</trk><wpt lat='49.0' lon='12.0'></wpt>"
    assert parse_gpx(_gpx(body))["bounds"] == [[49.0, 10.0], [50.5, 12.0]]


def test_parse_gpx_computes_distance():
    # One degree of latitude is ~111km; enough to catch a broken haversine.
    track = parse_gpx(_gpx(f"<trk>{_trkseg([(50.0, 10.0), (51.0, 10.0)])}</trk>"))
    assert 110.0 < track["distance_km"] < 112.0


def test_parse_gpx_skips_unparseable_and_out_of_range_points():
    body = (
        "<trk><trkseg>"
        '<trkpt lat="50.0" lon="10.0"></trkpt>'
        '<trkpt lat="not-a-number" lon="10.1"></trkpt>'
        '<trkpt lon="10.2"></trkpt>'
        '<trkpt lat="91.0" lon="10.3"></trkpt>'
        '<trkpt lat="50.4" lon="181.0"></trkpt>'
        '<trkpt lat="50.5" lon="10.5"></trkpt>'
        "</trkseg></trk>"
    )
    assert parse_gpx(_gpx(body))["segments"] == [[[50.0, 10.0], [50.5, 10.5]]]


def test_parse_gpx_single_point_segment_is_not_drawn_but_still_counts():
    track = parse_gpx(_gpx(f"<trk>{_trkseg([(50.0, 10.0)])}</trk>"))
    assert track["segments"] == []
    assert track["point_count"] == 1
    assert track["start"] == track["end"] == [50.0, 10.0]


def test_parse_gpx_empty_track():
    track = parse_gpx(_gpx("<trk></trk>"))
    assert track["segments"] == []
    assert track["bounds"] is None
    assert track["start"] is None


def test_parse_gpx_rejects_malformed_xml():
    assert parse_gpx("<gpx><trk>") is None


def test_parse_gpx_rejects_non_gpx_xml():
    assert parse_gpx("<rss><channel></channel></rss>") is None


def test_parse_gpx_rounds_coordinates():
    track = parse_gpx(_gpx(f"<trk>{_trkseg([(50.123456789, 10.987654321), (50.2, 10.9)])}</trk>"))
    assert track["segments"][0][0] == [50.12346, 10.98765]


# --- decimation ------------------------------------------------------------


def test_decimate_leaves_small_tracks_alone():
    segments = [[(0.0, 0.0), (1.0, 1.0), (2.0, 2.0)]]
    assert _decimate(segments) == segments


def test_decimate_caps_point_count_and_keeps_endpoints():
    segment = [(float(i) / 1000, 0.0) for i in range(5000)]
    thinned = _decimate([segment])[0]
    assert len(thinned) <= MAX_POINTS + 1  # +1 for the re-appended final point
    assert thinned[0] == segment[0]
    assert thinned[-1] == segment[-1]


def test_decimate_keeps_every_segments_endpoints():
    segments = [[(float(i), 0.0) for i in range(3000)] for _ in range(2)]
    thinned = _decimate(segments)
    assert len(thinned) == 2
    for original, kept in zip(segments, thinned):
        assert kept[0] == original[0]
        assert kept[-1] == original[-1]


def test_decimate_handles_no_points():
    assert _decimate([]) == []


# --- build_request ---------------------------------------------------------


def test_build_request_builds_device_gpx_url():
    url, params, headers = build_request({"base_url": "https://t.example", "imei": "123"})
    assert url == "https://t.example/v1/devices/123/gpx"
    assert params["hours"] == DEFAULT_HOURS
    assert params["waypoints"] == "true"
    assert "Authorization" not in headers


def test_build_request_strips_trailing_slash_from_base_url():
    url, _, _ = build_request({"base_url": "https://t.example/", "imei": "123"})
    assert url == "https://t.example/v1/devices/123/gpx"


def test_build_request_sends_token_as_bearer():
    _, params, headers = build_request({"base_url": "https://t.example", "imei": "1", "token": "s3cret"})
    assert headers["Authorization"] == "Bearer s3cret"
    # Never as ?key=, which would land in the upstream's access log.
    assert "key" not in params


def test_build_request_passes_optional_params_through():
    _, params, _ = build_request(
        {
            "base_url": "https://t.example",
            "imei": "1",
            "hours": "1.5",
            "track_name": "Wanderung",
            "gap": "5m",
            "waypoints": "no",
        }
    )
    assert params == {"hours": 1.5, "name": "Wanderung", "gap": "5m", "waypoints": "false"}


def test_build_request_omits_blank_optional_params():
    _, params, _ = build_request(
        {"base_url": "https://t.example", "imei": "1", "track_name": "  ", "gap": ""}
    )
    assert "name" not in params
    assert "gap" not in params


@pytest.mark.parametrize("hours", ["", "junk", "0", "-5"])
def test_build_request_falls_back_to_default_hours(hours):
    _, params, _ = build_request({"base_url": "https://t.example", "imei": "1", "hours": hours})
    assert params["hours"] == DEFAULT_HOURS


def test_build_request_clamps_hours_to_upstream_max_window():
    # The upstream answers 400 above -max-window; a blank slide would be worse
    # than a slightly shorter window than asked for.
    _, params, _ = build_request({"base_url": "https://t.example", "imei": "1", "hours": "5000"})
    assert params["hours"] == MAX_HOURS


@pytest.mark.parametrize(
    "config",
    [{}, {"base_url": "https://t.example"}, {"imei": "123"}, {"base_url": "", "imei": "123"}],
)
def test_build_request_needs_base_url_and_imei(config):
    assert build_request(config) is None


# --- upstream error mapping ------------------------------------------------


def test_upstream_error_uses_documented_json_body():
    resp = httpx.Response(404, json={"error": "unknown device", "status": 404})
    assert _upstream_error(resp) == {"error": "unknown device", "status": 404}


def test_upstream_error_falls_back_on_non_json_body():
    resp = httpx.Response(502, text="<html>bad gateway</html>")
    assert _upstream_error(resp) == {"error": "Upstream returned HTTP 502", "status": 502}


# --- fetch_track -----------------------------------------------------------


def _client_factory(handler):
    """Patch httpx.AsyncClient so fetch_track talks to `handler` instead of the net."""

    class FakeClient:
        def __init__(self, *args, **kwargs):
            self._transport = httpx.MockTransport(handler)
            self._kwargs = kwargs

        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc):
            return False

        async def get(self, url, params=None, headers=None):
            request = httpx.Request("GET", httpx.URL(url, params=params or {}), headers=headers)
            return handler(request)

    return FakeClient


CONFIG = {"base_url": "https://t.example", "imei": "123", "token": "s3cret"}


async def test_fetch_track_parses_response_and_window(monkeypatch):
    seen = {}

    def handler(request):
        seen["url"] = str(request.url)
        seen["auth"] = request.headers.get("authorization")
        return httpx.Response(
            200,
            text=_gpx(f"<trk><name>Tour</name>{_trkseg([(50.0, 10.0), (50.1, 10.1)])}</trk>"),
            headers={
                "Content-Type": "application/gpx+xml",
                "X-Track-From": "2026-08-21T10:00:00Z",
                "X-Track-Until": "2026-08-22T10:00:00Z",
            },
        )

    monkeypatch.setattr(httpx, "AsyncClient", _client_factory(handler))
    track = await fetch_track(CONFIG)

    assert track["name"] == "Tour"
    assert track["from"] == "2026-08-21T10:00:00Z"
    assert track["until"] == "2026-08-22T10:00:00Z"
    assert seen["auth"] == "Bearer s3cret"
    assert "/v1/devices/123/gpx" in seen["url"]
    # The token must travel in the header only.
    assert "s3cret" not in seen["url"]


async def test_fetch_track_surfaces_upstream_json_error(monkeypatch):
    def handler(request):
        return httpx.Response(401, json={"error": "missing token", "status": 401})

    monkeypatch.setattr(httpx, "AsyncClient", _client_factory(handler))
    assert await fetch_track(CONFIG) == {"error": "missing token", "status": 401}


async def test_fetch_track_rejects_non_gpx_body(monkeypatch):
    def handler(request):
        return httpx.Response(200, text="totally not xml")

    monkeypatch.setattr(httpx, "AsyncClient", _client_factory(handler))
    result = await fetch_track(CONFIG)
    assert result["status"] == 502
    assert "valid GPX" in result["error"]


async def test_fetch_track_reports_timeout_as_504(monkeypatch):
    def handler(request):
        raise httpx.TimeoutException("too slow", request=request)

    monkeypatch.setattr(httpx, "AsyncClient", _client_factory(handler))
    assert (await fetch_track(CONFIG))["status"] == 504


async def test_fetch_track_reports_transport_failure_as_502(monkeypatch):
    def handler(request):
        raise httpx.ConnectError("no route", request=request)

    monkeypatch.setattr(httpx, "AsyncClient", _client_factory(handler))
    assert (await fetch_track(CONFIG))["status"] == 502


async def test_fetch_track_reports_unconfigured_slide_without_calling_out(monkeypatch):
    def handler(request):
        raise AssertionError("should not have made a request")

    monkeypatch.setattr(httpx, "AsyncClient", _client_factory(handler))
    result = await fetch_track({"base_url": "", "imei": ""})
    assert result["status"] == 400


# --- slide type ------------------------------------------------------------


async def test_is_available_requires_base_url_and_imei():
    assert await is_available({"base_url": "https://t.example", "imei": "123"}) is True
    assert await is_available({"base_url": "https://t.example"}) is False
    assert await is_available({}) is False


async def test_render_iframes_the_map_page_by_slide_id():
    html = await render({"base_url": "https://t.example", "imei": "123"}, slide_id=7)
    assert 'src="/gpx/7"' in html
    # The display's periodic iframe reset would restart the map for nothing.
    assert "data-no-reset" in html


async def test_render_never_leaks_the_token_into_the_slide_html():
    html = await render({"base_url": "https://t.example", "imei": "123", "token": "s3cret"}, slide_id=7)
    assert "s3cret" not in html
    assert "123" not in html


async def test_render_without_a_slide_id_explains_itself():
    html = await render({"base_url": "https://t.example", "imei": "123"})
    assert "<iframe" not in html
    assert "saved" in html
