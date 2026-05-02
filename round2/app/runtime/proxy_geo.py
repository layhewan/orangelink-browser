from __future__ import annotations

import json
import socket
from dataclasses import dataclass, replace
from typing import Callable

from app.runtime.config import LaunchConfig, normalize_language_tag


GEO_PROVIDERS = (
    ("ip-api.com", "/json/?fields=status,message,countryCode,timezone,query", "ip_api"),
    ("ipapi.co", "/json/", "ipapi"),
    ("ipwho.is", "/", "ipwho"),
    ("ipinfo.io", "/json", "ipinfo"),
)

GEO_RETRIES = 2

# Paths for IP-specific geo lookups (direct, no proxy)
GEO_IP_PATHS = (
    ("ip-api.com", "/json/{ip}?fields=status,message,countryCode,timezone,query", "ip_api"),
    ("ipwho.is", "/{ip}", "ipwho"),
    ("ipinfo.io", "/{ip}/json", "ipinfo"),
)


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
    parsers = {
        "ip_api": parse_ip_api_payload,
        "ipapi": parse_ipapi_payload,
        "ipwho": parse_ipwho_payload,
        "ipinfo": parse_ipinfo_payload,
    }

    # Two-stage probe: get egress IP through proxy, then look up IP directly.
    # This avoids Clash domain-based routing rules that may send geo providers
    # through a different path (e.g., Cloudflare) than actual browser traffic.
    egress_ip = _fetch_egress_ip_via_proxy(config)
    if egress_ip:
        for host, path_template, parser_name in GEO_IP_PATHS:
            path = path_template.replace("{ip}", egress_ip)
            try:
                payload = _fetch_direct(host, path)
            except OSError:
                continue
            result = parsers[parser_name](payload)
            if result is not None:
                result = ProxyGeoResult(
                    timezone=result.timezone,
                    language=result.language,
                    query=egress_ip,
                )
                return result

    # Fallback: original proxy-based probe
    for attempt in range(GEO_RETRIES):
        for host, path, parser_name in GEO_PROVIDERS:
            try:
                payload = _fetch_geo_payload(config, host, path)
            except OSError:
                continue
            result = parsers[parser_name](payload)
            if result is not None:
                return result
    return None


