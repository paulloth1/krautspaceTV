from backend.slides.rss import (
    _first_image_url,
    _guess_author,
    _html_to_lines,
    _join_lines,
    _parse_items,
    _pick_headline,
    _strip_html,
)
from defusedxml import ElementTree


def _item(xml_fragment: str):
    """Parse a standalone <item>...</item> or <entry>...</entry> fragment
    (with the namespaces _parse_items relies on already declared) into an
    ElementTree element, for tests that exercise the per-item helpers
    directly rather than going through _parse_items."""
    wrapper = f"""<rss xmlns:content="http://purl.org/rss/1.0/modules/content/"
                        xmlns:dc="http://purl.org/dc/elements/1.1/"
                        xmlns:media="http://search.yahoo.com/mrss/">
        {xml_fragment}
    </rss>"""
    root = ElementTree.fromstring(wrapper)
    return root[0]


# ---------------------------------------------------------------------------
# _strip_html
# ---------------------------------------------------------------------------


def test_strip_html_removes_tags_and_collapses_whitespace():
    assert _strip_html("<p>Hello   <b>world</b>\n\n!</p>") == "Hello world !"


def test_strip_html_unescapes_entities():
    assert _strip_html("Fish &amp; Chips") == "Fish & Chips"


def test_strip_html_strips_markdown_bold_markers():
    assert _strip_html("This is **important** news") == "This is important news"


def test_strip_html_handles_empty_input():
    assert _strip_html("") == ""
    assert _strip_html(None) == ""


# ---------------------------------------------------------------------------
# _html_to_lines
# ---------------------------------------------------------------------------


def test_html_to_lines_splits_paragraphs_into_separate_lines():
    html = "<p>First paragraph.</p><p>Second paragraph.</p>"
    assert _html_to_lines(html) == ["First paragraph.", "Second paragraph."]


def test_html_to_lines_prefixes_list_items_with_bullet():
    html = "<ul><li>Apples</li><li>Oranges</li></ul>"
    assert _html_to_lines(html) == ["• Apples", "• Oranges"]


def test_html_to_lines_treats_br_and_div_as_breaks():
    html = "<div>Line one<br>Line two</div><div>Line three</div>"
    assert _html_to_lines(html) == ["Line one", "Line two", "Line three"]


def test_html_to_lines_strips_markdown_bold_markers():
    html = "<p>This is **bold** text</p>"
    assert _html_to_lines(html) == ["This is bold text"]


def test_html_to_lines_drops_empty_lines():
    html = "<p></p><p>Real content</p><p>   </p>"
    assert _html_to_lines(html) == ["Real content"]


def test_html_to_lines_empty_input():
    assert _html_to_lines("") == []
    assert _html_to_lines(None) == []


# ---------------------------------------------------------------------------
# _join_lines
# ---------------------------------------------------------------------------


def test_join_lines_keeps_all_lines_within_budget():
    lines = ["short line", "another short line"]
    assert _join_lines(lines, 100) == "short line\nanother short line"


def test_join_lines_truncates_with_ellipsis_when_over_budget():
    lines = ["this is a fairly long line that will not fit in the budget"]
    result = _join_lines(lines, 30)
    assert result.endswith("…")
    assert len(result) <= 31  # 30-char budget + the appended ellipsis char


def test_join_lines_does_not_cut_mid_line_for_earlier_lines():
    lines = ["exact line one", "line two which is much too long to fit at all here"]
    # "exact line one" (14 chars) fits; the second line would overflow.
    result = _join_lines(lines, 20)
    result_lines = result.split("\n")
    assert result_lines[0] == "exact line one"
    # the overflowing line, if included, must be truncated (not cut verbatim)
    if len(result_lines) > 1:
        assert result_lines[1].endswith("…")


def test_join_lines_omits_truncated_remainder_when_too_small():
    # remaining budget <= 20 chars after the first line -> drop it entirely
    lines = ["a line that uses up nearly the whole budget", "more"]
    result = _join_lines(lines, 45)
    assert "more" not in result


def test_join_lines_empty_list_returns_empty_string():
    assert _join_lines([], 100) == ""


# ---------------------------------------------------------------------------
# _pick_headline
# ---------------------------------------------------------------------------


