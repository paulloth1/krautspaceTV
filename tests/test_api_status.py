from types import SimpleNamespace

import aiomqtt
import pytest

from backend.slides.api_status import _extract, _fetch_mqtt, _is_truthy, is_available


def _client_factory(payload: bytes | None = None, error: Exception | None = None):
    """A fake aiomqtt.Client: connecting raises `error` if given, otherwise
    the fake subscription immediately yields one message with `payload`."""

    class _FakeClient:
        def __init__(self, **kwargs):
            self.kwargs = kwargs

        async def __aenter__(self):
            if error is not None:
                raise error
            return self

        async def __aexit__(self, *exc_info):
            return False

        async def subscribe(self, topic):
            pass

        @property
        def messages(self):
            async def _gen():
                if payload is not None:
                    yield SimpleNamespace(payload=payload)

            return _gen()

    return _FakeClient


def test_extract_dot_path():
    assert _extract({"door": {"open": True}}, "door.open") is True
    assert _extract({"door": {"open": True}}, "") == {"door": {"open": True}}
    assert _extract({"door": {}}, "door.open") is None
    assert _extract("not a dict", "door.open") is None


def test_is_truthy_variations():
    assert _is_truthy(True) is True
    assert _is_truthy(False) is False
    assert _is_truthy(1) is True
    assert _is_truthy(0) is False
    assert _is_truthy("open") is True
    assert _is_truthy("closed") is False
    assert _is_truthy(None) is False


async def test_is_available_http_needs_api_url():
    assert await is_available({}) is False
    assert await is_available({"api_url": "https://example.com"}) is True


async def test_is_available_mqtt_needs_host_and_topic():
    assert await is_available({"source": "mqtt"}) is False
    assert await is_available({"source": "mqtt", "mqtt_host": "broker"}) is False
    assert (
        await is_available({"source": "mqtt", "mqtt_host": "broker", "mqtt_topic": "t"}) is True
    )


async def test_fetch_mqtt_missing_config_skips_connecting():
    assert await _fetch_mqtt({}) is None
    assert await _fetch_mqtt({"mqtt_host": "broker"}) is None


async def test_fetch_mqtt_json_payload_is_decoded(monkeypatch):
    monkeypatch.setattr(aiomqtt, "Client", _client_factory(payload=b'{"open": true}'))
    result = await _fetch_mqtt({"mqtt_host": "broker", "mqtt_topic": "door"})
    assert result == {"open": True}


async def test_fetch_mqtt_plain_string_payload_passes_through(monkeypatch):
    monkeypatch.setattr(aiomqtt, "Client", _client_factory(payload=b"open"))
    result = await _fetch_mqtt({"mqtt_host": "broker", "mqtt_topic": "door"})
    assert result == "open"


async def test_fetch_mqtt_connection_error_returns_none(monkeypatch):
    monkeypatch.setattr(aiomqtt, "Client", _client_factory(error=aiomqtt.MqttError("boom")))
    result = await _fetch_mqtt({"mqtt_host": "broker", "mqtt_topic": "door"})
    assert result is None


async def test_fetch_mqtt_no_message_returns_none(monkeypatch):
    monkeypatch.setattr(aiomqtt, "Client", _client_factory(payload=None))
    result = await _fetch_mqtt({"mqtt_host": "broker", "mqtt_topic": "door"}, timeout=0.5)
    assert result is None
