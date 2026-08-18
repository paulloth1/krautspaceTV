from backend.printer import ACTIVE_STATES, _clean_filename, _parse_temp


def test_clean_filename_strips_path_and_slicer_suffix():
    raw = "/usr/data/printer_data/gcodes/DT770_Cat_Ear.stl_PETG_1h6m24s.gcode"
    assert _clean_filename(raw) == "DT770_Cat_Ear"


def test_clean_filename_handles_short_names_without_suffix():
    assert _clean_filename("test.gcode") == "test"


def test_clean_filename_handles_sub_hour_time_suffix():
    # printLeftTime under an hour omits the "h" component (e.g. "6m24s" not "0h6m24s")
    assert _clean_filename("thing.stl_PLA_6m24s.gcode") == "thing"


def test_clean_filename_none_and_empty():
    assert _clean_filename(None) is None
    assert _clean_filename("") is None


def test_parse_temp_valid_string():
    assert _parse_temp("28.000000") == 28.0


def test_parse_temp_invalid():
    assert _parse_temp(None) is None
    assert _parse_temp("not-a-number") is None


def test_active_states_covers_printing_paused_pausing():
    assert ACTIVE_STATES == {1, 5, 6}
