import httpx

from backend.slides.webcam import is_available, render


def _client_factory(handler):
    """Patch httpx.AsyncClient so is_available's stream() talks to `handler`
    instead of the net."""

    class FakeStream:
        def __init__(self, response):
            self._response = response

        async def __aenter__(self):
            return self._response

        async def __aexit__(self, *exc):
            return False

    class FakeClient:
        def __init__(self, *args, **kwargs):
            self._kwargs = kwargs

        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc):
            return False

        def stream(self, method, url):
            request = httpx.Request(method, url)
            return FakeStream(handler(request))

    return FakeClient


# ---------------------------------------------------------------------------
# is_available
# ---------------------------------------------------------------------------


async def test_is_available_false_when_no_url():
    assert await is_available({}) is False
    assert await is_available({"url": ""}) is False


async def test_is_available_true_on_success_status(monkeypatch):
    def handler(request):
        return httpx.Response(200)

    monkeypatch.setattr(httpx, "AsyncClient", _client_factory(handler))
    assert await is_available({"url": "http://cam.local/stream"}) is True


async def test_is_available_false_on_4xx_5xx_status(monkeypatch):
    def handler(request):
        return httpx.Response(404)

    monkeypatch.setattr(httpx, "AsyncClient", _client_factory(handler))
    assert await is_available({"url": "http://cam.local/stream"}) is False


async def test_is_available_false_on_connection_error(monkeypatch):
    def handler(request):
        raise httpx.ConnectError("no route", request=request)

    monkeypatch.setattr(httpx, "AsyncClient", _client_factory(handler))
    assert await is_available({"url": "http://cam.local/stream"}) is False


async def test_is_available_false_on_timeout(monkeypatch):
    def handler(request):
        raise httpx.TimeoutException("too slow", request=request)

    monkeypatch.setattr(httpx, "AsyncClient", _client_factory(handler))
    assert await is_available({"url": "http://cam.local/stream"}) is False


# ---------------------------------------------------------------------------
# render
# ---------------------------------------------------------------------------


async def test_render_produces_img_tag_with_url_and_label():
    html = await render({"url": "http://cam.local/stream", "label": "3D Printer"})
    assert '<div class="slide slide-webcam">' in html
    assert 'src="http://cam.local/stream"' in html
    assert 'alt="3D Printer"' in html


async def test_render_defaults_label_when_unset():
    html = await render({"url": "http://cam.local/stream"})
    assert 'alt="Webcam"' in html


async def test_render_escapes_url_and_label():
    html = await render(
        {"url": '"><script>alert(1)</script>', "label": "<b>cam</b>"}
    )
    assert "<script>alert(1)</script>" not in html
    assert "<b>cam</b>" not in html
    assert "&lt;script&gt;" in html
    assert "&lt;b&gt;cam&lt;/b&gt;" in html
