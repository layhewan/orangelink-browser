from __future__ import annotations

from dataclasses import dataclass, field
import json
import os
from pathlib import Path
import re
import shutil
from typing import Any, Callable, Mapping
from urllib.parse import urlparse
from urllib.request import ProxyHandler, Request, build_opener

from app.worker.stealth import apply_basic_stealth

RuntimeStrategy = Callable[[Any, "WorkerRuntimeConfig"], None]
RuntimeLauncher = Callable[["WorkerRuntimeConfig"], Any]

_IP_TIMEZONE_PATTERN = re.compile(r"IP 时区[：:]\s*([A-Za-z_/\-+]+)")
_TIMEZONE_VALUE_PATTERN = re.compile(r"^[A-Za-z]+(?:/[A-Za-z0-9_+\-]+)+$")
_PROXY_TIMEZONE_CACHE: dict[str, str] = {}
_PROXY_LOCALE_CACHE: dict[str, str] = {}
_PERSISTED_PROXY_PREFS_PATH = Path("data/proxy-preferences-cache.json")
_DIRECT_PREF_CACHE_KEY = "__direct__"
_LOCALE_PATTERN = re.compile(r"^[a-z]{2}(?:[-_][A-Za-z]{2})?$")
_LANGUAGE_TO_LOCALE = {
    "en": "en-US",
    "zh": "zh-CN",
    "ja": "ja-JP",
    "ko": "ko-KR",
    "fr": "fr-FR",
    "de": "de-DE",
    "ru": "ru-RU",
    "es": "es-ES",
}
_COUNTRY_CODE_TO_LOCALE = {
    "US": "en-US",
    "SG": "en-SG",
    "CN": "zh-CN",
    "TW": "zh-TW",
    "HK": "zh-HK",
    "JP": "ja-JP",
    "KR": "ko-KR",
    "GB": "en-GB",
    "CA": "en-CA",
    "AU": "en-AU",
    "DE": "de-DE",
    "FR": "fr-FR",
    "RU": "ru-RU",
    "IN": "en-IN",
}
_COUNTRY_NAME_TO_LOCALE = {
    "美国": "en-US",
    "新加坡": "en-SG",
    "中国": "zh-CN",
    "中国大陆": "zh-CN",
    "中国香港": "zh-HK",
    "中国台湾": "zh-TW",
    "香港": "zh-HK",
    "台湾": "zh-TW",
    "日本": "ja-JP",
    "韩国": "ko-KR",
    "英国": "en-GB",
    "加拿大": "en-CA",
    "澳大利亚": "en-AU",
    "德国": "de-DE",
    "法国": "fr-FR",
    "俄罗斯": "ru-RU",
    "印度": "en-IN",
    "United States": "en-US",
    "Singapore": "en-SG",
    "China": "zh-CN",
    "Japan": "ja-JP",
    "Korea": "ko-KR",
    "United Kingdom": "en-GB",
    "Canada": "en-CA",
    "Australia": "en-AU",
    "Germany": "de-DE",
    "France": "fr-FR",
    "Russia": "ru-RU",
    "India": "en-IN",
}
_BROWSERSCAN_HOSTS = ("browserscan.org", "browserscan.net")
_BROWSERSCAN_PROBE_ARTIFACT_CLEANUP_SCRIPT = r"""
(() => {
  window.__pbf_cleanup_installed = true;
  const host = (location.hostname || "").toLowerCase();
  if (!host.includes("browserscan.org") && !host.includes("browserscan.net")) {
    return;
  }

  const isProbeText = (text) => {
    if (!text) {
      return false;
    }
    const value = String(text).trim();
    if (!value) {
      return false;
    }
    if (value.includes("mmMwWLliI0fiflO")) {
      return true;
    }
    return /(?:\bword\b\s+){20,}/i.test(value);
  };

  const clean = () => {
    const body = document.body;
    if (!body) {
      return;
    }

    const tailNodes = Array.from(body.children).slice(-120);
    for (const node of tailNodes) {
      if (isProbeText(node.textContent || "")) {
        node.remove();
      }
    }

    const spans = body.querySelectorAll("span");
    for (const span of spans) {
      if (!isProbeText(span.textContent || "")) {
        continue;
      }
      let previous = span.previousSibling;
      while (previous && previous.nodeName === "BR") {
        const toRemove = previous;
        previous = previous.previousSibling;
        toRemove.remove();
      }
      span.remove();
    }
  };

  const run = () => {
    try {
      clean();
    } catch {
      // Ignore cleanup errors; page behavior should stay stable.
    }
  };

  const start = () => {
    run();
    const root = document.documentElement;
    if (root) {
      const observer = new MutationObserver(run);
      observer.observe(root, { childList: true, subtree: true });
    }
    setInterval(run, 1200);
  };

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", start, { once: true });
    return;
  }
  start();
})();
"""


