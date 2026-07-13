"""朝刊ニュース網羅確認 — RSS収集・ダイジェスト生成・メール送信。"""

from __future__ import annotations

import argparse
import html
import json
import os
import re
import smtplib
import ssl
from dataclasses import dataclass, field
from datetime import datetime
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlencode, urlparse
from xml.etree import ElementTree as ET
from zoneinfo import ZoneInfo

import requests
import yaml
from dotenv import load_dotenv

from morning_news.ai_summary import enrich_with_ai_summaries
from morning_news.priority import PRIORITY_LABEL, attach_priorities, curated_items
from morning_news.site import publish_site

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_SOURCES = ROOT / "config" / "sources.yaml"
ARCHIVE_DIR = ROOT / "data" / "archive"
JST = ZoneInfo("Asia/Tokyo")
HTTP_TIMEOUT_SEC = 20
USER_AGENT = "morning-news-digest/1.0 (+personal use)"
SUMMARY_MAX_CHARS = 280
GOOGLE_BATCH_EXECUTE_URL = "https://news.google.com/_/DotsSplashUi/data/batchexecute"

CATEGORY_ORDER = ("nikkei", "economy", "general")
CATEGORY_LABEL = {
    "nikkei": "日経",
    "economy": "経済",
    "general": "総合",
}


@dataclass
class SourceConfig:
    id: str
    name: str
    category: str
    url: str
    weight: int = 50
    max_items: int = 10
    access: str = "free"  # free | headline


@dataclass
class NewsItem:
    source_id: str
    source_name: str
    category: str
    weight: int
    title: str
    link: str
    summary: str = ""
    published: str = ""
    ai_summary: str = ""
    access: str = "free"
    priority: str = "C"
    priority_reason: str = ""
    priority_score: int = 0


@dataclass
class FetchResult:
    items: list[NewsItem] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)


def load_sources(path: Path = DEFAULT_SOURCES) -> list[SourceConfig]:
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    sources: list[SourceConfig] = []
    for row in raw.get("sources", []):
        access = str(row.get("access", "free")).strip().lower()
        if access not in {"free", "headline"}:
            access = "free"
        sources.append(
            SourceConfig(
                id=str(row["id"]),
                name=str(row["name"]),
                category=str(row.get("category", "general")),
                url=str(row["url"]),
                weight=int(row.get("weight", 50)),
                max_items=int(row.get("max_items", 10)),
                access=access,
            )
        )
    return sources


def _strip_html(text: str) -> str:
    no_tags = re.sub(r"<[^>]+>", " ", text or "")
    return re.sub(r"\s+", " ", html.unescape(no_tags)).strip()


def normalize_link(link: str) -> str:
    """Google News の中間URLなどから可能な範囲で正規化する。"""
    if not link:
        return ""
    parsed = urlparse(link)
    if "news.google.com" in parsed.netloc:
        query = parse_qs(parsed.query)
        if "url" in query and query["url"]:
            return query["url"][0]
    return link.strip()


def is_google_news_article_url(link: str) -> bool:
    parsed = urlparse(link)
    return "news.google.com" in parsed.netloc and "/articles/" in parsed.path


