"""
Static checks for Angle / Enhance ModelScope upload decoupling.

These checks keep the cloud/MS image-input flow independent from the local
ComfyUI /api/upload path while preserving the local-mode uploadedPath guard.

Run from the repository root:

    python .\\enterprise\\tests\\test_angle_enhance_upload_decouple.py
"""
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
ANGLE = ROOT / "static" / "angle.html"
ENHANCE = ROOT / "static" / "enhance.html"


def _source(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _require(source: str, needle: str, label: str) -> None:
    assert needle in source, f"missing {label}: {needle}"


def _run_checks() -> None:
    angle = _source(ANGLE)
    enhance = _source(ENHANCE)

    _require(angle, "uploadedFile = file; // Store for cloud usage", "Angle stores raw file")
    _require(angle, "uploadedPath = \"\";", "Angle clears stale local upload path")
    _require(angle, "if (currentEngine === 'cloud')", "Angle handles cloud upload fallback")
    _require(angle, "btnText.innerText = tr('studio.generateAngle');", "Angle cloud fallback keeps generate enabled")
    _require(angle, "if (!uploadedPath && currentEngine === 'local')", "Angle local mode still requires uploadedPath")
    _require(angle, "if (!uploadedFile && currentEngine === 'cloud')", "Angle cloud mode requires uploadedFile")
    _require(angle, "const dataUri = await toBase64(uploadedFile);", "Angle cloud uses raw file DataURL")
    _require(angle, "fetch('/api/angle/generate'", "Angle cloud still calls angle endpoint")

    _require(enhance, "let uploadedFile = null;", "Enhance stores raw file")
    _require(enhance, "let uploadedDataUrl = \"\";", "Enhance stores DataURL")
    _require(enhance, "uploadedFile = file;", "Enhance assigns raw file")
    _require(enhance, "uploadedDataUrl = e.target.result;", "Enhance captures preview DataURL")
    _require(enhance, "if (enhanceProvider === 'ms')", "Enhance handles MS upload fallback")
    _require(enhance, "btnText.innerText = tr('studio.beginRemaster');", "Enhance MS fallback keeps submit enabled")
    _require(
        enhance,
        "if ((enhanceProvider === 'local' && !uploadedPath) || (enhanceProvider === 'ms' && !msInputSrc))",
        "Enhance provider-specific input guard",
    )
    _require(enhance, "const previewSrc = msInputSrc;", "Enhance MS uses DataURL/preview input")
    _require(enhance, "fetch('/api/ms/generate'", "Enhance MS still calls ModelScope endpoint")
    _require(enhance, "params: { \"15\": { \"image\": uploadedPath }, \"204\":", "Enhance local mode still uses uploadedPath")


if __name__ == "__main__":
    _run_checks()
    print("angle/enhance upload decoupling checks passed")
