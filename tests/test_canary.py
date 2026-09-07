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


def _hanging_client_factory():
    """A fake aiomqtt.Client whose subscription never yields a message, so
    _listen_once's per-message wait always hits its recheck timeout."""

    class _FakeClient:
        def __init__(self, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc_info):
            return False

        async def subscribe(self, topic):
            pass

        @property
        def messages(self):
            async def _gen():
                await asyncio.Event().wait()  # never resolves
                yield  # pragma: no cover - unreachable, just satisfies "is a generator"

            return _gen()

    return _FakeClient


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
    config = ("broker", 1883, "canary/glasses/event", "canary/glasses/state", "canary/glasses/status")

    async def _config():
        return config

    # The fake client's message list is finite; _listen_once's "next message"
    # wait raises StopAsyncIteration once it's exhausted (a real connection
    # would instead just keep waiting) - that's fine here, we only care that
    # every message got dispatched to STATE before that happens.
    with pytest.raises(StopAsyncIteration):
        await _listen_once(*config, _config, config)

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
    config = ("broker", 1883, "canary/glasses/event", "canary/glasses/state", "canary/glasses/status")

    async def _config():
        return config

    with pytest.raises(StopAsyncIteration):
        await _listen_once(*config, _config, config)
    assert (await state.snapshot())["present"] is False


async def test_listen_once_reconnects_when_config_changes_mid_connection(monkeypatch):
    monkeypatch.setattr("backend.canary.STATE", CanaryState())
    monkeypatch.setattr("backend.canary.CONFIG_RECHECK_INTERVAL", 0.01)
    monkeypatch.setattr(aiomqtt, "Client", _hanging_client_factory())

    old_config = ("broker", 1883, "e", "s", "st")
    new_config = ("broker", 1883, "e2", "s2", "st2")

    async def _config():
        return new_config  # already different from old_config on the very first recheck

    # Returns normally (doesn't hang, doesn't raise) once it notices the
    # settings changed underneath an otherwise perfectly healthy, idle
    # connection - proving a saved settings change doesn't sit unapplied
    # until the connection happens to drop on its own for some other reason.
    await asyncio.wait_for(
        _listen_once("broker", 1883, "e", "s", "st", _config, old_config), timeout=1
    )


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
