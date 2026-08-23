from __future__ import annotations

import ctypes
import json
import os
import threading
import time
import uuid
import zipfile
from pathlib import Path

import pytest

from enterprise.install_setup_bridge import (
    MAX_FRAME_BYTES,
    REQUEST_SCHEMA,
    RESULT_SCHEMA,
    SetupBridgeError,
    _blocked,
    _current_user_security_attributes,
    _decode_request,
    _encode_frame,
    _paths_overlap,
    _release_asset_directory,
    _serve_once,
    _validated_install_root,
)
from enterprise.ops.update.providers import DEFAULT_GITHUB_REPOSITORY, GitHubReleasesProvider
from tools.build_install_ux_1 import InstallerBuildError, _inspect_archive, _safe_archive_name


def _request(**changes: object) -> dict[str, object]:
    value: dict[str, object] = {
        "schema_version": REQUEST_SCHEMA,
        "username": "安装管理员",
        "password": "Fixture-only-Strong-Passphrase-2026!",
        "password_confirmation": "Fixture-only-Strong-Passphrase-2026!",
        "install_mode": "quick",
        "install_root": None,
    }
    value.update(changes)
    return value


def _request_bytes(**changes: object) -> bytes:
    return json.dumps(_request(**changes), ensure_ascii=False, separators=(",", ":")).encode(
        "utf-8"
    )


def test_request_is_bounded_exact_utf8_schema() -> None:
    assert _decode_request(_request_bytes()) == _request()
    with pytest.raises(SetupBridgeError, match="INSTALL_SETUP_BRIDGE_REQUEST_INVALID"):
        _decode_request(b"not-json")
    with pytest.raises(SetupBridgeError, match="INSTALL_SETUP_BRIDGE_REQUEST_INVALID"):
        _decode_request(_request_bytes(extra=True))
    with pytest.raises(SetupBridgeError, match="INSTALL_SETUP_BRIDGE_REQUEST_TOO_LARGE"):
        _decode_request(b"x" * (MAX_FRAME_BYTES + 1))


@pytest.mark.parametrize(
    "changes",
    [
        {"schema_version": "install-ux-2-request-v1"},
        {"username": 1},
        {"install_mode": "silent"},
        {"install_mode": "quick", "install_root": "C:\\unexpected"},
        {"install_mode": "custom", "install_root": None},
    ],
)
def test_request_rejects_unknown_or_inconsistent_fields(changes: dict[str, object]) -> None:
    with pytest.raises(SetupBridgeError, match="INSTALL_SETUP_BRIDGE_REQUEST_INVALID"):
        _decode_request(_request_bytes(**changes))


def test_result_is_bounded_stable_and_contains_no_credentials() -> None:
    password = "Never-In-Result-2026!"
    payload = _blocked("INSTALL_PASSWORD_INVALID")
    frame = _encode_frame(payload)
    assert len(frame) < 1024
    assert frame[:8] == f"{len(frame) - 8:08x}".encode("ascii")
    assert password.encode() not in frame
    assert json.loads(frame[8:]) == {
        "schema_version": RESULT_SCHEMA,
        "status": "blocked",
        "code": "INSTALL_PASSWORD_INVALID",
    }


