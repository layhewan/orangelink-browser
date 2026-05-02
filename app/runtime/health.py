from __future__ import annotations

import json
import time
from dataclasses import dataclass
from typing import Any, Callable
from urllib.parse import quote_plus


GOOGLE_ROBOT_TOKENS = (
    "/sorry/",
    "unusual traffic",
    "not a robot",
    "captcha",
    "our systems have detected",
)

BROWSER_ERROR_TOKENS = (
    "err_",
    "dns_probe",
    "proxy_connection_failed",
    "this site can't be reached",
    "this site can’t be reached",
    "chrome-error://",
)


@dataclass(frozen=True)
class PageSnapshot:
    url: str
    title: str
    body_text: str


@dataclass(frozen=True)
class HealthResult:
    ok: bool
    detail: str
    failure_class: str | None = None
    duration_ms: int = 0


def check_public_ip(page_probe: Any, url: str) -> HealthResult:
    return _timed_check(lambda: _check_public_ip(page_probe, url))


def check_google_reachable(page_probe: Any, query: str) -> HealthResult:
    url = f"https://www.google.com/search?q={quote_plus(query)}"
    return _timed_check(lambda: _check_google(page_probe, url))


def check_browserscan_reachable(page_probe: Any, url: str) -> HealthResult:
    return _timed_check(lambda: _check_browserscan(page_probe, url))


def check_session_ready(page_probe: Any, start_url: str) -> HealthResult:
    return _timed_check(lambda: _classify_loaded_page(_load_page(page_probe, start_url)))


def _check_public_ip(page_probe: Any, url: str) -> HealthResult:
    snapshot = _load_page(page_probe, url)
    common_failure = _classify_common_failure(snapshot)
    if common_failure is not None:
        return common_failure

    try:
        payload = json.loads(snapshot.body_text)
    except json.JSONDecodeError:
        return HealthResult(False, "public IP response was not JSON", "site_load_failure")

    ip = payload.get("ip")
    if isinstance(ip, str) and ip.strip():
        return HealthResult(True, f"public_ip={ip.strip()}")
    return HealthResult(False, "public IP response missing ip", "site_load_failure")


def _check_google(page_probe: Any, url: str) -> HealthResult:
    snapshot = _load_page(page_probe, url)
    common_failure = _classify_common_failure(snapshot)
    if common_failure is not None:
        return common_failure

    text = _combined_text(snapshot)
    if any(token in text for token in GOOGLE_ROBOT_TOKENS):
        return HealthResult(True, "google robot verification reachable")

    if "google." in snapshot.url.lower() and (
        "search" in snapshot.url.lower()
        or "google search" in snapshot.title.lower()
        or "search results" in text
    ):
        return HealthResult(True, "google reachable")

    return HealthResult(False, "google page did not show search or robot verification", "site_load_failure")


def _check_browserscan(page_probe: Any, url: str) -> HealthResult:
    snapshot = _load_page(page_probe, url)
    common_failure = _classify_common_failure(snapshot)
    if common_failure is not None:
        return common_failure

    text = _combined_text(snapshot)
    if "browserscan" in text and len(snapshot.body_text.strip()) >= 24:
        return HealthResult(True, "browserscan reachable")
    return HealthResult(False, "browserscan page was not inspectable", "site_load_failure")


def _classify_loaded_page(snapshot: PageSnapshot) -> HealthResult:
    common_failure = _classify_common_failure(snapshot)
    if common_failure is not None:
        return common_failure
    return HealthResult(True, "start page ready")


def _classify_common_failure(snapshot: PageSnapshot) -> HealthResult | None:
    text = _combined_text(snapshot)
    if any(token in text for token in BROWSER_ERROR_TOKENS):
        return HealthResult(False, "browser error page loaded", "browser_error")
    if not snapshot.title.strip() and not snapshot.body_text.strip():
        return HealthResult(False, "blank page loaded", "blank_page")
    return None


def _load_page(page_probe: Any, url: str) -> PageSnapshot:
    if hasattr(page_probe, "load"):
        return page_probe.load(url)

    if hasattr(page_probe, "connection") and hasattr(page_probe, "session_id"):
        connection = page_probe.connection
        connection.navigate(page_probe.session_id, url)
        return PageSnapshot(
            url=str(connection.evaluate(page_probe.session_id, "window.location.href")),
            title=str(connection.evaluate(page_probe.session_id, "document.title")),
            body_text=str(
                connection.evaluate(
                    page_probe.session_id,
                    "document.body ? document.body.innerText : ''",
                )
            ),
        )

    raise TypeError("page_probe must provide load(url) or be a CdpSession")


def _timed_check(check: Callable[[], HealthResult]) -> HealthResult:
    started = time.perf_counter()
    try:
        result = check()
    except Exception as exc:
        result = HealthResult(False, f"network check failed: {exc}", "network_failure")

    duration_ms = max(0, int((time.perf_counter() - started) * 1000))
    return HealthResult(
        ok=result.ok,
        detail=result.detail,
        failure_class=result.failure_class,
        duration_ms=result.duration_ms or duration_ms,
    )


def _combined_text(snapshot: PageSnapshot) -> str:
    return f"{snapshot.url}\n{snapshot.title}\n{snapshot.body_text}".lower()
