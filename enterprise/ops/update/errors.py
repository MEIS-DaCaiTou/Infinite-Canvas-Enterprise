"""Stable, redacted errors for the OPS-3A online-update core."""

from __future__ import annotations


class OnlineUpdateError(RuntimeError):
    """Base error with a stable public code and secret-free message."""

    code = "ONLINE_UPDATE_FAILED"
    public_message = "Online update preparation failed"

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


class ReleaseStagingError(OnlineUpdateError):
    code = "RELEASE_STAGING_FAILED"
    public_message = "Release staging validation failed"


class UpdatePlanBlockedError(OnlineUpdateError):
    code = "ONLINE_UPDATE_BLOCKED"
    public_message = "Online update plan is blocked"
