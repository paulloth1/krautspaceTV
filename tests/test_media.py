from backend.slides.media import _parse_scale, is_available, render


# ---------------------------------------------------------------------------
# is_available
# ---------------------------------------------------------------------------


async def test_is_available_requires_src():
    assert await is_available({}) is False
    assert await is_available({"src": ""}) is False
    assert await is_available({"src": "https://example.com/x.jpg"}) is True


# ---------------------------------------------------------------------------
# _parse_scale
# ---------------------------------------------------------------------------


def test_parse_scale_defaults_to_one_when_unset():
    assert _parse_scale({}) == 1


def test_parse_scale_parses_numeric_string():
    assert _parse_scale({"scale": "2.5"}) == 2.5


def test_parse_scale_falls_back_to_one_on_invalid_value():
    assert _parse_scale({"scale": "not-a-number"}) == 1


def test_parse_scale_falls_back_to_one_when_zero_or_negative():
    assert _parse_scale({"scale": "0"}) == 1
    assert _parse_scale({"scale": "-3"}) == 1


def test_parse_scale_treats_empty_string_as_default():
    assert _parse_scale({"scale": ""}) == 1


# ---------------------------------------------------------------------------
# render - image
# ---------------------------------------------------------------------------


async def test_render_image_default_kind():
    html = await render({"kind": "image", "src": "https://example.com/a.jpg"})
    assert '<img src="https://example.com/a.jpg" alt="media">' in html
    assert 'class="slide slide-media slide-media-image"' in html


async def test_render_image_escapes_src():
    html = await render({"kind": "image", "src": '"><script>alert(1)</script>'})
    assert "<script>alert(1)</script>" not in html
    assert "&lt;script&gt;" in html


# ---------------------------------------------------------------------------
# render - video
# ---------------------------------------------------------------------------


async def test_render_video_tag():
    html = await render({"kind": "video", "src": "https://example.com/a.mp4"})
    assert '<video src="https://example.com/a.mp4" autoplay muted loop playsinline></video>' in html


async def test_render_video_escapes_src():
    html = await render({"kind": "video", "src": '"><script>bad()</script>'})
    assert "<script>bad()</script>" not in html


# ---------------------------------------------------------------------------
# render - url (plain iframe, no bypass_csp)
# ---------------------------------------------------------------------------


async def test_render_url_plain_iframe_uses_src_directly():
    html = await render({"kind": "url", "src": "https://example.com/widget"})
    assert '<iframe src="https://example.com/widget"' in html
    assert "/proxy" not in html


async def test_render_url_no_reset_attribute_present_when_set():
    html = await render({"kind": "url", "src": "https://example.com/w", "no_reset": "yes"})
    assert "data-no-reset" in html


async def test_render_url_no_reset_attribute_absent_by_default():
    html = await render({"kind": "url", "src": "https://example.com/w"})
    assert "data-no-reset" not in html


async def test_render_url_scale_applies_transform_style():
    html = await render({"kind": "url", "src": "https://example.com/w", "scale": "2"})
    assert "transform:scale(2.0)" in html
    assert "width:50.0%" in html


async def test_render_url_no_scale_uses_simple_style():
    html = await render({"kind": "url", "src": "https://example.com/w"})
    assert "overflow:hidden;" in html
    assert "transform:scale" not in html


# ---------------------------------------------------------------------------
# render - url with bypass_csp
# ---------------------------------------------------------------------------


async def test_render_url_bypass_csp_with_slide_id_uses_proxy_slide_id():
    html = await render(
        {"kind": "url", "src": "https://example.com/w", "bypass_csp": "yes"}, slide_id=42
    )
    assert '<iframe src="/proxy?slide_id=42"' in html


async def test_render_url_bypass_csp_without_slide_id_uses_proxy_url():
    html = await render({"kind": "url", "src": "https://example.com/w?a=1", "bypass_csp": "yes"})
    assert "/proxy?url=" in html
    # the URL must be quoted into the query string, not left raw with its own '?'
    assert "https%3A%2F%2Fexample.com%2Fw%3Fa%3D1" in html


async def test_render_url_bypass_csp_without_slide_id_includes_cookies_when_set():
    html = await render(
        {
            "kind": "url",
            "src": "https://example.com/w",
            "bypass_csp": "yes",
            "cookies": "a=b; c=d",
        }
    )
    assert "&amp;cookies=" in html
    assert "a%3Db%3B%20c%3Dd" in html


async def test_render_url_bypass_csp_without_cookies_omits_cookies_param():
    html = await render({"kind": "url", "src": "https://example.com/w", "bypass_csp": "yes"})
    assert "cookies=" not in html


async def test_render_url_bypass_csp_prefers_slide_id_over_url_when_both_available():
    html = await render(
        {"kind": "url", "src": "https://example.com/w", "bypass_csp": "yes", "cookies": "a=b"},
        slide_id=5,
    )
    assert html.count('src="/proxy?slide_id=5"') == 1
    assert "cookies=" not in html


async def test_render_url_bypass_csp_falsy_values_do_not_trigger_proxy():
    for falsy in ("no", "0", "false", "", None):
        html = await render({"kind": "url", "src": "https://example.com/w", "bypass_csp": falsy})
        assert "/proxy" not in html


async def test_render_url_bypass_csp_truthy_values_trigger_proxy():
    for truthy in ("1", "true", "yes", "on", "YES", "True"):
        html = await render(
            {"kind": "url", "src": "https://example.com/w", "bypass_csp": truthy}, slide_id=1
        )
        assert "/proxy?slide_id=1" in html


async def test_render_url_escapes_iframe_src():
    html = await render({"kind": "url", "src": '"><script>alert(1)</script>'})
    assert "<script>alert(1)</script>" not in html
    assert "&lt;script&gt;" in html