def resolve_google_news_url(
    article_url: str, session: requests.Session | None = None
) -> str | None:
    """Google News の articles URL を元記事 URL に解決する。

    2024以降の形式はリダイレクトだけでは取れないため、
    記事ページの署名を使い batchexecute API で取得する。
    """
    if not is_google_news_article_url(article_url):
        return None

    sess = session or requests.Session()
    article_id = article_url.rstrip("/").split("/")[-1].split("?")[0]
    headers = {"User-Agent": USER_AGENT, "Referer": "https://news.google.com/"}

    page = sess.get(article_url, timeout=HTTP_TIMEOUT_SEC, headers=headers)
    page.raise_for_status()
    sig_match = re.search(r'data-n-a-sg="([^"]+)"', page.text)
    ts_match = re.search(r'data-n-a-ts="([^"]+)"', page.text)
    if not sig_match or not ts_match:
        return None

    rpc_inner = json.dumps(
        [
            "garturlreq",
            [
                ["X", "X", ["X", "X"], None, None, 1, 1, "JP:ja", None, 1, None, None, None, None, None, 0, 1],
                "X",
                "X",
                1,
                [1, 1, 1],
                1,
                1,
                None,
                0,
                0,
                None,
                0,
            ],
            article_id,
            int(ts_match.group(1)),
            sig_match.group(1),
        ],
        separators=(",", ":"),
    )
    f_req = json.dumps([[["Fbv4je", rpc_inner, None, "generic"]]], separators=(",", ":"))
    post = sess.post(
        GOOGLE_BATCH_EXECUTE_URL,
        data=urlencode({"f.req": f_req}),
        timeout=HTTP_TIMEOUT_SEC,
        headers={
            **headers,
            "Content-Type": "application/x-www-form-urlencoded;charset=UTF-8",
        },
    )
    post.raise_for_status()
    body = post.text
    if body.startswith(")]}'"):
        body = body.split("\n", 1)[1]
    body = body.lstrip()
    head, _, tail = body.partition("\n")
    if head.strip().isdigit():
        body = tail
    envelopes = json.loads(body)
    for env in envelopes:
        if (
            isinstance(env, list)
            and len(env) >= 3
            and env[0] == "wrb.fr"
            and env[1] == "Fbv4je"
        ):
            payload = json.loads(env[2])
            if payload and payload[0] == "garturlres" and payload[1]:
                return str(payload[1])
    return None


def link_domain(link: str) -> str:
    host = urlparse(link).netloc.lower()
    return host.removeprefix("www.") if host else ""


def strip_source_suffix(title: str) -> str:
    """Google News 等で付く『 - 日本経済新聞』形式の末尾を落とす。"""
    cleaned = re.sub(r"\s+[-–—]\s+[^-–—]{2,40}$", "", title).strip()
    return cleaned or title


def clean_summary(title: str, summary: str) -> str:
    text = _strip_html(summary)
    if not text:
        return ""

    base_title = strip_source_suffix(title)
    candidates = {title, base_title}

    for candidate in candidates:
        compact_title = re.sub(r"[\s　]+", "", candidate)
        compact_summary = re.sub(r"[\s　]+", "", text)
        if not compact_summary:
            return ""
        if compact_summary == compact_title:
            return ""
        if compact_summary.startswith(compact_title):
            remainder = compact_summary[len(compact_title) :]
            remainder = re.sub(r"^[\-_|：:。．・]+", "", remainder)
            if len(remainder) <= 12:
                return ""
            if text.startswith(candidate):
                text = text[len(candidate) :]
            text = re.sub(r"^[\s\-_|：:。．・]+", "", text)
            break
        # 見出し本文が含まれ、残りが短い出典名だけのケース
        if compact_title and compact_title in compact_summary:
            idx = compact_summary.find(compact_title)
            before = compact_summary[:idx]
            after = compact_summary[idx + len(compact_title) :]
            after = re.sub(r"^[\-_|：:。．・]+", "", after)
            if not before and len(after) <= 12:
                return ""

    text = re.sub(r"\s+", " ", text).strip(" 。．")
    # 残った出典ラベルだけなら捨てる
    if text in {"日本経済新聞", "日経", "NHK", "Yahoo!ニュース", "毎日新聞"}:
        return ""
    if len(text) <= 12:
        return ""
    if len(text) > SUMMARY_MAX_CHARS:
        return text[: SUMMARY_MAX_CHARS - 1].rstrip() + "…"
    return text


