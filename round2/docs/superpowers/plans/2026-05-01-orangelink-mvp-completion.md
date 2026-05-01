# Orangelink MVP Completion Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Complete the MVP around selectable local proxy protocols, persistent fingerprint profiles, GUI session control, app icon packaging, and timezone alignment.

**Architecture:** Keep Chromium behind a local relay so the GUI can own diagnostics and logs. Saved configs map one-to-one to persistent profile directories. The PySide6 GUI becomes a compact workbench with config list, editor, running sessions, and diagnostics.

**Tech Stack:** Python 3.10, PySide6, Rust std relay, PyInstaller onedir, pytest, cargo test.

---

### Task 1: Proxy Protocol Support

**Files:**
- Modify: `app/runtime/config.py`
- Modify: `app/runtime/proxy_contract.py`
- Modify: `relay/src/main.rs`
- Test: `tests/runtime/test_config_contract.py`
- Test: `tests/runtime/test_proxy_contract.py`
- Test: `relay/tests/fail_closed.rs`

- [ ] Add failing tests for `http`, `https`, and `socks5` protocols.
- [ ] Make config accept exactly those protocols.
- [ ] Treat `https` as an HTTP CONNECT proxy scheme for local-port compatibility.
- [ ] Add SOCKS5 upstream CONNECT handling in relay.
- [ ] Run runtime proxy tests and relay tests.

### Task 2: Persistent Config Profiles

**Files:**
- Modify: `app/desktop/state_store.py`
- Modify: `app/runtime/session_manager.py`
- Modify: `app/desktop/window.py`
- Test: `tests/desktop/test_state_store.py`
- Test: `tests/runtime/test_session_lifecycle.py`
- Test: `tests/desktop/test_window_models.py`

- [ ] Add tests for saved config profile reuse and one running instance per saved config.
- [ ] Wire saved config launch to `ProfileManager.saved_config_profile`.
- [ ] Add GUI actions for create, save, duplicate, delete, launch, stop.
- [ ] Keep dangerous profile deletion explicit.

### Task 3: Timezone Alignment

**Files:**
- Create: `app/runtime/proxy_geo.py`
- Modify: `app/runtime/fingerprint.py`
- Modify: `app/desktop/window.py`
- Test: `tests/runtime/test_proxy_geo.py`
- Test: `tests/runtime/test_fingerprint_contract.py`

- [ ] Add proxy-aware geo probe abstraction with injectable opener.
- [ ] Cache timezone/language on saved configs when available.
- [ ] Keep manual timezone override available.
- [ ] Apply cached or manual timezone via existing CDP path.

### Task 4: GUI and Icon Polish

**Files:**
- Modify: `app/desktop/window.py`
- Modify: `scripts/build_portable.ps1`
- Modify: `scripts/packaging_contract.py`
- Test: `tests/desktop/test_window_models.py`
- Test: `tests/acceptance/test_packaging_contract.py`

- [ ] Use `app/assets/favicon.ico` as window and PyInstaller icon.
- [ ] Ensure taskbar icon comes from the app icon.
- [ ] Rework layout into config list, editor, session panel, diagnostics log.
- [ ] Keep all external process output in `data/logs`.

### Task 5: Verification and Review

**Files:**
- No production files unless review finds issues.

- [ ] Run `python -m pytest tests -q`.
- [ ] Run `cargo test --manifest-path relay\Cargo.toml`.
- [ ] Build `final_exe_rc`.
- [ ] Validate portable contract.
- [ ] Run packaged GUI smoke and proxy smoke as far as the local environment allows.
- [ ] Spawn a reviewer for functionality and simplicity review, then fix actionable findings.
