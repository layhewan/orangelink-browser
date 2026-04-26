from __future__ import annotations

import argparse
from datetime import datetime
import re
import sys
from pathlib import Path
from urllib.parse import urlparse

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.worker.runtime import (  # noqa: E402
    _extract_country_name,
    _locale_from_country_name,
    _locale_from_timezone,
    _normalize_locale,
)
from app.worker.stealth import apply_basic_stealth  # noqa: E402


def _accept_language_header(locale: str) -> str:
    primary = locale.split("-", 1)[0].lower()
    return f"{locale},{primary};q=0.9"


def _configure_console_encoding() -> None:
    try:
        if hasattr(sys.stdout, "reconfigure"):
            sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        if hasattr(sys.stderr, "reconfigure"):
            sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:  # noqa: BLE001
        return


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run BrowserScan score checks with project runtime.")
    parser.add_argument("--url", default="https://browserscan.org/", help="Primary BrowserScan URL")
    parser.add_argument(
        "--legacy-url",
        default="https://www.browserscan.net/zh",
        help="Legacy BrowserScan URL for non-regression checks",
    )
    parser.add_argument(
        "--check-legacy",
        dest="check_legacy",
        action="store_true",
        default=True,
        help="Check both primary and legacy BrowserScan URLs",
    )
    parser.add_argument(
        "--no-check-legacy",
        dest="check_legacy",
        action="store_false",
        help="Only check primary BrowserScan URL",
    )
    parser.add_argument("--min-score", type=int, default=95, help="Minimum acceptable score on each site")
    parser.add_argument("--proxy-host", default="127.0.0.1", help="Proxy host")
    parser.add_argument("--proxy-port", type=int, default=7897, help="Proxy port")
    parser.add_argument("--proxy-scheme", default="http", choices=["http", "https", "socks5"], help="Proxy scheme")
    parser.add_argument(
        "--chrome-executable-path",
        default=str(Path(".playwright/chrome-win64/chrome.exe")),
        help="Chrome executable path",
    )
    parser.add_argument("--timezone-id", default="UTC", help="Browser timezone id")
    parser.add_argument("--locale", default="en-US", help="Browser locale")
    parser.add_argument("--auto-timezone", action="store_true", help="Auto align timezone with detected IP timezone")
    parser.add_argument("--auto-locale", dest="auto_locale", action="store_true", default=True, help="Auto align locale")
    parser.add_argument("--no-auto-locale", dest="auto_locale", action="store_false", help="Disable automatic locale alignment")
    parser.add_argument("--wait-ms", type=int, default=12000, help="Max wait time for scan results")
    parser.add_argument("--keep-open-seconds", type=int, default=0, help="Keep browser window open after capture")
    parser.add_argument("--dump-dir", default="", help="Optional directory to save screenshot/html/text")
    parser.add_argument("--headless", action="store_true", help="Run headless")
    parser.add_argument("--debug", action="store_true", help="Print deduction hints")
    return parser.parse_args()


def extract_score(text: str) -> int | None:
    new_site = re.search(r"\n\s*(\d{2,3})\s*\n\s*[A-F](?:[+-])?\s*\n\s*STATUS\b", text, flags=re.IGNORECASE)
    if new_site:
        return int(new_site.group(1))

    patterns = (
        r"浏览器指纹真实度[：:]\s*(\d+)%",
        r"Fingerprint\s+Authenticity[^\d]*(\d+)%",
        r"Fingerprint\s+Score[^\d]*(\d+)%",
        r"Fingerprint[^\n]{0,80}(\d+)%",
    )
    for pattern in patterns:
        match = re.search(pattern, text, flags=re.IGNORECASE)
        if match:
            return int(match.group(1))
    return None


def extract_ip_timezone(text: str) -> str | None:
    new_site = re.search(r"IP\s*\(([A-Za-z_/\-+]+)\)\s*!=\s*System", text, flags=re.IGNORECASE)
    if new_site:
        return new_site.group(1).strip()

    patterns = (
        r"IP 时区[：:]\s*([A-Za-z_/\-+]+)",
        r"IP Timezone[：:]\s*([A-Za-z_/\-+]+)",
        r"IP Time Zone[：:]\s*([A-Za-z_/\-+]+)",
    )
    for pattern in patterns:
        match = re.search(pattern, text, flags=re.IGNORECASE)
        if match:
            return match.group(1).strip()
    return None


