"""Command-line Gate A preflight for RELEASE-MVP-1."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from enterprise.release.release_manifest_v2 import ReleaseManifestV2Error
from enterprise.release.release_mvp_preflight import ReleaseMvpPreflightError, run_release_mvp_preflight


class _JsonArgumentParser(argparse.ArgumentParser):
    def error(self, message: str) -> None:
        raise ReleaseMvpPreflightError("RELEASE_MVP_ARGUMENT_INVALID")


def _emit(payload: dict[str, object]) -> None:
    print(json.dumps(payload, ensure_ascii=True, sort_keys=True, separators=(",", ":")))


def main() -> int:
    parser = _JsonArgumentParser(description="Validate the three RELEASE-MVP-1 GitHub Release assets")
    parser.add_argument("--source-manifest", type=Path, required=True)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--inventory", type=Path, required=True)
    parser.add_argument("--archive", type=Path, required=True)
    parser.add_argument("--source-version", required=True)
    parser.add_argument("--target-version", required=True)
    parser.add_argument("--target-tag", required=True)
    try:
        args = parser.parse_args()
        payload = run_release_mvp_preflight(
            source_manifest_path=args.source_manifest,
            manifest_path=args.manifest,
            inventory_path=args.inventory,
            archive_path=args.archive,
            source_version=args.source_version,
            target_version=args.target_version,
            target_tag=args.target_tag,
        )
    except ReleaseMvpPreflightError as exc:
        _emit({"schema_version": "release-mvp-1-gate-a-preflight-v1", "status": "blocked", "ready": False, "ready_for_github_release": False, "code": exc.code})
        return 2
    except ReleaseManifestV2Error as exc:
        code = str(exc) if str(exc).startswith("RELEASE_") else "RELEASE_MVP_MANIFEST_VERIFY_FAILED"
        _emit({"schema_version": "release-mvp-1-gate-a-preflight-v1", "status": "blocked", "ready": False, "ready_for_github_release": False, "code": code})
        return 2
    except Exception:
        _emit({"schema_version": "release-mvp-1-gate-a-preflight-v1", "status": "blocked", "ready": False, "ready_for_github_release": False, "code": "RELEASE_MVP_INTERNAL_ERROR"})
        return 2
    _emit(payload)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
