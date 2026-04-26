from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=(".env.local", ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    app_name: str = "privacy-browser-framework"
    log_level: str = "INFO"
    data_dir: Path = Path("./data")
    db_file: Path = Path("./data/privacy_browser.db")

    max_parallel_workers: int = 5
    default_proxy_host: str = "127.0.0.1"
    default_proxy_port: int = Field(default=7897, ge=1, le=65535)

    detection_host: str = "127.0.0.1"
    detection_port: int = 8765
    gui_host: str = "127.0.0.1"
    gui_port: int = 8088

    playwright_browsers_path: Path = Path(".playwright")
    chrome_executable_path: Path = Path(".playwright/chrome-win64/chrome.exe")

    worker_heartbeat_interval_sec: int = 5
    worker_heartbeat_timeout_sec: int = 20

    @property
    def db_url(self) -> str:
        return f"sqlite:///{self.db_file.resolve().as_posix()}"

    def ensure_runtime_dirs(self) -> None:
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.playwright_browsers_path.mkdir(parents=True, exist_ok=True)


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    settings = Settings()
    settings.ensure_runtime_dirs()
    return settings