@dataclass(frozen=True, slots=True)
class ProxyPreferences:
    timezone_id: str | None = None
    locale: str | None = None


@dataclass(slots=True)
class WorkerRuntimeConfig:
    profile_id: str
    user_data_dir: str
    start_url: str = "about:blank"
    headless: bool = False
    locale: str | None = None
    timezone_id: str | None = None
    user_agent: str | None = None
    viewport: dict[str, int] | None = None
    proxy_server: str | None = None
    proxy_username: str | None = None
    proxy_password: str | None = None
    browser_channel: str | None = None
    chrome_executable_path: str | None = None
    launch_args: list[str] = field(default_factory=list)
    auto_timezone: bool = True
    auto_locale: bool = True
    timezone_probe_url: str = "https://www.browserscan.net/zh"
    timezone_probe_timeout_ms: int = 20_000

    @classmethod
    def from_mapping(cls, raw: Mapping[str, Any]) -> "WorkerRuntimeConfig":
        browser_config = raw.get("browser")
        if browser_config is None:
            browser_config = {}
        if not isinstance(browser_config, Mapping):
            raise ValueError("runtime config field 'browser' must be a mapping")

        viewport = raw.get("viewport")
        if viewport is not None and not isinstance(viewport, Mapping):
            raise ValueError("runtime config field 'viewport' must be a mapping")

        return cls(
            profile_id=str(raw.get("profile_id", "")),
            user_data_dir=str(raw.get("user_data_dir", "")),
            start_url=str(raw.get("start_url", "about:blank")),
            headless=bool(raw.get("headless", False)),
            locale=_optional_string(raw.get("locale")),
            timezone_id=_optional_string(raw.get("timezone_id")),
            user_agent=_optional_string(raw.get("user_agent")),
            viewport=_normalize_viewport(viewport),
            proxy_server=_optional_string(raw.get("proxy_server")),
            proxy_username=_optional_string(raw.get("proxy_username")),
            proxy_password=_optional_string(raw.get("proxy_password")),
            browser_channel=_optional_string(raw.get("browser_channel")),
            chrome_executable_path=resolve_chrome_executable_path(raw, browser_config),
            launch_args=[str(item) for item in raw.get("launch_args", [])],
            auto_timezone=_coerce_bool(raw.get("auto_timezone"), default=True),
            auto_locale=_coerce_bool(raw.get("auto_locale"), default=True),
            timezone_probe_url=_optional_string(raw.get("timezone_probe_url")) or "https://www.browserscan.net/zh",
            timezone_probe_timeout_ms=_coerce_int(raw.get("timezone_probe_timeout_ms"), default=20_000),
        )


def _optional_string(value: Any) -> str | None:
    if value is None:
        return None
    value = str(value).strip()
    return value or None


def _normalize_viewport(viewport: Mapping[str, Any] | None) -> dict[str, int] | None:
    if viewport is None:
        return None
    if "width" not in viewport or "height" not in viewport:
        raise ValueError("viewport must include width and height")
    return {
        "width": int(viewport["width"]),
        "height": int(viewport["height"]),
    }


def _coerce_bool(value: Any, *, default: bool) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in {"1", "true", "yes", "on"}:
            return True
        if normalized in {"0", "false", "no", "off"}:
            return False
    return default


def _coerce_int(value: Any, *, default: int) -> int:
    if value is None:
        return default
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return default
    return max(1000, parsed)