def is_site_temporarily_unavailable(text: str) -> bool:
    return bool(re.search(r"error code 522|connection timed out", text, flags=re.IGNORECASE))


def _launch_and_collect(
    args: argparse.Namespace,
    *,
    url: str,
    timezone_id: str,
    locale: str,
) -> tuple[int | None, str]:
    proxy_server = f"{args.proxy_scheme}://{args.proxy_host}:{args.proxy_port}"
    parsed = urlparse(url)
    host_token = (parsed.netloc or "default").replace(":", "_")
    profile_dir = Path("data") / f"browserscan-check-profile-{host_token}-{args.proxy_port}"
    with sync_playwright() as p:
        context = p.chromium.launch_persistent_context(
            user_data_dir=str(profile_dir),
            executable_path=args.chrome_executable_path,
            headless=args.headless,
            proxy={"server": proxy_server},
            locale=locale,
            timezone_id=timezone_id,
            extra_http_headers={"Accept-Language": _accept_language_header(locale)},
            ignore_default_args=["--enable-automation"],
            args=[
                "--disable-blink-features=AutomationControlled",
                "--webrtc-ip-handling-policy=disable_non_proxied_udp",
                "--force-webrtc-ip-handling-policy=disable_non_proxied_udp",
                "--disable-features=AsyncDns,DnsOverHttps,UseDnsHttpsSvcb",
                "--proxy-bypass-list=<-loopback>",
                "--no-first-run",
                "--no-default-browser-check",
            ],
        )
        try:
            stealth_profile = "strict" if "browserscan.org" in (parsed.netloc or "") else "compat"
            apply_basic_stealth(context, profile=stealth_profile)
            page = context.pages[0] if context.pages else context.new_page()
            page.goto(url, wait_until="domcontentloaded")
            if "browserscan.org" in (parsed.netloc or ""):
                try:
                    page.get_by_role("button", name=re.compile(r"(Start Scan|Re-Scan)", re.IGNORECASE)).first.click(timeout=5000)
                except Exception:  # noqa: BLE001
                    pass
            elif "browserscan.net" in (parsed.netloc or ""):
                for pattern in (r"^检测$", r"^Check$", r"^Scan$"):
                    try:
                        page.get_by_role("button", name=re.compile(pattern, re.IGNORECASE)).first.click(timeout=3000)
                        break
                    except Exception:  # noqa: BLE001
                        continue

            elapsed = 0
            timeout_ms = max(3000, int(args.wait_ms))
            latest_text = ""
            latest_score: int | None = None

            while elapsed < timeout_ms:
                page.wait_for_timeout(1000)
                elapsed += 1000
                latest_text = page.inner_text("body")
                candidate = extract_score(latest_text)
                if candidate is not None:
                    latest_score = candidate

            if not latest_text:
                latest_text = page.inner_text("body")
                latest_score = extract_score(latest_text)

            dump_dir_raw = str(getattr(args, "dump_dir", "") or "").strip()
            if dump_dir_raw:
                dump_dir = Path(dump_dir_raw)
                dump_dir.mkdir(parents=True, exist_ok=True)
                ts = datetime.now().strftime("%Y%m%d-%H%M%S")
                host_name = (parsed.netloc or "site").replace(":", "_")
                stem = f"{host_name}-{args.proxy_port}-{ts}"
                page.screenshot(path=str(dump_dir / f"{stem}.png"), full_page=True)
                (dump_dir / f"{stem}.html").write_text(page.content(), encoding="utf-8")
                (dump_dir / f"{stem}.txt").write_text(latest_text, encoding="utf-8")

            keep_open_seconds = max(0, int(getattr(args, "keep_open_seconds", 0)))
            if keep_open_seconds > 0:
                page.wait_for_timeout(keep_open_seconds * 1000)
            return latest_score, latest_text
        finally:
            context.close()


