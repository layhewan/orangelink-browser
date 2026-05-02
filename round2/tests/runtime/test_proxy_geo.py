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


def test_proxy_geo_result_can_use_provider_language_hint() -> None:
    from app.runtime.proxy_geo import ProxyGeoResult, parse_ipapi_payload

    result = parse_ipapi_payload(
        b'{"ip":"198.51.100.10","country_code":"BR","timezone":"America/Sao_Paulo","languages":"pt-BR,en"}'
    )

    assert result == ProxyGeoResult(
        timezone="America/Sao_Paulo",
        language="pt-BR",
        query="198.51.100.10",
    )


def test_proxy_geo_result_can_parse_ipwho_payload() -> None:
    from app.runtime.proxy_geo import ProxyGeoResult, parse_ipwho_payload

    result = parse_ipwho_payload(
        b'{"success":true,"ip":"203.0.113.30","country_code":"NL","timezone":{"id":"Europe/Amsterdam"}}'
    )

    assert result == ProxyGeoResult(
        timezone="Europe/Amsterdam",
        language="nl-NL",
        query="203.0.113.30",
    )


def test_proxy_geo_result_can_parse_ipinfo_payload() -> None:
    from app.runtime.proxy_geo import ProxyGeoResult, parse_ipinfo_payload

    result = parse_ipinfo_payload(
        b'{"ip":"203.0.113.40","country":"US","timezone":"America/Los_Angeles"}'
    )

    assert result == ProxyGeoResult(
        timezone="America/Los_Angeles",
        language="en-US",
        query="203.0.113.40",
    )


def test_proxy_geo_probe_tries_next_provider_after_failure(monkeypatch) -> None:
    from app.runtime.config import LaunchConfig
    import app.runtime.proxy_geo as proxy_geo

    calls = []

    def fake_fetch(config, host: str, path: str) -> bytes:
        calls.append(host)
        if host == "ip-api.com":
            # Make first provider fail
            return b'{"status":"fail","message":"reserved range"}'
        if host == "ipapi.co":
            return b'{"timezone":"Europe/Paris","country_code":"FR","country":"France","ip":"198.51.100.20"}'
        return b'{"status":"success","query":"198.51.100.20","countryCode":"FR","timezone":"Europe/Paris"}'

    monkeypatch.setattr(proxy_geo, "_fetch_geo_payload", fake_fetch)

    result = proxy_geo.probe_proxy_geo(
        LaunchConfig(
            name="Proxy",
            proxy_enabled=True,
            proxy_host="127.0.0.1",
            proxy_port=7897,
        )
    )

    assert result is not None
    assert result.timezone == "Europe/Paris"
    assert result.language == "fr-FR"
    # Two-stage probe tries httpbin.org first (×2 retries), then falls back to original providers
    assert calls[:4] == ["httpbin.org", "httpbin.org", "ip-api.com", "ipapi.co"]


def test_proxy_geo_keeps_hong_kong_as_web_visible_locale() -> None:
    from app.runtime.proxy_geo import parse_ip_api_payload

    result = parse_ip_api_payload(
        b'{"status":"success","countryCode":"HK","timezone":"Asia/Hong_Kong","query":"203.0.113.20"}'
    )

    assert result is not None
    assert result.language == "zh-HK"


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


def test_enrich_config_clears_stale_cache_when_proxy_geo_probe_fails() -> None:
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

    # Should clear stale cached values when probe fails with auto-detection
    assert enriched.cached_timezone == ""
    assert enriched.cached_language == ""
