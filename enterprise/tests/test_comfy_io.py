"""Variable inputs and reusable typed results without contacting a GPU backend."""
from copy import deepcopy
from pathlib import Path
import subprocess

import pytest

from enterprise.providers.comfy_workflow import (
    image_group_candidates, apply_workflow_values, validate_image_groups, select_history_outputs, field_role,
    field_activity, coerce_field_value, workflow_seed,
)


@pytest.fixture
def branched_prompt():
    graph = {
        "selector": {"class_type": "ComfySwitchNode", "inputs": {"switch": False, "on_false": "old costume prompt", "on_true": ["enhance", 0]}},
        "enhance": {"class_type": "TextGenerate", "inputs": {"prompt": "old", "thinking": False}},
        "preview": {"class_type": "PreviewAny", "inputs": {"source": ["selector", 0]}},
        "encoder": {"class_type": "CLIPTextEncode", "inputs": {"text": ["preview", 0]}},
        "sampler": {"class_type": "KSampler", "inputs": {"positive": ["encoder", 0], "seed": 891836227295375}},
    }
    config = {"fields": [
        {"id": "edit", "node": "enhance", "input": "prompt", "type": "text", "role": "prompt", "default": "edit"},
        {"id": "enable", "node": "selector", "input": "switch", "type": "boolean", "default": False},
        {"id": "thinking", "node": "enhance", "input": "thinking", "type": "boolean", "default": False},
    ]}
    return graph, config


def test_inactive_prompt_does_not_silently_generate_with_original_instruction(branched_prompt):
    graph, config = branched_prompt
    original = deepcopy(graph)
    with pytest.raises(ValueError, match="创作提示词未进入当前执行分支.*selector.switch"):
        apply_workflow_values(graph, config, {"edit": "replace background", "thinking": True})
    with pytest.raises(ValueError, match="当前执行分支"):
        apply_workflow_values(graph, config, {"edit": "replace background", "enable": "false"})
    result = apply_workflow_values(graph, config, {"edit": "replace background", "enable": "true", "thinking": "false"})
    assert result["selector"]["inputs"]["switch"] is True
    assert result["enhance"]["inputs"] == {"prompt": "replace background", "thinking": False}
    assert graph == original
    assert workflow_seed(result, 123) == 891836227295375
    config['fields'].append({'id':'direct','node':'selector','input':'on_false','type':'text','role':'prompt','default':'old costume prompt'})
    with pytest.raises(ValueError,match='当前执行分支'):
        apply_workflow_values(graph,config,{'edit':'user edit','direct':'old costume prompt'})
    both=apply_workflow_values(graph,config,{},prompt='one shared edit')
    assert both['selector']['inputs']['on_false']=='one shared edit'
    config['fields'][1]['role']='prompt'  # Repair old output-based inference on booleans.
    enabled=apply_workflow_values(graph,config,{'enable':True},prompt='connected user edit')
    assert enabled['selector']['inputs']['switch'] is True
    assert enabled['enhance']['inputs']['prompt']=='connected user edit'


def test_linked_selector_and_multiple_paths_are_resolved_without_guessing_custom_logic(branched_prompt):
    graph, config = branched_prompt
    graph["flag"] = {"class_type": "PrimitiveBoolean", "inputs": {"value": False}}
    graph["selector"]["inputs"]["switch"] = ["flag", 0]
    assert field_activity(graph, config["fields"])["edit"]["active"] is False
    graph["additional_output"] = {"class_type": "SaveText", "inputs": {"text": ["enhance", 0]}}
    assert field_activity(graph, config["fields"])["edit"]["active"] is True
    del graph["additional_output"]
    graph["flag"]["class_type"] = "UnknownCustomBoolean"
    assert field_activity(graph, config["fields"])["edit"]["active"] is True


