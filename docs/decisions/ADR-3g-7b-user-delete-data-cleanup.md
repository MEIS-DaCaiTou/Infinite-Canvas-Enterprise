# ADR: Task 3G-7B user delete and enterprise data cleanup

Status: Proposed design

Date: 2026-07-06

Scope: docs-only design for a later implementation. This ADR does not change
runtime code, database schema, upstream files, or enterprise API behavior.

## 1. Background And Goals

Infinite Canvas Enterprise has completed the first enterprise isolation base:
owner isolation, administrator fallback, enterprise gateway interception,
feature flags, WebSocket isolation, task/history isolation, and audit logs.
The project is still not a full organization collaboration or ACL platform.

Current member management already supports:

- Creating users.
- Resetting passwords.
- Editing display names.
- Switching administrator role.
- Enabling and disabling users.
- A backend `DELETE /enterprise/api/users/{id}` route.

The current delete route is a soft disable route: it sets `is_active=0`, writes
a disabled-style audit record, and does not clean owner mappings or runtime data.

3G-7B must fill the product and safety gap for abandoned or departed accounts:

- Provide a clear delete/disable/cleanup product meaning.
- Let administrators safely handle abandoned accounts.
- Preserve the enterprise owner isolation base.
- Never default to physical deletion of runtime files.
- Preserve audit records.
- Support later collaboration/ACL design without pretending this task is that
model.

Missing today:

- Delete impact preview.
- Data cleanup entry.
- Owner transfer capability.
- Feature override cleanup capability.
- Clear "delete user" product semantics.

## 2. Non Goals

This stage does not implement:

- Hard deletion of `users` rows.
- Physical deletion of `assets/`, `output/`, generated images, uploads, caches,
  databases, API keys, tokens, cookies, or env files.
- Batch file garbage collection.
- `team`, `workspace`, `project_members`, `canvas_grants`,
  `asset_library_grants`, or general ACL.
- Complex RBAC.
- Cross-organization collaboration.
- Large upstream `main.py` or `static/` rewrites.
- Provider, ComfyUI, ModelScope, RunningHub, token, key, or model-quality
  environment governance.

## 3. Terms

| Term | Definition |
|---|---|
| disable user | Set `users.is_active=0`. The account cannot authenticate; owned data remains unchanged. |
| soft delete user | Product-level delete that keeps the `users` row and audit trail but disables login. First version should be equivalent to disable plus optional follow-up actions. |
| cleanup enterprise mappings | Remove selected enterprise mapping rows, such as feature overrides or owner rows, without deleting runtime files. |
| transfer owner | Change owner mappings from source user to target active user for selected scopes. |
| archive owned data | Keep owner mappings and runtime data, but treat the account as disabled/archived for operational purposes. |
| dry-run | Read-only impact analysis that returns counts and samples before any destructive or transfer action. |
| runtime files | Files under `assets/`, `output/`, data caches, generated images, uploads, and provider outputs. |
| audit retention | `usage_logs` and relevant actor/target metadata are preserved even if an account is disabled or mappings are cleaned. |

## 4. Product Semantics

### Disable User

Disable is the safest account lifecycle action.

- Set `users.is_active=0`.
- User cannot log in.
- Existing JWT/cookie becomes ineffective because token verification re-checks
  the database user and requires active status.
- No data cleanup happens.
- Owner mappings remain intact.
- Audit event: `user_disabled`.

### Delete User, First Version

The first "delete user" product behavior should remain a soft delete.

- Do not hard-delete the `users` row.
- Do not delete audit logs.
- Do not delete runtime files.
- Do not rewrite `history.json`, canvas JSON, or conversation JSON by default.
- Optionally clear feature overrides.
- Optionally enter cleanup or owner transfer flows after dry-run.
- Recommended audit event: `user_deleted` with `soft_delete=true`, plus
  `user_disabled` only when the operation is literally the existing disable
  action.

This keeps user identity available for audit display and later recovery.

### Cleanup User Data

Cleanup means enterprise-layer cleanup unless a future ADR explicitly adds file
GC.

- Must require dry-run first.
- May remove selected enterprise mapping rows.
- May clear feature overrides.
- Must not physically delete files by default.
- Must write audit before and after high-risk operations.

### Transfer Owner

Transfer changes owner mappings for selected scopes.

Supported scopes should be explicit:

