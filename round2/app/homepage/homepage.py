from __future__ import annotations

from dataclasses import dataclass, field
from html import escape
from pathlib import Path

from app.runtime.config import PortablePaths


TEMPLATE_PATH = Path(__file__).resolve().parent / "static" / "homepage.html"


@dataclass(frozen=True)
class HomepageContext:
    session_id: str
    public_ip: str | None = None
    public_ip_error: str | None = None
    user_agent: str = "Unavailable"
    platform: str = "Unavailable"
    languages: list[str] = field(default_factory=list)
    timezone: str = "Unavailable"
    screen: str = "Unavailable"
    cpu: int | None = None
    memory: int | None = None
    webrtc_policy: str = "disable_non_proxied_udp"
    engine_version: str = "Unavailable"


def render_homepage_html(context: HomepageContext) -> str:
    template = TEMPLATE_PATH.read_text(encoding="utf-8")
    public_ip_value = context.public_ip or "Public IP unavailable"
    public_ip_detail = context.public_ip_error or context.public_ip or "Public IP unavailable"
    environment_rows = "\n".join(
        _row(label, value)
        for label, value in (
            ("User-Agent", context.user_agent),
            ("Platform", context.platform),
            ("Languages", ", ".join(context.languages) if context.languages else "Unavailable"),
            ("Timezone", context.timezone),
            ("Screen", context.screen),
            ("CPU", f"{context.cpu} cores" if context.cpu is not None else "Unavailable"),
            ("Memory", f"{context.memory} GB" if context.memory is not None else "Unavailable"),
            ("WebRTC policy", context.webrtc_policy),
            ("Engine version", context.engine_version),
        )
    )
    return (
        template.replace("{{SESSION_ID}}", escape(context.session_id))
        .replace("{{PUBLIC_IP_VALUE}}", escape(public_ip_value))
        .replace("{{PUBLIC_IP_DETAIL}}", escape(public_ip_detail))
        .replace("{{ENVIRONMENT_ROWS}}", environment_rows)
    )


def write_homepage(paths: PortablePaths, context: HomepageContext) -> Path:
    paths.homepage.mkdir(parents=True, exist_ok=True)
    homepage_path = paths.homepage / f"session-{context.session_id}.html"
    homepage_path.write_text(render_homepage_html(context), encoding="utf-8")
    return homepage_path


def _row(label: str, value: str) -> str:
    return (
        '<section class="metric">'
        f"<h2>{escape(label)}</h2>"
        f"<p>{escape(value)}</p>"
        "</section>"
    )