def enrich_item_links(items: list[NewsItem], session: requests.Session | None = None) -> list[str]:
    """Google News リンクを元記事へ解決する。失敗は警告として返す。"""
    sess = session or requests.Session()
    warnings: list[str] = []
    for item in items:
        if not is_google_news_article_url(item.link):
            continue
        try:
            resolved = resolve_google_news_url(item.link, session=sess)
            if resolved:
                item.link = resolved
            else:
                warnings.append(f"link_resolve:{item.source_id}: 解決失敗（Google Newsのまま）")
        except Exception as exc:  # noqa: BLE001
            warnings.append(f"link_resolve:{item.source_id}: {exc}")
    return warnings


def _local_tag(tag: str) -> str:
    if "}" in tag:
        return tag.rsplit("}", 1)[-1]
    return tag


def _child_text(node: ET.Element, names: set[str]) -> str:
    for child in list(node):
        if _local_tag(child.tag) in names:
            return (child.text or "").strip()
    return ""


def _child_link(node: ET.Element) -> str:
    for child in list(node):
        tag = _local_tag(child.tag)
        if tag == "link":
            href = child.attrib.get("href")
            if href:
                return href.strip()
            if child.text and child.text.strip():
                return child.text.strip()
        if tag == "guid" and child.attrib.get("isPermaLink", "true").lower() != "false":
            if child.text and child.text.strip().startswith("http"):
                return child.text.strip()
    return ""


def parse_feed_xml(xml_text: str, source: SourceConfig) -> list[NewsItem]:
    root = ET.fromstring(xml_text)
    entries: list[ET.Element] = []
    for node in root.iter():
        if _local_tag(node.tag) in {"item", "entry"}:
            entries.append(node)

    items: list[NewsItem] = []
    for entry in entries[: source.max_items]:
        title = strip_source_suffix(_strip_html(_child_text(entry, {"title"})))
        link = normalize_link(_child_link(entry))
        summary = clean_summary(
            title,
            _child_text(entry, {"description", "summary", "content", "content:encoded"}),
        )
        published = _child_text(entry, {"pubDate", "published", "updated", "date"})
        if not title or not link:
            continue
        items.append(
            NewsItem(
                source_id=source.id,
                source_name=source.name,
                category=source.category,
                weight=source.weight,
                title=title,
                link=link,
                summary=summary,
                published=published,
                access=source.access,
            )
        )
    return items


def fetch_source(source: SourceConfig, session: requests.Session | None = None) -> FetchResult:
    sess = session or requests.Session()
    result = FetchResult()
    try:
        response = sess.get(
            source.url,
            timeout=HTTP_TIMEOUT_SEC,
            headers={
                "User-Agent": USER_AGENT,
                "Accept": "application/rss+xml, application/xml, text/xml, */*",
            },
        )
        response.raise_for_status()
        response.encoding = response.apparent_encoding or "utf-8"
        result.items = parse_feed_xml(response.text, source)
        if not result.items:
            result.errors.append(f"{source.id}: 記事0件（フィード形式の可能性）")
    except Exception as exc:  # noqa: BLE001 - ソース単位で握りつぶして全体継続
        result.errors.append(f"{source.id}: {exc}")
    return result


def dedupe_items(items: list[NewsItem]) -> list[NewsItem]:
    seen_links: set[str] = set()
    seen_titles: set[str] = set()
    unique: list[NewsItem] = []
    for item in sorted(items, key=lambda x: (-x.weight, x.title)):
        link_key = item.link.split("?")[0].rstrip("/").lower()
        title_key = re.sub(r"\s+", "", item.title).lower()
        if link_key in seen_links or title_key in seen_titles:
            continue
        seen_links.add(link_key)
        seen_titles.add(title_key)
        unique.append(item)
    return unique


def collect_news(sources: list[SourceConfig] | None = None) -> FetchResult:
    source_list = sources if sources is not None else load_sources()
    merged = FetchResult()
    with requests.Session() as session:
        for source in source_list:
            partial = fetch_source(source, session=session)
            merged.items.extend(partial.items)
            merged.errors.extend(partial.errors)
        resolve_warnings = enrich_item_links(merged.items, session=session)
        merged.errors.extend(resolve_warnings)
    merged.items = dedupe_items(merged.items)
    return merged


