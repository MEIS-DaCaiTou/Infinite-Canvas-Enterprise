"""Stable, redacted errors for the OPS-3A online-update core."""

from __future__ import annotations


class OnlineUpdateError(RuntimeError):
    """Base error with a stable public code and secret-free message."""

    code = "ONLINE_UPDATE_FAILED"
    public_message = "Online update preparation failed"
    detail_code = ""

    def __init__(self, message: str | None = None) -> None:
        super().__init__(message or self.public_message)


class OnlineUpdateValidationError(OnlineUpdateError):
    code = "ONLINE_UPDATE_VALIDATION_FAILED"
    public_message = "Online update input validation failed"


class ReleaseManifestError(OnlineUpdateError):
    code = "RELEASE_MANIFEST_INVALID"
    public_message = "Release manifest validation failed"


class ReleaseProviderError(OnlineUpdateError):
    code = "RELEASE_PROVIDER_FAILED"
    public_message = "Trusted release metadata could not be obtained"


class ReleaseDownloadError(OnlineUpdateError):
    code = "RELEASE_DOWNLOAD_FAILED"
    public_message = "Release download validation failed"

    _DETAIL_CODES = frozenset(
        {
            "RELEASE_DOWNLOAD_UNCLASSIFIED",
            "RELEASE_DOWNLOAD_INPUT_INVALID",
            "RELEASE_DESTINATION_EXISTS",
            "RELEASE_HTTP_REQUEST_FAILED",
            "RELEASE_REDIRECT_REJECTED",
            "RELEASE_ADVERTISED_SIZE_MISMATCH",
            "RELEASE_READ_TIMEOUT",
            "RELEASE_ACTUAL_SIZE_MISMATCH",
            "RELEASE_SHA256_MISMATCH",
            "RELEASE_ATOMIC_PUBLICATION_FAILED",
            "RELEASE_LOCAL_IO_FAILED",
        }
    )

    def __init__(
        self,
        message: str | None = None,
        *,
        detail_code: str = "RELEASE_DOWNLOAD_UNCLASSIFIED",
    ) -> None:
        if detail_code not in self._DETAIL_CODES:
            raise ValueError("release download detail code is invalid")
        self.detail_code = detail_code
        super().__init__(message)


class ReleaseStagingError(OnlineUpdateError):
    code = "RELEASE_STAGING_FAILED"
    public_message = "Release staging validation failed"


class UpdatePlanBlockedError(OnlineUpdateError):
    code = "ONLINE_UPDATE_BLOCKED"
    public_message = "Online update plan is blocked"
