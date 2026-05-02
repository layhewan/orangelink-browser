from __future__ import annotations

import pytest


def test_proxy_mode_returns_none_for_direct_sessions() -> None:
    from app.runtime.config import LaunchConfig
    from app.runtime.proxy_contract import ProxyMode

    config = LaunchConfig(name="Direct")

    assert ProxyMode.from_config(config).chromium_proxy_server is None


@pytest.mark.parametrize(
    ("protocol", "expected"),
    [
        ("http", "http://127.0.0.1:7890"),
        ("https", "https://127.0.0.1:7897"),
        ("socks5", "socks5://127.0.0.1:10808"),
    ],
)
def test_proxy_mode_formats_enabled_proxy_url(protocol: str, expected: str) -> None:
    from app.runtime.config import LaunchConfig
    from app.runtime.proxy_contract import ProxyMode

    host, port_text = expected.split("://", 1)[1].rsplit(":", 1)
    config = LaunchConfig(
        name="Proxy",
        proxy_enabled=True,
        proxy_protocol=protocol,
        proxy_host=host,
        proxy_port=int(port_text),
    )

    assert ProxyMode.from_config(config).chromium_proxy_server == expected


def test_proxy_mode_exposes_reuse_key_without_credentials() -> None:
    from app.runtime.config import LaunchConfig
    from app.runtime.proxy_contract import ProxyMode

    config = LaunchConfig(
        name="Proxy",
        proxy_enabled=True,
        proxy_protocol="http",
        proxy_host="user:secret@127.0.0.1",
        proxy_port=7890,
    )

    proxy_mode = ProxyMode.from_config(config)

    assert proxy_mode.reuse_key == "http://127.0.0.1:7890"
    assert "secret" not in proxy_mode.reuse_key
