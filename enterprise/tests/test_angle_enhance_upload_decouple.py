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


def _reject(source: str, needle: str, label: str) -> None:
    assert needle not in source, f"unexpected {label}: {needle}"


def _between(source: str, start: str, end: str) -> str:
    assert start in source, f"missing segment start: {start}"
    tail = source.split(start, 1)[1]
    assert end in tail, f"missing segment end after {start}: {end}"
    return tail.split(end, 1)[0]


def _run_checks() -> None:
    angle = _source(ANGLE)
    enhance = _source(ENHANCE)

    angle_cloud_mode = _between(angle, "function isAngleCloudMode()", "function refreshAngleSubmitState()")
    angle_refresh = _between(angle, "function refreshAngleSubmitState()", "window.switchEngine = function")
    angle_switch = _between(angle, "window.switchEngine = function(mode)", "function generateUUID()")
    angle_file = _between(angle, "async function handleFile(file)", "function applyAngleToPrompt()")
    angle_generate = _between(angle, "async function handleGenerate()", "function loadNextPage()")

    _require(angle, "function isAngleCloudMode()", "Angle cloud mode helper")
    _require(angle, "function refreshAngleSubmitState()", "Angle submit refresh helper")
    _require(
        angle_cloud_mode,
        "return currentEngine === 'cloud' || cloudBtn?.classList.contains('active');",
        "Angle cloud mode uses state and active UI",
    )
    _require(angle_refresh, "if (isAngleCloudMode())", "Angle refresh uses cloud helper")
    _require(angle_switch, "refreshAngleSubmitState();", "Angle switch refreshes button")
    _require(angle_file, "refreshAngleSubmitState();", "Angle file path refreshes button")
    _require(
        angle_file,
        "console.warn(\"Local upload error\", err);\n                refreshAngleSubmitState();",
        "Angle upload catch refreshes button",
    )
    _require(angle, "uploadedFile = file; // Store for cloud usage", "Angle stores raw file")
    _require(angle, "uploadedPath = \"\";", "Angle clears stale local upload path")
    _require(angle_generate, "const cloudMode = isAngleCloudMode();", "Angle generate uses cloud helper")
    _require(angle_generate, "if (!uploadedPath && !cloudMode)", "Angle local mode still requires uploadedPath")
    _require(angle_generate, "if (!uploadedFile && cloudMode)", "Angle cloud mode requires uploadedFile")
    _require(angle_generate, "if (cloudMode)", "Angle cloud branch uses helper")
    _require(angle, "const dataUri = await toBase64(uploadedFile);", "Angle cloud uses raw file DataURL")
    _require(angle, "fetch('/api/angle/generate'", "Angle cloud still calls angle endpoint")

    enhance_ms_mode = _between(enhance, "function isEnhanceMsMode()", "function hasEnhancePreviewInput()")
    enhance_refresh = _between(enhance, "function refreshEnhanceSubmitState()", "function setEnhanceProvider(p)")
    enhance_provider = _between(enhance, "function setEnhanceProvider(p)", "const dropzone = document.getElementById('dropzone')")
    enhance_file = _between(enhance, "async function handleFile(file)", "function toggleUpscaleOptions()")
    enhance_generate = _between(enhance, "async function handleGenerate()", "async function loadHistory()")

    _require(enhance, "function isEnhanceMsMode()", "Enhance MS mode helper")
    _require(enhance, "function hasEnhancePreviewInput()", "Enhance preview input helper")
    _require(enhance, "function refreshEnhanceSubmitState()", "Enhance submit refresh helper")
    _require(
        enhance_ms_mode,
        "return enhanceProvider === 'ms' || msBtn?.classList.contains('active');",
        "Enhance MS mode uses state and active UI",
    )
    _require(enhance_refresh, "if (isEnhanceMsMode())", "Enhance refresh uses MS helper")
    _require(enhance_provider, "refreshEnhanceSubmitState();", "Enhance provider switch refreshes button")
    _reject(enhance_provider, "hasPreview && !btn.disabled", "Enhance stale disabled refresh guard")
    _require(enhance_file, "refreshEnhanceSubmitState();", "Enhance file path refreshes button")
    _require(
        enhance_file,
        "console.warn(\"Local upload error\", err);\n                refreshEnhanceSubmitState();",
        "Enhance upload catch refreshes button",
    )
    _require(enhance, "let uploadedFile = null;", "Enhance stores raw file")
    _require(enhance, "let uploadedDataUrl = \"\";", "Enhance stores DataURL")
    _require(enhance, "uploadedFile = file;", "Enhance assigns raw file")
    _require(enhance, "uploadedDataUrl = e.target.result;", "Enhance captures preview DataURL")
    _require(enhance_generate, "const msMode = isEnhanceMsMode();", "Enhance generate uses MS helper")
    _require(enhance_generate, "if ((!msMode && !uploadedPath) || (msMode && !msInputSrc))", "Enhance provider-specific input guard")
    _require(enhance_generate, "if (msMode)", "Enhance MS branch uses helper")
    _require(enhance, "const previewSrc = msInputSrc;", "Enhance MS uses DataURL/preview input")
    _require(enhance, "fetch('/api/ms/generate'", "Enhance MS still calls ModelScope endpoint")
    _require(enhance, "params: { \"15\": { \"image\": uploadedPath }, \"204\":", "Enhance local mode still uses uploadedPath")


if __name__ == "__main__":
    _run_checks()
    print("angle/enhance upload decoupling checks passed")
