async def test_init_db_creates_tables_and_default_setting(db_module):
    await db_module.init_db()

    slides = await db_module.list_slides()
    assert slides == []

    interval = await db_module.get_setting("rotation_interval_seconds")
    assert interval == "60"


async def test_add_get_list_slide_roundtrip(db_module):
    await db_module.init_db()

    slide_id = await db_module.add_slide("clock", "My Clock", {"timezone": "UTC"})

    slide = await db_module.get_slide(slide_id)
    assert slide is not None
    assert slide["id"] == slide_id
    assert slide["type"] == "clock"
    assert slide["name"] == "My Clock"
    assert slide["position"] == 0
    assert slide["enabled"] is True
    assert slide["config"] == {"timezone": "UTC"}

    slides = await db_module.list_slides()
    assert len(slides) == 1
    assert slides[0] == slide


async def test_add_slide_assigns_increasing_positions(db_module):
    await db_module.init_db()

    id1 = await db_module.add_slide("clock", "Clock", {})
    id2 = await db_module.add_slide("weather", "Weather", {})

    slides = await db_module.list_slides()
    assert [s["id"] for s in slides] == [id1, id2]
    assert [s["position"] for s in slides] == [0, 1]


async def test_get_slide_missing_returns_none(db_module):
    await db_module.init_db()
    assert await db_module.get_slide(999) is None


async def test_list_slides_enabled_only(db_module):
    await db_module.init_db()

    id1 = await db_module.add_slide("clock", "Clock", {})
    id2 = await db_module.add_slide("weather", "Weather", {})
    await db_module.toggle_slide(id2)

    all_slides = await db_module.list_slides()
    assert {s["id"] for s in all_slides} == {id1, id2}

    enabled = await db_module.list_slides(enabled_only=True)
    assert [s["id"] for s in enabled] == [id1]


async def test_update_slide(db_module):
    await db_module.init_db()
    slide_id = await db_module.add_slide("clock", "Old Name", {"a": 1})

    await db_module.update_slide(slide_id, "New Name", {"a": 2})

    slide = await db_module.get_slide(slide_id)
    assert slide["name"] == "New Name"
    assert slide["config"] == {"a": 2}


async def test_delete_slide(db_module):
    await db_module.init_db()
    slide_id = await db_module.add_slide("clock", "Clock", {})

    await db_module.delete_slide(slide_id)

    assert await db_module.get_slide(slide_id) is None
    assert await db_module.list_slides() == []


async def test_toggle_slide(db_module):
    await db_module.init_db()
    slide_id = await db_module.add_slide("clock", "Clock", {})

    slide = await db_module.get_slide(slide_id)
    assert slide["enabled"] is True

    await db_module.toggle_slide(slide_id)
    slide = await db_module.get_slide(slide_id)
    assert slide["enabled"] is False

    await db_module.toggle_slide(slide_id)
    slide = await db_module.get_slide(slide_id)
    assert slide["enabled"] is True


async def test_move_slide_up_and_down(db_module):
    await db_module.init_db()
    id1 = await db_module.add_slide("a", "A", {})
    id2 = await db_module.add_slide("b", "B", {})
    id3 = await db_module.add_slide("c", "C", {})

    await db_module.move_slide(id2, "up")
    slides = await db_module.list_slides()
    assert [s["id"] for s in slides] == [id2, id1, id3]

    await db_module.move_slide(id2, "down")
    slides = await db_module.list_slides()
    assert [s["id"] for s in slides] == [id1, id2, id3]


async def test_move_slide_first_up_is_noop(db_module):
    await db_module.init_db()
    id1 = await db_module.add_slide("a", "A", {})
    id2 = await db_module.add_slide("b", "B", {})

    await db_module.move_slide(id1, "up")

    slides = await db_module.list_slides()
    assert [s["id"] for s in slides] == [id1, id2]


async def test_move_slide_last_down_is_noop(db_module):
    await db_module.init_db()
    id1 = await db_module.add_slide("a", "A", {})
    id2 = await db_module.add_slide("b", "B", {})

    await db_module.move_slide(id2, "down")

    slides = await db_module.list_slides()
    assert [s["id"] for s in slides] == [id1, id2]


async def test_get_setting_default_for_missing_key(db_module):
    await db_module.init_db()
    assert await db_module.get_setting("does_not_exist") is None
    assert await db_module.get_setting("does_not_exist", "fallback") == "fallback"


async def test_set_setting_roundtrip_and_upsert(db_module):
    await db_module.init_db()

    await db_module.set_setting("rotation_interval_seconds", "30")
    assert await db_module.get_setting("rotation_interval_seconds") == "30"

    # calling again with a different value should update, not raise
    await db_module.set_setting("rotation_interval_seconds", "45")
    assert await db_module.get_setting("rotation_interval_seconds") == "45"


async def test_set_setting_new_key(db_module):
    await db_module.init_db()

    await db_module.set_setting("brand_new_key", "hello")
    assert await db_module.get_setting("brand_new_key") == "hello"
