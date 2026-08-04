from pathlib import Path

PAGE = Path("astrbot_plugin_anime_tracking/pages/anime-admin")


def test_plugin_page_is_discoverable_and_self_contained() -> None:
    html = (PAGE / "index.html").read_text()
    script = (PAGE / "app.js").read_text()
    styles = (PAGE / "styles.css").read_text()

    assert 'src="./app.js"' in html
    assert 'href="./styles.css"' in html
    assert "AstrBotPluginPage" in script
    assert "apiGet" in script
    assert "apiPost" in script
    assert "http://" not in html + script + styles
    assert "https://" not in html + script + styles


def test_page_covers_all_operations_sections_and_mobile() -> None:
    html = (PAGE / "index.html").read_text()
    script = (PAGE / "app.js").read_text()
    styles = (PAGE / "styles.css").read_text()

    for label in ("总览", "番剧目录", "群设置", "订阅", "映射", "通知", "数据源"):
        assert label in html
    assert "560px" in styles
    assert "prefers-reduced-motion" in styles
    assert 'id="napcat-banner"' in html
    assert 'id="napcat-history"' in html
    assert "docker compose restart napcat" in html
    assert "30_000" in script
    assert "qq_offline" in script
    assert ".session-banner" in styles
    assert 'id="catalog-content"' in html
    assert 'apiGet("catalog"' in script
    assert "catalog_animes" in script
    assert "future_exact_animes" in script
    assert "future_unmapped_anilist_animes" in script
    assert "future_mapped_without_exact_animes" in script
