# Orangelink Browser Acceptance Matrix

This checklist mirrors the product contract in `docs/ORANGELINK_BROWSER_REQUIREMENTS.md`.
Each packaged validation report must contain one result object for every ID below.

| ID | Priority | Scenario | Success summary |
| --- | --- | --- | --- |
| A1 | P0 | Packaged GUI launch | Packaged app launches and opens a usable browser page. |
| A2 | P0 | Current page network | Current page reaches public IP check and Google. |
| A3 | P0 | Repeated tabs | At least three user-created tabs reach required pages. |
| A4 | P0 | Keyboard tabs | Shortcut-created tabs behave like the first page. |
| A5 | P0 | Manual Google search | Browser UI search reaches results or robot verification. |
| A6 | P0 | Popup/new window | Popup or new window keeps required network behavior. |
| A7 | P0 | Exit cleanup | Stop and exit leave normal Windows networking usable. |
| A8 | P0 | Validation isolation | Validation does not close or break a user session. |
| A9 | P1 | browserscan.net detection | Detection page loads and remains inspectable. |
| A10 | P1 | Window resize | Browser and GUI remain usable after resize operations. |
| A11 | P1 | Multi-session | Two sessions browse independently. |
| A12 | P1 | Invalid proxy | Unavailable proxy fails quickly with a clear error. |
| A13 | P0 | Proxy loss fail-closed | Proxy loss does not fall back to the local network. |
| A14 | P1 | Performance baseline | Five sessions remain usable on the baseline Windows host. |
| A15 | P1 | Portable data warning | Local data risk is visible and cleanup is available. |
| A16 | P1 | Fingerprint scope | Required fingerprint dimensions are visible and consistent. |
| A17 | P1 | Engine version consistency | Actual and claimed browser versions are disclosed and compatible. |
| A18 | P1 | Extension isolation | Extensions persist only in the intended session profile. |

## Report Contract

The report root must contain package metadata, browser engine metadata, network proxy mode,
`verification_skipped`, and `results`. Failed checks must include `detail` and
`failure_class`. Failed P1 checks must include `user_impact` before the package can be
considered eligible for release decision review.