def _weekday_ja(dt: datetime) -> str:
    return "月火水木金土日"[dt.weekday()]


def group_by_category(items: list[NewsItem]) -> dict[str, list[NewsItem]]:
    grouped: dict[str, list[NewsItem]] = {key: [] for key in CATEGORY_ORDER}
    for item in items:
        key = item.category if item.category in grouped else "general"
        grouped[key].append(item)
    return grouped


def build_subject(now: datetime, item_count: int) -> str:
    return f"[朝刊] {now.strftime('%Y-%m-%d')}（{_weekday_ja(now)}） {item_count}件"


def display_summary(item: NewsItem) -> tuple[str, str]:
    """表示用の要約本文とラベルを返す。"""
    if item.ai_summary:
        return item.ai_summary, "補足"
    if item.summary:
        return item.summary, "要約"
    return "", ""


def access_label(access: str) -> str:
    if access == "headline":
        return "見出しのみ（本文は会員向けの場合あり）"
    return "無料で読める想定"


def cta_label(item: NewsItem) -> str:
    domain = link_domain(item.link)
    domain_label = domain or "元記事"
    if is_google_news_article_url(item.link):
        return "リンクを開く（Google経由）"
    if item.access == "headline":
        return f"公式ページを開く（{domain_label}・有料の場合あり）"
    return f"無料記事を開く（{domain_label}）"


def _priority_badge_text(item: NewsItem) -> str:
    label = PRIORITY_LABEL.get(item.priority, item.priority)
    return f"{item.priority}:{label}"


def render_text_digest(items: list[NewsItem], errors: list[str], now: datetime) -> str:
    items = attach_priorities(items)
    picks = curated_items(items, limit=10)
    lines = [
        build_subject(now, len(items)),
        "",
        "無料の見出し・リード中心です。有料全文は再配信しません。",
        "リンク先は日経など会員が必要な場合あり。上部が厳選、下部が網羅です。",
        "",
        f"■ 厳選（{_priority_badge_text(picks[0]) if picks else 'A/B'}優先・最大10件）",
    ]
    if not picks:
        lines.append("（該当なし）")
        lines.append("")
    for idx, item in enumerate(picks, start=1):
        lines.append(f"{idx}. [{_priority_badge_text(item)}] [{item.source_name}] {item.title}")
        if item.priority_reason:
            lines.append(f"   なぜ: {item.priority_reason}")
        lines.append(f"   リンク: {item.link}")
        lines.append("")
    lines.append("■ 網羅（全件）")
    lines.append("")
    grouped = group_by_category(items)
    for category in CATEGORY_ORDER:
        section_items = grouped.get(category) or []
        if not section_items:
            continue
        lines.append(f"■ {CATEGORY_LABEL[category]}（{len(section_items)}）")
        for idx, item in enumerate(section_items, start=1):
            lines.append(f"{idx}. [{item.source_name}] {item.title}")
            lines.append(f"   公開: {access_label(item.access)}")
            body, label = display_summary(item)
            if body:
                lines.append(f"   {label}: {body}")
            domain = link_domain(item.link)
            domain_note = f"（{domain}）" if domain else ""
            lines.append(f"   リンク{domain_note}: {item.link}")
            lines.append("")
    if errors:
        lines.append("■ 取得メモ / エラー")
        for err in errors:
            lines.append(f"- {err}")
        lines.append("")
    nikkei_count = len(grouped.get("nikkei") or [])
    if nikkei_count == 0:
        lines.append("⚠ 日経関連の見出しを取得できませんでした。ソース設定を確認してください。")
    return "\n".join(lines).strip() + "\n"


