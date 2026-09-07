import asyncio
from types import SimpleNamespace

import aiomqtt
import pytest

from backend.canary import CanaryState, _decode, _listen_once, canary_listener_loop


def _client_factory(messages):
    """A fake aiomqtt.Client whose subscription yields `messages` in order,
    each a (topic, payload) pair."""

    class _FakeClient:
        def __init__(self, **kwargs):
            self.kwargs = kwargs

        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc_info):
            return False

        async def subscribe(self, topic):
            pass

        @property
        def messages(self):
            async def _gen():
                for topic, payload in messages:
                    yield SimpleNamespace(topic=topic, payload=payload)

            return _gen()

    return _FakeClient


def test_decode_bytes_and_str():
    assert _decode(b"present") == "present"
    assert _decode(b"  spaced  ") == "spaced"
    assert _decode("already a string") == "already a string"


async def test_canary_state_snapshot_defaults():
    state = CanaryState()
    snap = await state.snapshot()
    assert snap == {"configured": False, "online": None, "present": None, "event": ""}


async def test_canary_state_set_configured_false_clears_everything():
    state = CanaryState()
    await state.set_online(True)
    await state.set_present(True)
    await state.set_event("Glasses detected: Meta Ray-Ban (-49 dBm)")
    await state.set_configured(False)
    snap = await state.snapshot()
    assert snap == {"configured": False, "online": None, "present": None, "event": ""}


async def test_listen_once_dispatches_each_topic(monkeypatch):
    state = CanaryState()
    monkeypatch.setattr("backend.canary.STATE", state)
    monkeypatch.setattr(
        aiomqtt,
        "Client",
        _client_factory(
            [
                ("canary/glasses/status", b"online"),
                ("canary/glasses/state", b"present"),
                ("canary/glasses/event", b"Glasses detected: Meta Ray-Ban (-49 dBm)"),
            ]
        ),
    )
    await _listen_once(
        "broker", 1883, "canary/glasses/event", "canary/glasses/state", "canary/glasses/status"
    )
    snap = await state.snapshot()
    assert snap["online"] is True
    assert snap["present"] is True
    assert snap["event"] == "Glasses detected: Meta Ray-Ban (-49 dBm)"


async def test_listen_once_state_clear(monkeypatch):
    state = CanaryState()
    monkeypatch.setattr("backend.canary.STATE", state)
    monkeypatch.setattr(
        aiomqtt, "Client", _client_factory([("canary/glasses/state", b"clear")])
    )
    await _listen_once(
        "broker", 1883, "canary/glasses/event", "canary/glasses/state", "canary/glasses/status"
    )
    assert (await state.snapshot())["present"] is False


async def test_canary_listener_loop_marks_unconfigured_when_no_config(monkeypatch):
    state = CanaryState()
    monkeypatch.setattr("backend.canary.STATE", state)
    monkeypatch.setattr("backend.canary.RECONNECT_DELAY", 0)

    async def _no_config():
        return None

    task = asyncio.create_task(canary_listener_loop(_no_config))
    await asyncio.sleep(0.05)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task

    assert (await state.snapshot())["configured"] is False


async def test_canary_listener_loop_marks_offline_on_connection_error(monkeypatch):
    state = CanaryState()
    monkeypatch.setattr("backend.canary.STATE", state)
    monkeypatch.setattr("backend.canary.RECONNECT_DELAY", 0)

    async def _boom(*args, **kwargs):
        raise aiomqtt.MqttError("connection refused")

    monkeypatch.setattr("backend.canary._listen_once", _boom)

    async def _config():
        return ("broker", 1883, "e", "s", "st")

    task = asyncio.create_task(canary_listener_loop(_config))
    await asyncio.sleep(0.05)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task

    snap = await state.snapshot()
    assert snap["configured"] is True
    assert snap["online"] is False