def test_pick_headline_uses_title_when_not_truncated():
    headline, lines = _pick_headline("A normal title", ["body line one", "body line two"])
    assert headline == "A normal title"
    assert lines == ["body line one", "body line two"]


def test_pick_headline_prefers_body_first_line_when_title_truncated_with_ellipsis_dots():
    headline, lines = _pick_headline(
        "This title got cut off by the sou...",
        ["This title got cut off by the source, in full", "second line"],
    )
    assert headline == "This title got cut off by the source, in full"
    assert lines == ["second line"]


def test_pick_headline_prefers_body_first_line_when_title_truncated_with_unicode_ellipsis():
    headline, lines = _pick_headline(
        "Truncated title…",
        ["Full untruncated body text", "more"],
    )
    assert headline == "Full untruncated body text"
    assert lines == ["more"]


def test_pick_headline_falls_back_to_title_when_no_lines_available():
    headline, lines = _pick_headline("Truncated...", [])
    assert headline == "Truncated..."
    assert lines == []


def test_pick_headline_uses_first_line_when_title_empty():
    headline, lines = _pick_headline("", ["Only body line"])
    assert headline == "Only body line"
    assert lines == []


# ---------------------------------------------------------------------------
# _guess_author
# ---------------------------------------------------------------------------


def test_guess_author_reduces_rss_email_display_name_format():
    item = _item("<item><link>https://example.com/post</link></item>")
    assert _guess_author(item, "someone@example.com (Jane Doe)") == "Jane Doe"


def test_guess_author_returns_author_as_is_when_not_email_format():
    item = _item("<item><link>https://example.com/post</link></item>")
    assert _guess_author(item, "Plain Author Name") == "Plain Author Name"


def test_guess_author_strips_html_from_author_field():
    item = _item("<item><link>https://example.com/post</link></item>")
    assert _guess_author(item, "<b>Jane</b> Doe") == "Jane Doe"


def test_guess_author_falls_back_to_mastodon_link_pattern():
    item = _item(
        "<item><link>https://mastodon.social/@someuser/109638128231</link></item>"
    )
    assert _guess_author(item, "") == "@someuser@mastodon.social"


def test_guess_author_falls_back_to_guid_when_no_link_match():
    item = _item(
        "<item><guid>https://fedi.example.org/@another/12345</guid></item>"
    )
    assert _guess_author(item, "") == "@another@fedi.example.org"


def test_guess_author_returns_empty_when_no_author_or_mastodon_pattern():
    item = _item("<item><link>https://example.com/plain-post</link></item>")
    assert _guess_author(item, "") == ""


# ---------------------------------------------------------------------------
# _first_image_url
# ---------------------------------------------------------------------------


def test_first_image_url_picks_media_content_with_image_type():
    item = _item(
        """<item>
            <media:content url="https://example.com/a.mp4" type="video/mp4"/>
            <media:content url="https://example.com/a.jpg" type="image/jpeg"/>
        </item>"""
    )
    assert _first_image_url(item) == "https://example.com/a.jpg"


def test_first_image_url_picks_media_medium_image_when_no_type():
    item = _item(
        '<item><media:content url="https://example.com/b.jpg" medium="image"/></item>'
    )
    assert _first_image_url(item) == "https://example.com/b.jpg"


def test_first_image_url_returns_empty_when_no_image_media():
    item = _item(
        '<item><media:content url="https://example.com/a.mp4" type="video/mp4"/></item>'
    )
    assert _first_image_url(item) == ""


def test_first_image_url_returns_empty_when_no_media_content_at_all():
    item = _item("<item><title>No media here</title></item>")
    assert _first_image_url(item) == ""


# ---------------------------------------------------------------------------
# _parse_items
# ---------------------------------------------------------------------------


def test_parse_items_normal_rss2_feed():
    xml = """<?xml version="1.0"?>
    <rss version="2.0">
      <channel>
        <title>Example Feed</title>
        <item>
          <title>Hello World</title>
          <description>A simple description.</description>
        </item>
      </channel>
    </rss>"""
    items = _parse_items(xml, limit=5)
    assert items == [
        {
            "title": "Hello World",
            "lines": ["A simple description."],
            "author": "",
            "image_url": "",
        }
    ]


