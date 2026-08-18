"""Local-only command for INSTALL-MVP-1 Greenfield bootstrap."""

from __future__ import annotations

import argparse
import getpass
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from enterprise.fresh_install import FreshInstallError, install_greenfield
from enterprise.runtime.portable import windows_local_app_data_known_folder


class _Parser(argparse.ArgumentParser):
    def error(self, message: str) -> None:
        raise FreshInstallError("INSTALL_ARGUMENT_INVALID")


def _emit(payload: dict[str, object]) -> None:
    print(json.dumps(payload, ensure_ascii=True, sort_keys=True, separators=(",", ":")))


def main() -> int:
    parser = _Parser(description="Install one verified Enterprise Release into a new local root")
    parser.add_argument("--release-dir", type=Path, required=True)
    parser.add_argument("--install-root", type=Path, required=True)
    try:
        args = parser.parse_args()
        username = input("First super_admin username: ")
        password = getpass.getpass("First super_admin password: ")
        confirmation = getpass.getpass("Confirm first super_admin password: ")
        result = install_greenfield(
            release_dir=args.release_dir,
            install_root=args.install_root,
            username=username,
            password=password,
            password_confirmation=confirmation,
            local_app_data_base=windows_local_app_data_known_folder(),
        )
    except FreshInstallError as exc:
        _emit({"schema_version": "install-mvp-1-result-v1", "status": "blocked", "code": exc.code})
        return 2
    except (EOFError, KeyboardInterrupt):
        _emit({"schema_version": "install-mvp-1-result-v1", "status": "blocked", "code": "INSTALL_INTERACTIVE_INPUT_REQUIRED"})
        return 2
    except Exception:
        _emit({"schema_version": "install-mvp-1-result-v1", "status": "blocked", "code": "INSTALL_INTERNAL_ERROR"})
        return 2
    _emit({"schema_version": "install-mvp-1-result-v1", "status": "succeeded", **result.public_dict()})
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
