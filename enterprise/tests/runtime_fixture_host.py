"""Detached service-host fixture used by the STAB-1 Windows process smoke."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from enterprise.runtime.process import CommandSpec
from enterprise.runtime.ownership import process_identity
from enterprise.runtime.state import RuntimeStateStore
from enterprise.runtime.supervisor import RuntimeSupervisor, SupervisorConfig


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--runtime-root", required=True)
    parser.add_argument("--upstream-port", type=int, required=True)
    parser.add_argument("--gateway-port", type=int, required=True)
    args = parser.parse_args()
    fixture = ROOT / "enterprise" / "tests" / "runtime_fixture_service.py"
    commands = {
        "upstream": CommandSpec(
            role="upstream",
            arguments=(sys.executable, str(fixture), "--role", "upstream", "--port", str(args.upstream_port)),
            host="127.0.0.1",
            port=args.upstream_port,
        ),
        "gateway": CommandSpec(
            role="gateway",
            arguments=(sys.executable, str(fixture), "--role", "gateway", "--port", str(args.gateway_port)),
            host="127.0.0.1",
            port=args.gateway_port,
        ),
    }
    config = SupervisorConfig(
        app_root=ROOT,
        runtime_root=Path(args.runtime_root),
        mode="service-host",
        upstream_port=args.upstream_port,
        gateway_port=args.gateway_port,
        startup_timeout_seconds=10,
        health_interval_seconds=1,
        health_failure_threshold=2,
        crash_window_seconds=60,
        max_abnormal_restarts=5,
        backoff_seconds=(1,),
        command_specs=commands,
    )
    supervisor = RuntimeSupervisor(config)
    owner = process_identity(supervisor.supervisor_identity.pid)
    if owner is None or not RuntimeStateStore(config.runtime_root).reserve_lock(instance_id=supervisor.instance_id, owner=owner):
        return 2
    return supervisor.run()


if __name__ == "__main__":
    raise SystemExit(main())
