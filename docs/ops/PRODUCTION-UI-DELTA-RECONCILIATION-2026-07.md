# PROD-UI-DELTA-1 Reconciliation Record

## Scope and method

- BASE: `deb22620f792e68d8c2ccd86218510420733be97`
- TARGET branch start: `ebe2b3b34099dabdb3b64dd0c5aad7584c8dc93d`
- Verified archive SHA256: `f25db4671a2c49d38e2f063d4a422b739c42c08236ac38a61421982c91db4448`

The archive was inspected before extraction. Its single package wrapper contained
exactly the 15 approved files, `delta-manifest.json`, and `README.txt`; there
were no absolute or traversal paths, symlinks, duplicate entries, or unexpected
payload files. Each payload size and SHA256 matched the manifest. The manifest
matched the required BASE and TARGET commits, and its sensitive rescan gate
passed with zero concrete credential findings and zero quoted-secret-literal
findings.

Each file was compared as BASE -> archive and BASE -> TARGET. The archive's HTML
changes only move static-resource cache query values. This is inferred to request
a browser refresh of the same static resources; it does not change page markup,
inline JavaScript behavior, routes, permissions, request contracts, or visual
rules. TARGET contains later behavior and security-compatible UI work, so its
cache values and all TARGET content are preserved. The two SVGs differ from BASE
only by line-ending representation. Git-normalized content is identical to
TARGET; any raw working-tree difference is limited to platform line-ending
representation.

## 15-file reconciliation matrix

| File | Production-only intent found | TARGET-only behavior preserved | Overlap resolution | Production result | Reason | Test coverage |
| --- | --- | --- | --- | --- | --- | --- |
| `static/angle.html` | Static cache-query refresh only | Cloud/local upload decoupling and submit-state guard | Kept TARGET cache values and code | Dropped | Reverting would remove current safe upload behavior | `test_angle_enhance_upload_decouple.py`, `test_upload_isolation.py` |
| `static/api-settings.html` | Static cache-query refresh only | Settings entry/permission guard and current upstream API-settings shell | Kept TARGET cache values and markup | Dropped | Preserves gated settings access, upstream synchronization, and secret-safe UI | `test_settings_entry_ux_guard.py`, `test_settings_permission_guard.py`, `test_api_settings_upstream_sync.py` |
| `static/asset-manager.html` | Static cache-query refresh only | Current asset-manager page contract | Kept TARGET cache values and markup | Dropped | No production behavior beyond cache versioning; TARGET remains compatible with asset isolation | `test_asset_library_isolation.py`, `test_upload_isolation.py` |
| `static/canvas-list.html` | Static cache-query refresh only | Current touch/mouse support and canvas-list contract | Kept TARGET cache values and imports | Dropped | TARGET has later interaction support and must remain current | `test_ownership_isolation.py`, `test_websocket_isolation.py` |
| `static/canvas.html` | Static cache-query refresh only | Touch support, collapsed toolbar default, arrange and image-edit controls | Kept TARGET cache values, markup, and routes | Dropped | TARGET is the newer compatible UI surface | `test_ownership_isolation.py`, `test_upload_isolation.py` |
| `static/comfyui-settings.html` | Static cache-query refresh only | Current settings-page contract and target resource references | Kept TARGET cache values and markup | Dropped | No functional production delta exists to port | `test_settings_permission_guard.py`, `test_feature_flags.py` |
| `static/enhance.html` | Static cache-query refresh only | ModelScope/local upload decoupling and provider-specific input guard | Kept TARGET cache values and code | Dropped | Reverting would weaken the current safe upload flow | `test_angle_enhance_upload_decouple.py`, `test_upload_isolation.py` |
| `static/gpt-chat.html` | Static cache-query refresh only | Current chat page resource references and enterprise-compatible surface | Kept TARGET cache values and markup | Dropped | Archive carries no chat behavior change | `test_task_history_isolation.py`, `test_websocket_isolation.py` |
| `static/index.html` | Iframe/static cache-query refresh only | Settings UX guard, feature-gated navigation, frame synchronization, and current layout behavior | Kept TARGET iframe/resource values and shell code | Dropped | TARGET controls protected settings entry and current frame behavior | `test_settings_entry_ux_guard.py`, `test_feature_flags.py`, `test_settings_permission_guard.py` |
| `static/klein.html` | Static cache-query refresh only | Explicit `klein` request/history type contract | Kept TARGET cache values and request payload | Dropped | Preserves normalized history typing and isolation compatibility | `test_history_type_consistency.py`, `test_history_isolation.py` |
| `static/online.html` | Static cache-query refresh only | Current RunningHub model/app/workflow selection contract | Kept TARGET cache values and selection behavior | Dropped | TARGET contains later compatible provider-selection behavior | `test_feature_flags.py`, `test_history_isolation.py` |
| `static/smart-canvas.html` | Static cache-query refresh only | Touch support, arrange/image-edit controls, and current log-compatible markup | Kept TARGET cache values, imports, and markup | Dropped | TARGET behavior is newer and Smart Canvas log compatibility must remain intact | `test_smart_canvas_logs.js` |
| `static/zimage.html` | Static cache-query refresh only | Explicit `zimage` request/history type contract | Kept TARGET cache values and request payload | Dropped | Preserves normalized history typing and isolation compatibility | `test_history_type_consistency.py`, `test_history_isolation.py` |
| `static/images/volcengine-theme-dark.svg` | Line-ending representation only; no visual change | Git-normalized content is identical to TARGET; any raw working-tree difference is limited to platform line-ending representation | No content conflict | Retained (Git-normalized identical) | No repository edit is needed | Archive manifest/hash verification |
| `static/images/volcengine-theme-light.svg` | Line-ending representation only; no visual change | Git-normalized content is identical to TARGET; any raw working-tree difference is limited to platform line-ending representation | No content conflict | Retained (Git-normalized identical) | No repository edit is needed | Archive manifest/hash verification |

## Result and validation

No scoped static file needs modification: the archive does not contain a
production-only behavior that can be safely or meaningfully ported onto TARGET.
This intentionally preserves all current authentication, role compatibility,
settings guards, feature flags, upload/asset/canvas/history/conversation/WebSocket
isolation, server-token preference, and API request/response contracts.

Executed locally without production data, production access, external model calls,
deployment, runtime workflow files, database changes, or migration changes:

- All 21 Python scripts discovered at `enterprise/tests/test_*.py` were invoked.
  Eighteen passed. `test_sec_1b1_role_auth.py`,
  `test_sec_1b2_activation_bootstrap.py`, and
  `test_sec_1c0_super_admin_protection.py` were blocked before their checks ran
  because the local Python environment lacks the `jwt` module (PyJWT).
- `node enterprise/tests/test_smart_canvas_logs.js` passed.

No focused regression test was added because no archive behavior was retained or
adapted. A final changed-file secret scan, scope check, and conflict-marker check
were completed before commit and passed.
