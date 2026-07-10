"""スマホ向け公開サイト（GitHub Pages用）を生成する。"""

from __future__ import annotations

import html
import re
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parent.parent
ARCHIVE_DIR = ROOT / "data" / "archive"
SITE_DIR = ROOT / "site"
JST = ZoneInfo("Asia/Tokyo")


def _weekday_ja(dt: datetime) -> str:
    return "月火水木金土日"[dt.weekday()]


def list_archive_days(archive_dir: Path = ARCHIVE_DIR) -> list[str]:
    days: list[str] = []
    if not archive_dir.exists():
        return days
    for path in sorted(archive_dir.glob("????-??-??.html"), reverse=True):
        days.append(path.stem)
    return days


def _extract_body_inner(html_text: str) -> str:
    match = re.search(r"<body[^>]*>(.*)</body>", html_text, flags=re.I | re.S)
    if not match:
        return html_text
    return match.group(1).strip()


def wrap_mobile_page(
    *,
    title: str,
    body_inner: str,
    nav_html: str = "",
    footer_html: str = "",
) -> str:
    return f"""<!DOCTYPE html>
<html lang="ja">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
  <meta name="apple-mobile-web-app-capable" content="yes">
  <meta name="mobile-web-app-capable" content="yes">
  <meta name="theme-color" content="#0b57d0">
  <meta http-equiv="Cache-Control" content="no-cache, no-store, must-revalidate">
  <title>{html.escape(title)}</title>
  <style>
    :root {{
      color-scheme: light;
      --bg: #f4f6f8;
      --card: #ffffff;
      --text: #111827;
      --muted: #6b7280;
      --line: #e5e7eb;
      --accent: #0b57d0;
    }}
    * {{ box-sizing: border-box; }}
    body {{
      margin: 0;
      font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", "Hiragino Sans", sans-serif;
      background: var(--bg);
      color: var(--text);
      line-height: 1.5;
    }}
    .wrap {{
      max-width: 720px;
      margin: 0 auto;
      padding: 12px 12px 40px;
    }}
    .card {{
      background: var(--card);
      border-radius: 14px;
      padding: 14px 14px 22px;
      box-shadow: 0 1px 2px rgba(0,0,0,.04);
    }}
    .nav {{
      display: flex;
      gap: 8px;
      flex-wrap: wrap;
      margin: 0 0 12px;
    }}
    .nav a {{
      display: inline-block;
      padding: 10px 12px;
      border-radius: 999px;
      background: #eef3ff;
      color: var(--accent);
      text-decoration: none;
      font-size: 14px;
      font-weight: 600;
    }}
    a {{
      -webkit-tap-highlight-color: transparent;
    }}
    h1 {{ font-size: 1.35rem; margin: 0 0 8px; }}
    h2 {{ font-size: 1.1rem; }}
    ol {{ padding-left: 1.1rem; }}
    li a {{
      min-height: 44px;
      display: inline-flex !important;
      align-items: center;
    }}
    .muted {{ color: var(--muted); font-size: 14px; }}
    .footer {{
      margin-top: 12px;
      color: var(--muted);
      font-size: 13px;
      text-align: center;
    }}
    .history a {{
      display: block;
      padding: 14px 0;
      border-bottom: 1px solid var(--line);
      color: var(--text);
      text-decoration: none;
      font-size: 16px;
    }}
  </style>
</head>
<body>
  <div class="wrap">
    {nav_html}
    <div class="card">
      {body_inner}
    </div>
    {footer_html}
  </div>
</body>
</html>
"""


def build_nav(*, current: str = "today") -> str:
    links = [
        ("today", "今日の朝刊", "index.html"),
        ("history", "履歴", "history.html"),
    ]
    parts = []
    for key, label, href in links:
        if key == current:
            parts.append(
                f"<a href='{href}' style='background:#0b57d0;color:#fff'>{html.escape(label)}</a>"
            )
        else:
            parts.append(f"<a href='{href}'>{html.escape(label)}</a>")
    return f"<nav class='nav'>{''.join(parts)}</nav>"


def publish_site(
    *,
    archive_dir: Path = ARCHIVE_DIR,
    site_dir: Path = SITE_DIR,
    keep_days: int = 30,
) -> Path:
    """archive の最新HTMLをスマホ向けサイトとして書き出す。"""
    site_dir.mkdir(parents=True, exist_ok=True)
    days = list_archive_days(archive_dir)[:keep_days]
    if not days:
        raise FileNotFoundError("公開できる朝刊アーカイブがありません")

    latest = days[0]
    published_at = datetime.now(JST).strftime("%Y-%m-%d %H:%M JST")
    footer_html = (
        "<p class='footer'>毎日 6:30 JST に自動更新"
        f" / 最終反映: {html.escape(published_at)}</p>"
    )

    latest_src = archive_dir / f"{latest}.html"
    latest_body = _extract_body_inner(latest_src.read_text(encoding="utf-8"))
    # 元HTMLの外側ラッパを外して中身だけ使う
    latest_body = re.sub(
        r'^<div style="max-width:720px;[^"]*">|</div>\s*$',
        "",
        latest_body,
        count=2,
        flags=re.S,
    ).strip()

    index_html = wrap_mobile_page(
        title=f"朝刊 {latest}",
        body_inner=latest_body,
        nav_html=build_nav(current="today"),
        footer_html=footer_html,
    )
    (site_dir / "index.html").write_text(index_html, encoding="utf-8")

    for day in days:
        src = archive_dir / f"{day}.html"
        body = _extract_body_inner(src.read_text(encoding="utf-8"))
        body = re.sub(
            r'^<div style="max-width:720px;[^"]*">|</div>\s*$',
            "",
            body,
            count=2,
            flags=re.S,
        ).strip()
        page = wrap_mobile_page(
            title=f"朝刊 {day}",
            body_inner=body,
            nav_html=build_nav(current="today" if day == latest else "history"),
            footer_html=footer_html,
        )
        (site_dir / f"{day}.html").write_text(page, encoding="utf-8")

    history_items = []
    for day in days:
        dt = datetime.strptime(day, "%Y-%m-%d").replace(tzinfo=JST)
        label = f"{day}（{_weekday_ja(dt)}）"
        history_items.append(f"<a href='{day}.html'>{html.escape(label)}</a>")
    history_body = (
        f"<h1>朝刊履歴</h1>"
        f"<p class='muted'>直近 {len(days)} 日分（毎日 6:30 JST 自動更新）</p>"
        f"<div class='history'>{''.join(history_items)}</div>"
    )
    (site_dir / "history.html").write_text(
        wrap_mobile_page(
            title="朝刊履歴",
            body_inner=history_body,
            nav_html=build_nav(current="history"),
            footer_html=footer_html,
        ),
        encoding="utf-8",
    )

    # GitHub Pages が Jekyll 処理しないようにする
    (site_dir / ".nojekyll").write_text("", encoding="utf-8")

    # 誤ったパスでも朝刊へ戻せるようにする（スマホの打ち間違い対策）
    (site_dir / "404.html").write_text(
        """<!DOCTYPE html>
<html lang="ja">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <meta http-equiv="refresh" content="0; url=./index.html">
  <title>朝刊へ移動</title>
</head>
<body>
  <p>ページが見つかりません。<a href="./index.html">今日の朝刊</a>へ戻る</p>
</body>
</html>
""",
        encoding="utf-8",
    )
    return site_dir / "index.html"
