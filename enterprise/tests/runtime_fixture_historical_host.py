"""TEST ONLY: isolate an immutable historical host's KnownFolder and ports.

Executes the original host/child/portable functions, including actual main.py
and gateway HTTP services. Only OS launch wrappers redirect KnownFolder into
the installation fixture. No installed payload file is edited. Not shipped.
"""
from __future__ import annotations

import argparse
import functools
import json
import os
import subprocess
import sys
from pathlib import Path


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--fixture-app-root', type=Path, required=True)
    parser.add_argument('--fixture-local-base', type=Path, required=True)
    parser.add_argument('--fixture-entry', choices=['host', 'child', 'start', 'health', 'stop'], required=True)
    opts, rest = parser.parse_known_args()
    sys.path.insert(0, str(opts.fixture_app_root))
    from enterprise.runtime import portable, supervisor
    from enterprise.runtime.ownership import PortListenerSnapshot
    portable.windows_local_app_data_known_folder = lambda: opts.fixture_local_base
    portable.build_portable_preflight = functools.partial(portable.build_portable_preflight,
        local_app_data_resolver=lambda: opts.fixture_local_base)
    portable.validate_portable_process_binding = functools.partial(portable.validate_portable_process_binding,
        local_app_data_resolver=lambda: opts.fixture_local_base)
    original_popen = subprocess.Popen
    class IsolatedPopen(original_popen):
        def __init__(self, arguments, *args, **kwargs):
            rewritten = list(arguments)
            if len(rewritten) >= 4 and rewritten[1:3] == ['-I', '-B']:
                entry = Path(rewritten[3])
                if entry in {opts.fixture_app_root / 'enterprise/runtime/host.py', opts.fixture_app_root / 'enterprise/runtime/child.py'}:
                    rewritten = rewritten[:3] + [str(Path(__file__).resolve()),
                        '--fixture-app-root', str(opts.fixture_app_root),
                        '--fixture-local-base', str(opts.fixture_local_base), '--fixture-entry', entry.stem] + rewritten[4:]
            super().__init__(rewritten, *args, **kwargs)
    subprocess.Popen = IsolatedPopen
    if opts.fixture_entry == 'host':
        original_tick = supervisor.RuntimeSupervisor._tick
        def tick(self):
            original_tick(self)
            armed = self.config.runtime_root / 'fixture-incident-armed'
            if armed.exists() and self.roles['gateway'].state == 'healthy':
                original_inspect = supervisor.inspect_port_listeners
                try:
                    supervisor.inspect_port_listeners = lambda port: (PortListenerSnapshot(port, (), (), (), True)
                        if port == self.config.gateway_port else original_inspect(port))
                    outcome = self._stop_role('gateway', reason='fixture_port_inspection_failure')
                finally:
                    supervisor.inspect_port_listeners = original_inspect
                assert self.roles['gateway'].process is None and not outcome['replacement_safe']
                self.roles['gateway'].state, self.roles['gateway'].health = 'degraded', 'recovery_blocked'
                self.roles['gateway'].restart_at = None
                armed.unlink()
                self._persist_state()
                (self.config.runtime_root / 'fixture-incident-observed').write_text('gateway_missing\n', encoding='ascii')
        supervisor.RuntimeSupervisor._tick = tick
        from enterprise.runtime.host import _main
        return _main(rest)
    if opts.fixture_entry == 'child':
        from enterprise.runtime.child import main as child_main
        return child_main(rest)
    payload, code = portable.execute_portable_command(app_root=opts.fixture_app_root, command=opts.fixture_entry)
    print(json.dumps(payload, ensure_ascii=False))
    return code


if __name__ == '__main__':
    raise SystemExit(main())
