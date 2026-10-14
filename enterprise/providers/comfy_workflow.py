"""Comfy workflow input groups and result selection; no IO or platform dependencies."""
from copy import deepcopy
import re


# Verified Comfy core Autogrow contracts. Arbitrary custom graphs are not rewritten.
IMAGE_GROUPS = {
    "TextEncodeQwenImage21": (re.compile(r"images\.image_(\d+)$"), "images.image_", 1, 16),
    "BatchImagesNode": (re.compile(r"images\.image(\d+)$"), "images.image", 0, 50),
}
TEXT_KEYS = ("text", "texts", "prompt", "prompts", "string", "strings", "caption", "captions")
TEXT_EXTENSIONS = (".txt", ".md", ".csv", ".json", ".srt", ".vtt")


def image_group_candidates(workflow):
    routes = {}
    for node_id, node in workflow.items():
        if not isinstance(node, dict):
            continue
        spec = IMAGE_GROUPS.get(node.get("class_type"))
        if not spec:
            continue
        slots = sorted(((int(spec[0].fullmatch(key)[1]), value) for key, value in node.get("inputs", {}).items()
                        if spec[0].fullmatch(key)), key=lambda item: item[0])
        if not slots or any(not isinstance(link, list) or len(link) != 2 or link[1] != 0
                            or workflow.get(str(link[0]), {}).get("class_type") != "LoadImage" for _, link in slots):
            continue
        sources = tuple(str(link[0]) for _, link in slots)
        if len(set(sources)) != len(sources):
            continue
        routes.setdefault(sources, []).append(str(node_id))
    candidates = []
    for sources, targets in routes.items():
        # Removing an optional loader must not break an unrelated branch/mask input.
        unsafe = False
        for node_id, node in workflow.items():
            if not isinstance(node, dict):
                continue
            for key, link in node.get("inputs", {}).items():
                if not isinstance(link, list) or len(link) != 2 or str(link[0]) not in sources[1:]:
                    continue
                spec = IMAGE_GROUPS.get(node.get("class_type"))
                if str(node_id) not in targets or not spec or not spec[0].fullmatch(key) or link[1] != 0:
                    unsafe = True
        if unsafe:
            continue
        limit = min(20, *(IMAGE_GROUPS[workflow[node_id]["class_type"]][3] for node_id in targets))
        candidates.append({"id": "images:" + ":".join(sources), "name": "主体图与参考图",
                           "source_nodes": list(sources), "min_images": 1,
                           "max_images": min(10, limit), "supported_max": limit, "targets": targets})
    return candidates


def validate_image_groups(workflow, groups):
    if not groups:
        return {}
    candidates = {tuple(item["source_nodes"]): item for item in image_group_candidates(workflow)}
    used = set()
    ids = set()
    for group in groups:
        sources = tuple(group.get("source_nodes", []))
        candidate = candidates.get(sources)
        minimum, maximum = group.get("min_images", 1), group.get("max_images", 10)
        if (not candidate or group.get("id") != candidate["id"] or used.intersection(sources)
                or group["id"] in ids or type(minimum) is not int or type(maximum) is not int
                or not 1 <= minimum <= maximum <= candidate["supported_max"]):
            raise ValueError("可变图片输入配置与工作流不匹配；请重新确认输入组及数量范围")
        used.update(sources)
        ids.add(group["id"])
    return candidates


def field_role(workflow, field):
    if field.get("role"):
        return field["role"]
    key = str(field.get("input", "")).lower()
    name = str(field.get("name", "")).lower()
    if key == "filename_prefix" or field.get("type") in {"image", "video", "audio", "number", "slider", "boolean", "dropdown"}:
        return "parameter"
    if "negative" in key or "negative" in name or "负向" in name or "负面" in name:
        return "negative"
    if "system" in key or "system" in name or "系统" in name:
        return "system"
    node_id = str(field.get("node", ""))
    destinations = [key.lower() for node in workflow.values() if isinstance(node, dict) for key, link in node.get("inputs", {}).items()
                    if isinstance(link, list) and len(link) == 2 and str(link[0]) == node_id and link[1] == 0]
    if "system_prompt" in destinations:
        return "system"
    if "negative" in destinations:
        return "negative"
    if any(key in {"prompt", "positive_prompt", "text", "positive"} for key in destinations):
        return "prompt"
    return "prompt" if key in {"prompt", "positive_prompt", "text"} else "parameter"


