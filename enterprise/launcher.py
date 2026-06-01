from __future__ import annotations

import ctypes
import os
import socket
import subprocess
import sys
import threading
import time
import webbrowser
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PYEXE = str(Path(sys.executable).resolve())
UPSTREAM_PORT = 3001
GATEWAY_PORT = 8000


class JOBOBJECT_BASIC_LIMIT_INFORMATION(ctypes.Structure):
    _fields_ = [
        ("PerProcessUserTimeLimit", ctypes.c_int64),
        ("PerJobUserTimeLimit", ctypes.c_int64),
        ("LimitFlags", ctypes.c_uint32),
        ("MinimumWorkingSetSize", ctypes.c_size_t),
        ("MaximumWorkingSetSize", ctypes.c_size_t),
        ("ActiveProcessLimit", ctypes.c_uint32),
        ("Affinity", ctypes.c_size_t),
        ("PriorityClass", ctypes.c_uint32),
        ("SchedulingClass", ctypes.c_uint32),
    ]


class IO_COUNTERS(ctypes.Structure):
    _fields_ = [
        ("ReadOperationCount", ctypes.c_uint64),
        ("WriteOperationCount", ctypes.c_uint64),
        ("OtherOperationCount", ctypes.c_uint64),
        ("ReadTransferCount", ctypes.c_uint64),
        ("WriteTransferCount", ctypes.c_uint64),
        ("OtherTransferCount", ctypes.c_uint64),
    ]


class JOBOBJECT_EXTENDED_LIMIT_INFORMATION(ctypes.Structure):
    _fields_ = [
        ("BasicLimitInformation", JOBOBJECT_BASIC_LIMIT_INFORMATION),
        ("IoInfo", IO_COUNTERS),
        ("ProcessMemoryLimit", ctypes.c_size_t),
        ("JobMemoryLimit", ctypes.c_size_t),
        ("PeakProcessMemoryUsed", ctypes.c_size_t),
        ("PeakJobMemoryUsed", ctypes.c_size_t),
    ]


class WindowsJob:
    JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE = 0x00002000
    JobObjectExtendedLimitInformation = 9

    def __init__(self) -> None:
        self._kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        self._handle = self._kernel32.CreateJobObjectW(None, None)
        if not self._handle:
            raise ctypes.WinError(ctypes.get_last_error())

        info = JOBOBJECT_EXTENDED_LIMIT_INFORMATION()
        info.BasicLimitInformation.LimitFlags = self.JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
        ok = self._kernel32.SetInformationJobObject(
            self._handle,
            self.JobObjectExtendedLimitInformation,
            ctypes.byref(info),
            ctypes.sizeof(info),
        )
        if not ok:
            raise ctypes.WinError(ctypes.get_last_error())

    def add(self, process: subprocess.Popen[bytes]) -> None:
        ok = self._kernel32.AssignProcessToJobObject(self._handle, int(process._handle))
        if not ok:
            raise ctypes.WinError(ctypes.get_last_error())

    def close(self) -> None:
        if self._handle:
            self._kernel32.CloseHandle(self._handle)
            self._handle = None


def port_open(host: str, port: int, timeout: float = 0.3) -> bool:
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


def wait_for_port(host: str, port: int, seconds: int) -> bool:
    for waited in range(seconds):
        if port_open(host, port):
            print(f"      Upstream service is ready. Waited about {waited} seconds.")
            return True
        time.sleep(1)
        if waited + 1 in (5, 15, 30):
            print(f"      Waited {waited + 1} seconds...")
    return False


def pick_lan_ip() -> str:
    script = ROOT / "enterprise" / "pick_lan_ip.ps1"
    if script.exists():
        try:
            output = subprocess.check_output(
                ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(script)],
                cwd=str(ROOT),
                text=True,
                stderr=subprocess.DEVNULL,
                timeout=5,
            ).strip()
            if output:
                return output.splitlines()[-1].strip()
        except Exception:
            pass
    return "127.0.0.1"


def browser_disabled() -> bool:
    return "--no-browser" in sys.argv or os.environ.get("ENTERPRISE_NO_BROWSER") == "1"