def resolve_chrome_executable_path(
    runtime_config: Mapping[str, Any],
    browser_config: Mapping[str, Any] | None = None,
) -> str | None:
    if browser_config is None:
        browser_config = {}

    explicit_path = _optional_string(runtime_config.get("chrome_executable_path"))
    if explicit_path:
        return explicit_path

    local_path = _optional_string(runtime_config.get("local_chrome_executable_path"))
    if local_path:
        return local_path

    nested_path = _optional_string(browser_config.get("chrome_executable_path"))
    if nested_path:
        return nested_path

    env_path = _optional_string(os.getenv("CHROME_EXECUTABLE_PATH"))
    if env_path:
        return env_path

    legacy_env_path = _optional_string(os.getenv("PBF_CHROME_EXECUTABLE_PATH"))
    if legacy_env_path:
        return legacy_env_path

    return None


class WorkerRuntime:
    def __init__(
        self,
        runtime_config: Mapping[str, Any],
        *,
        launcher: RuntimeLauncher | None = None,
        strategy_injectors: list[RuntimeStrategy] | None = None,
    ) -> None:
        self.config = WorkerRuntimeConfig.from_mapping(runtime_config)
        if not self.config.profile_id:
            raise ValueError("runtime config requires profile_id")
        if not self.config.user_data_dir:
            raise ValueError("runtime config requires user_data_dir")

        self._launcher = launcher or self._launch_with_playwright
        self._strategy_injectors = list(strategy_injectors or [])
        self._playwright = None
        self._playwright_manager = None
        self._context = None

    @property
    def context(self) -> Any:
        return self._context

    def launch(self) -> Any:
        if self._context is not None:
            return self._context

        self._context = self._launcher(self.config)
        self._apply_strategy_injectors(self._context)
        return self._context

    def _launch_with_playwright(self, config: WorkerRuntimeConfig) -> Any:
        from playwright.sync_api import sync_playwright

        launch_args = list(config.launch_args)
        launch_kwargs: dict[str, Any] = {
            "headless": config.headless,
            "args": launch_args,
            "ignore_default_args": ["--enable-automation"],
        }

        if config.user_agent:
            launch_kwargs["user_agent"] = config.user_agent
        if config.viewport:
            launch_kwargs["viewport"] = dict(config.viewport)
        if config.chrome_executable_path:
            launch_kwargs["executable_path"] = config.chrome_executable_path
        elif config.browser_channel:
            launch_kwargs["channel"] = config.browser_channel

        if config.proxy_server:
            proxy_payload: dict[str, str] = {"server": config.proxy_server}
            if config.proxy_username:
                proxy_payload["username"] = config.proxy_username
            if config.proxy_password:
                proxy_payload["password"] = config.proxy_password
            launch_kwargs["proxy"] = proxy_payload

        self._playwright_manager = sync_playwright()
        self._playwright = self._playwright_manager.start()
        effective_timezone_id, effective_locale = self._resolve_effective_browser_preferences(config, launch_kwargs)
        if effective_locale:
            launch_kwargs["locale"] = effective_locale
            launch_kwargs["args"] = _apply_lang_arg(launch_args, effective_locale)
            launch_kwargs["extra_http_headers"] = {"Accept-Language": _accept_language_header(effective_locale)}
        if effective_timezone_id:
            launch_kwargs["timezone_id"] = effective_timezone_id

        context = self._playwright.chromium.launch_persistent_context(
            user_data_dir=config.user_data_dir,
            **launch_kwargs,
        )

        def bind_page_handlers(page: Any) -> None:
            if getattr(page, "_pbf_handlers_bound", False):
                return
            setattr(page, "_pbf_handlers_bound", True)
            _ensure_page_cleanup_script(page)

            def on_frame_navigated(frame: Any) -> None:
                try:
                    main_frame = getattr(page, "main_frame", None)
                    if main_frame is not None and frame != main_frame:
                        return

                    raw_url = str(getattr(frame, "url", "") or "")
                    normalized_url = _normalize_probe_url(raw_url)
                    if not normalized_url:
                        return

                    current_profile = _page_stealth_profile(page)
                    target_profile = _stealth_profile_for_url(normalized_url)

                    if current_profile is None:
                        _ensure_page_stealth(page, url=normalized_url)
                        if normalized_url.startswith(("http://", "https://")):
                            page.goto(normalized_url, wait_until="domcontentloaded")
                            _trigger_known_scan_buttons(page, normalized_url)
                        return

                    if current_profile != target_profile and _is_browserscan_url(normalized_url):
                        if getattr(page, "_pbf_replacing", False):
                            return
                        setattr(page, "_pbf_replacing", True)
                        replacement = context.new_page()
                        _ensure_page_cleanup_script(replacement)
                        apply_basic_stealth(replacement, profile=target_profile)
                        _set_page_stealth_profile(replacement, target_profile)
                        bind_page_handlers(replacement)
                        replacement.goto(normalized_url, wait_until="domcontentloaded")
                        _trigger_known_scan_buttons(replacement, normalized_url)
                        try:
                            if not page.is_closed():
                                page.close()
                        except Exception:  # noqa: BLE001
                            pass
                        return

                    _trigger_known_scan_buttons(page, normalized_url)
                except Exception:  # noqa: BLE001
                    return

            page.on("framenavigated", on_frame_navigated)

        context.on("page", bind_page_handlers)

        page = context.pages[0] if getattr(context, "pages", []) else context.new_page()
        bind_page_handlers(page)

        if config.start_url:
            normalized_start_url = _normalize_probe_url(config.start_url)
            _ensure_page_stealth(page, url=normalized_start_url)
            page.goto(normalized_start_url, wait_until="domcontentloaded")
            _trigger_known_scan_buttons(page, normalized_start_url)

        return context

    def _apply_strategy_injectors(self, context: Any) -> None:
        for strategy in self._strategy_injectors:
            strategy(context, self.config)

    def _resolve_effective_browser_preferences(
        self,
        config: WorkerRuntimeConfig,
        launch_kwargs: Mapping[str, Any],
    ) -> tuple[str | None, str | None]:
        timezone_id = None if config.auto_timezone else config.timezone_id
        locale = None if config.auto_locale else config.locale
        cache_key = config.proxy_server or _DIRECT_PREF_CACHE_KEY
        cached_timezone = _PROXY_TIMEZONE_CACHE.get(cache_key)
        cached_locale = _PROXY_LOCALE_CACHE.get(cache_key)
        persisted = _load_persisted_proxy_preferences(cache_key)
        if not cached_timezone and persisted.timezone_id:
            cached_timezone = persisted.timezone_id
            _PROXY_TIMEZONE_CACHE[cache_key] = cached_timezone
        if not cached_locale and persisted.locale:
            cached_locale = persisted.locale
            _PROXY_LOCALE_CACHE[cache_key] = cached_locale

        if cached_timezone and config.auto_timezone:
            timezone_id = cached_timezone
        if cached_locale and config.auto_locale:
            locale = cached_locale
        if (not config.auto_timezone or cached_timezone) and (not config.auto_locale or cached_locale):
            return timezone_id, locale

        probed = self._probe_proxy_preferences(config=config, launch_kwargs=launch_kwargs)
        if probed.timezone_id:
            _PROXY_TIMEZONE_CACHE[cache_key] = probed.timezone_id
            if config.auto_timezone:
                timezone_id = probed.timezone_id
        if probed.locale:
            _PROXY_LOCALE_CACHE[cache_key] = probed.locale
            if config.auto_locale:
                locale = probed.locale

        if probed.timezone_id or probed.locale:
            _persist_proxy_preferences(
                cache_key,
                ProxyPreferences(
                    timezone_id=probed.timezone_id or timezone_id,
                    locale=probed.locale or locale,
                ),
            )

        if config.auto_locale and not locale and timezone_id:
            locale = _locale_from_timezone(timezone_id)
        if config.auto_locale and not locale:
            locale = "en-US"
        if config.auto_timezone and (
            not timezone_id or timezone_id.strip().upper() in {"UTC", "ETC/UTC", "GMT"}
        ) and locale:
            timezone_id = _timezone_from_locale(locale)
        return timezone_id, locale

    def _probe_proxy_preferences(
        self,
        *,
        config: WorkerRuntimeConfig,
        launch_kwargs: Mapping[str, Any],
    ) -> ProxyPreferences:
        geo_result = self._probe_proxy_preferences_via_http_api(config)
        timezone_id = geo_result.timezone_id
        locale = geo_result.locale
        if not locale and timezone_id:
            locale = _locale_from_timezone(timezone_id)
        return ProxyPreferences(timezone_id=timezone_id, locale=locale)

    def _probe_proxy_preferences_via_http_api(self, config: WorkerRuntimeConfig) -> ProxyPreferences:
        proxy_server = config.proxy_server
        if proxy_server:
            parsed = urlparse(proxy_server)
            if parsed.scheme not in {"http", "https"}:
                return ProxyPreferences()
            opener = build_opener(ProxyHandler({"http": proxy_server, "https": proxy_server}))
        else:
            opener = build_opener()

        timeout_s = max(3.0, min(15.0, config.timezone_probe_timeout_ms / 1000.0))
        endpoints = (
            "https://ipapi.co/json/",
            "https://ipwho.is/",
            "https://ipinfo.io/json",
        )
        timezone_votes: dict[str, int] = {}
        locale_votes: dict[str, int] = {}

        for endpoint in endpoints:
            payload = _fetch_json_via_proxy(opener=opener, url=endpoint, timeout_s=timeout_s)
            if payload is None:
                continue

            timezone_id = _extract_timezone_from_geo_payload(payload)
            if not _is_valid_timezone_id(timezone_id):
                timezone_id = None

            locale = _extract_locale_from_geo_payload(payload)
            if not locale:
                locale = _locale_from_timezone(timezone_id)

            if timezone_id:
                timezone_votes[timezone_id] = timezone_votes.get(timezone_id, 0) + 1
            if locale:
                locale_votes[locale] = locale_votes.get(locale, 0) + 1

        return ProxyPreferences(
            timezone_id=_pick_top_vote(timezone_votes),
            locale=_pick_top_vote(locale_votes),
        )

    def stop(self) -> None:
        if self._context is not None:
            self._context.close()
            self._context = None

        stop_callable = None
        if self._playwright is not None:
            stop_callable = getattr(self._playwright, "stop", None)
        elif self._playwright_manager is not None:
            stop_callable = getattr(self._playwright_manager, "stop", None)

        if callable(stop_callable):
            stop_callable()

        self._playwright_manager = None
        self._playwright = None

    def destroy_profile_env(self) -> None:
        self.stop()
        profile_dir = Path(self.config.user_data_dir)
        if profile_dir.exists() and profile_dir.is_dir():
            shutil.rmtree(profile_dir, ignore_errors=True)

    def is_running(self) -> bool:
        return self._context is not None


