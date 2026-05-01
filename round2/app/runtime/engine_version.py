from __future__ import annotations

import re
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path


VERSION_RE = re.compile(r"(?P<family>Chromium|Google Chrome|Chrome)\s+(?P<version>\d+(?:\.\d+)+)")


class EngineVersionError(ValueError):
    pass


@dataclass(frozen=True)
class BrowserEngineVersion:
    family: str
    major: int
    full_version: str


def parse_chromium_version_output(output: str) -> BrowserEngineVersion:
    match = VERSION_RE.search(output.strip())
    if match is None:
        raise EngineVersionError(f"无法识别浏览器内核版本: {output}")

    family = match.group("family")
    if family == "Google Chrome":
        family = "Chrome"
    full_version = match.group("version")
    return BrowserEngineVersion(
        family=family,
        major=int(full_version.split(".", 1)[0]),
        full_version=full_version,
    )


def read_chromium_version(chrome_executable: Path) -> BrowserEngineVersion:
    try:
        result = subprocess.run(
            [str(chrome_executable), "--version"],
            check=True,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
        try:
            return parse_chromium_version_output(result.stdout or result.stderr)
        except EngineVersionError as exc:
            return _read_chromium_file_version_or_raise(chrome_executable, exc)
    except (OSError, subprocess.CalledProcessError, UnicodeDecodeError) as exc:
        return _read_chromium_file_version_or_raise(chrome_executable, exc)


def ensure_claim_compatible(
    actual: BrowserEngineVersion,
    *,
    claimed_family: str,
    claimed_major: int,
) -> None:
    if claimed_major > actual.major:
        raise EngineVersionError(
            "浏览器版本声明不能高于实际内核版本: "
            f"claimed={claimed_family} {claimed_major}, actual={actual.family} {actual.major}"
        )


def build_engine_report_metadata(
    *,
    actual: BrowserEngineVersion,
    claimed_family: str,
    claimed_major: int,
    package_version: str,
    package_build_date: str,
) -> dict:
    ensure_claim_compatible(
        actual,
        claimed_family=claimed_family,
        claimed_major=claimed_major,
    )
    return {
        "browser_engine": {
            "actual_family": actual.family,
            "actual_major_version": actual.major,
            "actual_version": actual.full_version,
            "claimed_family": claimed_family,
            "claimed_major_version": claimed_major,
        },
        "package": {
            "version": package_version,
            "build_date": package_build_date,
        },
    }


def _read_chromium_file_version_or_raise(
    chrome_executable: Path,
    exc: Exception,
) -> BrowserEngineVersion:
    file_version = _read_windows_file_version(chrome_executable)
    if file_version:
        return BrowserEngineVersion(
            family="Chromium",
            major=int(file_version.split(".", 1)[0]),
            full_version=file_version,
        )
    raise EngineVersionError(f"无法读取浏览器内核版本: {chrome_executable}") from exc


def _read_windows_file_version(executable: Path) -> str | None:
    if sys.platform != "win32":
        return None

    try:
        import ctypes
        from ctypes import wintypes

        version_dll = ctypes.WinDLL("version", use_last_error=True)
        size = version_dll.GetFileVersionInfoSizeW(str(executable), None)
        if not size:
            return None

        buffer = ctypes.create_string_buffer(size)
        if not version_dll.GetFileVersionInfoW(str(executable), 0, size, buffer):
            return None

        value = ctypes.c_void_p()
        value_len = wintypes.UINT()
        if not version_dll.VerQueryValueW(
            buffer,
            "\\",
            ctypes.byref(value),
            ctypes.byref(value_len),
        ):
            return None

        class VS_FIXEDFILEINFO(ctypes.Structure):
            _fields_ = [
                ("dwSignature", wintypes.DWORD),
                ("dwStrucVersion", wintypes.DWORD),
                ("dwFileVersionMS", wintypes.DWORD),
                ("dwFileVersionLS", wintypes.DWORD),
                ("dwProductVersionMS", wintypes.DWORD),
                ("dwProductVersionLS", wintypes.DWORD),
                ("dwFileFlagsMask", wintypes.DWORD),
                ("dwFileFlags", wintypes.DWORD),
                ("dwFileOS", wintypes.DWORD),
                ("dwFileType", wintypes.DWORD),
                ("dwFileSubtype", wintypes.DWORD),
                ("dwFileDateMS", wintypes.DWORD),
                ("dwFileDateLS", wintypes.DWORD),
            ]

        fixed_info = ctypes.cast(value, ctypes.POINTER(VS_FIXEDFILEINFO)).contents
        major = fixed_info.dwFileVersionMS >> 16
        minor = fixed_info.dwFileVersionMS & 0xFFFF
        build = fixed_info.dwFileVersionLS >> 16
        patch = fixed_info.dwFileVersionLS & 0xFFFF
        if not major:
            return None
        return f"{major}.{minor}.{build}.{patch}"
    except Exception:
        return None