def open_browser_later(url: str, delay: int = 3) -> None:
    if browser_disabled():
        return

    def worker() -> None:
        time.sleep(delay)
        webbrowser.open(url)

    threading.Thread(target=worker, daemon=True).start()


def start_child(args: list[str], title: str) -> subprocess.Popen[bytes]:
    creationflags = 0
    if os.name == "nt":
        creationflags = subprocess.CREATE_NEW_PROCESS_GROUP
    return subprocess.Popen(args, cwd=str(ROOT), creationflags=creationflags)


def terminate(process: subprocess.Popen[bytes] | None) -> None:
    if process is None or process.poll() is not None:
        return
    try:
        process.terminate()
        process.wait(timeout=5)
    except Exception:
        try:
            process.kill()
        except Exception:
            pass


def add_to_job(job: WindowsJob | None, process: subprocess.Popen[bytes]) -> None:
    if not job:
        return
    try:
        job.add(process)
    except Exception as exc:
        print(f"[WARN] Could not attach process {process.pid} to job control: {exc}")
        print("       Cleanup will still be attempted when this launcher exits.")


def print_urls(lan_ip: str, managed: bool = True) -> None:
    print("============================================================")
    print(f"  LAN URL:   http://{lan_ip}:8000/")
    print("  Local URL: http://127.0.0.1:8000/")
    print(f"  Admin URL: http://{lan_ip}:8000/enterprise/admin")
    print()
    print("  Admin account is configured in enterprise.env")
    if managed:
        print("  Press Ctrl+C or close this window to stop services.")
    print("============================================================")
    print()


def main() -> int:
    lan_ip = pick_lan_ip()

    print("============================================================")
    print("  Infinite Canvas Enterprise Launcher")
    print("============================================================")
    print()

    if port_open("127.0.0.1", GATEWAY_PORT):
        print("[INFO] Enterprise gateway port 8000 is already running.")
        print("       No duplicate service was started.")
        print("       This window did not start the existing service.")
        print()
        print_urls(lan_ip, managed=False)
        if not browser_disabled():
            webbrowser.open(f"http://{lan_ip}:8000/")
        try:
            input("Press Enter to close this window...")
        except EOFError:
            pass
        return 0

    job = None
    if os.name == "nt":
        try:
            job = WindowsJob()
        except Exception as exc:
            print(f"[WARN] Process job control is unavailable: {exc}")
            print("       Ctrl+C cleanup will still be attempted.")

    upstream: subprocess.Popen[bytes] | None = None
    gateway: subprocess.Popen[bytes] | None = None
    try:
        print("[1/2] Starting upstream service: 127.0.0.1:3001")
        upstream = start_child(
            [
                PYEXE,
                "-m",
                "uvicorn",
                "main:app",
                "--host",
                "127.0.0.1",
                "--port",
                str(UPSTREAM_PORT),
                "--log-level",
                "warning",
            ],
            "InfiniteCanvas-Internal",
        )
        add_to_job(job, upstream)

        print("      Waiting for upstream service...")
        if not wait_for_port("127.0.0.1", UPSTREAM_PORT, 60):
            print("[ERROR] Upstream service timeout after 60 seconds.")
            return 1

        print()
        print("[2/2] Starting enterprise gateway: 0.0.0.0:8000")
        print()
        print_urls(lan_ip)
        open_browser_later(f"http://{lan_ip}:8000/")

        gateway = start_child(
            [
                PYEXE,
                "-m",
                "uvicorn",
                "enterprise.gateway:app",
                "--host",
                "0.0.0.0",
                "--port",
                str(GATEWAY_PORT),
                "--log-level",
                "warning",
            ],
            "InfiniteCanvas-Enterprise",
        )
        add_to_job(job, gateway)

        return gateway.wait()
    except KeyboardInterrupt:
        print()
        print("Stop requested.")
        return 0
    finally:
        print()
        print("Stopping enterprise services...")
        terminate(gateway)
        terminate(upstream)
        if job:
            job.close()
        print("All services stopped.")


if __name__ == "__main__":
    raise SystemExit(main())