def _extract_label_value(text: str, labels: tuple[str, ...]) -> str | None:
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    for index, line in enumerate(lines):
        for label in labels:
            if line == label or line.startswith(f"{label}:") or line.startswith(f"{label}："):
                if ":" in line:
                    value = line.split(":", 1)[1].strip()
                    if value:
                        return value
                if "：" in line:
                    value = line.split("：", 1)[1].strip()
                    if value:
                        return value
                if index + 1 < len(lines):
                    return lines[index + 1]
    return None


def _normalize_probe_url(url: str) -> str:
    raw = (url or "").strip()
    if not raw:
        return raw
    parsed = urlparse(raw)
    host = (parsed.netloc or "").lower()
    if host == "www.browserscan.org":
        return raw.replace("//www.browserscan.org", "//browserscan.org", 1)
    return raw


def _stealth_profile_for_url(url: str | None) -> str:
    if not url:
        return "compat"
    host = (urlparse(url).netloc or "").lower()
    if "browserscan.org" in host:
        return "strict"
    return "compat"


def _is_browserscan_url(url: str | None) -> bool:
    if not url:
        return False
    host = (urlparse(url).netloc or "").lower()
    return any(token in host for token in _BROWSERSCAN_HOSTS)


def _page_stealth_profile(page: Any) -> str | None:
    return getattr(page, "_pbf_stealth_profile", None)


