from __future__ import annotations

from dataclasses import dataclass

from app.runtime.config import LaunchConfig, ValidationError


@dataclass(frozen=True)
class ConfigValidationResult:
    ok: bool
    config: LaunchConfig | None = None
    error: str = ""


@dataclass(frozen=True)
class LaunchConfigForm:
    name: str
    proxy_enabled: bool = False
    proxy_protocol: str = "http"
    proxy_host: str = ""
    proxy_port: int | None = None
    start_page: str = ""
    automatic_language: bool = True
    manual_language: str = "en-US"
    automatic_timezone: bool = True
    manual_timezone: str = "UTC"
    os_fingerprint: str = "windows"
    extension_support: bool = True

    def validate(self) -> ConfigValidationResult:
        try:
            return ConfigValidationResult(ok=True, config=self.to_launch_config())
        except ValidationError as exc:
            return ConfigValidationResult(ok=False, error=str(exc))

    def to_launch_config(self) -> LaunchConfig:
        return LaunchConfig(
            name=self.name,
            proxy_enabled=self.proxy_enabled,
            proxy_protocol=self.proxy_protocol,
            proxy_host=self.proxy_host,
            proxy_port=self.proxy_port,
            start_page=self.start_page,
            automatic_language=self.automatic_language,
            manual_language=self.manual_language,
            automatic_timezone=self.automatic_timezone,
            manual_timezone=self.manual_timezone,
            os_fingerprint=self.os_fingerprint,
            extension_support=self.extension_support,
        )
