from datetime import datetime
from unittest.mock import MagicMock, patch
from zoneinfo import ZoneInfo

from morning_news.digest import (
    NewsItem,
    SourceConfig,
    build_subject,
    clean_summary,
    dedupe_items,
    is_google_news_article_url,
    normalize_link,
    parse_feed_xml,
    render_html_digest,
    render_text_digest,
    resolve_google_news_url,
)

JST = ZoneInfo("Asia/Tokyo")


SAMPLE_RSS = """<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0">
  <channel>
    <title>sample</title>
    <item>
      <title>日経の見出しA</title>
      <link>https://www.nikkei.com/article/A</link>
      <description>これは記事の要約文です。見出しより詳しい内容を書きます。</description>
      <pubDate>Fri, 10 Jul 2026 06:00:00 +0900</pubDate>
    </item>
    <item>
      <title>日経の見出しB</title>
      <link>https://www.nikkei.com/article/B</link>
      <description>日経の見出しB</description>
    </item>
  </channel>
</rss>
"""


def test_parse_feed_xml_extracts_items_and_cleans_summary():
    source = SourceConfig(
        id="nikkei_gnews",
        name="日経",
        category="nikkei",
        url="https://example.com/rss",
        max_items=10,
    )
    items = parse_feed_xml(SAMPLE_RSS, source)
    assert len(items) == 2
    assert items[0].title == "日経の見出しA"
    assert items[0].link.endswith("/A")
    assert "要約文" in items[0].summary
    assert items[1].summary == ""


def test_dedupe_items_removes_same_link_and_title():
    items = [
        NewsItem("a", "A", "nikkei", 100, "同一タイトル", "https://ex.com/1", ""),
        NewsItem("b", "B", "economy", 80, "同一タイトル", "https://ex.com/2", ""),
        NewsItem("c", "C", "general", 50, "別タイトル", "https://ex.com/1?utm=1", ""),
        NewsItem("d", "D", "general", 40, "完全に別", "https://ex.com/3", ""),
    ]
    unique = dedupe_items(items)
    titles = {i.title for i in unique}
    assert "同一タイトル" in titles
    assert "完全に別" in titles
    assert len(unique) == 2


def test_normalize_google_news_link_query_url():
    link = "https://news.google.com/rss/articles/CBMi?url=https%3A%2F%2Fwww.nikkei.com%2Farticle%2FX"
    assert normalize_link(link) == "https://www.nikkei.com/article/X"
    assert is_google_news_article_url(
        "https://news.google.com/rss/articles/CBMibEFVX3lxTE1RNXh?oc=5"
    )


def test_clean_summary_drops_title_only():
    assert clean_summary("同じ見出し", "同じ見出し") == ""
    assert clean_summary("同じ見出し", "同じ見出し 日本経済新聞") == ""
    assert clean_summary(
        "ANA、赤字の国内線でLCC流の運賃体系",
        "ANA、赤字の国内線でLCC流の運賃体系 日本経済新聞",
    ) == ""
    result = clean_summary("同じ見出し", "同じ見出し。これは補足の本文で詳細がわかる。")
    assert "補足" in result
    assert "詳細" in result


def test_strip_source_suffix():
    from morning_news.digest import strip_source_suffix

    assert (
        strip_source_suffix("ANA、赤字の国内線でLCC流の運賃体系 - 日本経済新聞")
        == "ANA、赤字の国内線でLCC流の運賃体系"
    )


def test_resolve_google_news_url_parses_batch_response():
    article = "https://news.google.com/rss/articles/CBMiTESTARTICLEID?oc=5"
    page_html = '<div data-n-a-sg="SIG123" data-n-a-ts="1710000000"></div>'
    batch_body = (
        ")]}'\n"
        "12\n"
        + json_dumps_batch("https://www.nikkei.com/article/RESOLVED")
    )

    session = MagicMock()
    page_resp = MagicMock()
    page_resp.text = page_html
    page_resp.raise_for_status = MagicMock()
    post_resp = MagicMock()
    post_resp.text = batch_body
    post_resp.raise_for_status = MagicMock()
    session.get.return_value = page_resp
    session.post.return_value = post_resp

    resolved = resolve_google_news_url(article, session=session)
    assert resolved == "https://www.nikkei.com/article/RESOLVED"


def json_dumps_batch(url: str) -> str:
    import json

    payload = json.dumps(["garturlres", url])
    envelope = ["wrb.fr", "Fbv4je", payload]
    return json.dumps([envelope])


def test_render_digest_includes_summary_and_original_link_cta():
    now = datetime(2026, 7, 10, 6, 30, tzinfo=JST)
    items = [
        NewsItem(
            "n",
            "日経",
            "nikkei",
            100,
            "日経記事",
            "https://www.nikkei.com/article/1",
            "本文要約がここに入ります。",
            access="headline",
        ),
        NewsItem(
            "e",
            "経済紙",
            "economy",
            80,
            "経済記事",
            "https://eco.example/1",
            "",
            ai_summary="AIで書いた短い補足です。",
            access="free",
        ),
    ]
    text = render_text_digest(items, [], now)
    html_body = render_html_digest(items, [], now)
    assert "要約: 本文要約がここに入ります。" in text
    assert "補足: AIで書いた短い補足です。" in text
    assert "見出しのみ" in text
    assert "無料で読める想定" in text
    assert "無料記事を開く" in html_body
    assert "有料の場合あり" in html_body
    assert "有料全文は再配信しません" in text
    assert "有料全文は再配信しません" in html_body
    assert "会員が必要" in text
    assert "会員が必要" in html_body
    assert build_subject(now, 2) == "[朝刊] 2026-07-10（金） 2件"


def test_render_digest_includes_nikkei_warning_when_empty():
    now = datetime(2026, 7, 10, 6, 30, tzinfo=JST)
    items = [
        NewsItem("nhk", "NHK", "general", 50, "総合ニュース", "https://ex.com/n", "s"),
    ]
    text = render_text_digest(items, [], now)
    assert "日経関連の見出しを取得できませんでした" in text