def _set_page_stealth_profile(page: Any, profile: str) -> None:
    setattr(page, "_pbf_stealth_profile", profile)


def _ensure_page_cleanup_script(page: Any) -> None:
    if getattr(page, "_pbf_cleanup_script_installed", False):
        return
    page.add_init_script(_BROWSERSCAN_PROBE_ARTIFACT_CLEANUP_SCRIPT)
    setattr(page, "_pbf_cleanup_script_installed", True)


def _ensure_page_stealth(page: Any, *, url: str) -> str:
    target = _stealth_profile_for_url(url)
    current = _page_stealth_profile(page)
    if current is None:
        apply_basic_stealth(page, profile=target)
        _set_page_stealth_profile(page, target)
        return target
    return current


def _trigger_known_scan_buttons(page: Any, url: str) -> None:
    host = (urlparse(url).netloc or "").lower()
    patterns: tuple[str, ...]
    if "browserscan.org" in host:
        patterns = (r"(Start Scan|Re-Scan)",)
    elif "browserscan.net" in host:
        patterns = (r"^检测$", r"^Check$", r"^Scan$")
    else:
        return

    for pattern in patterns:
        try:
            page.get_by_role("button", name=re.compile(pattern, re.IGNORECASE)).first.click(timeout=3000)
            break
        except Exception:  # noqa: BLE001
            continue


