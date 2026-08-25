"""Fetch and parse GPX tracks for the `gpx` map slide.

The upstream is a Protegear-backed GPX API: `GET /v1/devices/{imei}/gpx`
returns GPX 1.1 for a look-back window, optionally behind a bearer token, and
reports the window it actually resolved via `X-Track-From`/`X-Track-Until`.

Parsing happens here rather than in the browser on purpose. The Pi 2 is slow
enough that DOM-parsing a multi-thousand-point GPX file visibly stalls the
kiosk tab, so the map page gets pre-parsed, pre-decimated JSON instead and
Leaflet only ever draws a bounded number of points. Keeping the fetch
server-side also means the API token never reaches the browser.
"""

import math

import httpx
from defusedxml import ElementTree
from defusedxml.ElementTree import ParseError

# The upstream proxies another service, so it can be slow; still well under the
# display's own 15s READY_TIMEOUT_MS budget for revealing a slide.
FETCH_TIMEOUT = 15.0

# Upper bound on points handed to Leaflet. A 24h tracker window is routinely
# several thousand fixes, which the Pi 2 renders at a crawl; at ~2000 points a
# polyline still looks continuous on a 1080p TV.
MAX_POINTS = 2000

# ~1.1m at the equator — far finer than consumer GPS, and it roughly halves the
# JSON payload versus full float repr.
COORD_PRECISION = 5

EARTH_RADIUS_KM = 6371.0

DEFAULT_HOURS = 24.0
# Matches the upstream's own default -max-window.
MAX_HOURS = 720.0


def _local(tag: str) -> str:
    """Strip the XML namespace, so GPX 1.0, 1.1 and namespace-less files all
    parse through the same code path."""
    return tag.rpartition("}")[2]


def _children(element, name: str):
    return (child for child in element if _local(child.tag) == name)


def _find_text(element, name: str) -> str:
    for child in _children(element, name):
        return (child.text or "").strip()
    return ""


def _coord(element) -> tuple[float, float] | None:
    try:
        lat = float(element.get("lat"))
        lon = float(element.get("lon"))
    except (TypeError, ValueError):
        return None
    # Reject out-of-range junk rather than handing Leaflet a point it will
    # silently clamp, dragging the fitted bounds off to nowhere.
    if not (-90.0 <= lat <= 90.0 and -180.0 <= lon <= 180.0):
        return None
    return lat, lon


