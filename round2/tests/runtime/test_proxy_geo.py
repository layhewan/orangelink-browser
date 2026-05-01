from __future__ import annotations


def test_proxy_geo_result_maps_ip_api_timezone_and_language() -> None:
    from app.runtime.proxy_geo import ProxyGeoResult, parse_ip_api_payload

    result = parse_ip_api_payload(
        b'{"status":"success","countryCode":"JP","timezone":"Asia/Tokyo","query":"203.0.113.10"}'
    )

    assert result == ProxyGeoResult(
        timezone="Asia/Tokyo",
        language="ja-JP",
        query="203.0.113.10",
    )


def test_proxy_geo_result_rejects_failed_payload() -> None:
    from app.runtime.proxy_geo import parse_ip_api_payload

    assert parse_ip_api_payload(b'{"status":"fail","message":"reserved range"}') is None


def test_enrich_config_with_proxy_geo_cache_keeps_manual_timezone() -> None:
    from app.runtime.config import LaunchConfig
    from app.runtime.proxy_geo import ProxyGeoResult, enrich_config_with_proxy_geo

    config = LaunchConfig(
        name="Manual",
        proxy_enabled=True,
        proxy_host="127.0.0.1",
        proxy_port=7897,
        automatic_timezone=False,
        manual_timezone="America/New_York",
    )

    enriched = enrich_config_with_proxy_geo(
        config,
        probe=lambda _: ProxyGeoResult(timezone="Asia/Tokyo", language="ja-JP"),
    )

    assert enriched.cached_timezone == ""
    assert enriched.manual_timezone == "America/New_York"


def test_enrich_config_with_proxy_geo_cache_sets_auto_values() -> None:
    from app.runtime.config import LaunchConfig
    from app.runtime.proxy_geo import ProxyGeoResult, enrich_config_with_proxy_geo

    config = LaunchConfig(
        name="Auto",
        proxy_enabled=True,
        proxy_host="127.0.0.1",
        proxy_port=7897,
    )

    enriched = enrich_config_with_proxy_geo(
        config,
        probe=lambda _: ProxyGeoResult(timezone="Asia/Tokyo", language="ja-JP"),
    )

    assert enriched.cached_timezone == "Asia/Tokyo"
    assert enriched.cached_language == "ja-JP"


def test_enrich_config_clears_stale_auto_cache_when_proxy_geo_probe_fails() -> None:
    from app.runtime.config import LaunchConfig
    from app.runtime.proxy_geo import enrich_config_with_proxy_geo

    config = LaunchConfig(
        name="Auto",
        proxy_enabled=True,
        proxy_host="127.0.0.1",
        proxy_port=7897,
        cached_timezone="Asia/Shanghai",
        cached_language="zh-CN",
    )

    enriched = enrich_config_with_proxy_geo(config, probe=lambda _: None)

    assert enriched.cached_timezone == ""
    assert enriched.cached_language == ""