- `projects`
- `canvases`
- `conversations`
- `resources`
- `history`
- `asset_objects`
- `canvas_tasks`
- `tasks`

Rules:

- Target must be an active user.
- Target cannot be missing or disabled.
- Admin actor must be recorded.
- Counts and scopes must be recorded.
- Transfer must not imply shared access or ACL.

## 5. API Design

All APIs are administrator-only and live under `/enterprise/api`.

### GET `/enterprise/api/users/{id}/delete-impact`

Purpose: read-only dry-run impact preview.

Request parameters:

- Path: `id`
- Query optional: `sample_limit=20`

Response draft:

```json
{
  "user": {
    "id": "user_id",
    "username": "user_a",
    "display_name": "User A",
    "is_admin": false,
    "is_active": true
  },
  "counts": {
    "projects": 2,
    "canvases": 8,
    "conversations": 4,
    "resources": 30,
    "history": 12,
    "asset_objects": 9,
    "canvas_tasks": 3,
    "tasks": 5,
    "feature_overrides": 2,
    "audit_logs": 20
  },
  "samples": {
    "canvases": ["canvas_id_1"],
    "resources": ["/assets/input/a.png"]
  },
  "warnings": [
    "Runtime files are not deleted by this operation.",
    "Audit logs are retained."
  ]
}
```

Permissions: admin only.

Audit: recommended to write `user_delete_dry_run`, because viewing deletion
impact is a privileged operation. If implementation chooses not to audit every
preview to reduce noise, it must still audit any preview used as the basis for
cleanup/transfer.

Failures:

- `401` unauthenticated.
- `403` non-admin.
- `404` target user not found.

Forbidden:

- No writes to owner mappings.
- No runtime file operations.

### DELETE `/enterprise/api/users/{id}`

Purpose: explicit soft delete.

Request body draft:

```json
{
  "confirm_username": "user_a",
  "reason": "departed account"
}
```

Response draft:

```json
{
  "success": true,
  "user_id": "user_id",
  "soft_deleted": true,
  "is_active": false
}
```

Permissions: admin only.

Audit: write `user_deleted` with `soft_delete=true`, `target_user_id`,
`target_username`, `reason`, and `updated_by`.

Failures:

- `400` missing confirmation.
- `400` deleting self.
- `400` deleting or disabling the last active administrator.
- `401` unauthenticated.
- `403` non-admin.
- `404` target user not found.

Forbidden:

- Do not hard-delete `users`.
- Do not clean owner mappings.
- Do not delete runtime files.
- Do not delete audit logs.

### POST `/enterprise/api/users/{id}/cleanup-preview`

Purpose: preview selected enterprise cleanup scopes.

Request body draft:

```json
{
  "scopes": [
    "feature_overrides",
    "project_mappings",
    "canvas_mappings",
    "conversation_mappings",
    "history_mappings",
    "asset_object_mappings",
    "task_mappings"
  ],
  "sample_limit": 20
}
```

Response: same shape as delete-impact, scoped to selected cleanup categories.

Permissions: admin only.

Audit: optional `user_data_cleanup_requested` with `dry_run=true`.

Failures: `400` invalid scope, `401`, `403`, `404`.

Forbidden:

- No cleanup execution.
- No runtime file operations.

### POST `/enterprise/api/users/{id}/cleanup`

Purpose: execute selected enterprise mapping cleanup.

Request body draft:

```json
{
  "scopes": ["feature_overrides"],
  "confirm_username": "user_a",
  "dry_run_token": "optional-preview-token",
  "reason": "cleanup after account deletion"
}
```

Response draft:

```json
{
  "success": true,
  "user_id": "user_id",
  "cleaned": {
    "feature_overrides": 2
  },
  "skipped": {
    "usage_logs": "audit logs are retained",
    "runtime_files": "not supported"
  }
}
```

Permissions: admin only.

Audit:

- `user_data_cleanup_requested` before execution.
- `user_data_cleanup_completed` after success.
- `user_data_cleanup_failed` on error.

Failures:

- `400` missing confirmation.
- `400` invalid scope.
- `409` preview token stale, if implemented.
- `500` cleanup failed.

Forbidden:

- Do not delete runtime files.
- Do not delete `usage_logs`.
- Do not rewrite upstream JSON by default.

### POST `/enterprise/api/users/{id}/transfer`

Purpose: transfer owner mappings to another active user.

Request body draft:

