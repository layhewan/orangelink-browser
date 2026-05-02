from __future__ import annotations

import shutil
from pathlib import Path


def test_homepage_renders_public_ip_success_and_environment_summary() -> None:
    from app.homepage.homepage import HomepageContext, render_homepage_html

    html = render_homepage_html(
        HomepageContext(
            session_id="session-1",
            public_ip="203.0.113.10",
            user_agent="Mozilla/5.0 Chrome/123.0.0.0",
            platform="Windows",
            languages=["zh-CN", "zh"],
            timezone="Asia/Shanghai",
            screen="1280x800",
            cpu=8,
            memory=8,
            webrtc_policy="disable_non_proxied_udp",
            engine_version="Chromium 123.0.0.0",
        )
    )

    for expected in (
        "203.0.113.10",
        "Mozilla/5.0 Chrome/123.0.0.0",
        "Windows",
        "zh-CN, zh",
        "Asia/Shanghai",
        "1280x800",
        "8 cores",
        "8 GB",
        "disable_non_proxied_udp",
        "Chromium 123.0.0.0",
    ):
        assert expected in html


def test_homepage_renders_public_ip_failure_text() -> None:
    from app.homepage.homepage import HomepageContext, render_homepage_html

    html = render_homepage_html(
        HomepageContext(
            session_id="session-1",
            public_ip_error="IP lookup unavailable",
        )
    )

    assert "IP lookup unavailable" in html
    assert "Public IP unavailable" in html


def test_homepage_template_is_responsive_without_fixed_width_layout() -> None:
    template = Path("app/homepage/static/homepage.html").read_text(encoding="utf-8")

    assert '<meta name="viewport" content="width=device-width, initial-scale=1">' in template
    assert "width: 980px" not in template
    assert "width: 1200px" not in template
    assert "grid-template-columns: repeat(auto-fit" in template


def test_write_homepage_creates_session_file_under_portable_homepage_dir() -> None:
    from app.homepage.homepage import HomepageContext, write_homepage
    from app.runtime.config import resolve_portable_paths

    base = Path(__file__).resolve().parent / "_tmp_homepage_base"
    shutil.rmtree(base, ignore_errors=True)
    paths = resolve_portable_paths(base=base, create=True)

    try:
        homepage = write_homepage(paths, HomepageContext(session_id="abc", public_ip="203.0.113.10"))

        assert homepage == paths.homepage / "session-abc.html"
        assert homepage.is_file()
        assert "203.0.113.10" in homepage.read_text(encoding="utf-8")
    finally:
        shutil.rmtree(base, ignore_errors=True)


def test_chromium_args_resolve_homepage_marker_to_file_uri() -> None:
    from app.runtime.chromium_launcher import build_chromium_args
    from app.runtime.config import DEFAULT_START_PAGE, LaunchConfig

    homepage_file = Path(__file__).resolve()
    args = build_chromium_args(
        config=LaunchConfig(name="Homepage"),
        chrome_executable=Path("runtime/chromium/chrome.exe"),
        profile_dir=Path("data/profiles/session-1"),
        remote_debugging_port=9222,
        relay_port=None,
        start_url=DEFAULT_START_PAGE,
        homepage_file=homepage_file,
    )

    assert homepage_file.as_uri() in args
