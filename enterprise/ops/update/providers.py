"""Trusted release metadata providers for OPS-3A preparation only."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Literal, Mapping, Protocol
from urllib.parse import urlparse

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
GITHUB_METADATA_ACCEPT = "application/vnd.github+json"
GITHUB_ASSET_ACCEPT = "application/octet-stream"
GITHUB_API_VERSION = "2022-11-28"
GITHUB_USER_AGENT = "Infinite-Canvas-Enterprise-OPS-3A"
MAX_GITHUB_METADATA_BYTES = 1024 * 1024
MAX_FIXTURE_BYTES = 1024 * 1024
MAX_PROVIDER_DIAGNOSTICS = 16


class ReleaseProvider(Protocol):
    """Return normalized metadata only; providers never stage or upgrade."""

    name: str
    url_policy: UrlPolicy
    diagnostics: tuple[str, ...]
    record_count: int

    def list_releases(self) -> list[ReleaseMetadata]:
        """Return trusted release metadata in provider order."""

    def release_asset_request_headers(
        self,
        metadata: ReleaseMetadata,
        *,
        asset_kind: Literal["manifest", "archive"],
    ) -> Mapping[str, str]:
        """Return transient headers for one trusted manifest or archive request."""


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


def _optional_positive_int(value: object, label: str) -> int | None:
    if value is None:
        return None
    if type(value) is not int or value < 1:
        raise ReleaseProviderError(f"{label} is invalid")
    return value


def _optional_asset_name(value: object, label: str) -> str | None:
    if value is None:
        return None
    return _required_text(value, label, maximum=512)


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
        manifest_asset_name=_optional_asset_name(payload.get("manifest_asset_name"), "manifest asset name"),
        archive_asset_name=_optional_asset_name(payload.get("archive_asset_name"), "archive asset name"),
        manifest_asset_size_bytes=_optional_positive_int(payload.get("manifest_asset_size_bytes"), "manifest asset size"),
        archive_asset_size_bytes=_optional_positive_int(payload.get("archive_asset_size_bytes"), "archive asset size"),
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
        self.diagnostics: tuple[str, ...] = ()
        self.record_count = 0

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
        self.record_count = len(records)
        return [
            normalize_release_metadata(
                record,
                provider=self.name,
                repository=self.repository,
                url_policy=self.url_policy,
            )
            for record in records
        ]

    def release_asset_request_headers(
        self,
        metadata: ReleaseMetadata,
        *,
        asset_kind: Literal["manifest", "archive"],
    ) -> Mapping[str, str]:
        if metadata.provider != self.name or metadata.repository != self.repository:
            raise ReleaseProviderError("release metadata is not owned by this provider")
        if asset_kind not in {"manifest", "archive"}:
            raise ReleaseProviderError("release asset kind is invalid")
        return {}


class GitHubReleasesProvider:
    """Trusted GitHub release metadata provider with a fixed repository allowlist."""

    name = "github-releases"
    url_policy = UrlPolicy(GITHUB_ALLOWED_HOSTS)
    # These are deliberately fixed in the production provider. The loopback
    # fixture subclass overrides them only to exercise the same repository and
    # asset-path checks without making Internet requests in tests.
    asset_api_scheme = "https"
    asset_api_host = "api.github.com"

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
        self.diagnostics: tuple[str, ...] = ()
        self.record_count = 0
        self._asset_request_headers: dict[str, str] = {}

    def list_releases(self) -> list[ReleaseMetadata]:
        url = f"https://api.github.com/repos/{self.repository}/releases?per_page=50"
        headers = {"Accept": GITHUB_METADATA_ACCEPT, "User-Agent": GITHUB_USER_AGENT}
        token = os.environ.get("GITHUB_TOKEN")
        if token:
            headers["Authorization"] = f"Bearer {token}"
        # This mapping is held only by the provider instance. It is supplied to
        # trusted initial asset requests and never enters metadata, reports,
        # logs, URLs, or exceptions. SafeHttpClient strips it on any redirect
        # that crosses an origin boundary.
        self._asset_request_headers = {"Authorization": headers["Authorization"]} if "Authorization" in headers else {}
        payload = self.http_client.read_json(url, maximum_bytes=MAX_GITHUB_METADATA_BYTES, headers=headers)
        if type(payload) is not list or len(payload) > 50:
            raise ReleaseProviderError("GitHub release metadata is invalid")
        self.record_count = len(payload)
        releases: list[ReleaseMetadata] = []
        diagnostics: list[str] = []

        def skip(code: str) -> None:
            if len(diagnostics) < MAX_PROVIDER_DIAGNOSTICS:
                diagnostics.append(code)

        for release in payload:
            if type(release) is not dict:
                skip("invalid_release_record_skipped")
                continue
            # Drafts are never visible update candidates. Skip them before
            # checking assets so an incomplete draft cannot block valid history.
            if release.get("draft") is True:
                skip("draft_release_skipped")
                continue
            try:
                assets = release.get("assets")
                if type(assets) is not list:
                    raise ReleaseProviderError("GitHub release assets are invalid")
                manifest_asset = self._release_asset(assets, exact_name=GITHUB_MANIFEST_ASSET)
                archive_asset = self._release_asset(assets, suffix=".zip")
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
                            # Browser download URLs are not the private-release
                            # fetch path. Use the repository-bound asset REST API.
                            "manifest_url": manifest_asset["api_url"],
                            "archive_url": archive_asset["api_url"],
                            "manifest_asset_name": manifest_asset["name"],
                            "archive_asset_name": archive_asset["name"],
                            "manifest_asset_size_bytes": manifest_asset["size_bytes"],
                            "archive_asset_size_bytes": archive_asset["size_bytes"],
                            "release_notes": release.get("body") or "",
                        },
                        provider=self.name,
                        repository=self.repository,
                        url_policy=self.url_policy,
                    )
                )
            except ReleaseProviderError:
                # A bad historical or incomplete release is not trusted, but it
                # cannot make later complete releases unavailable. Diagnostics
                # deliberately carry only bounded generic codes.
                skip("invalid_or_incomplete_release_skipped")
        self.diagnostics = tuple(diagnostics)
        return releases

    def release_asset_request_headers(
        self,
        metadata: ReleaseMetadata,
        *,
        asset_kind: Literal["manifest", "archive"],
    ) -> Mapping[str, str]:
        if metadata.provider != self.name or metadata.repository != self.repository:
            raise ReleaseProviderError("release metadata is not owned by this provider")
        if asset_kind not in {"manifest", "archive"}:
            raise ReleaseProviderError("release asset kind is invalid")
        expected_url = metadata.manifest_url if asset_kind == "manifest" else metadata.archive_url
        self._validate_asset_api_url(expected_url, asset_id=None)
        return {
            "Accept": GITHUB_ASSET_ACCEPT,
            "X-GitHub-Api-Version": GITHUB_API_VERSION,
            "User-Agent": GITHUB_USER_AGENT,
            **self._asset_request_headers,
        }

    def _release_asset(self, assets: list[object], *, exact_name: str = "", suffix: str = "") -> dict[str, object]:
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
        asset_id = asset.get("id")
        if type(asset_id) is not int or asset_id < 0:
            raise ReleaseProviderError("GitHub release asset identifier is invalid")
        if "state" in asset and asset["state"] != "uploaded":
            raise ReleaseProviderError("GitHub release asset state is invalid")
        api_url = self._validate_asset_api_url(asset.get("url"), asset_id=asset_id)
        browser_url = asset.get("browser_download_url")
        if browser_url is not None and not isinstance(browser_url, str):
            raise ReleaseProviderError("GitHub release browser asset metadata is invalid")
        return {
            "id": asset_id,
            "name": asset["name"],
            "api_url": api_url,
            "size_bytes": _optional_positive_int(asset.get("size"), "GitHub release asset size"),
        }

    def _validate_asset_api_url(self, value: object, *, asset_id: int | None) -> str:
        url = _required_text(value, "GitHub release asset API URL", maximum=2048)
        try:
            parsed = urlparse(url)
            port = parsed.port
        except ValueError as exc:
            raise ReleaseProviderError("GitHub release asset API URL is invalid") from exc
        expected_prefix = f"/repos/{self.repository}/releases/assets/"
        if (
            parsed.scheme != self.asset_api_scheme
            or (parsed.hostname or "").casefold() != self.asset_api_host
            or (self.asset_api_scheme == "https" and port not in {None, 443})
            or parsed.username
            or parsed.password
            or parsed.query
            or parsed.fragment
            or not parsed.path.startswith(expected_prefix)
        ):
            raise ReleaseProviderError("GitHub release asset API URL is invalid")
        raw_id = parsed.path[len(expected_prefix):]
        if not raw_id.isascii() or not raw_id.isdecimal() or (asset_id is not None and raw_id != str(asset_id)):
            raise ReleaseProviderError("GitHub release asset API URL is invalid")
        return self.url_policy.validate(url)


def _tag_to_version(value: object) -> str:
    tag = _required_text(value, "release tag", maximum=128)
    return tag[1:] if tag.startswith("v") else tag
