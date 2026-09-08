import httpx

from backend.slides.mastodon import (
    _headers,
    _strip_html,
    _timeline_url,
    is_available,
    render,
)


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
# _timeline_url
# ---------------------------------------------------------------------------


def test_timeline_url_builds_tag_timeline_endpoint():
    url = _timeline_url({"instance": "mastodon.social", "hashtag": "krautspace"}, 10)
    assert url == "https://mastodon.social/api/v1/timelines/tag/krautspace?limit=10"


def test_timeline_url_strips_hash_prefix_and_trailing_slash():
    url = _timeline_url({"instance": "mastodon.social/", "hashtag": "#foo"}, 5)
    assert url == "https://mastodon.social/api/v1/timelines/tag/foo?limit=5"


def test_timeline_url_quotes_hashtag():
    url = _timeline_url({"instance": "example.com", "hashtag": "foo bar"}, 5)
    assert "foo%20bar" in url


# ---------------------------------------------------------------------------
# _strip_html
# ---------------------------------------------------------------------------


def test_strip_html_removes_tags_and_collapses_whitespace():
    assert _strip_html("<p>Hello   <b>world</b>\n\n!</p>") == "Hello world !"


def test_strip_html_unescapes_entities():
    assert _strip_html("Fish &amp; Chips") == "Fish & Chips"


def test_strip_html_handles_empty_input():
    assert _strip_html("") == ""


# ---------------------------------------------------------------------------
# _headers
# ---------------------------------------------------------------------------


def test_headers_includes_bearer_token_when_present():
    assert _headers({"access_token": "s3cret"}) == {"Authorization": "Bearer s3cret"}


def test_headers_empty_when_no_token():
    assert _headers({}) == {}
    assert _headers({"access_token": ""}) == {}


# ---------------------------------------------------------------------------
# is_available
# ---------------------------------------------------------------------------


async def test_is_available_requires_instance_and_hashtag():
    assert await is_available({}) is False
    assert await is_available({"instance": "mastodon.social"}) is False
    assert await is_available({"hashtag": "foo"}) is False
    assert await is_available({"instance": "mastodon.social", "hashtag": "foo"}) is True


# ---------------------------------------------------------------------------
# render
# ---------------------------------------------------------------------------


CONFIG = {"instance": "mastodon.social", "hashtag": "krautspace"}


async def test_render_lists_posts_with_display_name_and_stripped_content(monkeypatch):
    def handler(request):
        return httpx.Response(
            200,
            json=[
                {
                    "account": {"display_name": "Jane", "acct": "jane@example.com"},
                    "content": "<p>Hello <b>world</b></p>",
                }
            ],
        )

    monkeypatch.setattr(httpx, "AsyncClient", _client_factory(handler))
    html = await render(CONFIG)
    assert '<h2>#krautspace</h2>' in html
    assert "Jane" in html
    assert "Hello world" in html
    assert '<li><span class="sender">Jane</span>: Hello world</li>' in html


async def test_render_falls_back_to_acct_when_no_display_name(monkeypatch):
    def handler(request):
        return httpx.Response(
            200,
            json=[{"account": {"display_name": "", "acct": "jane"}, "content": "hi"}],
        )

    monkeypatch.setattr(httpx, "AsyncClient", _client_factory(handler))
    html = await render(CONFIG)
    assert '<span class="sender">jane</span>' in html


async def test_render_uses_configured_title_when_present(monkeypatch):
    def handler(request):
        return httpx.Response(200, json=[])

    monkeypatch.setattr(httpx, "AsyncClient", _client_factory(handler))
    html = await render({**CONFIG, "title": "Krautspace Toots"})
    assert "<h2>Krautspace Toots</h2>" in html


async def test_render_escapes_sender_and_body_html(monkeypatch):
    def handler(request):
        return httpx.Response(
            200,
            json=[
                {
                    "account": {"display_name": "<script>alert(1)</script>", "acct": ""},
                    "content": "<p>&lt;danger&gt; &amp; co</p>",
                }
            ],
        )

    monkeypatch.setattr(httpx, "AsyncClient", _client_factory(handler))
    html = await render(CONFIG)
    assert "<script>alert(1)</script>" not in html
    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in html
    # content is HTML-unescaped by _strip_html then markupsafe-escaped again
    assert "&lt;danger&gt; &amp; co" in html


async def test_render_escapes_title_when_derived_from_config(monkeypatch):
    def handler(request):
        return httpx.Response(200, json=[])

    monkeypatch.setattr(httpx, "AsyncClient", _client_factory(handler))
    html = await render({**CONFIG, "title": "<b>Bold</b> title"})
    assert "<b>Bold</b>" not in html
    assert "&lt;b&gt;Bold&lt;/b&gt;" in html


async def test_render_shows_no_posts_message_when_timeline_empty(monkeypatch):
    def handler(request):
        return httpx.Response(200, json=[])

    monkeypatch.setattr(httpx, "AsyncClient", _client_factory(handler))
    html = await render(CONFIG)
    assert "No recent posts." in html


async def test_render_shows_friendly_error_on_fetch_failure(monkeypatch):
    def handler(request):
        return httpx.Response(500, text="boom")

    monkeypatch.setattr(httpx, "AsyncClient", _client_factory(handler))
    html = await render(CONFIG)
    assert "Unable to load posts." in html


async def test_render_shows_friendly_error_on_non_list_json(monkeypatch):
    def handler(request):
        return httpx.Response(200, json={"error": "nope"})

    monkeypatch.setattr(httpx, "AsyncClient", _client_factory(handler))
    html = await render(CONFIG)
    assert "Unable to load posts." in html


async def test_render_shows_friendly_error_on_timeout(monkeypatch):
    def handler(request):
        raise httpx.TimeoutException("too slow", request=request)

    monkeypatch.setattr(httpx, "AsyncClient", _client_factory(handler))
    html = await render(CONFIG)
    assert "Unable to load posts." in html
