# STAB-1 / OPS-L1: Supervisor and Persistent Logging Implementation (2026-07)

## Scope

STAB-1 moves the enterprise `3001` upstream and `8000` gateway lifecycle out
of the old foreground-only launcher into `enterprise/runtime/`.  It is a local
Windows runtime foundation for later OPS-3B orchestration, not an updater,
service installer, migration runner, remote control API, or Update Center.

This repository implementation and its temporary-process tests do not mean a
production host was started, changed, or validated.

## Runtime layout

| Module | Responsibility |
| --- | --- |
| `supervisor.py` | Per-role state machine, health recovery, backoff, crash-loop and controlled shutdown. |
| `process.py` | Fixed uvicorn command arrays, child launch, stream pumps and owned-only termination. |
| `health.py` | Bounded TCP, upstream `/api/app-info` and gateway `/enterprise/health` checks. |
| `logging.py` | Rotated persistent files, JSONL events and secret redaction. |
| `state.py` | Atomic `runtime-state.json`, instance lock and instance-bound local command files. |
| `ownership.py` | PID, creation time, executable-path and port listener identity checks. |
| `windows.py` | Service-host-owned Windows Job Object with kill-on-close cleanup. |
| `control.py` / `cli.py` | Fixed local `start`, `stop`, `restart`, `status` and `health` commands. |

The public CLI accepts no arbitrary child command, shell expression, network
control request or upgrade operation.  Its control channel is a runtime-root
command file bound to the current `supervisor_instance_id`; it does not open a
new listener port.

## Modes and local commands

Normal Windows startup is:

```powershell
.\启动企业版.bat
```

It starts a detached `service-host`, waits for it to become healthy and then
allows the command window to close.  The service host itself owns the Job
Object and its child process tree; the short-lived start command does not own
that job.

Foreground diagnosis is explicit:

```powershell
.\启动企业版前台.bat
```

Closing this foreground console is an intentional stop.  It never opens a
browser or waits for `input()`.

Other local lifecycle entry points are:

```powershell
.\停止企业版.bat
.\重启企业版.bat
.\查看企业版状态.bat
python\python.exe -m enterprise.runtime.cli health
```

The old port-wide `taskkill` stop path is removed from the enterprise stop
entry point.  A stop first validates the current state instance and child
identity, then asks the supervisor to stop its own gateway and upstream.  It
never terminates a foreign port listener.  A second stop is idempotent.

## State machine and recovery

The supervisor state is one of `starting`, `healthy`, `degraded`,
`restarting`, `crash_loop`, `stopping`, `stopped`, or `blocked`.  Each role
holds its own PID identity, health failure count, restart count and rolling
crash window.

- Startup health timeout: 60 seconds.
- Runtime health interval: 5 seconds.
- Consecutive role-health failures: 3.
- Crash-loop window: 5 minutes.
- Maximum abnormal restarts per role: 5.
- Backoff: 1, 2, 5, 10, 30 seconds (maximum 30 seconds).

An upstream exit only schedules upstream recovery; a gateway which returns
`503` because upstream is unavailable is recorded as degraded but is not
restarted merely because upstream is down.  Gateway recovery is likewise
independent.  Explicit `restart` clears the role crash-loop bookkeeping; an
automatic crash-loop never retries indefinitely.

Before startup, the runtime checks both ports, listener PID identities,
runtime state, upstream health and gateway health.  It distinguishes stopped,
healthy/unhealthy complete instance, gateway-only, upstream-only, stale state,
owned orphan and foreign occupant.  Half instances and foreign occupants are
blocked and are never auto-killed.  A stale lock is cleared only after stored
PIDs are gone and both ports are free.

## Ownership and Windows cleanup

For every managed child the supervisor records and rechecks PID, process
creation time, executable path, parent PID, role and instance ID.  PID reuse
therefore cannot turn a normal stop into a kill of an unrelated process.

The service host creates the Windows Job Object, attaches only its fixed
upstream and gateway children, and configures kill-on-close.  A supervisor
exit therefore cleans its own descendants; normal role health recovery still
operates role by role.  Forced termination is used only after a bounded
graceful-stop timeout and only after ownership revalidation.

## Logs and state

The runtime root is configurable with `--runtime-root` and defaults outside
the application root under the local application-data area.  It rejects roots
inside the application, `data/`, `assets/`, `output/`, bundled `python/`, or
the ordinary application `logs/` tree.

It writes:

```text
launcher.log
supervisor.log
upstream.stdout.log
upstream.stderr.log
gateway.stdout.log
gateway.stderr.log
health.log
crash-events.jsonl
runtime-state.json
```

Logs rotate at 10 MiB with five retained files by default (hard maximum ten).
Child stdout/stderr are pumped through the same redaction and rotation path.
Structured events contain UTC time, instance ID, role, PID, parent PID,
state, restart count, health/failure category, and both signed decimal plus
unsigned 32-bit hexadecimal exit code.  Native Windows failures such as
`0xC0000005`, `0xC0000409`, and `0xC0000374` are evidence to record and
recover from; STAB-1 does not claim to fix their CPython or system root cause.

Authorization values, Bearer tokens, cookies, API keys, JWTs, passwords,
secrets, `GITHUB_TOKEN`, environment-value assignments and matching traceback
content are redacted before file or console output.  `runtime-state.json` is
atomically published using a short same-directory temporary filename and
`os.replace`, and contains no command line, environment value, database data,
token or user data.  Its role shape is:

```json
{
  "schema_version": "runtime-supervisor-state-v1",
  "supervisor_instance_id": "...",
  "mode": "service-host",
  "state": "healthy",
  "upstream": {"pid": 0, "state": "healthy", "health": "ok", "restart_count": 0},
  "gateway": {"pid": 0, "state": "healthy", "health": "ok", "restart_count": 0}
}
```

## Test coverage and boundaries

`enterprise/tests/test_stab_1_supervisor_logging.py` uses a temporary runtime
root, random local fixture ports and short-lived HTTP fixture children.  It
covers healthy startup, independent upstream/gateway restart, crash-loop,
manual stop, child cleanup, persistent logs, rotation, redaction, atomic state
publication, port-gate classification and static no-shell/no-browser checks.
It never starts the production `3001`/`8000` application or opens a production
database.

Still not implemented: Windows Service/NSSM/WinSW installation, remote/web
process control, arbitrary commands, apply-upgrade, rollback/restore, database
migration apply, Update Center UI, event-log/dump collection, or any claimed
production rollout.  OPS-3B may use the fixed local lifecycle interface only
after separate review.
