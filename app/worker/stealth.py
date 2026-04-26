from __future__ import annotations

from typing import Any

from playwright_stealth import Stealth

STEALTH_INIT_SCRIPT = r"""
for (const key of ['__playwright__binding__', '__pwInitScripts', '__pwManual', '__PW_inspect']) {
  try {
    delete window[key];
  } catch {
    // Ignore read-only globals in some browser builds.
  }
}
"""


def _stealth_for_profile(profile: str) -> Stealth:
    if profile == "strict":
        return Stealth()
    return Stealth(
        navigator_user_agent=False,
        webgl_vendor=False,
    )


def apply_basic_stealth(context: object, *, profile: str = "compat") -> None:
    target: Any = context
    try:
        _stealth_for_profile(profile).apply_stealth_sync(target)
    except Exception:  # noqa: BLE001
        pass

    add_init_script = getattr(target, "add_init_script", None)
    if callable(add_init_script):
        add_init_script(STEALTH_INIT_SCRIPT)
