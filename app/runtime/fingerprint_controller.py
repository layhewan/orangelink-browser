from __future__ import annotations

import threading
from typing import Any, Callable

from app.runtime.fingerprint import FingerprintProfile, apply_fingerprint_overrides


class BrowserFingerprintController:
    def __init__(
        self,
        *,
        connection_factory: Callable[[], Any],
        profile: FingerprintProfile,
        start_url: str,
    ) -> None:
        self._connection_factory = connection_factory
        self._profile = profile
        self._start_url = start_url
        self._ready = threading.Event()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._connection: Any | None = None
        self._startup_error: BaseException | None = None

    def start(self) -> None:
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def wait_ready(self, *, timeout_s: float) -> None:
        if not self._ready.wait(timeout_s):
            raise TimeoutError("fingerprint controller did not become ready")
        if self._startup_error is not None:
            raise RuntimeError("fingerprint controller failed to start") from self._startup_error

    def stop(self) -> None:
        self._stop.set()
        connection = self._connection
        if connection is not None:
            _close_quietly(connection)
        if self._thread is not None:
            self._thread.join(timeout=2)

    def _run(self) -> None:
        try:
            connection = self._connection_factory()
            self._connection = connection

            start_session_id = apply_existing_page_targets(connection, self._profile)
            enable_target_auto_attach(connection)
            if start_session_id is not None:
                navigate_start_page(connection, start_session_id, self._start_url)
            set_timeout = getattr(connection, "set_timeout", None)
            if callable(set_timeout):
                set_timeout(0.5)
            self._ready.set()

            while not self._stop.is_set():
                try:
                    message = connection.recv_message()
                except TimeoutError:
                    continue
                except OSError:
                    if self._stop.is_set():
                        break
                    raise
                handle_auto_attached_target(connection, self._profile, message)
        except BaseException as exc:
            self._startup_error = exc
            self._ready.set()
        finally:
            connection = self._connection
            if connection is not None:
                _close_quietly(connection)


def apply_existing_page_targets(cdp: Any, profile: FingerprintProfile) -> str | None:
    first_page_session: str | None = None
    for target in cdp.list_targets():
        if target.type != "page":
            continue
        page = cdp.attach_to_target(target.target_id)
        apply_fingerprint_overrides(cdp, page.session_id, profile)
        if first_page_session is None:
            first_page_session = page.session_id

    return first_page_session


def navigate_start_page(cdp: Any, session_id: str, start_url: str) -> None:
    try:
        cdp.navigate(session_id, start_url)
    except TimeoutError:
        return


def enable_target_auto_attach(cdp: Any) -> None:
    cdp.send_command(
        "Target.setAutoAttach",
        {
            "autoAttach": True,
            "waitForDebuggerOnStart": True,
            "flatten": True,
        },
    )


def handle_auto_attached_target(cdp: Any, profile: FingerprintProfile, message: dict[str, Any]) -> bool:
    if message.get("method") != "Target.attachedToTarget":
        return False

    params = message.get("params", {})
    session_id = params.get("sessionId")
    target_info = params.get("targetInfo", {})
    if not session_id:
        return False

    try:
        if target_info.get("type") == "page":
            apply_fingerprint_overrides(cdp, session_id, profile)
    except Exception:
        pass

    try:
        cdp.send_command("Runtime.runIfWaitingForDebugger", {}, session_id=session_id)
    except Exception:
        return False
    return True


def _close_quietly(connection: Any) -> None:
    close = getattr(connection, "close", None)
    if callable(close):
        try:
            close()
        except Exception:
            return