def _priority_badge_html(item: NewsItem) -> str:
    colors = {
        "A": ("#b91c1c", "#fee2e2"),
        "B": ("#b45309", "#ffedd5"),
        "C": ("#475569", "#e2e8f0"),
    }
    fg, bg = colors.get(item.priority, colors["C"])
    label = PRIORITY_LABEL.get(item.priority, item.priority)
    return (
        f"<span style='display:inline-block;font-size:11px;padding:2px 6px;"
        f"border-radius:999px;background:{bg};color:{fg};margin-right:6px'>"
        f"{html.escape(item.priority)} {html.escape(label)}</span>"
    )


def render_html_digest(items: list[NewsItem], errors: list[str], now: datetime) -> str:
    items = attach_priorities(items)
    picks = curated_items(items, limit=10)
    curated_rows: list[str] = []
    for item in picks:
        body, label = display_summary(item)
        reason = (
            f"<p style='margin:4px 0 8px;color:#555;font-size:13px'>なぜ見るか: "
            f"{html.escape(item.priority_reason)}</p>"
            if item.priority_reason
            else ""
        )
        summary_html = ""
        if body:
            summary_html = (
                f"<p style='margin:6px 0 8px;color:#333;font-size:14px;line-height:1.55'>"
                f"{html.escape(label)}: {html.escape(body)}</p>"
            )
        curated_rows.append(
            "<li style='margin:0 0 16px;padding-bottom:12px;border-bottom:1px solid #eee'>"
            f"<div style='font-size:12px;color:#888;margin-bottom:4px'>"
            f"{_priority_badge_html(item)}{html.escape(item.source_name)}</div>"
            f"<div style='font-size:17px;font-weight:600;line-height:1.4'>{html.escape(item.title)}</div>"
            f"{reason}{summary_html}"
            f"<a href='{html.escape(item.link, quote=True)}' target='_blank' rel='noopener noreferrer' "
            "style='display:inline-flex;align-items:center;min-height:44px;padding:10px 14px;"
            "background:#111827;color:#fff;text-decoration:none;border-radius:8px;font-size:15px'>"
            f"{html.escape(cta_label(item))}</a></li>"
        )
    curated_section = (
        "<h2 style='font-size:18px;border-bottom:2px solid #111;padding-bottom:6px;margin-top:20px'>"
        f"厳選（最大10件・重要度A/B）</h2>"
        "<p style='color:#555;font-size:13px;margin:8px 0 12px'>"
        "ストラテジスト視点で、意思決定や実務に効きやすいものだけ先に並べています。"
        "</p>"
        f"<ol style='padding-left:18px;margin:0'>{''.join(curated_rows) or '<li>該当なし</li>'}</ol>"
        "<h2 style='font-size:18px;border-bottom:2px solid #111;padding-bottom:6px;margin-top:28px'>"
        "網羅（全件）</h2>"
    )

    grouped = group_by_category(items)
    sections: list[str] = []
    for category in CATEGORY_ORDER:
        section_items = grouped.get(category) or []
        if not section_items:
            continue
        rows = []
        for item in section_items:
            body, label = display_summary(item)
            access_badge_bg = "#fff4e5" if item.access == "headline" else "#e8f5e9"
            access_badge_fg = "#9a5b00" if item.access == "headline" else "#1b5e20"
            access_badge = (
                f"<span style='display:inline-block;font-size:11px;padding:2px 6px;"
                f"border-radius:999px;background:{access_badge_bg};color:{access_badge_fg};"
                f"margin-right:6px'>{html.escape(access_label(item.access))}</span>"
            )
            if body:
                summary_badge = (
                    "<span style='display:inline-block;font-size:11px;padding:2px 6px;"
                    "border-radius:999px;background:#eef3ff;color:#0b57d0;margin-right:6px'>"
                    f"{html.escape(label)}</span>"
                )
                summary_html = (
                    f"<p style='margin:6px 0 8px;color:#333;font-size:14px;line-height:1.55'>"
                    f"{summary_badge}{html.escape(body)}</p>"
                )
            else:
                summary_html = (
                    "<p style='margin:6px 0 8px;color:#999;font-size:13px'>"
                    "要約なし（見出しのみ）</p>"
                )
            button_label = html.escape(cta_label(item))
            button_bg = "#6b7280" if item.access == "headline" else "#0b57d0"
            rows.append(
                "<li style='margin:0 0 18px;padding-bottom:14px;border-bottom:1px solid #eee'>"
                f"<div style='font-size:12px;color:#888;margin-bottom:4px'>"
                f"{_priority_badge_html(item)}{html.escape(item.source_name)} {access_badge}</div>"
                f"<div style='font-size:17px;font-weight:600;line-height:1.4;margin-bottom:2px'>"
                f"{html.escape(item.title)}</div>"
                f"{summary_html}"
                f"<a href='{html.escape(item.link, quote=True)}' target='_blank' rel='noopener noreferrer' "
                f"style='display:inline-flex;align-items:center;min-height:44px;padding:10px 14px;"
                f"background:{button_bg};color:#fff;text-decoration:none;border-radius:8px;font-size:15px'>"
                f"{button_label}</a></li>"
            )
        sections.append(
            f"<h2 style='font-size:18px;border-bottom:2px solid #111;padding-bottom:6px;margin-top:28px'>"
            f"{html.escape(CATEGORY_LABEL[category])}（{len(section_items)}）</h2>"
            f"<ol style='padding-left:18px;margin:12px 0 0'>{''.join(rows)}</ol>"
        )

    error_block = ""
    if errors:
        error_items = "".join(f"<li>{html.escape(err)}</li>" for err in errors)
        error_block = f"<h2 style='margin-top:28px'>取得メモ / エラー</h2><ul>{error_items}</ul>"

    warning = ""
    if not (grouped.get("nikkei") or []):
        warning = (
            "<p style='color:#b00020;font-weight:bold'>"
            "日経関連の見出しを取得できませんでした。ソース設定を確認してください。"
            "</p>"
        )

    return f"""<!DOCTYPE html>
<html lang="ja">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
  <meta name="theme-color" content="#0b57d0">
  <title>{html.escape(build_subject(now, len(items)))}</title>
</head>
<body style="font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;margin:0;padding:16px;background:#fafafa;color:#111">
  <div style="max-width:720px;margin:0 auto;background:#fff;padding:16px 16px 28px;border-radius:10px">
    <h1 style="font-size:22px;margin:0 0 8px">{html.escape(build_subject(now, len(items)))}</h1>
    <p style="color:#555;font-size:14px;line-height:1.5;margin:0 0 8px">
      無料の見出し・リード中心です。有料全文は再配信しません。
      リンク先は日経など会員が必要な場合があり、全文が読めないことがあります。
      上部の「厳選」は時短用、下部の「網羅」は漏れ確認用です。
    </p>
    {warning}
    {curated_section}
    {''.join(sections)}
    {error_block}
  </div>
</body>
</html>
"""


