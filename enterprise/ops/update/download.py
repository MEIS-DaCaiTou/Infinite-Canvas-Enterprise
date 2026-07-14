"""Atomic streaming download with strict size and SHA-256 confirmation."""

from __future__ import annotations

import hashlib
import os
import socket
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping

from enterprise.ops.update.errors import ReleaseDownloadError
from enterprise.ops.update.http_client import SafeHttpClient


CHUNK_SIZE = 64 * 1024


@dataclass(frozen=True)
class DownloadResult:
    path: Path
    size_bytes: int
    sha256: str
    redirect_count: int


def atomic_download(
    client: SafeHttpClient,
    *,
    url: str,
    destination: Path,
    maximum_bytes: int,
    expected_size_bytes: int | None = None,
    expected_sha256: str | None = None,
    headers: Mapping[str, str] | None = None,
) -> DownloadResult:
    """Stream to a job-owned temporary file, verify, then atomically publish once."""
    if destination.exists():
        raise ReleaseDownloadError(
            "release download destination already exists",
            detail_code="RELEASE_DESTINATION_EXISTS",
        )
    if type(maximum_bytes) is not int or maximum_bytes < 1:
        raise ValueError("maximum_bytes must be positive")
    if expected_size_bytes is not None and (type(expected_size_bytes) is not int or expected_size_bytes < 1):
        raise ReleaseDownloadError("release expected size is invalid", detail_code="RELEASE_DOWNLOAD_INPUT_INVALID")
    if expected_sha256 is not None and (
        not isinstance(expected_sha256, str)
        or len(expected_sha256) != 64
        or any(character not in "0123456789abcdef" for character in expected_sha256)
    ):
        raise ReleaseDownloadError("release expected SHA256 is invalid", detail_code="RELEASE_DOWNLOAD_INPUT_INVALID")
    destination.parent.mkdir(parents=True, exist_ok=True)
    # Keep the job-owned part file on the same volume without repeating a long
    # release filename. Repeating it can cross the legacy Windows MAX_PATH
    # boundary even when the final destination itself remains addressable.
    temporary = destination.with_name(f".release-{uuid.uuid4().hex}.part")
    digest = hashlib.sha256()
    received = 0
    redirect_count = 0
    try:
        with temporary.open("xb") as handle:
            for response, advertised_size, redirect_count in client.stream(url, maximum_bytes=maximum_bytes, headers=headers):
                if expected_size_bytes is not None and advertised_size is not None and advertised_size != expected_size_bytes:
                    raise ReleaseDownloadError(
                        "release response size does not match the manifest",
                        detail_code="RELEASE_ADVERTISED_SIZE_MISMATCH",
                    )
                while True:
                    chunk = response.read(CHUNK_SIZE)
                    if not chunk:
                        break
                    received += len(chunk)
                    if received > maximum_bytes:
                        raise ReleaseDownloadError(
                            "release download exceeds its size limit",
                            detail_code="RELEASE_ACTUAL_SIZE_MISMATCH",
                        )
                    handle.write(chunk)
                    digest.update(chunk)
            handle.flush()
            os.fsync(handle.fileno())
        actual_sha256 = digest.hexdigest()
        if expected_size_bytes is not None and received != expected_size_bytes:
            raise ReleaseDownloadError(
                "release download size does not match the manifest",
                detail_code="RELEASE_ACTUAL_SIZE_MISMATCH",
            )
        if expected_sha256 is not None and actual_sha256 != expected_sha256:
            raise ReleaseDownloadError(
                "release download SHA256 does not match the manifest",
                detail_code="RELEASE_SHA256_MISMATCH",
            )
        try:
            os.link(temporary, destination)
        except FileExistsError as exc:
            raise ReleaseDownloadError(
                "release download destination already exists",
                detail_code="RELEASE_DESTINATION_EXISTS",
            ) from exc
        except OSError as exc:
            raise ReleaseDownloadError(
                "release download could not be atomically published",
                detail_code="RELEASE_ATOMIC_PUBLICATION_FAILED",
            ) from exc
        temporary.unlink()
        return DownloadResult(
            path=destination,
            size_bytes=received,
            sha256=actual_sha256,
            redirect_count=redirect_count,
        )
    except ReleaseDownloadError:
        raise
    except (socket.timeout, TimeoutError) as exc:
        raise ReleaseDownloadError(
            "release download could not be completed",
            detail_code="RELEASE_READ_TIMEOUT",
        ) from exc
    except ConnectionError as exc:
        raise ReleaseDownloadError(
            "release download could not be completed",
            detail_code="RELEASE_HTTP_REQUEST_FAILED",
        ) from exc
    except OSError as exc:
        raise ReleaseDownloadError(
            "release download could not be completed",
            detail_code="RELEASE_LOCAL_IO_FAILED",
        ) from exc
    finally:
        if temporary.exists():
            try:
                temporary.unlink()
            except OSError:
                pass
