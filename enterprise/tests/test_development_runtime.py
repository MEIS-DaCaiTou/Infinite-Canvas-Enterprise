import importlib.metadata
import re

from tools.check_development_runtime import ROOT, check_runtime


def release_packages():
    return dict(re.findall(r"^([\w.-]+)==([^\s]+)", (ROOT / "runtime/windows/requirements.lock").read_text(), re.M))


def test_release_runtime_policy_matches_installed_environment():
    assert check_runtime() == []


def test_wrong_interpreter_and_dependency_drift_are_reported():
    packages = release_packages()
    packages["pyjwt"] = "2.8.0"
    errors = check_runtime(version="3.11.0", package_version=packages.__getitem__)
    assert any("Python:" in error for error in errors)
    assert any("pyjwt:" in error for error in errors)


def test_missing_application_package_is_reported():
    def missing(name):
        raise importlib.metadata.PackageNotFoundError(name)
    assert all("found missing" in error for error in check_runtime(version="3.14.6", package_version=missing))
