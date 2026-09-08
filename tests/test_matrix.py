import httpx

from backend.slides.matrix import _headers, _messages_url, is_available, render


def _client_factory(handler):
    """Patch httpx.AsyncClient so fetch_json talks to `handler` instead of the net."""

    class FakeClient:
        def __init__(self, *args, **kwargs):
            self._kwargs = kwargs

        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc):
            return False

        async def get(self, url, headers=None):
            request = httpx.Request("GET", url, headers=headers)
            response = handler(request)
            response.request = request
            return response

    return FakeClient


# ---------------------------------------------------------------------------
# _messages_url
# ---------------------------------------------------------------------------


def test_messages_url_builds_room_messages_endpoint():
    url = _messages_url({"homeserver": "https://matrix.org", "room_id": "!abc:matrix.org"}, 15)
    assert url == (
        "https://matrix.org/_matrix/client/v3/rooms/%21abc%3Amatrix.org/messages?dir=b&limit=15"
    )


def test_messages_url_strips_trailing_slash_from_homeserver():
    url = _messages_url({"homeserver": "https://matrix.org/", "room_id": "!x:matrix.org"}, 5)
    assert url.startswith("https://matrix.org/_matrix")


# ---------------------------------------------------------------------------
# _headers
# ---------------------------------------------------------------------------


def test_headers_always_includes_bearer_token():
    assert _headers({"access_token": "s3cret"}) == {"Authorization": "Bearer s3cret"}
    assert _headers({}) == {"Authorization": "Bearer "}


# ---------------------------------------------------------------------------
# is_available
# ---------------------------------------------------------------------------


async def test_is_available_requires_homeserver_room_id_and_token():
    assert await is_available({}) is False
    assert await is_available({"homeserver": "https://matrix.org"}) is False
    assert (
        await is_available({"homeserver": "https://matrix.org", "room_id": "!x:matrix.org"})
        is False
    )
    assert (
        await is_available(
            {
                "homeserver": "https://matrix.org",
                "room_id": "!x:matrix.org",
                "access_token": "tok",
            }
        )
        is True
    )


# ---------------------------------------------------------------------------
# render
# ---------------------------------------------------------------------------


CONFIG = {
    "homeserver": "https://matrix.org",
    "room_id": "!abc:matrix.org",
    "access_token": "tok",
}


async def test_render_lists_messages_oldest_first(monkeypatch):
    def handler(request):
        return httpx.Response(
            200,
            json={
                "chunk": [
                    {
                        "type": "m.room.message",
                        "sender": "@bob:matrix.org",
                        "content": {"body": "second"},
                    },
                    {
                        "type": "m.room.message",
                        "sender": "@alice:matrix.org",
                        "content": {"body": "first"},
                    },
                ]
            },
        )

    monkeypatch.setattr(httpx, "AsyncClient", _client_factory(handler))
    html = await render(CONFIG)
    # the homeserver returns newest-first (dir=b); render() reverses it
    first_pos = html.index("first")
    second_pos = html.index("second")
    assert first_pos < second_pos
    assert '<span class="sender">alice</span>' in html
    assert '<span class="sender">bob</span>' in html


async def test_render_filters_non_message_events_and_empty_bodies(monkeypatch):
    def handler(request):
        return httpx.Response(
            200,
            json={
                "chunk": [
                    {"type": "m.room.member", "sender": "@bob:matrix.org", "content": {}},
                    {
                        "type": "m.room.message",
                        "sender": "@bob:matrix.org",
                        "content": {"body": ""},
                    },
                    {
                        "type": "m.room.message",
                        "sender": "@alice:matrix.org",
                        "content": {"body": "hi"},
                    },
                ]
            },
        )

    monkeypatch.setattr(httpx, "AsyncClient", _client_factory(handler))
    html = await render(CONFIG)
    assert html.count("<li>") == 1
    assert "hi" in html


async def test_render_uses_configured_room_name(monkeypatch):
    def handler(request):
        return httpx.Response(200, json={"chunk": []})

    monkeypatch.setattr(httpx, "AsyncClient", _client_factory(handler))
    html = await render({**CONFIG, "room_name": "General"})
    assert "<h2>General</h2>" in html


async def test_render_defaults_room_name_when_unset(monkeypatch):
    def handler(request):
        return httpx.Response(200, json={"chunk": []})

    monkeypatch.setattr(httpx, "AsyncClient", _client_factory(handler))
    html = await render(CONFIG)
    assert "<h2>Matrix chat</h2>" in html


async def test_render_escapes_sender_and_body_html(monkeypatch):
    def handler(request):
        return httpx.Response(
            200,
            json={
                "chunk": [
                    {
                        "type": "m.room.message",
                        "sender": "@<script>:matrix.org",
                        "content": {"body": "<b>hi</b> & bye"},
                    }
                ]
            },
        )

    monkeypatch.setattr(httpx, "AsyncClient", _client_factory(handler))
    html = await render(CONFIG)
    assert "<script>" not in html
    assert "&lt;script&gt;" in html
    assert "<b>hi</b>" not in html
    assert "&lt;b&gt;hi&lt;/b&gt; &amp; bye" in html


async def test_render_escapes_room_name(monkeypatch):
    def handler(request):
        return httpx.Response(200, json={"chunk": []})

    monkeypatch.setattr(httpx, "AsyncClient", _client_factory(handler))
    html = await render({**CONFIG, "room_name": "<i>Room</i>"})
    assert "<i>Room</i>" not in html
    assert "&lt;i&gt;Room&lt;/i&gt;" in html


async def test_render_shows_no_messages_message_when_chunk_empty(monkeypatch):
    def handler(request):
        return httpx.Response(200, json={"chunk": []})

    monkeypatch.setattr(httpx, "AsyncClient", _client_factory(handler))
    html = await render(CONFIG)
    assert "No recent messages." in html


async def test_render_shows_friendly_error_on_fetch_failure(monkeypatch):
    def handler(request):
        return httpx.Response(500, text="boom")

    monkeypatch.setattr(httpx, "AsyncClient", _client_factory(handler))
    html = await render(CONFIG)
    assert "Unable to load messages." in html


async def test_render_shows_friendly_error_on_timeout(monkeypatch):
    def handler(request):
        raise httpx.TimeoutException("too slow", request=request)

    monkeypatch.setattr(httpx, "AsyncClient", _client_factory(handler))
    html = await render(CONFIG)
    assert "Unable to load messages." in html
