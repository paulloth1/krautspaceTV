from backend.slides.train import _format_time


def test_format_time_unix_timestamp_renders_hh_mm():
    # 2026-09-01 08:05:00 Europe/Berlin (CEST, UTC+2)
    assert _format_time(1788242700) == "08:05"


def test_format_time_passes_through_already_formatted_string():
    assert _format_time("08:05") == "08:05"


def test_format_time_none_and_missing():
    assert _format_time(None) == ""
    assert _format_time("") == ""
