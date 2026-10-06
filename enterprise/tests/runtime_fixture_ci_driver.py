"""TEST ONLY: real lifecycle assertions outside a restrictive CI runner Job.

Spawned by Win32_Process.Create (WMI) in Windows CI; never shipped. The driver
checks that its enclosing Job permits the unchanged production host flags.
Windows compatibility Jobs may remain present even outside the runner Job.
No Job limits are changed and no process is killed by this helper.
"""
from __future__ import annotations

import argparse
import ctypes
import json
import os
import subprocess
import sys
from ctypes import wintypes
from pathlib import Path


def main():
    parser = argparse.ArgumentParser()
    for name in ('repo', 'assets', 'base', 'report-root'):
        parser.add_argument('--'+name, type=Path, required=True)
    parser.add_argument('--smoke-only', action='store_true')
    args = parser.parse_args()
    result = {'schema_version':'enterprise-ci-lifecycle-driver-v1', 'result':'failed', 'exit_code':2}
    try:
        if os.name != 'nt' or args.base.exists() or not args.report_root.is_dir():
            raise RuntimeError('CI_DRIVER_INPUT_INVALID')
        kernel = ctypes.WinDLL('kernel32', use_last_error=True)
        kernel.GetCurrentProcess.argtypes = ()
        kernel.GetCurrentProcess.restype = wintypes.HANDLE
        kernel.IsProcessInJob.argtypes = (wintypes.HANDLE, wintypes.HANDLE, ctypes.POINTER(wintypes.BOOL))
        kernel.IsProcessInJob.restype = wintypes.BOOL
        inside = wintypes.BOOL()
        if not kernel.IsProcessInJob(kernel.GetCurrentProcess(), None, ctypes.byref(inside)):
            raise RuntimeError('CI_DRIVER_JOB_INSPECTION_FAILED')
        job_flags = None
        if inside.value:
            kernel.QueryInformationJobObject.argtypes = (wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD, ctypes.c_void_p)
            kernel.QueryInformationJobObject.restype = wintypes.BOOL
            information = ctypes.create_string_buffer(144)
            if not kernel.QueryInformationJobObject(None, 9, information, len(information), None):
                raise RuntimeError('CI_DRIVER_JOB_LIMIT_INSPECTION_FAILED')
            job_flags = ctypes.c_uint32.from_buffer_copy(information.raw[16:20]).value
            # Read only: never enable BREAKAWAY_OK or alter a runner Job.
            if not job_flags & (0x800 | 0x1000):
                raise RuntimeError('CI_DRIVER_CALLER_JOB_RESTRICTED')
        result.update(caller_in_job=bool(inside.value), caller_job_limit_flags=job_flags,
            caller_job_compatible=True, production_host_flags_unchanged=True)
        if args.smoke_only:
            result.update(result='pass', exit_code=0, smoke_only=True)
            return 0
        environment = dict(os.environ)
        environment['PYTEST_DISABLE_PLUGIN_AUTOLOAD'] = '1'
        environment['PYTHONDONTWRITEBYTECODE'] = '1'
        environment['ICE_HISTORICAL_ASSETS'] = str(args.assets)
        with (args.report_root/'real-lifecycle.log').open('x', encoding='utf-8') as output:
            done = subprocess.run([sys.executable, '-B', '-m', 'pytest', '-q',
                'enterprise/tests/test_stab_1_supervisor_logging.py::test_real_cli_lifecycle_and_acknowledgements',
                'enterprise/tests/test_historical_runtime_recovery_installed.py',
                '--basetemp', str(args.base), '--junitxml', str(args.report_root/'real-historical-recovery.xml')],
                cwd=args.repo, env=environment, stdin=subprocess.DEVNULL, stdout=output, stderr=output,
                timeout=1000, creationflags=subprocess.CREATE_NO_WINDOW)
        result.update(result='pass' if done.returncode == 0 else 'failed', exit_code=done.returncode, smoke_only=False)
    except Exception as exc:
        code = str(exc)
        result['code'] = code if code.startswith('CI_DRIVER_') and len(code)<100 else 'CI_DRIVER_FAILED'
    finally:
        # Only isolated synthetic-fixture logs; no customer directory is read.
        # Retain why a frozen host never reached readiness on a hosted VM.
        fixture_logs = []
        if args.base.is_dir():
            allowed = {'launcher.log', 'supervisor.log', 'upstream.stderr.log', 'gateway.stderr.log', 'runtime-state.json'}
            for path in sorted(args.base.rglob('*')):
                if path.is_file() and path.name in allowed and len(fixture_logs) < 16:
                    with path.open('rb') as handle:
                        handle.seek(max(0, path.stat().st_size - 12000))
                        tail = handle.read(12000).decode('utf-8', errors='replace')
                    fixture_logs.append({'fixture_file':str(path.relative_to(args.base)), 'tail':tail})
        (args.report_root/'historical-fixture-debug.json').write_text(json.dumps(fixture_logs, sort_keys=True), encoding='utf-8')
        (args.report_root/'ci-lifecycle-driver-result.json').write_text(json.dumps(result, sort_keys=True), encoding='utf-8')
    return result['exit_code']


if __name__ == '__main__':
    raise SystemExit(main())
