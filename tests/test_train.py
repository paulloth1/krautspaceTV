from backend.slides.train import (
    _disruption_texts,
    _format_time,
    _int_or_none,
    _max_rows,
    _product_class,
    _render_row,
    render,
)


def test_format_time_unix_timestamp_renders_hh_mm():
    # 2026-09-01 08:05:00 Europe/Berlin (CEST, UTC+2)
    assert _format_time(1788242700) == "08:05"


def test_format_time_passes_through_already_formatted_string():
    assert _format_time("08:05") == "08:05"


def test_format_time_none_and_missing():
    assert _format_time(None) == ""
    assert _format_time("") == ""


def test_product_class():
    assert _product_class("Bus 12") == "bus"
    assert _product_class("Str 5") == "tram"
    assert _product_class("RE 15") == "rail"
    assert _product_class("RB28") == "rail"
    assert _product_class("Fähre 3") == ""
    assert _product_class("") == ""


def test_int_or_none():
    assert _int_or_none(5) == 5
    assert _int_or_none("7") == 7
    assert _int_or_none(None) is None
    assert _int_or_none("nope") is None


def test_max_rows_default_and_override():
    assert _max_rows({}) == 12
    assert _max_rows({"max_rows": "5"}) == 5
    assert _max_rows({"max_rows": "0"}) == 12
    assert _max_rows({"max_rows": "-3"}) == 12
    assert _max_rows({"max_rows": "junk"}) == 12


def test_disruption_texts_keeps_him_drops_amenities():
    messages = [
        {"code": "NAME", "text": "RE 15", "type": "A", "is_him": None},
        {"code": "FM", "text": "Fahrkartenautomat im Zug", "type": "A", "is_him": None},
        {"code": "text", "text": "Umleitung wegen Bauarbeiten", "type": "H", "is_him": True},
        {"code": "text", "text": "Umleitung wegen Bauarbeiten", "type": "H", "is_him": True},
    ]
    assert _disruption_texts(messages) == ["Umleitung wegen Bauarbeiten"]


def test_disruption_texts_handles_junk():
    assert _disruption_texts(None) == []
    assert _disruption_texts("not a list") == []
    assert _disruption_texts([None, 42, {"is_him": True, "text": "  "}]) == []


def test_render_row_on_time():
    html = _render_row(
        {"train": "Str 5", "destination": "Lobeda-West", "scheduledTime": 1788242700, "delay": 0}
    )
    assert 'class="dep"' in html
    assert "08:05" in html
    assert "delay" not in html
    assert 'class="line-pill line-tram"' in html


def test_render_row_delayed_minor_and_major():
    minor = _render_row({"train": "Bus 1", "destination": "X", "scheduledTime": 1788242700, "delay": 3})
    assert "dep-late" in minor and "dep-late-major" not in minor
    assert "+3" in minor

    major = _render_row({"train": "Bus 1", "destination": "X", "scheduledTime": 1788242700, "delay": 27})
    assert "dep-late-major" in major
    assert "+27" in major


def test_render_row_cancelled():
    html = _render_row(
        {
            "train": "Bus 10",
            "destination": "Burgaupark",
            "scheduledTime": 1788242700,
            "delay": 12,
            "isCancelled": True,
        }
    )
    assert "dep-cancelled" in html
    assert "Fällt aus" in html
    # a cancelled trip shows no "+N" delay figure
    assert "+12" not in html


def test_render_row_platform_change():
    html = _render_row(
        {
            "train": "Bus 424",
            "destination": "Busbahnhof",
            "scheduledTime": 1788242700,
            "platform": "3",
            "scheduledPlatform": "1",
        }
    )
    assert 'class="dep-platform changed"' in html
    assert "<s>1</s> 3" in html


def test_render_row_via_and_disruption_and_escaping():
    html = _render_row(
        {
            "train": "RE 1",
            "destination": "<script>",
            "scheduledTime": 1788242700,
            "via": ["Weimar", "Erfurt"],
            "messages": [{"is_him": True, "text": "Gleiswechsel", "type": "H"}],
        }
    )
    assert "über Weimar · Erfurt" in html
    assert "Gleiswechsel" in html
    assert "&lt;script&gt;" in html
    assert "<script>" not in html


async def test_render_error_and_empty(monkeypatch):
    async def _fake_fetch_non_dict(url):
        return None

    async def _fake_fetch_empty(url):
        return {"departures": []}

    async def _fake_fetch_many(url):
        return {
            "departures": [
                {"train": f"Bus {i}", "destination": f"Stop {i}", "scheduledTime": 1788242700}
                for i in range(30)
            ]
        }

    monkeypatch.setattr("backend.slides.train.fetch_json", _fake_fetch_non_dict)
    assert "Unable to load departures" in await render({"api_url": "x"}, None)

    monkeypatch.setattr("backend.slides.train.fetch_json", _fake_fetch_empty)
    assert "No departures found" in await render({"api_url": "x"}, None)

    monkeypatch.setattr("backend.slides.train.fetch_json", _fake_fetch_many)
    html = await render({"api_url": "x", "max_rows": "4"}, None)
    assert "<thead>" in html
    assert html.count('<tr class="dep') == 4  # capped