def save_archive(
    html_body: str, text_body: str, now: datetime, archive_dir: Path = ARCHIVE_DIR
) -> Path:
    archive_dir.mkdir(parents=True, exist_ok=True)
    day = now.strftime("%Y-%m-%d")
    html_path = archive_dir / f"{day}.html"
    text_path = archive_dir / f"{day}.txt"
    html_path.write_text(html_body, encoding="utf-8")
    text_path.write_text(text_body, encoding="utf-8")
    return html_path


def send_email(
    *,
    subject: str,
    text_body: str,
    html_body: str,
    smtp_host: str,
    smtp_port: int,
    smtp_user: str,
    smtp_password: str,
    mail_from: str,
    mail_to: str,
) -> None:
    message = MIMEMultipart("alternative")
    message["Subject"] = subject
    message["From"] = mail_from
    message["To"] = mail_to
    message.attach(MIMEText(text_body, "plain", "utf-8"))
    message.attach(MIMEText(html_body, "html", "utf-8"))

    context = ssl.create_default_context()
    with smtplib.SMTP(smtp_host, smtp_port, timeout=30) as server:
        server.starttls(context=context)
        server.login(smtp_user, smtp_password)
        server.sendmail(mail_from, [mail_to], message.as_bytes())


def _require_env(name: str) -> str:
    value = os.getenv(name, "").strip()
    if not value:
        raise RuntimeError(f"環境変数 {name} が未設定です")
    return value


