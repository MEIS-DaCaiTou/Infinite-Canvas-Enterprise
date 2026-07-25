"""ENV-1B1C-B1 release mismatch pure state table tests."""

from __future__ import annotations

import pytest

from enterprise.runtime.error_contract import RuntimeContractError
from enterprise.runtime.preflight import decide_release_mismatch


def test_old_release_batch_is_rejected_for_all_formal_commands() -> None:
    for command in ("start", "stop", "restart", "status", "health"):
        decision = decide_release_mismatch(
            launcher_release_id="old",
            current_release_id="new",
            running_release_id="old",
            owned_instance_valid=True,
            command=command,
        )
        assert decision.allowed is False
        assert decision.exit_code == 2
        assert decision.status_code == "PORTABLE_RELEASE_NOT_CURRENT"


def test_current_release_stop_can_stop_owned_old_instance() -> None:
    decision = decide_release_mismatch(
        launcher_release_id="new",
        current_release_id="new",
        running_release_id="old",
        owned_instance_valid=True,
        command="stop",
    )
    assert decision.allowed is True
    assert decision.exit_code == 0
    assert decision.running_release_mismatch is True
    assert decision.status_code == "STOP_OWNED_MISMATCH_ALLOWED"


def test_current_release_status_mismatch_exits_zero_but_health_exits_two() -> None:
    status = decide_release_mismatch(
        launcher_release_id="new",
        current_release_id="new",
        running_release_id="old",
        owned_instance_valid=True,
        command="status",
    )
    health = decide_release_mismatch(
        launcher_release_id="new",
        current_release_id="new",
        running_release_id="old",
        owned_instance_valid=True,
        command="health",
    )
    assert status.allowed is True and status.exit_code == 0
    assert health.allowed is False and health.exit_code == 2


def test_restart_mismatch_is_blocked_and_invalid_ownership_blocks_stop() -> None:
    restart = decide_release_mismatch(
        launcher_release_id="new",
        current_release_id="new",
        running_release_id="old",
        owned_instance_valid=True,
        command="restart",
    )
    stop = decide_release_mismatch(
        launcher_release_id="new",
        current_release_id="new",
        running_release_id="old",
        owned_instance_valid=False,
        command="stop",
    )
    assert restart.status_code == "RESTART_RELEASE_MISMATCH_BLOCKED"
    assert stop.status_code == "STOP_OWNERSHIP_UNAVAILABLE"


def test_r3_same_release_running_instance_still_requires_valid_stop_ownership() -> None:
    decision = decide_release_mismatch(
        launcher_release_id="new",
        current_release_id="new",
        running_release_id="new",
        owned_instance_valid=False,
        command="stop",
    )
    assert decision.allowed is False
    assert decision.exit_code == 2
    assert decision.launcher_release_mismatch is False
    assert decision.running_release_mismatch is False
    assert decision.running_instance_present is True
    assert decision.ownership_valid is False
    assert decision.status_code == "STOP_OWNERSHIP_UNAVAILABLE"


def test_r3_mismatch_properties_distinguish_launcher_and_running_instance() -> None:
    decision = decide_release_mismatch(
        launcher_release_id="old",
        current_release_id="new",
        running_release_id="old",
        owned_instance_valid=True,
        command="status",
    )
    assert decision.launcher_release_mismatch is True
    assert decision.running_release_mismatch is True
    assert decision.running_instance_present is True
    assert decision.ownership_valid is True


def test_invalid_release_mismatch_command_fails() -> None:
    with pytest.raises(RuntimeContractError) as exc:
        decide_release_mismatch(
            launcher_release_id="new",
            current_release_id="new",
            running_release_id=None,
            owned_instance_valid=False,
            command="delete",
        )
    assert exc.value.code == "RELEASE_MISMATCH_COMMAND_INVALID"
