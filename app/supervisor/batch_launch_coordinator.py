from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from typing import Any

from app.core import events
from app.core.config import get_settings
from app.core.schemas import ProxyConfigContract


@dataclass(slots=True)
class LaunchDecision:
    profile_id: int
    status: str
    reason: str | None = None
    final_runtime_config: dict[str, Any] | None = None


@dataclass(slots=True)
class WorkerLaunchResult:
    ok: bool
    worker_pid: int | None = None
    error_code: str | None = None
    error_message: str | None = None


class BatchLaunchCoordinator:
    def __init__(
        self,
        repository: Any,
        template_resolver: Any,
        proxy_reuse_guard: Any,
        resource_governor: Any,
        worker_manager: Any,
        max_parallel: int = 5,
        detection_api_url: str = "http://127.0.0.1:8765/probe",
    ) -> None:
        self.repository = repository
        self.template_resolver = template_resolver
        self.proxy_reuse_guard = proxy_reuse_guard
        self.resource_governor = resource_governor
        self.worker_manager = worker_manager
        self.max_parallel = max_parallel
        self.detection_api_url = detection_api_url

    def launch_batch(self, profile_ids: Iterable[int], template_id: int | None = None) -> dict[str, Any]:
        profile_ids = [int(x) for x in profile_ids]
        batch = self.repository.create_launch_batch(profile_ids=profile_ids, template_id=template_id, max_parallel=self.max_parallel)
        batch_id = int(batch["id"])
        self.repository.record_audit_event(events.BATCH_LAUNCH_REQUESTED, batch_id=batch_id, payload={"profile_ids": profile_ids})

        profiles = {p["id"]: p for p in self.repository.get_profiles(profile_ids)}
        template = self.repository.get_profile_template(template_id) if template_id else None
        defaults = self.repository.get_system_defaults()

        active_proxy_keys = set(self.repository.get_active_proxy_keys())
        decisions: list[LaunchDecision] = []

        for profile_id in profile_ids:
            profile = profiles.get(profile_id)
            if not profile:
                decisions.append(LaunchDecision(profile_id=profile_id, status="skipped", reason="profile_not_found"))
                continue

            final_runtime_config = self.template_resolver.resolve(
                defaults=defaults,
                template=template["config_json"] if template else {},
                profile_overrides=profile.get("profile_template_overrides_json") or {},
            )
            resolved_config = final_runtime_config.final_runtime_config

            proxy_validation = self._validate_proxy_config(resolved_config)
            if proxy_validation is not None:
                decisions.append(
                    LaunchDecision(profile_id=profile_id, status="skipped", reason=proxy_validation, final_runtime_config=resolved_config)
                )
                self.repository.record_audit_event(
                    events.BATCH_ITEM_SKIPPED_PROXY_FAILURE,
                    batch_id=batch_id,
                    profile_id=profile_id,
                    payload={"reason": proxy_validation},
                )
                continue

            proxy_key = self._proxy_key_from_runtime_config(resolved_config)
            reuse_result = self.proxy_reuse_guard.decide(
                proxy_key=proxy_key or "none",
                allow_proxy_reuse=bool(profile.get("allow_proxy_reuse", False)),
                active_proxy_keys=active_proxy_keys,
            )
            if not reuse_result.allowed:
                decisions.append(
                    LaunchDecision(profile_id=profile_id, status="skipped", reason=reuse_result.reason, final_runtime_config=resolved_config)
                )
                self.repository.record_audit_event(
                    events.BATCH_ITEM_SKIPPED_PROXY_REUSE_CONFLICT,
                    batch_id=batch_id,
                    profile_id=profile_id,
                    payload={"reason": reuse_result.reason},
                )
                continue

            if proxy_key:
                active_proxy_keys.add(proxy_key)

            decisions.append(LaunchDecision(profile_id=profile_id, status="pending", final_runtime_config=resolved_config))

        self.repository.update_batch_status(batch_id=batch_id, status="running")
        item_records = []
        for decision in decisions:
            item = self.repository.create_batch_item(
                batch_id=batch_id,
                profile_id=decision.profile_id,
                status=decision.status,
                error_message=decision.reason,
                final_runtime_config_json=decision.final_runtime_config or {},
            )
            item_records.append(item)

        launchable = [r for r in item_records if r["status"] == "pending"]
        parallel_limit = self.resource_governor.next_dispatch_count(
            current_running=len(self.worker_manager.active_pids()),
            pending_count=len(launchable),
        )
        start_count = parallel_limit

        for item in launchable[:start_count]:
            self.repository.update_batch_item_status(batch_item_id=item["id"], status="launching")
            result = self._launch_worker(item)
            if result.ok:
                self.repository.update_batch_item_status(
                    batch_item_id=item["id"],
                    status="running",
                    worker_pid=result.worker_pid,
                )
                self.repository.record_runtime_process(
                    profile_id=item["profile_id"],
                    worker_pid=result.worker_pid,
                    batch_id=batch_id,
                    process_role="worker",
                )
            else:
                self.repository.update_batch_item_status(
                    batch_item_id=item["id"],
                    status="failed",
                    error_code=result.error_code,
                    error_message=result.error_message,
                )

        return self.finalize_batch(batch_id)

    def finalize_batch(self, batch_id: int) -> dict[str, Any]:
        items = self.repository.list_batch_items(batch_id)
        counts = {
            "running": sum(1 for x in items if x["status"] == "running"),
            "failed": sum(1 for x in items if x["status"] == "failed"),
            "skipped": sum(1 for x in items if x["status"] == "skipped"),
            "pending": sum(1 for x in items if x["status"] == "pending"),
            "launching": sum(1 for x in items if x["status"] == "launching"),
            "stopped": sum(1 for x in items if x["status"] == "stopped"),
        }

        if counts["running"] > 0 or counts["launching"] > 0 or counts["pending"] > 0:
            status = "running"
        elif counts["failed"] > 0 and (counts["running"] == 0 and counts["stopped"] == 0):
            status = "failed"
        elif counts["failed"] > 0 or counts["skipped"] > 0:
            status = "partial_success"
            self.repository.record_audit_event(events.BATCH_COMPLETED_PARTIAL_SUCCESS, batch_id=batch_id, payload={"counts": counts})
        else:
            status = "completed"

        summary = {"counts": counts}
        self.repository.finalize_launch_batch(batch_id=batch_id, status=status, summary_json=summary)
        return {"batch_id": batch_id, "status": status, "summary": summary, "items": items}

    def dispatch_pending(self, batch_id: int) -> int:
        items = self.repository.list_batch_items(batch_id)
        pending = [x for x in items if x["status"] == "pending"]
        if not pending:
            return 0

        available = self.resource_governor.next_dispatch_count(
            current_running=len(self.worker_manager.active_pids()),
            pending_count=len(pending),
        )
        started = 0
        for item in pending[:available]:
            self.repository.update_batch_item_status(batch_item_id=item["id"], status="launching")
            result = self._launch_worker(item)
            if result.ok:
                started += 1
                self.repository.update_batch_item_status(
                    batch_item_id=item["id"],
                    status="running",
                    worker_pid=result.worker_pid,
                )
                self.repository.record_runtime_process(
                    profile_id=item["profile_id"],
                    worker_pid=result.worker_pid,
                    batch_id=batch_id,
                    process_role="worker",
                )
            else:
                self.repository.update_batch_item_status(
                    batch_item_id=item["id"],
                    status="failed",
                    error_code=result.error_code,
                    error_message=result.error_message,
                )
        return started

    def _launch_worker(self, item: dict[str, Any]) -> WorkerLaunchResult:
        try:
            settings = get_settings()
            runtime_config = dict(item["final_runtime_config_json"])
            browser_cfg = runtime_config.get("browser") if isinstance(runtime_config.get("browser"), dict) else {}
            proxy_cfg = runtime_config.get("proxy") if isinstance(runtime_config.get("proxy"), dict) else {}

            runtime_config["profile_id"] = str(item["profile_id"])
            runtime_config.setdefault("user_data_dir", f"data/profiles/{item['profile_id']}")
            runtime_config.setdefault("start_url", browser_cfg.get("start_url", "about:blank"))
            runtime_config.setdefault("headless", bool(browser_cfg.get("headless", False)))
            runtime_config.setdefault("locale", browser_cfg.get("locale", "en-US"))
            runtime_config.setdefault("timezone_id", browser_cfg.get("timezone_id", "UTC"))
            runtime_config.setdefault("auto_timezone", bool(browser_cfg.get("auto_timezone", True)))
            runtime_config.setdefault("auto_locale", bool(browser_cfg.get("auto_locale", True)))
            runtime_config.setdefault("timezone_probe_url", browser_cfg.get("timezone_probe_url", "https://www.browserscan.net/zh"))
            timeout_value = browser_cfg.get("timezone_probe_timeout_ms", 20000)
            try:
                timeout_ms = int(timeout_value)
            except (TypeError, ValueError):
                timeout_ms = 20000
            runtime_config.setdefault("timezone_probe_timeout_ms", timeout_ms)
            runtime_config.setdefault("user_agent", browser_cfg.get("user_agent"))
            runtime_config.setdefault(
                "chrome_executable_path",
                browser_cfg.get("chrome_executable_path", str(settings.chrome_executable_path)),
            )
            runtime_config.setdefault("proxy_server", self._proxy_key_from_runtime_config(runtime_config))
            credentials = proxy_cfg.get("credentials") if isinstance(proxy_cfg.get("credentials"), dict) else {}
            runtime_config.setdefault("proxy_username", credentials.get("username"))
            runtime_config.setdefault("proxy_password", credentials.get("password"))
            runtime_config.setdefault("scoring_api_url", self.detection_api_url)
            runtime_config.setdefault(
                "launch_args",
                [
                    "--disable-blink-features=AutomationControlled",
                    "--no-first-run",
                    "--no-default-browser-check",
                    "--disable-dev-shm-usage",
                    "--webrtc-ip-handling-policy=disable_non_proxied_udp",
                    "--force-webrtc-ip-handling-policy=disable_non_proxied_udp",
                    "--disable-features=AsyncDns,DnsOverHttps,UseDnsHttpsSvcb",
                    "--proxy-bypass-list=<-loopback>",
                ],
            )
            record = self.worker_manager.spawn(str(item["profile_id"]), runtime_config)
            return WorkerLaunchResult(ok=True, worker_pid=record.pid)
        except Exception as exc:  # noqa: BLE001
            return WorkerLaunchResult(ok=False, error_code="worker_boot_failure", error_message=str(exc))

    @staticmethod
    def _validate_proxy_config(runtime_config: dict[str, Any]) -> str | None:
        proxy_section = runtime_config.get("proxy")
        if proxy_section is None:
            return None
        if not isinstance(proxy_section, dict):
            return "proxy_section_invalid"
        try:
            ProxyConfigContract.model_validate(proxy_section)
        except Exception as exc:  # noqa: BLE001
            return str(exc)
        return None

    @staticmethod
    def _proxy_key_from_runtime_config(runtime_config: dict[str, Any]) -> str | None:
        proxy = runtime_config.get("proxy")
        if not isinstance(proxy, dict):
            return None
        host = proxy.get("proxy_host")
        port = proxy.get("proxy_port")
        scheme = proxy.get("scheme", "http")
        if not host or not port:
            return None
        return f"{scheme}://{host}:{port}"