def _extract_ip_timezone(text: str) -> str | None:
    match = _IP_TIMEZONE_PATTERN.search(text)
    if match:
        value = match.group(1).strip()
        if _is_valid_timezone_id(value):
            return value
    fallback = _extract_label_value(text, ("IP 时区", "IP Timezone", "IP Time Zone"))
    if _is_valid_timezone_id(fallback):
        return fallback
    return None


def _is_valid_timezone_id(value: str | None) -> bool:
    if not value:
        return False
    return _TIMEZONE_VALUE_PATTERN.fullmatch(value.strip()) is not None


def _extract_country_name(text: str) -> str | None:
    return _extract_label_value(text, ("国家/地区", "Country/Region", "Country"))


def _locale_from_languages(languages: str | None) -> str | None:
    if not languages:
        return None
    for token in re.split(r"[,; ]+", languages):
        value = token.strip()
        if not value:
            continue
        normalized = _normalize_locale(value)
        if normalized:
            return normalized
        if re.fullmatch(r"[A-Za-z]{2}", value):
            fallback = _LANGUAGE_TO_LOCALE.get(value.lower())
            if fallback:
                return fallback
    return None


def _normalize_locale(locale: str | None) -> str | None:
    if not locale:
        return None
    candidate = locale.strip()
    if not candidate or not _LOCALE_PATTERN.fullmatch(candidate):
        return None
    parts = candidate.replace("_", "-").split("-")
    if len(parts) == 1:
        fallback = _LANGUAGE_TO_LOCALE.get(parts[0].lower())
        return fallback
    return f"{parts[0].lower()}-{parts[1].upper()}"


def _locale_from_country_code(country_code: str | None) -> str | None:
    if not country_code:
        return None
    return _COUNTRY_CODE_TO_LOCALE.get(country_code.strip().upper())


def _locale_from_country_name(country_name: str | None) -> str | None:
    if not country_name:
        return None
    normalized = country_name.strip()
    if not normalized:
        return None
    if normalized in _COUNTRY_NAME_TO_LOCALE:
        return _COUNTRY_NAME_TO_LOCALE[normalized]

    upper = normalized.upper()
    if upper in _COUNTRY_CODE_TO_LOCALE:
        return _COUNTRY_CODE_TO_LOCALE[upper]

    for key, locale in _COUNTRY_NAME_TO_LOCALE.items():
        if key in normalized:
            return locale
    return None


def _locale_from_timezone(timezone_id: str | None) -> str | None:
    if not timezone_id:
        return None
    normalized = timezone_id.strip()
    if not normalized:
        return None

    exact_map = {
        "Asia/Shanghai": "zh-CN",
        "Asia/Hong_Kong": "zh-HK",
        "Asia/Taipei": "zh-TW",
        "Asia/Tokyo": "ja-JP",
        "Asia/Seoul": "ko-KR",
        "Asia/Singapore": "en-SG",
        "Europe/London": "en-GB",
        "Europe/Paris": "fr-FR",
        "Europe/Berlin": "de-DE",
        "Europe/Moscow": "ru-RU",
        "America/Toronto": "en-CA",
        "Australia/Sydney": "en-AU",
    }
    if normalized in exact_map:
        return exact_map[normalized]

    if normalized.startswith("America/"):
        return "en-US"
    if normalized.startswith("Europe/"):
        return "en-GB"
    if normalized.startswith("Asia/"):
        return "en-SG"
    return "en-US"


