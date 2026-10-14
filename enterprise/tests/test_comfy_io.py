"""Variable inputs and reusable typed results without contacting a GPU backend."""
from copy import deepcopy
from pathlib import Path
import subprocess

import pytest

from enterprise.providers.comfy_workflow import (
    image_group_candidates, apply_workflow_values, validate_image_groups, select_history_outputs, field_role,
)


@pytest.fixture
def graph():
    return {
        "a": {"class_type": "LoadImage", "inputs": {"image": "old-subject.png"}},
        "b": {"class_type": "LoadImage", "inputs": {"image": "old-reference.png"}},
        "edit": {"class_type": "TextEncodeQwenImage21", "inputs": {
            "images.image_1": ["a", 0], "images.image_2": ["b", 0], "prompt": "edit"}},
        "batch": {"class_type": "BatchImagesNode", "inputs": {
            "images.image0": ["a", 0], "images.image1": ["b", 0]}},
        "compare": {"class_type": "ImageCompare", "inputs": {"image_a": ["a", 0]}},
    }


def test_variable_images_update_both_branches_and_leave_saved_graph_unchanged(graph):
    original = deepcopy(graph)
    candidate, = image_group_candidates(graph)
    config = {"fields": [{"id": "old", "node": "b", "input": "image", "type": "image", "default": "old.png"}],
              "image_groups": [candidate]}
    one = apply_workflow_values(graph, config, {candidate["id"]: ["new-subject.png"]})
    assert "b" not in one
    assert one["edit"]["inputs"] == {"images.image_1": ["a", 0], "prompt": "edit"}
    assert one["batch"]["inputs"] == {"images.image0": ["a", 0]}
    names = [f"selected-{i}.png" for i in range(10)]
    ten = apply_workflow_values(graph, config, {candidate["id"]: names})
    for i, name in enumerate(names):
        loader = ten["edit"]["inputs"][f"images.image_{i+1}"][0]
        assert ten[loader]["inputs"]["image"] == name
        assert ten["batch"]["inputs"][f"images.image{i}"] == [loader, 0]
    assert ten["compare"]["inputs"]["image_a"] == ["a", 0]
    assert graph == original
    for values in [[], names + ["excess.png"], [""], "not-a-list"]:
        with pytest.raises(ValueError, match="需要"):
            apply_workflow_values(graph, config, {candidate["id"]: values})


def test_unsupported_optional_branch_is_not_guessed_and_invalid_config_rejected(graph):
    candidate, = image_group_candidates(graph)
    for changes in [{"max_images": 100}, {"min_images": 0}, {"source_nodes": ["unknown"]}]:
        with pytest.raises(ValueError):
            validate_image_groups(graph, [{**candidate, **changes}])
    graph["mask"] = {"class_type": "OtherNode", "inputs": {"mask": ["b", 1]}}
    assert image_group_candidates(graph) == []


def test_prompt_roles_distinguish_user_system_and_filename(graph):
    graph["input"] = {"class_type": "PrimitiveStringMultiline", "inputs": {"value": "edit"}}
    graph["system"] = {"class_type": "PrimitiveStringMultiline", "inputs": {"value": "system"}}
    graph["enhance"] = {"class_type": "TextGenerate", "inputs": {"prompt": ["input", 0], "system_prompt": ["system", 0]}}
    assert field_role(graph, {"node": "input", "input": "value"}) == "prompt"
    assert field_role(graph, {"node": "system", "input": "value"}) == "system"
    assert field_role(graph, {"node": "save", "input": "filename_prefix"}) == "parameter"
    assert field_role(graph, {"node": "edit", "input": "negative_prompt"}) == "negative"


def test_text_body_and_saved_attachment_form_one_output_without_cross_run_dedup():
    workflow = {"save": {"class_type": "SaveText"}, "preview": {"class_type": "PreviewAny"}}
    history = {"outputs": {
        "save": {"text": ["完整提示词\nsecond line"], "files": [{"filename": "prompt.txt", "type": "output"}]},
        "preview": {"text": ["debug"]},
    }}
    debug = lambda value: value == "PreviewAny"
    files, texts = select_history_outputs(history, workflow, is_preview=lambda _: False, is_debug=debug)
    assert len(files) == 1 and texts == []
    assert files[0]["text"] == "完整提示词\nsecond line"
    assert select_history_outputs(history, workflow, is_preview=lambda _: False, is_debug=debug)[0] == files
    files, texts = select_history_outputs({"outputs": {"preview": {"text": ["only text"]}}}, workflow,
                                         is_preview=lambda _: False, is_debug=debug)
    assert not files and texts[0]["text"] == "only text"


def test_shared_frontend_typed_outputs_and_image_ranges():
    subprocess.run(["node", str(Path(__file__).with_suffix(".js"))], check=True)