```json
{
  "target_user_id": "target_user",
  "scopes": ["projects", "canvases", "resources"],
  "confirm_username": "user_a",
  "reason": "handoff to teammate"
}
```

Response draft:

```json
{
  "success": true,
  "source_user_id": "user_a_id",
  "target_user_id": "target_user",
  "transferred": {
    "projects": 2,
    "canvases": 8,
    "resources": 30
  }
}
```

Permissions: admin only.

Audit:

- Scope-level events such as `user_project_transferred`,
  `user_canvas_transferred`, `user_resource_transferred`.
- Summary event with source, target, scopes, before/after counts.

Failures:

- `400` target disabled.
- `400` target equals source unless explicitly allowed later.
- `400` invalid scope.
- `400` missing confirmation.
- `401`, `403`, `404`.

Forbidden:

- Do not transfer to disabled users.
- Do not create collaboration grants.
- Do not delete files.

### POST `/enterprise/api/users/{id}/purge-overrides`

Purpose: clear `enterprise_user_feature_overrides` for the target user.

Request body draft:

```json
{
  "confirm_username": "user_a",
  "reason": "account cleanup"
}
```

Response draft:

```json
{
  "success": true,
  "user_id": "user_id",
  "deleted_count": 3
}
```

Permissions: admin only.

Audit: `user_feature_overrides_cleared`.

Failures: `400` confirmation missing, `401`, `403`, `404`.

Forbidden:

- Do not change global feature flags.
- Do not change other users' overrides.

## 6. Data Scope Design

| Table | Dry-run count | Cleanup | Transfer | Hard delete | Retain | Audit requirement |
|---|---:|---|---|---|---|---|
| `users` | yes | soft delete only | no | no | yes | `user_deleted` / `user_disabled` |
| `user_project_map` | yes | optional remove mapping | yes | mapping only | optional | `user_project_transferred` or cleanup summary |
| `user_canvas_map` | yes | optional remove mapping | yes | mapping only | optional | `user_canvas_transferred` |
| `user_conversation_map` | yes | optional remove mapping | yes | mapping only | optional | `user_conversation_transferred` |
| `user_resource_map` | yes by prefix | optional remove mapping only | yes | mapping only | optional | `user_resource_transferred`; never physical file deletion |
| `user_canvas_task_map` | yes | optional remove mapping | yes | mapping only | optional | `user_task_transferred` |
| `user_task_map` | yes by task_type | optional remove mapping | yes | mapping only | optional | `user_task_transferred` |
| `user_history_map` | yes | optional remove mapping | yes | mapping only | optional | cleanup/transfer summary |
| `user_asset_object_map` | yes by object_type | optional remove mapping | yes | mapping only | optional | `user_asset_library_transferred` |
| `enterprise_user_feature_overrides` | yes | yes | no | row delete allowed | no for deleted account | `user_feature_overrides_cleared` |
| `enterprise_feature_flags` | no target user relation | no | no | no | yes | unchanged |
| `usage_logs` | yes count only | no | no | no | yes | never delete; record all operations |

Cleanup should default to feature overrides only. Removing owner mappings is
high risk because it can convert owned data into unowned data and hide it from
all normal users.

## 7. UI Design

Target file for later implementation: `enterprise-static/admin.html`.

Member list additions:

- Keep existing enable/disable controls.
- Add "Delete / Cleanup" entry for non-current users.
- Hide delete entry for current administrator.
- Disable delete entry for the last active administrator.

Modal flow:

1. Impact Preview
   - Fetch `GET /enterprise/api/users/{id}/delete-impact`.
   - Show counts by data type.
   - Show warning that runtime files and audit logs are retained.

2. Choose Action
   - Soft delete account only.
   - Clear permission overrides.
   - Transfer owner.
   - Cleanup enterprise mappings.

3. Confirm
   - Require typing target username.
   - Show red high-risk warning.
   - Explicitly state: `assets/`, `output/`, runtime images, and audit logs are
     not deleted.

First version should not include complex bulk operations, role templates, team
selectors, or ACL grants.

## 8. Audit Event Design

