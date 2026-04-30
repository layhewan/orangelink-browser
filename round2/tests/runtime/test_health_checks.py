from __future__ import annotations

import pytest


class FakePageProbe:
    def __init__(self, *pages, error: Exception | None = None) -> None:
        self.pages = list(pages)
        self.error = error
        self.loaded_urls: list[str] = []

    def load(self, url: str):
        self.loaded_urls.append(url)
        if self.error is not None:
            raise self.error
        return self.pages.pop(0)


def test_public_ip_json_success() -> None:
    from app.runtime.health import PageSnapshot, check_public_ip

    result = check_public_ip(
        FakePageProbe(PageSnapshot(url="https://api.test", title="", body_text='{"ip":"203.0.113.10"}')),
        "https://api.test",
    )

    assert result.ok is True
    assert result.detail == "public_ip=203.0.113.10"
    assert result.failure_class is None


def test_google_search_result_success() -> None:
    from app.runtime.health import PageSnapshot, check_google_reachable

    result = check_google_reachable(
        FakePageProbe(
            PageSnapshot(
                url="https://www.google.com/search?q=orangelink",
                title="orangelink - Google Search",
                body_text="Search Results About 10 results",
            )
        ),
        "orangelink",
    )

    assert result.ok is True
    assert "google reachable" in result.detail


@pytest.mark.parametrize(
    "body",
    [
        "Our systems have detected unusual traffic from your computer network.",
        "Please confirm you are not a robot.",
        "captcha challenge",
        "/sorry/index",
    ],
)
def test_google_robot_verification_counts_as_reachable(body: str) -> None:
    from app.runtime.health import PageSnapshot, check_google_reachable

    result = check_google_reachable(
        FakePageProbe(
            PageSnapshot(
                url="https://www.google.com/sorry/index",
                title="Google",
                body_text=body,
            )
        ),
        "orangelink",
    )

    assert result.ok is True
    assert result.detail == "google robot verification reachable"


def test_blank_page_is_failure() -> None:
    from app.runtime.health import PageSnapshot, check_google_reachable

    result = check_google_reachable(
        FakePageProbe(PageSnapshot(url="about:blank", title="", body_text="   ")),
        "orangelink",
    )

    assert result.ok is False
    assert result.failure_class == "blank_page"


def test_browser_error_page_is_failure() -> None:
    from app.runtime.health import PageSnapshot, check_google_reachable

    result = check_google_reachable(
        FakePageProbe(
            PageSnapshot(
                url="chrome-error://chromewebdata/",
                title="This site can't be reached",
                body_text="ERR_PROXY_CONNECTION_FAILED",
            )
        ),
        "orangelink",
    )

    assert result.ok is False
    assert result.failure_class == "browser_error"


def test_network_exception_is_failure() -> None:
    from app.runtime.health import check_google_reachable

    result = check_google_reachable(
        FakePageProbe(error=TimeoutError("timed out")),
        "orangelink",
    )

    assert result.ok is False
    assert result.failure_class == "network_failure"
    assert "timed out" in result.detail


def test_browserscan_load_success_when_body_is_inspectable() -> None:
    from app.runtime.health import PageSnapshot, check_browserscan_reachable

    result = check_browserscan_reachable(
        FakePageProbe(
            PageSnapshot(
                url="https://www.browserscan.net/",
                title="BrowserScan",
                body_text="BrowserScan browser fingerprint IP address timezone language",
            )
        ),
        "https://www.browserscan.net/",
    )

    assert result.ok is True
    assert result.detail == "browserscan reachable"


def test_health_result_maps_to_validation_report_entry() -> None:
    from app.runtime.health import HealthResult
    from scripts.validate_packaged_release import health_result_to_report_entry

    entry = health_result_to_report_entry(
        HealthResult(
            ok=False,
            detail="proxy failed closed",
            failure_class="proxy_loss",
            duration_ms=12,
        )
    )

    assert entry == {
        "ok": False,
        "detail": "proxy failed closed",
        "duration_ms": 12,
        "failure_class": "proxy_loss",
    }
