import asyncio

import pytest

from backend.rotation import EMPTY_HTML, RotationState


@pytest.fixture
def state():
    # Fresh instance per test -- never touch the module-level STATE singleton.
    return RotationState()


async def test_initial_snapshot_is_empty(state):
    snap = await state.snapshot()
    assert snap["id"] is None
    assert snap["html"] == EMPTY_HTML
    assert snap["forced"] is False
    assert snap["seconds_remaining"] is None


async def test_set_current_then_snapshot(state):
    await state.set_current(5, "<p>hi</p>", forced=True, interval=10)

    snap = await state.snapshot()
    assert snap["id"] == 5
    assert snap["html"] == "<p>hi</p>"
    assert snap["forced"] is True


async def test_snapshot_seconds_remaining_counts_down(state):
    await state.set_current(1, "<p>x</p>", interval=10)

    snap = await state.snapshot()
    assert snap["seconds_remaining"] is not None
    assert snap["seconds_remaining"] >= 9


async def test_snapshot_seconds_remaining_none_with_zero_interval(state):
    await state.set_current(1, "<p>x</p>")  # default interval=0.0

    snap = await state.snapshot()
    assert snap["seconds_remaining"] is None


async def test_request_and_take_forced(state):
    assert await state.is_forced_pending() is False

    await state.request_forced(42)
    assert await state.is_forced_pending() is True

    taken = await state.take_forced()
    assert taken == 42
    assert await state.is_forced_pending() is False


async def test_take_forced_when_nothing_requested_returns_none(state):
    assert await state.take_forced() is None


async def test_interruptible_sleep_returns_early_when_forced(state):
    async def request_soon():
        await asyncio.sleep(0.1)
        await state.request_forced(7)

    start = asyncio.get_event_loop().time()
    await asyncio.wait_for(
        asyncio.gather(state.interruptible_sleep(5), request_soon()),
        timeout=1,
    )
    elapsed = asyncio.get_event_loop().time() - start
    assert elapsed < 1


async def test_interruptible_sleep_runs_full_duration_when_uninterrupted(state):
    start = asyncio.get_event_loop().time()
    await state.interruptible_sleep(0.2)
    elapsed = asyncio.get_event_loop().time() - start
    assert elapsed >= 0.2
