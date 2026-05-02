from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from app.runtime.config import LaunchConfig, normalize_language_tag
from app.runtime.engine_version import BrowserEngineVersion


OS_PROFILES = {
    "windows": {
        "ua_platform_token": "Windows NT 10.0; Win64; x64",
        "platform": "Windows",
        "navigator_platform": "Win32",
    },
    "macos": {
        "ua_platform_token": "Macintosh; Intel Mac OS X 10_15_7",
        "platform": "macOS",
        "navigator_platform": "MacIntel",
    },
    "linux": {
        "ua_platform_token": "X11; Linux x86_64",
        "platform": "Linux",
        "navigator_platform": "Linux x86_64",
    },
}


@dataclass(frozen=True)
class FingerprintProfile:
    language: str
    accept_language: str
    timezone: str
    os_family: str
    platform: str
    navigator_platform: str
    user_agent: str
    user_agent_metadata: dict[str, Any]
    hardware_concurrency: int = 8
    device_memory: int = 8


def build_fingerprint_profile(
    config: LaunchConfig,
    *,
    actual_engine: BrowserEngineVersion,
    proxy_geo_cache: dict[str, str] | None = None,
    claimed_family: str = "Chrome",
    claimed_major: int | None = None,
) -> FingerprintProfile:
    geo_cache = proxy_geo_cache or {}
    cached_language = config.cached_language if config.proxy_enabled else ""
    cached_timezone = config.cached_timezone if config.proxy_enabled else ""
    raw_language = config.manual_language
    if config.automatic_language:
        raw_language = geo_cache.get("language") or cached_language or config.manual_language
    language = normalize_language_tag(
        raw_language,
        fallback=config.manual_language,
    )
    timezone_raw = (
        geo_cache.get("timezone") or cached_timezone
        if config.automatic_timezone
        else config.manual_timezone
    ) or config.manual_timezone
    # Only set timezone if we have a meaningful value to avoid UTC fallback
    timezone = timezone_raw if timezone_raw and timezone_raw not in ("UTC", "") else ""
    os_family = config.os_fingerprint.lower()
    os_profile = OS_PROFILES.get(os_family, OS_PROFILES["windows"])
    major = claimed_major or actual_engine.major
    user_agent = (
        f"Mozilla/5.0 ({os_profile['ua_platform_token']}) "
        f"AppleWebKit/537.36 (KHTML, like Gecko) "
        f"{claimed_family}/{major}.0.0.0 Safari/537.36"
    )

    return FingerprintProfile(
        language=language,
        accept_language=_accept_language(language),
        timezone=timezone,
        os_family=os_family,
        platform=os_profile["platform"],
        navigator_platform=os_profile["navigator_platform"],
        user_agent=user_agent,
        user_agent_metadata={
            "brands": [
                {"brand": "Chromium", "version": str(major)},
                {"brand": claimed_family, "version": str(major)},
            ],
            "fullVersionList": [
                {"brand": "Chromium", "version": f"{major}.0.0.0"},
                {"brand": claimed_family, "version": f"{major}.0.0.0"},
            ],
            "platform": os_profile["platform"],
            "platformVersion": "10.0.0",
            "architecture": "x86",
            "model": "",
            "mobile": False,
        },
    )


def apply_fingerprint_overrides(cdp: Any, session_id: str, profile: FingerprintProfile) -> None:
    _send_cdp(
        cdp,
        "Network.setUserAgentOverride",
        {
            "userAgent": profile.user_agent,
            "acceptLanguage": profile.accept_language,
            "platform": profile.navigator_platform,
            "userAgentMetadata": profile.user_agent_metadata,
        },
        session_id=session_id,
    )
    if profile.timezone:
        _send_cdp(
            cdp,
            "Emulation.setTimezoneOverride",
            {"timezoneId": profile.timezone},
            session_id=session_id,
        )
    _send_cdp(
        cdp,
        "Page.addScriptToEvaluateOnNewDocument",
        {"source": _navigator_override_script(profile)},
        session_id=session_id,
    )


def _accept_language(language: str) -> str:
    language = normalize_language_tag(language, fallback="en-US")
    if "-" not in language:
        return language
    base = language.split("-", 1)[0]
    # No q factors — Chrome adds them internally
    return f"{language},{base}"