def _fetch_egress_ip_via_proxy(config: LaunchConfig) -> str:
    """Get the proxy's real egress IP via httpbin.org (default Clash route)."""
    for _ in range(2):
        try:
            payload = _fetch_geo_payload(config, "httpbin.org", "/ip")
        except OSError:
            continue
        if not payload:
            continue
        try:
            data = json.loads(payload.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            continue
        ip = str(data.get("origin") or "")
        if ip:
            return ip
    return ""


def _fetch_direct(host: str, path: str) -> bytes:
    """Fetch from a geo provider directly (no proxy), following redirects."""
    import urllib.request

    proxy_handler = urllib.request.ProxyHandler({})
    opener = urllib.request.build_opener(proxy_handler)
    # Try HTTPS first (providers commonly redirect HTTP to HTTPS)
    for scheme in ("https", "http"):
        try:
            url = f"{scheme}://{host}{path}"
            with opener.open(url, timeout=10) as resp:
                return resp.read()
        except Exception:
            continue
    raise OSError(f"Failed to direct-fetch {host}{path}")


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


def parse_ipapi_payload(payload: bytes) -> ProxyGeoResult | None:
    try:
        data = json.loads(payload.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return None
    if data.get("error") is True:
        return None
    timezone = str(data.get("timezone") or "")
    country_code = str(data.get("country_code") or data.get("country") or "")
    if not timezone:
        return None
    return ProxyGeoResult(
        timezone=timezone,
        language=_language_from_provider_hint(data) or _language_for_country(country_code),
        query=str(data.get("ip") or ""),
    )


def parse_ipwho_payload(payload: bytes) -> ProxyGeoResult | None:
    try:
        data = json.loads(payload.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return None
    if data.get("success") is False:
        return None
    timezone_data = data.get("timezone")
    timezone = ""
    if isinstance(timezone_data, dict):
        timezone = str(timezone_data.get("id") or "")
    elif timezone_data:
        timezone = str(timezone_data)
    if not timezone:
        return None
    country_code = str(data.get("country_code") or "")
    return ProxyGeoResult(
        timezone=timezone,
        language=_language_from_provider_hint(data) or _language_for_country(country_code),
        query=str(data.get("ip") or ""),
    )


def _fetch_geo_payload(config: LaunchConfig, host: str, path: str) -> bytes:
    if config.proxy_protocol == "socks5":
        return _fetch_via_socks5(config, host, path)
    if config.proxy_protocol == "https":
        return _fetch_via_https_connect(config, host, path)
    return _fetch_via_http_proxy(config, host, path)


def _fetch_via_http_proxy(config: LaunchConfig, host: str, path: str) -> bytes:
    with socket.create_connection((config.proxy_host, int(config.proxy_port or 0)), timeout=5) as sock:
        sock.settimeout(5)
        sock.sendall(
            (
                f"GET http://{host}{path} HTTP/1.1\r\n"
                f"Host: {host}\r\n"
                "Connection: close\r\n\r\n"
            ).encode("ascii")
        )
        return _read_http_response(sock)


def _fetch_via_socks5(config: LaunchConfig, host: str, path: str) -> bytes:
    with socket.create_connection((config.proxy_host, int(config.proxy_port or 0)), timeout=5) as sock:
        sock.settimeout(5)
        _socks5_connect(sock, host, 80)
        sock.sendall(
            (
                f"GET {path} HTTP/1.1\r\n"
                f"Host: {host}\r\n"
                "Connection: close\r\n\r\n"
            ).encode("ascii")
        )
        return _read_http_response(sock)


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


def _fetch_via_https_connect(config: LaunchConfig, host: str, path: str) -> bytes:
    with socket.create_connection((config.proxy_host, int(config.proxy_port or 0)), timeout=5) as sock:
        sock.settimeout(5)
        connect_header = (
            f"CONNECT {host}:80 HTTP/1.1\r\n"
            f"Host: {host}:80\r\n\r\n"
        ).encode("ascii")
        sock.sendall(connect_header)
        # Read CONNECT response header (ends with \r\n\r\n)
        connect_response = bytearray()
        while not connect_response.endswith(b"\r\n\r\n"):
            chunk = sock.recv(1)
            if not chunk:
                raise OSError("CONNECT response truncated")
            connect_response.extend(chunk)
        status_line = connect_response.split(b"\r\n", 1)[0]
        if b"200" not in status_line:
            raise OSError(f"CONNECT failed: {status_line.decode('ascii', errors='replace')}")
        # Tunnel established; send GET with relative path
        sock.sendall(
            (
                f"GET {path} HTTP/1.1\r\n"
                f"Host: {host}\r\n"
                "Connection: close\r\n\r\n"
            ).encode("ascii")
        )
        return _read_http_response(sock)


def _read_http_response(sock: socket.socket) -> bytes:
    """Read HTTP response and return body bytes, handling Content-Length."""
    # Read status line and headers until \r\n\r\n
    header_bytes = bytearray()
    while not header_bytes.endswith(b"\r\n\r\n"):
        chunk = sock.recv(1)
        if not chunk:
            break
        header_bytes.extend(chunk)
    headers = bytes(header_bytes)

    # Parse Content-Length
    content_length = 0
    for line in headers.split(b"\r\n"):
        if line.lower().startswith(b"content-length:"):
            try:
                content_length = int(line.split(b":", 1)[1].strip())
            except ValueError:
                pass
            break

    if content_length > 0:
        return _recv_exact(sock, content_length)
    # Fallback: read until connection closes (Transfer-Encoding: chunked etc.)
    chunks: list[bytes] = []
    sock.settimeout(2)
    try:
        while True:
            chunk = sock.recv(4096)
            if not chunk:
                break
            chunks.append(chunk)
    except socket.timeout:
        pass
    return b"".join(chunks)


def _recv_exact(sock: socket.socket, size: int) -> bytes:
    data = bytearray()
    while len(data) < size:
        chunk = sock.recv(size - len(data))
        if not chunk:
            break
        data.extend(chunk)
    return bytes(data)


def parse_ipinfo_payload(payload: bytes) -> ProxyGeoResult | None:
    try:
        data = json.loads(payload.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return None
    timezone = str(data.get("timezone") or "")
    country_code = str(data.get("country") or "")
    if not timezone or not country_code:
        return None
    return ProxyGeoResult(
        timezone=timezone,
        language=_language_for_country(country_code),
        query=str(data.get("ip") or ""),
    )


def _language_from_provider_hint(data: dict) -> str:
    raw_value = data.get("languages") or data.get("language")
    if raw_value is None:
        return ""
    if isinstance(raw_value, list):
        candidates = [str(item) for item in raw_value]
    else:
        candidates = str(raw_value).replace(";", ",").split(",")
    for candidate in candidates:
        language = normalize_language_tag(candidate, fallback="")
        if language:
            return language
    return ""


_COUNTRY_LANGUAGE: dict[str, str] = {
    # English
    "AS": "en", "AU": "en", "BZ": "en", "CA": "en", "GB": "en", "GU": "en",
    "IE": "en", "IN": "en", "JM": "en", "MH": "en", "MP": "en", "MW": "en",
    "NA": "en", "NG": "en", "NZ": "en", "PH": "en", "PR": "en", "SB": "en",
    "SG": "en", "TT": "en", "UM": "en", "US": "en", "VG": "en", "VI": "en",
    "ZA": "en", "ZM": "en", "ZW": "en",
    # Spanish
    "AR": "es", "BO": "es", "CL": "es", "CO": "es", "CR": "es", "CU": "es",
    "DO": "es", "EC": "es", "ES": "es", "GT": "es", "HN": "es", "MX": "es",
    "NI": "es", "PA": "es", "PE": "es", "PY": "es", "SV": "es", "UY": "es",
    "VE": "es",
    # Portuguese
    "AO": "pt", "BR": "pt", "CV": "pt", "GW": "pt", "MO": "pt", "MZ": "pt",
    "PT": "pt", "ST": "pt", "TL": "pt",
    # French
    "BF": "fr", "BI": "fr", "BJ": "fr", "BL": "fr", "CD": "fr", "CF": "fr",
    "CG": "fr", "CI": "fr", "CM": "fr", "DJ": "fr", "FR": "fr", "GA": "fr",
    "GF": "fr", "GN": "fr", "GP": "fr", "HT": "fr", "LU": "fr", "MA": "fr",
    "MC": "fr", "ML": "fr", "MQ": "fr", "NE": "fr", "PF": "fr", "PM": "fr",
    "RE": "fr", "RW": "fr", "SC": "fr", "SN": "fr", "TG": "fr", "WF": "fr",
    "YT": "fr",
    # German
    "AT": "de", "DE": "de", "LI": "de",
    # Italian
    "IT": "it", "SM": "it",
    # Dutch
    "NL": "nl", "SR": "nl",
    # Russian
    "BY": "ru", "KG": "ru", "KZ": "ru", "RU": "ru", "UA": "ru",
    # Arabic
    "AE": "ar", "BH": "ar", "DJ": "ar", "DZ": "ar", "EG": "ar", "EH": "ar",
    "ER": "ar", "IQ": "ar", "JO": "ar", "KM": "ar", "KW": "ar", "LB": "ar",
    "LY": "ar", "MA": "ar", "MR": "ar", "OM": "ar", "PS": "ar", "QA": "ar",
    "SA": "ar", "SD": "ar", "SO": "ar", "SY": "ar", "TD": "ar", "TN": "ar",
    "YE": "ar",
    # Chinese
    "CN": "zh", "HK": "zh", "MO": "zh", "SG": "zh", "TW": "zh",
    # Japanese
    "JP": "ja",
    # Korean
    "KP": "ko", "KR": "ko",
    # Nordic / Baltic
    "DK": "da", "FO": "fo", "FI": "fi", "IS": "is", "NO": "no", "SE": "sv",
    "EE": "et", "LT": "lt", "LV": "lv",
    # Central / Eastern Europe
    "BG": "bg", "CZ": "cs", "HR": "hr", "HU": "hu", "PL": "pl", "RO": "ro",
    "SK": "sk", "SI": "sl", "AL": "sq", "MK": "mk", "ME": "sr", "RS": "sr",
    "BA": "bs",
    # Western Europe
    "BE": "nl", "CH": "de", "CY": "el", "GR": "el", "IE": "en", "LU": "fr",
    "MT": "mt",
    # Asia
    "AF": "ps", "AM": "hy", "AZ": "az", "BD": "bn", "BN": "ms", "BT": "dz",
    "CC": "ms", "GE": "ka", "ID": "id", "IL": "he", "KH": "km", "LA": "lo",
    "LK": "si", "MM": "my", "MN": "mn", "MV": "dv", "MY": "ms", "NP": "ne",
    "PK": "ur", "TH": "th", "TR": "tr", "VN": "vi",
    # Africa
    "ET": "am", "KE": "sw", "MG": "mg", "MZ": "pt", "SW": "sw", "TZ": "sw",
    "UG": "sw", "ER": "ti",
    # Middle East / South Asia
    "IR": "fa", "SA": "ar", "TM": "tk", "UZ": "uz",
    # Americas
    "GY": "en", "HT": "ht",
}
# Build full language mapping dynamically
_COUNTRY_LANGUAGE_FULL: dict[str, str] = {}
for cc, lang in _COUNTRY_LANGUAGE.items():
    _COUNTRY_LANGUAGE_FULL[cc] = f"{lang}-{cc}"
_COUNTRY_LANGUAGE_FULL.update({
    # Overrides for special cases
    "BE": "nl-BE",
    "CA": "en-CA",
    "CH": "de-CH",
    "GB": "en-GB",
    "IE": "en-IE",
    "IL": "he-IL",
    "IN": "en-IN",
    "MY": "ms-MY",
    "NZ": "en-NZ",
    "PE": "es-PE",
    "PH": "en-PH",
    "SG": "en-SG",
    "ZA": "en-ZA",
    "AE": "ar-AE",
    "HK": "zh-HK",
    "MO": "zh-MO",
    "TW": "zh-TW",
})


def _language_for_country(country_code: str) -> str:
    code = country_code.upper()
    cached = _COUNTRY_LANGUAGE_FULL.get(code)
    if cached:
        return cached
    # Dynamic fallback: try lowercased country code as ISO 639-1 language code,
    # but only accept it if we've actually seen that language code in our mapping
    candidate = normalize_language_tag(code.lower(), fallback="")
    if candidate and candidate in _COUNTRY_LANGUAGE.values():
        return f"{candidate}-{code}"
    return "en-US"