def _haversine_km(a: tuple[float, float], b: tuple[float, float]) -> float:
    lat1, lon1 = math.radians(a[0]), math.radians(a[1])
    lat2, lon2 = math.radians(b[0]), math.radians(b[1])
    dlat, dlon = lat2 - lat1, lon2 - lon1
    h = math.sin(dlat / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin(dlon / 2) ** 2
    return 2 * EARTH_RADIUS_KM * math.asin(math.sqrt(h))


def _decimate(segments: list[list[tuple[float, float]]]) -> list[list[tuple[float, float]]]:
    """Thin the track to at most MAX_POINTS, keeping each segment's first and
    last point so segment ends (and therefore the gaps between them) stay put."""
    total = sum(len(seg) for seg in segments)
    if total <= MAX_POINTS or total == 0:
        return segments
    stride = math.ceil(total / MAX_POINTS)
    thinned = []
    for seg in segments:
        if len(seg) <= 2:
            thinned.append(seg)
            continue
        kept = seg[::stride]
        if kept[-1] != seg[-1]:
            kept.append(seg[-1])
        thinned.append(kept)
    return thinned


def _round(point: tuple[float, float]) -> list[float]:
    return [round(point[0], COORD_PRECISION), round(point[1], COORD_PRECISION)]


def parse_gpx(text: str) -> dict | None:
    """Parse GPX into the shape the map page consumes. None if it isn't GPX."""
    try:
        root = ElementTree.fromstring(text)
    except (ParseError, ValueError):
        return None
    if _local(root.tag) != "gpx":
        return None

    name = ""
    for metadata in _children(root, "metadata"):
        name = _find_text(metadata, "name")
        break

    segments: list[list[tuple[float, float]]] = []
    last_time = ""
    for trk in _children(root, "trk"):
        name = name or _find_text(trk, "name")
        for seg in _children(trk, "trkseg"):
            points = []
            for trkpt in _children(seg, "trkpt"):
                point = _coord(trkpt)
                if point is None:
                    continue
                points.append(point)
                last_time = _find_text(trkpt, "time") or last_time
            if points:
                segments.append(points)

    waypoints = []
    for wpt in _children(root, "wpt"):
        point = _coord(wpt)
        if point is None:
            continue
        waypoints.append(
            {
                "lat": round(point[0], COORD_PRECISION),
                "lon": round(point[1], COORD_PRECISION),
                "name": _find_text(wpt, "name") or _find_text(wpt, "sym"),
                "time": _find_text(wpt, "time"),
            }
        )

    flat = [point for seg in segments for point in seg]
    distance_km = sum(
        _haversine_km(seg[i - 1], seg[i]) for seg in segments for i in range(1, len(seg))
    )

    bounds = None
    if flat or waypoints:
        lats = [p[0] for p in flat] + [w["lat"] for w in waypoints]
        lons = [p[1] for p in flat] + [w["lon"] for w in waypoints]
        bounds = [[min(lats), min(lons)], [max(lats), max(lons)]]

    # Only multi-point segments become polylines; a lone fix would draw nothing,
    # but it still counts for bounds, start/end markers and the point total.
    drawable = _decimate([seg for seg in segments if len(seg) >= 2])

    return {
        "name": name,
        "segments": [[_round(point) for point in seg] for seg in drawable],
        "waypoints": waypoints,
        "bounds": bounds,
        "start": _round(flat[0]) if flat else None,
        "end": _round(flat[-1]) if flat else None,
        "last_fix": last_time,
        "point_count": len(flat),
        "distance_km": round(distance_km, 2),
    }


def _hours(config: dict) -> float:
    try:
        hours = float(config.get("hours") or DEFAULT_HOURS)
    except ValueError:
        return DEFAULT_HOURS
    if hours <= 0:
        return DEFAULT_HOURS
    # The upstream answers 400 for anything over its -max-window; clamp instead
    # of turning a slightly-too-large config value into a blank slide.
    return min(hours, MAX_HOURS)


def build_request(config: dict) -> tuple[str, dict, dict] | None:
    """Build (url, params, headers) for the upstream GPX export, or None if the
    slide isn't configured enough to ask."""
    base_url = (config.get("base_url") or "").strip().rstrip("/")
    imei = (config.get("imei") or "").strip()
    if not base_url or not imei:
        return None

    params: dict = {"hours": _hours(config)}
    track_name = (config.get("track_name") or "").strip()
    if track_name:
        params["name"] = track_name
    gap = (config.get("gap") or "").strip()
    if gap:
        params["gap"] = gap
    params["waypoints"] = (
        "true" if str(config.get("waypoints") or "yes").lower() in ("1", "true", "yes", "on") else "false"
    )

    headers = {"Accept": "application/gpx+xml"}
    token = (config.get("token") or "").strip()
    if token:
        # Bearer rather than ?key=, so the token stays out of the upstream's
        # access log as well as out of the browser.
        headers["Authorization"] = f"Bearer {token}"

    return f"{base_url}/v1/devices/{imei}/gpx", params, headers


def _upstream_error(resp: httpx.Response) -> dict:
    """Turn the upstream's {"error": "...", "status": N} body into ours, falling
    back to the HTTP status when the body isn't the documented JSON."""
    message = ""
    try:
        body = resp.json()
        if isinstance(body, dict):
            message = str(body.get("error") or "")
    except ValueError:
        pass
    if not message:
        message = f"Upstream returned HTTP {resp.status_code}"
    return {"error": message, "status": resp.status_code}


async def fetch_track(config: dict) -> dict:
    """Fetch and parse the configured device's track.

    Always returns a dict: either the parsed track (plus the resolved window)
    or `{"error": ..., "status": ...}` for the map page to display.
    """
    request = build_request(config)
    if request is None:
        return {"error": "Slide is missing its API base URL or device IMEI", "status": 400}
    url, params, headers = request

    try:
        async with httpx.AsyncClient(timeout=FETCH_TIMEOUT, follow_redirects=True) as client:
            resp = await client.get(url, params=params, headers=headers)
    except httpx.TimeoutException:
        return {"error": "Track API timed out", "status": 504}
    except httpx.HTTPError:
        return {"error": "Could not reach the track API", "status": 502}

    if resp.status_code != 200:
        return _upstream_error(resp)

    track = parse_gpx(resp.text)
    if track is None:
        return {"error": "Track API did not return valid GPX", "status": 502}

    track["from"] = resp.headers.get("X-Track-From", "")
    track["until"] = resp.headers.get("X-Track-Until", "")
    return track