def test_custom_target_is_fixed_empty_nonoverlapping(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    raw = tmp_path / "bundle" / "raw" / "app"
    assets = tmp_path / "bundle"
    known = tmp_path / "known"
    raw.mkdir(parents=True)
    monkeypatch.setattr("enterprise.install_setup_bridge._drive_type", lambda _path: 3)
    custom = tmp_path / "custom target"
    request = _request(install_mode="custom", install_root=str(custom))
    assert _validated_install_root(
        request, raw_app_root=raw, release_dir=assets, known_folder=known
    ) == custom.absolute()
    custom.mkdir()
    (custom / "user.txt").write_text("preserve", encoding="utf-8")
    with pytest.raises(SetupBridgeError, match="INSTALL_TARGET_NOT_GREENFIELD"):
        _validated_install_root(
            request, raw_app_root=raw, release_dir=assets, known_folder=known
        )
    assert (custom / "user.txt").read_text(encoding="utf-8") == "preserve"


def test_target_overlap_and_network_are_rejected(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    raw = tmp_path / "bundle" / "raw" / "app"
    raw.mkdir(parents=True)
    assets = tmp_path / "bundle"
    known = tmp_path / "known"
    monkeypatch.setattr("enterprise.install_setup_bridge._drive_type", lambda _path: 3)
    with pytest.raises(SetupBridgeError, match="INSTALL_TARGET_OVERLAP"):
        _validated_install_root(
            _request(install_mode="custom", install_root=str(raw / "installed")),
            raw_app_root=raw,
            release_dir=assets,
            known_folder=known,
        )
    with pytest.raises(SetupBridgeError, match="INSTALL_TARGET_UNSAFE"):
        _validated_install_root(
            _request(install_mode="custom", install_root=r"\\server\share\install"),
            raw_app_root=raw,
            release_dir=assets,
            known_folder=known,
        )
    assert _paths_overlap(raw, raw / "child") is True
    assert _paths_overlap(raw, tmp_path / "other") is False


def test_setup_asset_directory_is_derived_from_private_bundle_topology(tmp_path: Path) -> None:
    asset_root = tmp_path / "install-ux-bundle"
    raw_app_root = asset_root / "raw" / "release-id"
    raw_app_root.mkdir(parents=True)
    assert _release_asset_directory(raw_app_root) == asset_root

    invalid = tmp_path / "untrusted" / "raw" / "release-id"
    invalid.mkdir(parents=True)
    with pytest.raises(SetupBridgeError, match="INSTALL_RELEASE_ASSETS_REQUIRED"):
        _release_asset_directory(invalid)


@pytest.mark.skipif(os.name != "nt", reason="Windows named-pipe contract")
def test_pipe_security_descriptor_is_current_user_only() -> None:
    from enterprise import install_setup_bridge as bridge

    attributes, descriptor, sid = _current_user_security_attributes()
    try:
        assert attributes.bInheritHandle == 0
        assert sid.startswith("S-1-5-")
        assert descriptor != 0
    finally:
        bridge.kernel32.LocalFree(descriptor)


def _client_exchange(suffix: str, request: dict[str, object]) -> dict[str, object]:
    from enterprise import install_setup_bridge as bridge

    name = rf"\\.\pipe\{bridge.PIPE_PREFIX}{suffix}"
    deadline = time.monotonic() + 5
    while not bridge.kernel32.WaitNamedPipeW(name, 100):
        if time.monotonic() >= deadline:
            raise AssertionError("server pipe was not available")
        time.sleep(0.01)
    bridge.kernel32.CreateFileW.restype = ctypes.c_void_p
    handle = bridge.kernel32.CreateFileW(name, 0xC0000000, 0, None, 3, 0, None)
    assert handle not in {None, ctypes.c_void_p(-1).value}
    try:
        raw = json.dumps(request, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode(
            "utf-8"
        )
        frame = f"{len(raw):08x}".encode("ascii") + raw
        written = ctypes.c_ulong()
        assert bridge.kernel32.WriteFile(handle, frame, len(frame), ctypes.byref(written), None)
        assert written.value == len(frame)

        def read_exact(size: int) -> bytes:
            output = bytearray()
            while len(output) < size:
                chunk = ctypes.create_string_buffer(size - len(output))
                received = ctypes.c_ulong()
                assert bridge.kernel32.ReadFile(
                    handle, chunk, len(chunk), ctypes.byref(received), None
                )
                assert received.value > 0
                output.extend(chunk.raw[: received.value])
            return bytes(output)

        size = int(read_exact(8).decode("ascii"), 16)
        return json.loads(read_exact(size).decode("utf-8"))
    finally:
        bridge.kernel32.CloseHandle(handle)


@pytest.mark.skipif(os.name != "nt", reason="Windows named-pipe contract")
def test_real_current_user_pipe_round_trip_and_single_instance() -> None:
    from enterprise import install_setup_bridge as bridge

    suffix = uuid.uuid4().hex
    result: dict[str, object] = {}

    def serve() -> None:
        try:
            result["exit"] = _serve_once(
                suffix,
                lambda request: {
                    "schema_version": RESULT_SCHEMA,
                    "status": "succeeded",
                    "code": "INSTALL_SUCCEEDED",
                    "release_id": "fixture",
                    "username_seen": request["username"],
                },
            )
        except BaseException as exc:  # pragma: no cover - asserted below
            result["error"] = repr(exc)

    thread = threading.Thread(target=serve, daemon=True)
    thread.start()
    response = _client_exchange(suffix, _request())
    thread.join(timeout=5)
    assert not thread.is_alive()
    assert result == {"exit": 0}
    assert response["status"] == "succeeded"
    assert response["username_seen"] == "安装管理员"
    pipe_name = rf"\\.\pipe\{bridge.PIPE_PREFIX}{suffix}"
    assert not bridge.kernel32.WaitNamedPipeW(pipe_name, 50)


@pytest.mark.skipif(os.name != "nt", reason="Windows named-pipe contract")
def test_pipe_timeout_is_bounded(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("enterprise.install_setup_bridge.CONNECT_TIMEOUT_SECONDS", 0.05)
    started = time.monotonic()
    with pytest.raises(SetupBridgeError, match="INSTALL_SETUP_BRIDGE_TIMEOUT"):
        _serve_once(uuid.uuid4().hex, lambda _request: pytest.fail("no client expected"))
    assert time.monotonic() - started < 1.0


@pytest.mark.skipif(os.name != "nt", reason="Windows named-pipe contract")
def test_wrong_client_identity_fails_closed(monkeypatch: pytest.MonkeyPatch) -> None:
    def reject(_handle: int, _sid: str) -> None:
        raise SetupBridgeError("INSTALL_SETUP_BRIDGE_CLIENT_IDENTITY_MISMATCH")

    monkeypatch.setattr("enterprise.install_setup_bridge._validate_client_sid", reject)
    suffix = uuid.uuid4().hex
    observed: list[str] = []

    def serve() -> None:
        try:
            _serve_once(suffix, lambda _request: pytest.fail("identity must fail first"))
        except SetupBridgeError as exc:
            observed.append(exc.code)
        except BaseException as exc:  # pragma: no cover - diagnostic assertion below
            observed.append(type(exc).__name__ + ":" + str(exc))

    thread = threading.Thread(target=serve, daemon=True)
    thread.start()
    with pytest.raises(AssertionError):
        _client_exchange(suffix, _request())
    thread.join(timeout=5)
    assert not thread.is_alive()
    assert observed == ["INSTALL_SETUP_BRIDGE_CLIENT_IDENTITY_MISMATCH"]


@pytest.mark.parametrize(
    "name",
    [
        "../escape.txt",
        "/absolute.txt",
        "C:/drive.txt",
        "root/file.txt:ads",
        "root/CON.txt",
        "root/trailing. ",
    ],
)
def test_archive_path_safety_rejects_unsafe_names(name: str) -> None:
    with pytest.raises(InstallerBuildError, match="INSTALL_UX_BUILD_ARCHIVE_PATH_INVALID"):
        _safe_archive_name(name)


def test_archive_inspection_rejects_casefold_collision(tmp_path: Path) -> None:
    archive = tmp_path / "payload.zip"
    with zipfile.ZipFile(archive, "w") as target:
        target.writestr("root/File.txt", b"a")
        target.writestr("root/file.TXT", b"b")
    policy = {
        "archive_safety": {
            "maximum_entries": 10,
            "maximum_uncompressed_bytes": 1024,
        }
    }
    with pytest.raises(InstallerBuildError, match="INSTALL_UX_BUILD_ARCHIVE_PATH_COLLISION"):
        _inspect_archive(archive, policy)


def test_installer_source_is_single_user_gui_and_keeps_credentials_off_process_surfaces() -> None:
    root = Path(__file__).resolve().parents[2]
    source = (root / "installer" / "windows" / "InfiniteCanvasEnterprise.iss").read_text(
        encoding="utf-8"
    )
    lowered = source.casefold()
    assert "privilegesrequired=lowest" in lowered
    assert "setuparchitecture=x64" in lowered
    assert "uninstallable=no" in lowered
    assert "createinputquerypage" in lowered
    assert "password\":\"" in source
    parameters_body = source[source.index("Parameters :=") : source.index("if not Exec(")]
    assert "CredentialPage" not in parameters_body
    assert "--password" not in source
    assert "setenvironmentvariable" not in lowered
    assert "shell=true" not in lowered
    assert "powershell" not in lowered
    assert "python.exe'" in lowered or "python.exe\"" in lowered
    assert "-I -B" in source
    assert "install_setup_bridge.py" in source
    assert "GetSHA256OfFile" in source
    assert "Utf8Encode(Value)" in source
    assert "Utf8Decode(Value)" in source
    assert "WideCharToMultiByte" not in source
    assert "MultiByteToWideChar" not in source
    assert "desktopicon" in source
    assert "查看企业版状态.bat" in source
    assert "企业版健康检查.bat" in source


def test_bridge_bootstraps_before_product_install_import_and_has_no_credential_cli() -> None:
    root = Path(__file__).resolve().parents[2]
    source = (root / "enterprise" / "install_setup_bridge.py").read_text(encoding="utf-8")
    main = source[source.index("def main(") :]
    assert main.index("_python_isolation_ready()") < main.index("_prebootstrap_app_root")
    assert main.index("_prebootstrap_app_root") < main.index("_bootstrap_fixed_install_entry")
    assert "parser.add_argument(\"--pipe-name\"" in source
    assert "--password" not in source
    assert "GITHUB_TOKEN" not in source
    assert "subprocess" not in source
    assert "shell" not in source.casefold()
    assert "install_greenfield(" in source


def test_toolchain_and_build_policies_are_pinned_and_nonsecret() -> None:
    root = Path(__file__).resolve().parents[2]
    tool = json.loads(
        (root / "installer" / "windows" / "inno-setup-toolchain-policy.json").read_text(
            encoding="utf-8"
        )
    )
    build = json.loads(
        (root / "installer" / "windows" / "install-ux-1-build-policy.json").read_text(
            encoding="utf-8"
        )
    )
    assert tool["version"] == "7.1.0"
    assert len(tool["official_installer_sha256"]) == 64
    assert set(tool["compiler_closure"]) == {"ISCC.exe", "ISCmplr.dll", "Setup.e64"}
    assert all(len(value) == 64 for value in tool["compiler_closure"].values())
    assert build["core_asset_count"] == 3
    assert build["security_authority"] == "enterprise.fresh_install.install_greenfield"
    assert build["uninstaller_created"] is False
    combined = json.dumps({"tool": tool, "build": build}).casefold()
    assert "private_key" not in combined
    assert "password" not in combined
    assert "token" not in combined


def test_github_provider_ignores_installer_exe_and_keeps_three_core_asset_selection() -> None:
    def asset(name: str, asset_id: int) -> dict[str, object]:
        return {
            "id": asset_id,
            "name": name,
            "state": "uploaded",
            "size": asset_id,
            "url": f"https://api.github.com/repos/{DEFAULT_GITHUB_REPOSITORY}/releases/assets/{asset_id}",
        }

    release = {
        "id": 101,
        "tag_name": "v2026.08.5",
        "draft": False,
        "prerelease": False,
        "published_at": "2026-08-24T00:00:00Z",
        "body": "fixture",
        "assets": [
            asset("ops-release-manifest-v2.json", 1),
            asset("release-payload-inventory.json", 2),
            asset("Infinite-Canvas-Enterprise-ice-2026.08.5-aabbccddeeff-win-x64.zip", 3),
            asset("Infinite-Canvas-Enterprise-Setup-2026.08.5-x64.exe", 4),
        ],
    }

    class Client:
        def read_json(self, *_args, **_kwargs):
            return [release]

    candidates = GitHubReleasesProvider(http_client=Client()).list_release_v2_candidates()
    assert len(candidates) == 1
    assert candidates[0].manifest_url.endswith("/1")
    assert candidates[0].inventory_url.endswith("/2")
    assert candidates[0].archive_url.endswith("/3")
    assert not candidates[0].archive_url.endswith("/4")