def _run_single_site(
    args: argparse.Namespace,
    *,
    label: str,
    url: str,
    timezone_id: str,
    locale: str,
) -> tuple[int, str]:
    effective_timezone_id = timezone_id
    effective_locale = locale
    score, text = _launch_and_collect(args, url=url, timezone_id=effective_timezone_id, locale=effective_locale)
    ip_tz = extract_ip_timezone(text)
    inferred_locale: str | None = None
    if args.auto_locale:
        country_name = _extract_country_name(text)
        inferred_locale = _normalize_locale(_locale_from_country_name(country_name) or _locale_from_timezone(ip_tz))

    should_retry = False
    if args.auto_timezone and ip_tz and ip_tz != effective_timezone_id:
        effective_timezone_id = ip_tz
        should_retry = True
        print(f"{label} auto-timezone retry: {ip_tz}")
    if args.auto_locale and inferred_locale and inferred_locale != effective_locale:
        effective_locale = inferred_locale
        should_retry = True
        print(f"{label} auto-locale retry: {effective_locale}")

    if should_retry:
        score, text = _launch_and_collect(
            args,
            url=url,
            timezone_id=effective_timezone_id,
            locale=effective_locale,
        )

    if score is None:
        if is_site_temporarily_unavailable(text):
            print(f"{label} unavailable (Cloudflare 522 / timeout).")
            return 3, text
        print(f"{label} score not found.")
        return 2, text
    print(f"{label} score: {score}%")
    if score < args.min_score:
        print(f"{label} FAIL (score < {args.min_score})")
        return 1, text
    print(f"{label} PASS")
    return 0, text


def run_check(args: argparse.Namespace) -> int:
    effective_timezone_id = args.timezone_id
    effective_locale = args.locale
    primary_unavailable = False

    primary_score, primary_text = _launch_and_collect(
        args,
        url=args.url,
        timezone_id=effective_timezone_id,
        locale=effective_locale,
    )
    ip_tz = extract_ip_timezone(primary_text)

    inferred_locale: str | None = None
    if args.auto_locale:
        country_name = _extract_country_name(primary_text)
        inferred_locale = _normalize_locale(_locale_from_country_name(country_name) or _locale_from_timezone(ip_tz))

    should_retry = False
    if args.auto_timezone and ip_tz and ip_tz != effective_timezone_id:
        effective_timezone_id = ip_tz
        should_retry = True
        print(f"Auto-timezone: retry with {ip_tz}")
    elif args.auto_timezone and ip_tz == effective_timezone_id:
        print(f"Auto-timezone: already aligned ({ip_tz})")
    elif args.auto_timezone and not ip_tz:
        print("Auto-timezone: IP timezone not found, keep current timezone setting.")

    if args.auto_locale and inferred_locale and inferred_locale != effective_locale:
        effective_locale = inferred_locale
        should_retry = True
        print(f"Auto-locale: retry with {effective_locale}")

    if should_retry:
        primary_score, primary_text = _launch_and_collect(
            args,
            url=args.url,
            timezone_id=effective_timezone_id,
            locale=effective_locale,
        )

    if primary_score is None:
        if is_site_temporarily_unavailable(primary_text):
            print("Primary BrowserScan site unavailable (Cloudflare 522 / timeout).")
            primary_unavailable = True
        else:
            print("Primary BrowserScan score not found.")
            return 2
    else:
        print(f"Primary score ({args.url}): {primary_score}%")
        if args.debug:
            lines = [line.strip() for line in primary_text.splitlines() if line.strip()]
            hints = [
                ln
                for ln in lines
                if re.search(r"-\d+%|timezone|机器人|IP 地址不同|WebRTC|泄漏|DNS|语言|请求头语言|country", ln, flags=re.IGNORECASE)
            ]
            print("Primary deduction hints:")
            for line in hints[:60]:
                print(f"- {line}")

        if primary_score < args.min_score:
            print(f"Result: FAIL (primary score < {args.min_score})")
            return 1

    if args.check_legacy:
        legacy_code, _ = _run_single_site(
            args,
            label=f"Legacy ({args.legacy_url})",
            url=args.legacy_url,
            timezone_id=effective_timezone_id,
            locale=effective_locale,
        )
        if legacy_code != 0:
            print("Result: FAIL (legacy score regression)")
            return legacy_code

    if primary_unavailable:
        print("Result: INCOMPLETE (primary site unavailable; legacy check passed).")
        return 3

    print("Result: PASS")
    return 0


if __name__ == "__main__":
    _configure_console_encoding()
    raise SystemExit(run_check(parse_args()))
