"""Trusted release metadata providers for OPS-3A preparation only."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Protocol

from enterprise.ops.update.errors import ReleaseProviderError
from enterprise.ops.update.http_client import SafeHttpClient, UrlPolicy
from enterprise.ops.update.models import ReleaseMetadata
from enterprise.ops.update.versions import parse_version


DEFAULT_GITHUB_REPOSITORY = "MEIS-DaCaiTou/Infinite-Canvas-Enterprise"
TRUSTED_GITHUB_REPOSITORIES = frozenset({DEFAULT_GITHUB_REPOSITORY})
GITHUB_ALLOWED_HOSTS = frozenset(
    {
        "api.github.com",
        "github.com",
        "objects.githubusercontent.com",
        "release-assets.githubusercontent.com",
        "github-releases.githubusercontent.com",
    }
)
GITHUB_MANIFEST_ASSET = "ops-release-manifest-v1.json"
MAX_GITHUB_METADATA_BYTES = 1024 * 1024
MAX_FIXTURE_BYTES = 1024 * 1024


class ReleaseProvider(Protocol):
    """Return normalized metadata only; providers never stage or upgrade."""

    name: str
    url_policy: UrlPolicy

    def list_releases(self) -> list[ReleaseMetadata]:
        """Return trusted release metadata in provider order."""


def _required_text(value: object, label: str, maximum: int = 16 * 1024) -> str:
    if not isinstance(value, str) or not value or value != value.strip() or len(value) > maximum:
        raise ReleaseProviderError(f"{label} is invalid")
    return value


def _release_id(value: object) -> str:
    if isinstance(value, bool):
        raise ReleaseProviderError("release identifier is invalid")
    if isinstance(value, int) and value >= 0:
        return str(value)
    return _required_text(value, "release identifier", maximum=256)


def _normalized_version(tag_name: str, value: object) -> str:
    raw = _required_text(value, "release version", maximum=64)
    try:
        version = str(parse_version(raw))
    except ValueError as exc:
        raise ReleaseProviderError("release version is invalid") from exc
    if tag_name not in {version, f"v{version}"}:
        raise ReleaseProviderError("release tag and version differ")
    return version


def normalize_release_metadata(
    payload: object,
    *,
    provider: str,
    repository: str,
    url_policy: UrlPolicy,
) -> ReleaseMetadata:
    """Validate a provider record before it can become an update candidate."""
    if type(payload) is not dict:
        raise ReleaseProviderError("release metadata record is invalid")
    source_repository = _required_text(payload.get("repository", repository), "release repository", maximum=256)
    if source_repository != repository:
        raise ReleaseProviderError("release repository is not trusted")
    tag_name = _required_text(payload.get("tag_name"), "release tag", maximum=128)
    prerelease = payload.get("prerelease")
    draft = payload.get("draft")
    if type(prerelease) is not bool or type(draft) is not bool:
        raise ReleaseProviderError("release visibility flags are invalid")
    metadata = ReleaseMetadata(
        provider=provider,
        repository=repository,
        release_id=_release_id(payload.get("release_id")),
        tag_name=tag_name,
        version=_normalized_version(tag_name, payload.get("version")),
        prerelease=prerelease,
        draft=draft,
        published_at=_required_text(payload.get("published_at"), "release publication time", maximum=64),
        manifest_url=_required_text(payload.get("manifest_url"), "manifest URL", maximum=2048),
        archive_url=_required_text(payload.get("archive_url"), "archive URL", maximum=2048),
        release_notes=str(payload.get("release_notes") or ""),
    )
    if len(metadata.release_notes) > 16 * 1024:
        raise ReleaseProviderError("release notes exceed their size limit")
    url_policy.validate(metadata.manifest_url)
    url_policy.validate(metadata.archive_url)
    return metadata


class LocalFixtureProvider:
    """Offline fixture provider; loopback HTTP is allowed only for this provider."""

    name = "local-fixture"
    url_policy = UrlPolicy(frozenset(), allow_loopback_http=True)

    def __init__(self, fixture_path: str | os.PathLike[str], *, repository: str = DEFAULT_GITHUB_REPOSITORY) -> None:
        self.fixture_path = Path(fixture_path)
        self.repository = repository

    def list_releases(self) -> list[ReleaseMetadata]:
        try:
            if not self.fixture_path.is_file() or self.fixture_path.stat().st_size > MAX_FIXTURE_BYTES:
                raise ReleaseProviderError("local release fixture is invalid")
            payload = json.loads(self.fixture_path.read_text(encoding="utf-8"))
        except ReleaseProviderError:
            raise
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            raise ReleaseProviderError("local release fixture could not be read") from exc
        records = payload.get("releases") if type(payload) is dict else None
        if type(records) is not list or len(records) > 100:
            raise ReleaseProviderError("local release fixture records are invalid")
        return [
            normalize_release_metadata(
                record,
                provider=self.name,
                repository=self.repository,
                url_policy=self.url_policy,
            )
            for record in records
        ]


class GitHubReleasesProvider:
    """Trusted GitHub release metadata provider with a fixed repository allowlist."""

    name = "github-releases"
    url_policy = UrlPolicy(GITHUB_ALLOWED_HOSTS)

    def __init__(
        self,
        *,
        repository: str = DEFAULT_GITHUB_REPOSITORY,
        http_client: SafeHttpClient | None = None,
    ) -> None:
        if repository not in TRUSTED_GITHUB_REPOSITORIES:
            raise ReleaseProviderError("GitHub repository is not approved")
        self.repository = repository
        self.http_client = http_client or SafeHttpClient(self.url_policy)

    def list_releases(self) -> list[ReleaseMetadata]:
        url = f"https://api.github.com/repos/{self.repository}/releases?per_page=50"
        headers = {"Accept": "application/vnd.github+json", "User-Agent": "Infinite-Canvas-Enterprise-OPS-3A"}
        token = os.environ.get("GITHUB_TOKEN")
        if token:
            headers["Authorization"] = f"Bearer {token}"
        payload = self.http_client.read_json(url, maximum_bytes=MAX_GITHUB_METADATA_BYTES, headers=headers)
        if type(payload) is not list or len(payload) > 50:
            raise ReleaseProviderError("GitHub release metadata is invalid")
        releases: list[ReleaseMetadata] = []
        for release in payload:
            if type(release) is not dict:
                raise ReleaseProviderError("GitHub release metadata is invalid")
            assets = release.get("assets")
            if type(assets) is not list:
                raise ReleaseProviderError("GitHub release assets are invalid")
            manifest_asset = _single_asset(assets, exact_name=GITHUB_MANIFEST_ASSET)
            archive_asset = _single_asset(assets, suffix=".zip")
            releases.append(
                normalize_release_metadata(
                    {
                        "repository": self.repository,
                        "release_id": release.get("id"),
                        "tag_name": release.get("tag_name"),
                        "version": _tag_to_version(release.get("tag_name")),
                        "prerelease": release.get("prerelease"),
                        "draft": release.get("draft"),
                        "published_at": release.get("published_at"),
                        "manifest_url": manifest_asset["browser_download_url"],
                        "archive_url": archive_asset["browser_download_url"],
                        "release_notes": release.get("body") or "",
                    },
                    provider=self.name,
                    repository=self.repository,
                    url_policy=self.url_policy,
                )
            )
        return releases


def _tag_to_version(value: object) -> str:
    tag = _required_text(value, "release tag", maximum=128)
    return tag[1:] if tag.startswith("v") else tag


def _single_asset(assets: list[object], *, exact_name: str = "", suffix: str = "") -> dict[str, Any]:
    matches = [
        asset
        for asset in assets
        if type(asset) is dict
        and isinstance(asset.get("name"), str)
        and ((exact_name and asset["name"] == exact_name) or (suffix and asset["name"].endswith(suffix)))
    ]
    if len(matches) != 1:
        raise ReleaseProviderError("GitHub release assets are ambiguous or incomplete")
    asset = matches[0]
    if not isinstance(asset.get("browser_download_url"), str):
        raise ReleaseProviderError("GitHub release asset URL is invalid")
    return asset
