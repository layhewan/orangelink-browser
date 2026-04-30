from __future__ import annotations

from app.runtime.health import (
    check_browserscan_reachable,
    check_google_reachable,
    check_public_ip,
)
from scripts.validate_packaged_release import health_result_to_report_entry


HEALTH_ACCEPTANCE_IDS = {
    "public_ip": "A2",
    "google": "A5",
    "browserscan": "A9",
    "invalid_proxy": "A12",
    "proxy_loss": "A13",
}

MANUAL_OBSERVATION_FIELDS = (
    "url",
    "title",
    "network_failures",
    "duration_ms",
)


def collect_basic_health_entries(page_probe, *, ip_url: str, google_query: str, browserscan_url: str) -> dict:
    return {
        HEALTH_ACCEPTANCE_IDS["public_ip"]: health_result_to_report_entry(
            check_public_ip(page_probe, ip_url)
        ),
        HEALTH_ACCEPTANCE_IDS["google"]: health_result_to_report_entry(
            check_google_reachable(page_probe, google_query)
        ),
        HEALTH_ACCEPTANCE_IDS["browserscan"]: health_result_to_report_entry(
            check_browserscan_reachable(page_probe, browserscan_url)
        ),
    }
