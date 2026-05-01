from __future__ import annotations

import json
import socket
from dataclasses import dataclass, replace
from typing import Callable

from app.runtime.config import LaunchConfig


IP_API_HOST = "ip-api.com"
IP_API_PATH = "/json/?fields=status,message,countryCode,timezone,query"


@dataclass(frozen=True)
class ProxyGeoResult:
    timezone: str
    language: str
    query: str = ""


def enrich_config_with_proxy_geo(
    config: LaunchConfig,
    *,
    probe: Callable[[LaunchConfig], ProxyGeoResult | None] | None = None,
) -> LaunchConfig:
    if not config.proxy_enabled:
        return replace(
            config,
            cached_language="" if config.automatic_language else config.cached_language,
            cached_timezone="" if config.automatic_timezone else config.cached_timezone,
        )
    if not config.automatic_language and not config.automatic_timezone:
        return config

    result = (probe or probe_proxy_geo)(config)
    if result is None:
        return replace(
            config,
            cached_language="" if config.automatic_language else config.cached_language,
            cached_timezone="" if config.automatic_timezone else config.cached_timezone,
        )

    return replace(
        config,
        cached_language=result.language if config.automatic_language else config.cached_language,
        cached_timezone=result.timezone if config.automatic_timezone else config.cached_timezone,
    )


def probe_proxy_geo(config: LaunchConfig) -> ProxyGeoResult | None:
    try:
        if config.proxy_protocol == "socks5":
            payload = _fetch_via_socks5(config)
        else:
            payload = _fetch_via_http_proxy(config)
    except OSError:
        return None
    return parse_ip_api_payload(payload)


def parse_ip_api_payload(payload: bytes) -> ProxyGeoResult | None:
    try:
        data = json.loads(payload.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return None
    if data.get("status") != "success":
        return None
    timezone = str(data.get("timezone") or "")
    if not timezone:
        return None
    return ProxyGeoResult(
        timezone=timezone,
        language=_language_for_country(str(data.get("countryCode") or "")),
        query=str(data.get("query") or ""),
    )


def _fetch_via_http_proxy(config: LaunchConfig) -> bytes:
    with socket.create_connection((config.proxy_host, int(config.proxy_port or 0)), timeout=5) as sock:
        sock.settimeout(5)
        sock.sendall(
            (
                f"GET http://{IP_API_HOST}{IP_API_PATH} HTTP/1.1\r\n"
                f"Host: {IP_API_HOST}\r\n"
                "Connection: close\r\n\r\n"
            ).encode("ascii")
        )
        return _read_http_body(sock)


def _fetch_via_socks5(config: LaunchConfig) -> bytes:
    with socket.create_connection((config.proxy_host, int(config.proxy_port or 0)), timeout=5) as sock:
        sock.settimeout(5)
        _socks5_connect(sock, IP_API_HOST, 80)
        sock.sendall(
            (
                f"GET {IP_API_PATH} HTTP/1.1\r\n"
                f"Host: {IP_API_HOST}\r\n"
                "Connection: close\r\n\r\n"
            ).encode("ascii")
        )
        return _read_http_body(sock)


def _socks5_connect(sock: socket.socket, host: str, port: int) -> None:
    sock.sendall(bytes([0x05, 0x01, 0x00]))
    if _recv_exact(sock, 2) != bytes([0x05, 0x00]):
        raise OSError("socks5 no-auth handshake failed")

    host_bytes = host.encode("ascii")
    request = bytes([0x05, 0x01, 0x00, 0x03, len(host_bytes)])
    request += host_bytes
    request += port.to_bytes(2, "big")
    sock.sendall(request)
    response = _recv_exact(sock, 4)
    if len(response) < 4 or response[0] != 0x05 or response[1] != 0x00:
        raise OSError("socks5 connect failed")

    if response[3] == 0x01:
        _recv_exact(sock, 6)
    elif response[3] == 0x03:
        length = _recv_exact(sock, 1)
        if not length:
            raise OSError("socks5 response missing domain length")
        _recv_exact(sock, length[0] + 2)
    elif response[3] == 0x04:
        _recv_exact(sock, 18)
    else:
        raise OSError("socks5 response address type is invalid")


def _read_http_body(sock: socket.socket) -> bytes:
    chunks: list[bytes] = []
    while True:
        chunk = sock.recv(4096)
        if not chunk:
            break
        chunks.append(chunk)
    response = b"".join(chunks)
    _, _, body = response.partition(b"\r\n\r\n")
    return body


def _recv_exact(sock: socket.socket, size: int) -> bytes:
    data = bytearray()
    while len(data) < size:
        chunk = sock.recv(size - len(data))
        if not chunk:
            break
        data.extend(chunk)
    return bytes(data)


def _language_for_country(country_code: str) -> str:
    return {
        "CN": "zh-CN",
        "HK": "zh-HK",
        "TW": "zh-TW",
        "US": "en-US",
        "GB": "en-GB",
        "JP": "ja-JP",
        "KR": "ko-KR",
        "DE": "de-DE",
        "FR": "fr-FR",
        "ES": "es-ES",
        "RU": "ru-RU",
    }.get(country_code.upper(), "en-US")