def _timezone_from_locale(locale: str | None) -> str | None:
    normalized = _normalize_locale(locale)
    if not normalized:
        return None
    mapping = {
        "en-US": "America/Los_Angeles",
        "en-SG": "Asia/Singapore",
        "en-GB": "Europe/London",
        "zh-CN": "Asia/Shanghai",
        "zh-HK": "Asia/Hong_Kong",
        "zh-TW": "Asia/Taipei",
        "ja-JP": "Asia/Tokyo",
        "ko-KR": "Asia/Seoul",
        "de-DE": "Europe/Berlin",
        "fr-FR": "Europe/Paris",
        "ru-RU": "Europe/Moscow",
    }
    return mapping.get(normalized, "America/Los_Angeles")


def _apply_lang_arg(args: list[str], locale: str) -> list[str]:
    cleaned = [arg for arg in args if not str(arg).startswith("--lang=")]
    cleaned.append(f"--lang={locale}")
    return cleaned


def _accept_language_header(locale: str) -> str:
    primary = locale.split("-", 1)[0].lower()
    return f"{locale},{primary};q=0.9"


def _pick_top_vote(votes: Mapping[str, int]) -> str | None:
    if not votes:
        return None
    return max(votes.items(), key=lambda item: item[1])[0]


def _load_persisted_proxy_preferences(proxy_key: str) -> ProxyPreferences:
    try:
        if not _PERSISTED_PROXY_PREFS_PATH.exists():
            return ProxyPreferences()
        payload = json.loads(_PERSISTED_PROXY_PREFS_PATH.read_text(encoding="utf-8"))
        if not isinstance(payload, dict):
            return ProxyPreferences()
        node = payload.get(proxy_key)
        if not isinstance(node, dict):
            return ProxyPreferences()
        timezone_id = _optional_string(node.get("timezone_id"))
        if not _is_valid_timezone_id(timezone_id):
            timezone_id = None
        locale = _normalize_locale(_optional_string(node.get("locale")))
        return ProxyPreferences(timezone_id=timezone_id, locale=locale)
    except Exception:  # noqa: BLE001
        return ProxyPreferences()


def _persist_proxy_preferences(proxy_key: str, preferences: ProxyPreferences) -> None:
    if not preferences.timezone_id and not preferences.locale:
        return
    try:
        _PERSISTED_PROXY_PREFS_PATH.parent.mkdir(parents=True, exist_ok=True)
        if _PERSISTED_PROXY_PREFS_PATH.exists():
            payload = json.loads(_PERSISTED_PROXY_PREFS_PATH.read_text(encoding="utf-8"))
            if not isinstance(payload, dict):
                payload = {}
        else:
            payload = {}
        payload[proxy_key] = {
            "timezone_id": preferences.timezone_id,
            "locale": preferences.locale,
        }
        _PERSISTED_PROXY_PREFS_PATH.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception:  # noqa: BLE001
        return


def _fetch_json_via_proxy(*, opener: Any, url: str, timeout_s: float) -> dict[str, Any] | None:
    request = Request(
        url=url,
        headers={
            "User-Agent": "Mozilla/5.0",
            "Accept": "application/json",
        },
    )
    try:
        with opener.open(request, timeout=timeout_s) as response:
            body = response.read().decode("utf-8", errors="ignore")
        payload = json.loads(body)
    except Exception:  # noqa: BLE001
        return None

    if not isinstance(payload, dict):
        return None
    return payload


def _extract_timezone_from_geo_payload(payload: Mapping[str, Any]) -> str | None:
    timezone_id = _optional_string(payload.get("timezone"))
    if _is_valid_timezone_id(timezone_id):
        return timezone_id

    timezone_node = payload.get("timezone")
    if isinstance(timezone_node, Mapping):
        nested = _optional_string(timezone_node.get("id"))
        if _is_valid_timezone_id(nested):
            return nested
    return None


def _extract_locale_from_geo_payload(payload: Mapping[str, Any]) -> str | None:
    locale = _locale_from_languages(_optional_string(payload.get("languages")))
    if locale:
        return locale

    locale = _locale_from_country_code(_optional_string(payload.get("country_code")))
    if locale:
        return locale

    locale = _locale_from_country_code(_optional_string(payload.get("country")))
    if locale:
        return locale
    return None
