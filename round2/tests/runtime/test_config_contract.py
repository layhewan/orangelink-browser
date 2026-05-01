from __future__ import annotations

import shutil
from pathlib import Path

import pytest


def test_launch_config_defaults_cover_required_fields() -> None:
    from app.runtime.config import LaunchConfig

    config = LaunchConfig(name="Default")

    assert config.name == "Default"
    assert config.proxy_enabled is False
    assert config.proxy_protocol == "http"
    assert config.proxy_host == ""
    assert config.proxy_port is None
    assert config.start_page
    assert config.automatic_language is True
    assert config.manual_language == "en-US"
    assert config.automatic_timezone is True
    assert config.manual_timezone == "UTC"
    assert config.os_fingerprint == "windows"
    assert config.extension_support is True


@pytest.mark.parametrize(
    ("kwargs", "message"),
    [
        ({"name": "   "}, "配置名称不能为空"),
        (
            {"name": "Proxy", "proxy_enabled": True, "proxy_host": ""},
            "代理主机不能为空",
        ),
        (
            {
                "name": "Proxy",
                "proxy_enabled": True,
                "proxy_host": "127.0.0.1",
                "proxy_port": 0,
            },
            "代理端口必须在 1 到 65535 之间",
        ),
        (
            {
                "name": "Proxy",
                "proxy_enabled": True,
                "proxy_protocol": "ftp",
                "proxy_host": "127.0.0.1",
                "proxy_port": 7890,
            },
            "代理协议必须是 http、https 或 socks5",
        ),
        (
            {"name": "Manual", "automatic_language": False, "manual_language": "english"},
            "手动语言必须类似 en 或 en-US",
        ),
        (
            {"name": "Manual", "automatic_timezone": False, "manual_timezone": ""},
            "手动时区不能为空",
        ),
    ],
)
def test_launch_config_rejects_invalid_required_fields(
    kwargs: dict, message: str
) -> None:
    from app.runtime.config import LaunchConfig, ValidationError

    with pytest.raises(ValidationError) as exc_info:
        LaunchConfig(**kwargs)

    assert message in str(exc_info.value)


def test_launch_config_accepts_manual_language_forms() -> None:
    from app.runtime.config import LaunchConfig

    assert LaunchConfig(
        name="Language",
        automatic_language=False,
        manual_language="en",
    ).manual_language == "en"
    assert LaunchConfig(
        name="Language",
        automatic_language=False,
        manual_language="zh-CN",
    ).manual_language == "zh-CN"


@pytest.mark.parametrize("protocol", ["http", "https", "socks5"])
def test_launch_config_accepts_supported_proxy_protocols(protocol: str) -> None:
    from app.runtime.config import LaunchConfig

    config = LaunchConfig(
        name="Proxy",
        proxy_enabled=True,
        proxy_protocol=protocol,
        proxy_host="127.0.0.1",
        proxy_port=7897,
    )

    assert config.proxy_protocol == protocol


def test_portable_paths_are_created_under_base_data() -> None:
    from app.runtime.config import resolve_portable_paths

    base = Path(__file__).resolve().parent / "_tmp_portable_base"
    shutil.rmtree(base, ignore_errors=True)

    try:
        paths = resolve_portable_paths(base=base, create=True)

        assert paths.base == base
        assert paths.data == base / "data"
        assert paths.configs == base / "data" / "configs"
        assert paths.profiles == base / "data" / "profiles"
        assert paths.logs == base / "data" / "logs"
        assert paths.reports == base / "data" / "reports"
        assert paths.homepage == base / "data" / "homepage"
        for path in paths.required_directories:
            assert path.is_dir()
            assert path.resolve().is_relative_to((base / "data").resolve())
    finally:
        shutil.rmtree(base, ignore_errors=True)


def test_portable_paths_default_to_repository_root_when_not_frozen() -> None:
    from app.runtime.config import resolve_portable_paths

    paths = resolve_portable_paths(create=False)

    assert paths.base == Path(__file__).resolve().parents[2]
    assert paths.data == paths.base / "data"