| Event | Actor | Target | Metadata |
|---|---|---|---|
| `user_delete_dry_run` | admin | target user | counts, sample_limit, scopes |
| `user_deleted` | admin | target user | soft_delete, reason, previous_is_active |
| `user_disabled` | admin | target user | is_active=false |
| `user_data_cleanup_requested` | admin | target user | scopes, dry_run_token, reason |
| `user_data_cleanup_completed` | admin | target user | scopes, before/after counts, cleaned counts |
| `user_data_cleanup_failed` | admin | target user | scopes, error, partial counts if any |
| `user_resource_transferred` | admin | source/target user | count, prefixes, sample resource URLs |
| `user_canvas_transferred` | admin | source/target user | count, sample canvas IDs |
| `user_project_transferred` | admin | source/target user | count, sample project IDs |
| `user_conversation_transferred` | admin | source/target user | count, sample conversation IDs |
| `user_asset_library_transferred` | admin | source/target user | counts by library/category/item |
| `user_task_transferred` | admin | source/target user | counts by task_type |
| `user_feature_overrides_cleared` | admin | target user | deleted_count, old feature keys |

Metadata should include:

- `actor_user_id`
- `target_user_id`
- `target_username`
- `target_user_is_active`
- `source_user_id` and `target_user_id` for transfers
- `scopes`
- before/after counts where applicable
- confirmation marker, but not password or token values

`enterprise-static/logs.html` currently hardcodes action filter options. The
implementation PR should either:

- Add the new event names to the hardcoded dropdown in the same PR, or
- Introduce a dynamic action-types API in a separate small PR.

For 3G-7B, updating the hardcoded dropdown is acceptable and lower risk.

## 9. Security Constraints

Required constraints:

- Normal users cannot call delete, cleanup, transfer, or impact APIs.
- Administrators cannot delete themselves.
- Administrators cannot disable themselves.
- The system cannot delete or disable the last active administrator.
- Transfer target must be an active user.
- `usage_logs` cannot be cleaned or deleted.
- `assets/` and `output/` cannot be deleted by this task.
- `history.json`, canvas JSON, and conversation JSON must not be rewritten by
  default.
- High-risk actions require secondary confirmation.
- Cleanup and transfer require a dry-run path.
- Failure must not silently leave partial success without audit or clear error.
- This task cannot introduce collaboration ACL grants.

## 10. Test Matrix

Future implementation should add:

`enterprise/tests/test_user_delete_cleanup.py`

Minimum cases:

- Normal user calling delete-impact returns 403.
- Admin delete-impact returns complete counts.
- Admin cannot delete self.
- Admin cannot delete the last active admin.
- Soft delete prevents login.
- Soft delete invalidates old JWT.
- Soft delete does not remove `users` row.
- Purge overrides removes `enterprise_user_feature_overrides`.
- Transfer changes selected owner maps to target user.
- Disabled user cannot be transfer target.
- `assets/` is not deleted.
- `usage_logs` is not deleted.
- Audit events are written.
- User B cannot see deleted user A's resources.
- Admin can still see retained objects.
- task/history/resource/asset-library isolation does not regress.

Regression suites to run:

- `test_ownership_isolation.py`
- `test_upload_isolation.py`
- `test_asset_library_isolation.py`
- `test_task_history_isolation.py`
- `test_feature_flags.py`
- `test_websocket_isolation.py`

## 11. Implementation Split

Do not implement all 3G-7B capabilities in one PR.

### PR 1: Dry-run preview

- `GET /enterprise/api/users/{id}/delete-impact`
- Admin UI read-only preview entry.
- `user_delete_dry_run` audit.
- Tests for counts and admin-only access.

### PR 2: Soft delete semantics and override cleanup

- Clarify `DELETE /enterprise/api/users/{id}` as soft delete.
- Block self-delete.
- Block deleting/disabling last active admin.
- Add `purge-overrides`.
- Tests for login/JWT invalidation and override cleanup.

### PR 3: Owner transfer

- `POST /enterprise/api/users/{id}/transfer`
- Scopes for project/canvas/conversation/resource/history/asset/task owner
  mappings.
- Active target user check.
- UI transfer entry.
- Scope-level audit.

### PR 4: Optional enterprise mapping cleanup

- `cleanup-preview`
- `cleanup`
- Strong confirmation.
- Mapping-only cleanup.
- Tests proving runtime files and audit logs are retained.

## 12. Acceptance Standard For This ADR

This ADR is complete when:

- It is docs-only.
- It does not modify `enterprise/` runtime code.
- It does not modify `static/`.
- It does not stage or commit `assets/`.
- It does not implement user deletion APIs.
- It clearly separates 3G-7B from future collaboration ACL work.