def _navigator_override_script(profile: FingerprintProfile) -> str:
    languages = [profile.language]
    if "-" in profile.language:
        languages.append(profile.language.split("-", 1)[0])
    return f"""
(() => {{
  const language = {json.dumps(profile.language)};
  const languages = {json.dumps(languages)};
  const define = (target, key, value) => {{
    try {{
      Object.defineProperty(target, key, {{get: () => value, configurable: true}});
    }} catch (_) {{}}
  }};
  const defineReadOnly = (target, key, value) => {{
    try {{
      Object.defineProperty(target, key, {{value, writable: false, configurable: true}});
    }} catch (_) {{}}
  }};

  /* --- navigator properties --- */
  define(navigator, 'language', language);
  define(navigator, 'languages', languages);
  define(navigator, 'platform', {json.dumps(profile.navigator_platform)});
  define(navigator, 'hardwareConcurrency', {profile.hardware_concurrency});
  define(navigator, 'deviceMemory', {profile.device_memory});
  define(navigator, 'webdriver', false);

  /* --- remove automation traces --- */
  if (window.cdc_adoQpoasnfa76pfcZLmcfl_Array) {{ window.cdc_adoQpoasnfa76pfcZLmcfl_Array = undefined; }}
  if (window.cdc_adoQpoasnfa76pfcZLmcfl_Promise) {{ window.cdc_adoQpoasnfa76pfcZLmcfl_Promise = undefined; }}
  if (window.cdc_adoQpoasnfa76pfcZLmcfl_Symbol) {{ window.cdc_adoQpoasnfa76pfcZLmcfl_Symbol = undefined; }}

  /* --- chrome.runtime --- */
  if (window.chrome && window.chrome.runtime) {{
    defineReadOnly(window.chrome.runtime, 'id', undefined);
    const dummyApp = {{ isInstalled: false, InstallState: {{ DISABLED: 'disabled', INSTALLED: 'installed', NOT_INSTALLED: 'not_installed' }}, RunningState: {{ CANNOT_RUN: 'cannot_run', READY_TO_RUN: 'ready_to_run', RUNNING: 'running' }} }};
    defineReadOnly(window.chrome.runtime, 'onInstalled', {{ addListener: function() {{}} }});
    defineReadOnly(window.chrome.runtime, 'onStartup', {{ addListener: function() {{}} }});
  }}

  /* --- screen properties --- */
  try {{
    define(screen, 'width', 1920);
    define(screen, 'height', 1080);
    define(screen, 'availWidth', 1920);
    define(screen, 'availHeight', 1040);
    define(screen, 'colorDepth', 24);
    define(screen, 'pixelDepth', 24);
  }} catch (_) {{}}

  /* --- permissions --- */
  if (navigator.permissions && navigator.permissions.query) {{
    const origQuery = navigator.permissions.query.bind(navigator.permissions);
    navigator.permissions.query = (desc) => {{
      if (desc && desc.name === 'notifications') {{
        return Promise.resolve({{ state: 'prompt', onchange: null }});
      }}
      return origQuery(desc);
    }};
  }}

  /* --- Intl locale patching --- */
  const defaultIntlInstances = new WeakSet();
  const normalizeLocaleArgs = (args) => {{
    const values = Array.from(args);
    const usesDefaultLocale = values.length === 0
      || values[0] === undefined
      || values[0] === null
      || (Array.isArray(values[0]) && values[0].length === 0);
    if (usesDefaultLocale) {{
      values[0] = language;
      values.__orangelinkDefaultLocale = true;
    }}
    return values;
  }};
  const patchIntlConstructor = (name) => {{
    const Original = Intl[name];
    if (typeof Original !== 'function') {{
      return;
    }}
    if (Original.prototype && Original.prototype.resolvedOptions) {{
      const origResolved = Original.prototype.resolvedOptions;
      try {{
        Original.prototype.resolvedOptions = function(...args) {{
          const options = origResolved.apply(this, args);
          if (defaultIntlInstances.has(this)) {{
            options.locale = language;
          }}
          return options;
        }};
      }} catch (_) {{}}
    }}
    const Wrapped = new Proxy(Original, {{
      apply(target, thisArg, args) {{
        const localeArgs = normalizeLocaleArgs(args);
        const instance = Reflect.apply(target, thisArg, localeArgs);
        if (localeArgs.__orangelinkDefaultLocale && instance && typeof instance === 'object') {{
          defaultIntlInstances.add(instance);
        }}
        return instance;
      }},
      construct(target, args, newTarget) {{
        const localeArgs = normalizeLocaleArgs(args);
        const instance = Reflect.construct(target, localeArgs, newTarget);
        if (localeArgs.__orangelinkDefaultLocale && instance && typeof instance === 'object') {{
          defaultIntlInstances.add(instance);
        }}
        return instance;
      }}
    }});
    try {{ Object.defineProperty(Wrapped, 'toString', {{value: () => Original.toString()}}); }} catch (_) {{}}
    try {{ Object.defineProperty(Intl, name, {{value: Wrapped, configurable: true, writable: true}}); }} catch (_) {{}}
  }};
  [
    'DateTimeFormat', 'NumberFormat', 'Collator', 'PluralRules',
    'RelativeTimeFormat', 'ListFormat', 'Segmenter',
    'DisplayNames', 'DurationFormat', 'Locale'
  ].forEach((name) => patchIntlConstructor(name));
}})();
"""


def _send_cdp(cdp: Any, method: str, params: dict[str, Any], *, session_id: str) -> None:
    if hasattr(cdp, "send_command"):
        cdp.send_command(method, params, session_id=session_id)
        return
    cdp._send(method, params, session_id=session_id)