def test_parse_items_gotosocial_prefers_content_encoded_over_truncated_title():
    xml = """<?xml version="1.0"?>
    <rss version="2.0" xmlns:content="http://purl.org/rss/1.0/modules/content/">
      <channel>
        <item>
          <title>Someone made a new post: This is the beginning of a very lo...</title>
          <content:encoded><![CDATA[<p>This is the beginning of a very long post that got cut off in the title but is complete here.</p>]]></content:encoded>
          <description>Someone made a new post: This is the beginning of a very lo...</description>
        </item>
      </channel>
    </rss>"""
    items = _parse_items(xml, limit=5)
    assert len(items) == 1
    assert items[0]["title"] == (
        "This is the beginning of a very long post that got cut off "
        "in the title but is complete here."
    )
    assert items[0]["lines"] == []


def test_parse_items_mastodon_tag_feed_no_title_or_author():
    xml = """<?xml version="1.0"?>
    <rss version="2.0">
      <channel>
        <item>
          <link>https://mastodon.social/@someuser/109638128231</link>
          <guid>https://mastodon.social/@someuser/109638128231</guid>
          <description><![CDATA[<p>First paragraph of the toot.</p><p>Second paragraph.</p>]]></description>
        </item>
      </channel>
    </rss>"""
    items = _parse_items(xml, limit=5)
    assert len(items) == 1
    item = items[0]
    assert item["title"] == "First paragraph of the toot."
    assert item["lines"] == ["Second paragraph."]
    assert item["author"] == "@someuser@mastodon.social"


def test_parse_items_extracts_media_content_image():
    xml = """<?xml version="1.0"?>
    <rss version="2.0" xmlns:media="http://search.yahoo.com/mrss/">
      <channel>
        <item>
          <title>Post with image</title>
          <description>Some text</description>
          <media:content url="https://example.com/photo.jpg" type="image/jpeg"/>
        </item>
      </channel>
    </rss>"""
    items = _parse_items(xml, limit=5)
    assert items[0]["image_url"] == "https://example.com/photo.jpg"


def test_parse_items_rss_author_email_display_name_format():
    xml = """<?xml version="1.0"?>
    <rss version="2.0">
      <channel>
        <item>
          <title>Post</title>
          <description>Body</description>
          <author>writer@example.com (A. Writer)</author>
        </item>
      </channel>
    </rss>"""
    items = _parse_items(xml, limit=5)
    assert items[0]["author"] == "A. Writer"


def test_parse_items_respects_limit():
    xml = """<?xml version="1.0"?>
    <rss version="2.0">
      <channel>
        <item><title>One</title><description>a</description></item>
        <item><title>Two</title><description>b</description></item>
        <item><title>Three</title><description>c</description></item>
      </channel>
    </rss>"""
    items = _parse_items(xml, limit=2)
    assert len(items) == 2
    assert [i["title"] for i in items] == ["One", "Two"]


def test_parse_items_falls_back_to_atom_when_no_rss_items():
    xml = """<?xml version="1.0"?>
    <feed xmlns="http://www.w3.org/2005/Atom">
      <title>Example Atom Feed</title>
      <entry>
        <title>Atom Entry Title</title>
        <summary>Atom entry summary text.</summary>
        <author><name>Atom Author</name></author>
      </entry>
    </feed>"""
    items = _parse_items(xml, limit=5)
    assert items == [
        {
            "title": "Atom Entry Title",
            "lines": ["Atom entry summary text."],
            "author": "Atom Author",
            "image_url": "",
        }
    ]


def test_parse_items_atom_falls_back_to_content_when_no_summary():
    xml = """<?xml version="1.0"?>
    <feed xmlns="http://www.w3.org/2005/Atom">
      <entry>
        <title>Entry</title>
        <content>Content body text.</content>
      </entry>
    </feed>"""
    items = _parse_items(xml, limit=5)
    assert items[0]["lines"] == ["Content body text."]


def test_parse_items_returns_none_on_invalid_xml():
    assert _parse_items("<not valid xml", limit=5) is None


def test_parse_items_returns_empty_list_when_no_items_or_entries():
    xml = """<?xml version="1.0"?><rss version="2.0"><channel><title>Empty</title></channel></rss>"""
    assert _parse_items(xml, limit=5) == []
