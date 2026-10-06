"""TEST ONLY: real lifecycle assertions outside a restrictive CI runner Job.

Spawned by Win32_Process.Create (WMI) in Windows CI; never shipped. The driver
checks its job boundary, then executes unchanged tests/production host flags.
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
        if inside.value:
            raise RuntimeError('CI_DRIVER_RUNNER_JOB_NOT_ISOLATED')
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
        result.update(result='pass' if done.returncode == 0 else 'failed', exit_code=done.returncode,
            caller_job_isolated=True, production_host_flags_unchanged=True)
    except Exception as exc:
        code = str(exc)
        result['code'] = code if code.startswith('CI_DRIVER_') and len(code)<100 else 'CI_DRIVER_FAILED'
    finally:
        (args.report_root/'ci-lifecycle-driver-result.json').write_text(json.dumps(result, sort_keys=True), encoding='utf-8')
    return result['exit_code']


if __name__ == '__main__':
    raise SystemExit(main())
