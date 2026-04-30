from __future__ import annotations

from dataclasses import dataclass

from app.runtime.config import LaunchConfig


@dataclass(frozen=True)
class ProxyMode:
    chromium_proxy_server: str | None
    reuse_key: str | None

    @classmethod
    def from_config(cls, config: LaunchConfig) -> "ProxyMode":
        if not config.proxy_enabled:
            return cls(chromium_proxy_server=None, reuse_key=None)

        host = _strip_credentials(config.proxy_host)
        proxy_url = f"{config.proxy_protocol}://{host}:{config.proxy_port}"
        return cls(chromium_proxy_server=proxy_url, reuse_key=proxy_url)


def _strip_credentials(host: str) -> str:
    if "@" not in host:
        return host
    return host.rsplit("@", 1)[1]
