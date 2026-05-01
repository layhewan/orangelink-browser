from __future__ import annotations

import re
import sys
from dataclasses import dataclass
from pathlib import Path


ALLOWED_PROXY_PROTOCOLS = frozenset({"http", "https", "socks5"})
DEFAULT_START_PAGE = "orangelink://homepage"
LANGUAGE_RE = re.compile(r"^[a-z]{2}(?:-[A-Z]{2})?$")


class ValidationError(ValueError):
    """Raised when a launch configuration cannot be used."""


@dataclass(frozen=True)
class LaunchConfig:
    name: str
    proxy_enabled: bool = False
    proxy_protocol: str = "http"
    proxy_host: str = ""
    proxy_port: int | None = None
    start_page: str = DEFAULT_START_PAGE
    automatic_language: bool = True
    manual_language: str = "en-US"
    automatic_timezone: bool = True
    manual_timezone: str = "UTC"
    cached_language: str = ""
    cached_timezone: str = ""
    os_fingerprint: str = "windows"
    extension_support: bool = True
    proxy_reuse_allowed: bool = False

    def __post_init__(self) -> None:
        normalized_name = self.name.strip()
        if not normalized_name:
            raise ValidationError("配置名称不能为空")
        object.__setattr__(self, "name", normalized_name)

        protocol = self.proxy_protocol.strip().lower()
        if protocol not in ALLOWED_PROXY_PROTOCOLS:
            raise ValidationError("代理协议必须是 http、https 或 socks5")
        object.__setattr__(self, "proxy_protocol", protocol)

        host = self.proxy_host.strip()
        object.__setattr__(self, "proxy_host", host)

        if self.proxy_enabled:
            if not host:
                raise ValidationError("代理主机不能为空")
            if self.proxy_port is None or not 1 <= int(self.proxy_port) <= 65535:
                raise ValidationError("代理端口必须在 1 到 65535 之间")

        if not self.automatic_language and not LANGUAGE_RE.fullmatch(self.manual_language):
            raise ValidationError("手动语言必须类似 en 或 en-US")

        if not self.automatic_timezone and not self.manual_timezone.strip():
            raise ValidationError("手动时区不能为空")

        if not self.start_page.strip():
            object.__setattr__(self, "start_page", DEFAULT_START_PAGE)


@dataclass(frozen=True)
class PortablePaths:
    base: Path
    data: Path
    configs: Path
    profiles: Path
    logs: Path
    reports: Path
    homepage: Path

    @property
    def required_directories(self) -> tuple[Path, ...]:
        return (
            self.data,
            self.configs,
            self.profiles,
            self.logs,
            self.reports,
            self.homepage,
        )


def resolve_portable_paths(base: Path | None = None, create: bool = False) -> PortablePaths:
    resolved_base = (base if base is not None else _default_base()).resolve()
    data = resolved_base / "data"
    paths = PortablePaths(
        base=resolved_base,
        data=data,
        configs=data / "configs",
        profiles=data / "profiles",
        logs=data / "logs",
        reports=data / "reports",
        homepage=data / "homepage",
    )

    if create:
        for directory in paths.required_directories:
            directory.mkdir(parents=True, exist_ok=True)

    return paths


def _default_base() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parents[2]
