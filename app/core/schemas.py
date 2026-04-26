from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, field_validator

DEFAULT_PROXY_PORT = 7897


class ProxyCredentials(BaseModel):
    username: str
    password: str


class ProxyConfigContract(BaseModel):
    model_config = ConfigDict(extra="ignore")

    proxy_host: str = "127.0.0.1"
    proxy_port: int = DEFAULT_PROXY_PORT
    scheme: Literal["http", "https", "socks5"] = "http"
    credentials: ProxyCredentials | None = None

    @field_validator("proxy_host")
    @classmethod
    def validate_proxy_host(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("proxy_host must not be empty")
        return stripped

    @field_validator("proxy_port")
    @classmethod
    def validate_proxy_port(cls, value: int) -> int:
        if not 1 <= value <= 65535:
            raise ValueError("proxy_port must be in range 1..65535")
        return value
