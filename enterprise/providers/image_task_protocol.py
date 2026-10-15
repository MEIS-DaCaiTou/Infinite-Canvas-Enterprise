"""Existing JSON image-task status contract, shared by maintained HTTP adapters."""
SUCCESS_STATUSES = {"SUCCESS", "SUCCESSFUL", "SUCCEED", "SUCCEEDED", "COMPLETED", "COMPLETE", "DONE", "FINISHED", "OK", "READY"}
FAILED_STATUSES = {"FAILURE", "FAILED", "FAIL", "ERROR", "ERRORED", "CANCELED", "CANCELLED", "TIMEOUT", "REJECTED", "EXPIRED"}


def task_data(payload):
    if isinstance(payload, dict) and isinstance(payload.get("data"), dict):
        return payload["data"]
    return payload if isinstance(payload, dict) else {}


def task_status(payload):
    data = task_data(payload)
    return str(data.get("status") or data.get("task_status") or "").upper()


def failure_reason(payload):
    data = task_data(payload)
    error = data.get("error") if isinstance(data.get("error"), dict) else {}
    return data.get("fail_reason") or data.get("message") or error.get("message") or (payload.get("message") if isinstance(payload, dict) else "") or "生图任务失败"
