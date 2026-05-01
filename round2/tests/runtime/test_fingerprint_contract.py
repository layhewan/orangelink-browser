from __future__ import annotations


class FakeCdp:
    def __init__(self) -> None:
        self.commands: list[tuple[str | None, str, dict]] = []

    def send_command(self, method: str, params: dict, *, session_id: str | None = None) -> None:
        self.commands.append((session_id, method, params))


def test_manual_language_and_timezone_build_profile() -> None:
    from app.runtime.config import LaunchConfig
    from app.runtime.engine_version import BrowserEngineVersion
    from app.runtime.fingerprint import build_fingerprint_profile

    profile = build_fingerprint_profile(
        LaunchConfig(
            name="Manual",
            automatic_language=False,
            manual_language="zh-CN",
            automatic_timezone=False,
            manual_timezone="Asia/Shanghai",
        ),
        actual_engine=BrowserEngineVersion(family="Chromium", major=123, full_version="123.0.0.0"),
    )

    assert profile.language == "zh-CN"
    assert profile.accept_language == "zh-CN,zh;q=0.9"
    assert profile.timezone == "Asia/Shanghai"


def test_automatic_language_and_timezone_can_use_geo_cache() -> None:
    from app.runtime.config import LaunchConfig
    from app.runtime.engine_version import BrowserEngineVersion
    from app.runtime.fingerprint import build_fingerprint_profile

    profile = build_fingerprint_profile(
        LaunchConfig(name="Auto"),
        actual_engine=BrowserEngineVersion(family="Chromium", major=123, full_version="123.0.0.0"),
        proxy_geo_cache={"language": "de-DE", "timezone": "Europe/Berlin"},
    )

    assert profile.language == "de-DE"
    assert profile.timezone == "Europe/Berlin"


def test_automatic_language_and_timezone_can_use_config_cache() -> None:
    from app.runtime.config import LaunchConfig
    from app.runtime.engine_version import BrowserEngineVersion
    from app.runtime.fingerprint import build_fingerprint_profile

    profile = build_fingerprint_profile(
        LaunchConfig(
            name="Cached",
            cached_language="ja-JP",
            cached_timezone="Asia/Tokyo",
        ),
        actual_engine=BrowserEngineVersion(family="Chromium", major=123, full_version="123.0.0.0"),
    )

    assert profile.language == "ja-JP"
    assert profile.timezone == "Asia/Tokyo"


def test_fingerprint_overrides_are_applied_through_cdp() -> None:
    from app.runtime.config import LaunchConfig
    from app.runtime.engine_version import BrowserEngineVersion
    from app.runtime.fingerprint import apply_fingerprint_overrides, build_fingerprint_profile

    cdp = FakeCdp()
    profile = build_fingerprint_profile(
        LaunchConfig(
            name="Manual",
            automatic_language=False,
            manual_language="en-US",
            automatic_timezone=False,
            manual_timezone="America/New_York",
        ),
        actual_engine=BrowserEngineVersion(family="Chromium", major=123, full_version="123.0.0.0"),
    )

    apply_fingerprint_overrides(cdp, "session-1", profile)

    methods = [method for _, method, _ in cdp.commands]
    assert "Network.setUserAgentOverride" in methods
    assert "Emulation.setTimezoneOverride" in methods
    assert "Page.addScriptToEvaluateOnNewDocument" in methods
    ua_params = next(params for _, method, params in cdp.commands if method == "Network.setUserAgentOverride")
    assert ua_params["acceptLanguage"] == "en-US,en;q=0.9"
    assert ua_params["userAgentMetadata"]["platform"] == "Windows"
    timezone_params = next(params for _, method, params in cdp.commands if method == "Emulation.setTimezoneOverride")
    assert timezone_params == {"timezoneId": "America/New_York"}


def test_os_override_changes_user_agent_platform_consistently() -> None:
    from app.runtime.config import LaunchConfig
    from app.runtime.engine_version import BrowserEngineVersion
    from app.runtime.fingerprint import build_fingerprint_profile

    profile = build_fingerprint_profile(
        LaunchConfig(name="Mac", os_fingerprint="macos"),
        actual_engine=BrowserEngineVersion(family="Chromium", major=123, full_version="123.0.0.0"),
    )

    assert profile.platform == "macOS"
    assert "Mac OS X" in profile.user_agent
    assert profile.user_agent_metadata["platform"] == "macOS"
