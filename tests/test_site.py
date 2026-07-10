from __future__ import annotations

from pathlib import Path

from morning_news.site import publish_site


def test_publish_site_creates_index_and_history(tmp_path: Path) -> None:
    archive = tmp_path / "archive"
    archive.mkdir()
    (archive / "2099-01-02.html").write_text(
        "<html><body><h1>test digest</h1></body></html>",
        encoding="utf-8",
    )
    site_dir = tmp_path / "site"

    index = publish_site(archive_dir=archive, site_dir=site_dir)
    assert index.exists()
    html = index.read_text(encoding="utf-8")
    assert "viewport" in html
    assert "今日の朝刊" in html
    assert "2099-01-02" in html
    assert "test digest" in html
    assert "毎日 6:30 JST に自動更新" in html
    assert "最終反映:" in html
    assert (site_dir / "history.html").exists()
    assert (site_dir / "2099-01-02.html").exists()
    assert (site_dir / ".nojekyll").exists()
    assert (site_dir / "404.html").exists()