def apply_workflow_values(workflow, config, values):
    """Construct one request graph, retaining the original loaders/ordering where possible."""
    graph = deepcopy(workflow)
    groups = config.get("image_groups", [])
    candidates = validate_image_groups(graph, groups)
    grouped = {source for group in groups for source in group["source_nodes"]}
    for field in config.get("fields", []):
        node_id, key = str(field.get("node", "")), field.get("input", "")
        if node_id in grouped and key == "image":
            continue
        if not node_id or not key:
            continue
        if node_id not in graph or key not in graph[node_id].get("inputs", {}):
            raise ValueError(f"工作流参数映射已失效：#{node_id}.{key}")
        value = values.get(field["id"], field.get("default"))
        if field.get("type") in {"number", "slider"}:
            value = float(value) if field.get("step") and field["step"] < 1 else int(float(value))
        elif field.get("type") == "boolean":
            value = bool(value)
        elif field.get("type") == "dropdown" and isinstance(value, str):
            try:
                value = float(value) if any(c in value.lower() for c in ".e") else int(value)
            except ValueError:
                pass
        graph[node_id]["inputs"][key] = value
    for group_index, group in enumerate(groups):
        names = values.get(group["id"], [])
        if (not isinstance(names, list) or not group["min_images"] <= len(names) <= group["max_images"]
                or any(not isinstance(name, str) or not name.strip() for name in names)):
            raise ValueError(f"{group.get('name', '图片输入')}需要 {group['min_images']}–{group['max_images']} 张已上传图片")
        sources = group["source_nodes"]
        actual = []
        for index, name in enumerate(names):
            node_id = sources[index] if index < len(sources) else f"ice_image_{group_index}_{index}"
            if index >= len(sources):
                if node_id in graph:
                    raise ValueError("动态图片节点身份冲突，请调整工作流节点身份")
                graph[node_id] = deepcopy(graph[sources[0]])
            graph[node_id]["inputs"]["image"] = name
            actual.append(node_id)
        for node_id in candidates[tuple(sources)]["targets"]:
            pattern, prefix, start, _ = IMAGE_GROUPS[graph[node_id]["class_type"]]
            inputs = graph[node_id]["inputs"]
            for key in list(inputs):
                if pattern.fullmatch(key):
                    del inputs[key]
            inputs.update({f"{prefix}{index + start}": [source, 0] for index, source in enumerate(actual)})
        for unused in sources[len(names):]:
            del graph[unused]
    return graph


def select_history_outputs(history, workflow, *, is_preview, is_debug):
    """Retain typed outputs; a SaveText body and its file are one result, not two."""
    files, texts = [], []
    for node_id, output in history.get("outputs", {}).items():
        class_type = workflow.get(str(node_id), {}).get("class_type", "")
        node_texts = []
        for key in TEXT_KEYS:
            raw = output.get(key, [])
            for value in raw if isinstance(raw, list) else [raw]:
                if isinstance(value, dict):
                    value = next((value[k] for k in ("text", "prompt", "caption", "value") if k in value), None)
                if value is not None and str(value).strip():
                    node_texts.append((key, str(value)))
        text_files = []
        for key, raw in output.items():
            if key in TEXT_KEYS:
                continue
            for index, item in enumerate(raw if isinstance(raw, list) else [raw]):
                if not isinstance(item, dict) or not item.get("filename"):
                    continue
                entry = {"node_id": str(node_id), "class_type": class_type, "output_key": key,
                         "index": index, "file": item}
                files.append(entry)
                if str(item["filename"]).lower().endswith(TEXT_EXTENSIONS):
                    text_files.append(entry)
        if text_files and len(text_files) == len(node_texts):
            for entry, (_, text) in zip(text_files, node_texts):
                entry["text"] = text
        else:
            texts.extend({"node_id": str(node_id), "class_type": class_type, "output_key": key,
                          "index": index, "text": text} for index, (key, text) in enumerate(node_texts))
    primary_text = any(not is_debug(item["class_type"]) for item in texts) or any(not is_preview(item["class_type"]) for item in files)
    texts = [item for item in texts if not is_debug(item["class_type"]) or not primary_text]
    return files, texts