def _smtp_configured() -> bool:
    return bool(
        os.getenv("SMTP_USER", "").strip()
        and os.getenv("SMTP_PASSWORD", "").strip()
        and os.getenv("MAIL_TO", "").strip()
    )


def run_digest(
    *,
    send: bool,
    sources_path: Path | None = None,
    use_ai: bool = True,
    publish: bool = True,
) -> dict[str, Any]:
    load_dotenv()
    now = datetime.now(JST)
    sources = load_sources(sources_path or DEFAULT_SOURCES)
    fetched = collect_news(sources)
    ai_messages = enrich_with_ai_summaries(fetched.items, enabled=use_ai)
    fetched.errors.extend(ai_messages)
    subject = build_subject(now, len(fetched.items))
    text_body = render_text_digest(fetched.items, fetched.errors, now)
    html_body = render_html_digest(fetched.items, fetched.errors, now)
    archive_path = save_archive(html_body, text_body, now)

    site_path = ""
    if publish:
        site_index = publish_site()
        site_path = str(site_index)

    sent = False
    if send:
        if not _smtp_configured():
            fetched.errors.append("mail: SMTP設定がないためメール送信をスキップ")
        else:
            send_email(
                subject=subject,
                text_body=text_body,
                html_body=html_body,
                smtp_host=os.getenv("SMTP_HOST", "smtp.gmail.com"),
                smtp_port=int(os.getenv("SMTP_PORT", "587")),
                smtp_user=_require_env("SMTP_USER"),
                smtp_password=_require_env("SMTP_PASSWORD"),
                mail_from=os.getenv("MAIL_FROM", "").strip() or _require_env("SMTP_USER"),
                mail_to=_require_env("MAIL_TO"),
            )
            sent = True

    ai_count = sum(1 for item in fetched.items if item.ai_summary)
    return {
        "subject": subject,
        "item_count": len(fetched.items),
        "error_count": len(fetched.errors),
        "errors": fetched.errors,
        "archive_path": str(archive_path),
        "site_path": site_path,
        "sent": sent,
        "nikkei_count": sum(1 for i in fetched.items if i.category == "nikkei"),
        "ai_summary_count": ai_count,
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="朝刊ニュースダイジェスト")
    parser.add_argument("--send", action="store_true", help="メール送信する（SMTP設定時）")
    parser.add_argument("--no-ai", action="store_true", help="無料リード補足を無効化する")
    parser.add_argument("--no-publish", action="store_true", help="スマホ向けサイト生成をスキップ")
    parser.add_argument("--sources", type=Path, default=DEFAULT_SOURCES, help="sources.yaml のパス")
    return parser


def main() -> None:
    args = build_parser().parse_args()
    result = run_digest(
        send=args.send,
        sources_path=args.sources,
        use_ai=not args.no_ai,
        publish=not args.no_publish,
    )
    print(result["subject"])
    print(
        f"items={result['item_count']} ai={result['ai_summary_count']} "
        f"errors={result['error_count']} sent={result['sent']}"
    )
    print(f"archive={result['archive_path']}")
    if result.get("site_path"):
        print(f"site={result['site_path']}")
    if result["errors"]:
        print("errors:")
        for err in result["errors"]:
            print(f"  - {err}")
    if result["nikkei_count"] == 0:
        raise SystemExit(2)


if __name__ == "__main__":
    main()