def test_prompt_role_can_follow_passthroughs_and_branch_output(branched_prompt):
    graph, _ = branched_prompt
    assert field_role(graph, {"node": "selector", "input": "on_false", "type": "text"}) == "prompt"
    graph["input"] = {"class_type": "PrimitiveStringMultiline", "inputs": {"value": "edit"}}
    graph["selector"]["inputs"]["on_false"] = ["input", 0]
    assert field_role(graph, {"node": "input", "input": "value", "type": "text"}) == "prompt"
    with pytest.raises(ValueError, match="已改为节点连线"):
        apply_workflow_values(graph, {"fields": [{"id": "stale", "node": "selector", "input": "on_false", "default": "old"}]}, {"stale": "break link"})


def test_parameter_types_preserve_models_precision_and_false():
    graph={'llm':{'class_type':'TextGenerate','inputs':{'prompt':'edit','thinking':False,'sampling_mode.seed':123,'mtp':'auto'}},'encoder':{'class_type':'CLIPTextEncode','inputs':{'text':['llm',0]}}}
    for key,kind in [('thinking','boolean'),('sampling_mode.seed','number'),('mtp','dropdown')]:
        assert field_role(graph,{'node':'llm','input':key})=='parameter'
        assert field_role(graph,{'node':'llm','input':key,'type':kind,'role':'prompt'})=='parameter'
    assert coerce_field_value({"type": "dropdown", "options": ["001", "002"]}, "001", "002") == "001"
    assert coerce_field_value({"type": "dropdown", "options": ["1", "2"]}, "2", 1) == 2
    assert coerce_field_value({"type": "boolean"}, "false", True) is False
    assert coerce_field_value({"type": "number", "value_type": "number", "min": 0, "max": 2}, "0.125", 1) == 0.125
    assert coerce_field_value({"type": "number", "value_type": "integer"}, "891836227295375", 1) == 891836227295375
    for v in ["NaN", "Infinity", "", -1, 3]:
        with pytest.raises(ValueError):
            coerce_field_value({"type": "slider", "min": 0, "max": 2}, v, 1.0)
    with pytest.raises(ValueError):
        coerce_field_value({"type": "number", "value_type": "integer"}, 2.5, 1)


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


def test_canvas_prompt_reaches_direct_and_enhanced_branches_without_changing_graph_defaults():
    graph = {
        "switch": {"class_type": "ComfySwitchNode", "inputs": {"switch": False, "on_false": "old instruction", "on_true": ["llm", 0]}},
        "llm": {"class_type": "TextGenerate", "inputs": {"prompt": "old instruction", "system_prompt": "keep system"}},
        "encoder": {"class_type": "TextEncodeQwenImage21", "inputs": {"prompt": ["switch", 0], "negative_prompt": "keep negative"}},
    }
    original = deepcopy(graph)
    config = {"fields": [
        {"id": "direct", "node": "switch", "input": "on_false", "type": "text", "role": "prompt"},
        {"id": "enhancer", "node": "llm", "input": "prompt", "type": "textarea", "role": "prompt"},
        {"id": "system", "node": "llm", "input": "system_prompt", "type": "textarea", "role": "system", "default": "keep system"},
        {"id": "negative", "node": "encoder", "input": "negative_prompt", "type": "textarea", "role": "negative", "default": "keep negative"},
    ]}
    result = apply_workflow_values(graph, config, {"direct": "stale", "enhancer": "stale"}, prompt="将文本去除")
    assert result["switch"]["inputs"]["on_false"] == result["llm"]["inputs"]["prompt"] == "将文本去除"
    assert result["llm"]["inputs"]["system_prompt"] == "keep system"
    assert result["encoder"]["inputs"]["negative_prompt"] == "keep negative"
    assert result["encoder"]["inputs"]["prompt"] == ["switch", 0]
    assert graph == original
    with pytest.raises(ValueError, match="未配置创作提示词映射"):
        apply_workflow_values(graph, {"fields": []}, {}, prompt="将文本去除")


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
    subprocess.run(["node", str(Path(__file__).with_name("test_comfy_input_order.js"))], check=True)
    subprocess.run(["node", str(Path(__file__).with_name("test_canvas_comfy_controls.js"))], check=True)
