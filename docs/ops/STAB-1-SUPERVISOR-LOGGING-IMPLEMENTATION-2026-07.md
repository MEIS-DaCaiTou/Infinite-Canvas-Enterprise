# STAB-1 / OPS-L1: Supervisor and Persistent Logging Implementation (2026-07)

Status: merged by PR #78 at `a00a2fd2807b41a9fee3c267ee1116986b52fd7e`; detached service-host startup was subsequently fixed by PR #79 at `396cccc68d63bd16393a2cb72d24e4a48fcf47cb`. These repository facts do not mean production switched supervisors or installed a Windows Service.

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
| `process.py` / `child.py` | Fixed command arrays, an internal Uvicorn wrapper, child launch, stream pumps and owned-only shutdown. |
| `host.py` | Fixed absolute service-host bootstrap for the bundled Python when a detached child does not inherit an importable project root. |
| `health.py` | Bounded TCP, upstream `/api/app-info` and gateway `/enterprise/health` checks. |
| `logging.py` | Rotated persistent files, JSONL events and secret redaction. |
| `state.py` | Atomic `runtime-state.json`, two-phase instance lock and instance-bound command/ack files. |
| `ownership.py` | PID, creation time, executable-path and port listener identity checks. |
| `windows.py` | Service-host-owned Windows Job Object with kill-on-close cleanup. |
| `control.py` / `cli.py` | Fixed local `start`, `stop`, `restart`, `status` and `health` commands. |

Both host and child bootstrap paths use fixed absolute repository scripts rather
than relying on `-m enterprise...` module discovery in a detached bundled-Python
process.  The public CLI accepts no arbitrary child command, shell expression, network
control request or upgrade operation.  Its control channel is a runtime-root
command file bound to the current `supervisor_instance_id`; it does not open a
new listener port.

`start` first writes a `reserved` lock containing the launcher's PID, creation
time and executable identity.  The service host can adopt only that fresh,
matching reservation into `adopted`.  Both the lock and state persist the full
supervisor identity.  Stale-lock cleanup additionally requires no live matching
supervisor or child, no project listener, and either an expired startup grace
period or an explicitly stopped/failed state.

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

Control requests and acknowledgements are per-instance JSON files under the
runtime root.  Requests carry a random ID, the fixed command, the instance ID,
issue time and expected state generation.  Completion ACKs bind that request
to the accepting instance and record before/after generation plus role PID
generations.  `restart` returns only after both roles have new identities and
are healthy; `stop` returns only after its ACK and supervisor exit verification.
CLI exit status is stable: successful `start`, idempotent `start`, completed or
idempotent `stop`, and completed `restart` return zero.  Structured control
failures return two.  `status` returns zero after a successful read even when
the reported state is unhealthy; `health` returns zero only for verified healthy
roles.  A second stop cannot infer completion from `state=stopped` alone: it
also requires the supervisor identity, owned descendants, owned listeners,
adopted lock, and active stop command/ACK to be absent.

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

Port inspection preserves raw listener PIDs even when process identity lookup
is unavailable.  An unresolved PID or a failed port inspection is a fail-closed
startup disposition, not an empty port.  Status exposes the stable unresolved
classification, while stop never claims the port was released until the raw
listener set is empty.

## Ownership and Windows cleanup

For every managed child the supervisor records and rechecks PID, process
creation time, executable path, parent PID, role and instance ID.  PID reuse
therefore cannot turn a normal stop into a kill of an unrelated process.

The service host creates the Windows Job Object, attaches only its fixed
upstream and gateway children, and configures kill-on-close.  The normal stop
path writes each wrapper's instance-local stop file; the wrapper sets
`uvicorn.Server.should_exit`, allowing the application shutdown lifecycle and
stream flushing to finish.  Only after the bounded graceful timeout does the
supervisor terminate its own Job Object.  If a nested Job leaves a direct child
alive, a narrow fallback targets only that child after PID, creation-time and
executable identity revalidation.  It never targets a foreign listener.

The final stop ACK is emitted after child shutdown, Job closure, owned-PID
verification and port-release checks.  It records child results, whether Job
termination was required, owned PID release, per-port release and foreign
listener detection.

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
secrets, `GITHUB_TOKEN`, `token`, `access_token`, `refresh_token`, `id_token`,
and signed URL credential/signature parameters in query, JSON or traceback
content are redacted before file or console output.  Configured exact secret
values are collected only from explicit configuration fields such as
`JWT_SECRET` and `ADMIN_PASSWORD`, filtered, deduplicated and passed as an
in-memory tuple.  They are excluded from `SupervisorConfig` representations
and are never persisted in state, control files, exceptions or logger
representations.  `runtime-state.json` is
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

`enterprise/tests/test_stab_1_supervisor_logging.py` and parameterized
`test_start_stop.ps1` use a temporary runtime root, random local fixture ports
and short-lived HTTP fixture children.  They cover independent role restart,
crash-loop, lock adoption/stale cleanup, completion ACKs, graceful wrapper
markers, owned-child fallback after Job termination, persistent logs, extended
redaction, CLI exit results, concurrent-stop quiescence, unresolved listener
gates, atomic state publication, port gates and static no-shell/no-browser
checks.  They never start a production application or open a production
database.

The isolated development-device real-application probe uses a temporary
runtime/database root, non-production ports and a disposable copy of bundled
Python.  Its first attempt established that `enterprise.auth` imports `jwt`
while the install manifest omitted `PyJWT`; `requirements.txt` now declares
that direct dependency.  With the isolated dependency in place, the probe
verified `main.app`, `enterprise.gateway.app`, the internal child/host wrappers,
Uvicorn, `/api/app-info`, `/enterprise/health`, restart ACK/PID generations,
stop ACK/supervisor exit, port release, idempotent stop, start-to-stop reuse,
and independent upstream/gateway recovery.  This is development-device
evidence only: it is not a production rollout, Windows Service installation,
or a claimed fix for a native Windows/CPython crash root cause.

Still not implemented: Windows Service/NSSM/WinSW installation, remote/web
process control, arbitrary commands, apply-upgrade, rollback/restore, database
migration apply, Update Center UI, event-log/dump collection, or any claimed
production rollout.  OPS-3B may use the fixed local lifecycle interface only
after separate review.
