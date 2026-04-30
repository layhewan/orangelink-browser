# Release Runbook

Run this sequence from the `round2` folder before treating any portable package as a release candidate.

```powershell
python -m pytest tests -q
cargo test --manifest-path relay\Cargo.toml
powershell -ExecutionPolicy Bypass -File scripts\build_portable.ps1 -OutputDir final_exe_rc -VerifyProxyServer http://127.0.0.1:7897
.\final_exe_rc\脐橙浏览器.exe --gui-runtime-e2e --profile-id release-final --user-data-dir data\release-final-profile --chrome-executable-path runtime\chromium\chrome.exe --proxy-server http://127.0.0.1:7897 --start-url https://www.google.com/search?q=orangelink+release+final&hl=en --ip-check-url https://api.ipify.org?format=json --shortcut-tabs 3 --google-searches 3 --manual-ui-google-pages --headful --report-file data\release-final-report.json
```

Release review requires:

- A1-A8 and A13 pass.
- Failed P1 items include user impact and a release decision.
- `data\release-final-report.json` includes package, engine, claimed browser, proxy, and build metadata.
- Stopping and exiting the packaged app leaves normal Windows networking usable.
- No known issue reproduces first tab working while later user-created tabs fail.
