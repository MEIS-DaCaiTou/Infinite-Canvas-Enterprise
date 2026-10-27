"""Comfy workflow input groups and result selection; no IO or platform dependencies."""
from copy import deepcopy
import math
import re


# Verified Comfy core Autogrow contracts. Arbitrary custom graphs are not rewritten.
IMAGE_GROUPS = {
    "TextEncodeQwenImage21": (re.compile(r"images\.image_(\d+)$"), "images.image_", 1, 16),
    "BatchImagesNode": (re.compile(r"images\.image(\d+)$"), "images.image", 0, 50),
}
TEXT_KEYS = ("text", "texts", "prompt", "prompts", "string", "strings", "caption", "captions")
TEXT_EXTENSIONS = (".txt", ".md", ".csv", ".json", ".srt", ".vtt")


def workflow_link(graph, value):
    return (isinstance(value, list) and len(value) == 2 and type(value[1]) is int
            and str(value[0]) in graph)


def field_activity(graph, fields):
    """Trace wiring, resolving only the verified core lazy switch contract.

    Unknown custom selectors keep both paths possible. Never guess their meaning
    or rewrite a user's workflow to force a branch on.
    """
    def literal(value, seen=()):
        if not workflow_link(graph, value):
            return value
        nid = str(value[0])
        if nid in seen or value[1] != 0:
            return None
        node = graph[nid]
        if node.get("class_type") in {"PrimitiveBoolean", "PrimitiveInt", "PrimitiveFloat"}:
            return literal(node.get("inputs", {}).get("value"), (*seen, nid))
        return None

    consumed, blocked, parents = set(), {}, {}
    for nid, node in graph.items():
        inputs = node.get("inputs", {})
        choice = literal(inputs.get("switch")) if node.get("class_type") == "ComfySwitchNode" else None
        if type(choice) is bool:
            blocked[(nid, "on_false" if choice else "on_true")] = {
                "node": nid, "input": "switch", "value": not choice,
            }
        for key, value in inputs.items():
            if workflow_link(graph, value):
                source = str(value[0])
                consumed.add(source)
                parents.setdefault(source, []).append((nid, key))
    roots = set(graph) - consumed
    active, pending = set(), list(roots or graph)
    while pending:
        nid = pending.pop()
        if nid in active:
            continue
        active.add(nid)
        pending.extend(str(v[0]) for key, v in graph[nid].get("inputs", {}).items()
                       if (nid, key) not in blocked and workflow_link(graph, v))

    def blocking_gate(nid, seen):
        if nid in seen:
            return None
        seen.add(nid)
        for target, key in parents.get(nid, []):
            gate = blocked.get((target, key)) or blocking_gate(target, seen)
            if gate:
                return gate
        return None

    return {f["id"]: {"active": str(f.get("node", "")) in active
                       and (str(f.get("node", "")), f.get("input")) not in blocked,
                       "gate": blocked.get((str(f.get("node", "")), f.get("input")))
                       or blocking_gate(str(f.get("node", "")), set())}
            for f in fields}


def coerce_field_value(field, value, original=None):
    """Keep Comfy primitive types; never turn 'false' on or a model ID into a number."""
    if value is None:
        value = field.get("default")
    kind = field.get("type")
    numeric = kind in {"number", "slider"}
    target = field.get("value_type")
    if kind == "dropdown":
        target = ("boolean" if type(original) is bool else "integer" if type(original) is int
                  else "number" if type(original) is float else "string" if isinstance(original, str) else target)
        if field.get("options"):
            def token(v):
                if target == "boolean":
                    return str(v).lower()
                if target in {"integer", "number"}:
                    try:
                        return float(v)
                    except (ValueError, TypeError):
                        return v
                return str(v)
            if token(value) not in [token(v) for v in field["options"]]:
                raise ValueError(f"{field.get('name') or field.get('input')}：请选择已配置的选项")
    if kind == "boolean" or target == "boolean":
        if type(value) is bool:
            return value
        if value in (0, 1):
            return bool(value)
        if isinstance(value, str) and value.lower() in {"true", "false", "0", "1"}:
            return value.lower() in {"true", "1"}
        raise ValueError(f"{field.get('name') or field.get('input')}：需要开启或关闭")
    if numeric or target in {"integer", "number"}:
        integer = target == "integer" or (not target and type(original) is int
                  and kind != "slider" and not (field.get("step") and field["step"] < 1))
        try:
            if type(value) is bool or value is None or value == "":
                raise ValueError()
            number = int(value) if integer and re.fullmatch(r"[+-]?\d+", str(value)) else float(value)
            if not math.isfinite(number) or (integer and number != int(number)):
                raise ValueError()
            if integer:
                number = int(number)
            if field.get("min") is not None and number < field["min"]:
                raise ValueError()
            if field.get("max") is not None and number > field["max"]:
                raise ValueError()
            return number
        except (TypeError, ValueError, OverflowError) as exc:
            raise ValueError(f"{field.get('name') or field.get('input')}：数值无效或超出配置范围") from exc
    return str(value) if kind == "dropdown" and target == "string" else value


def workflow_seed(graph, fallback):
    fields = [{"id": f"{nid}.{key}", "node": nid, "input": key}
              for nid, node in graph.items() for key, value in node.get("inputs", {}).items()
              if (key == "seed" or key == "noise_seed" or key.endswith(".seed")) and type(value) is int]
    usage = field_activity(graph, fields)
    fields.sort(key=lambda f: 0 if "Sampler" in graph[f["node"]].get("class_type", "") else 1)
    return next((graph[f["node"]]["inputs"][f["input"]] for f in fields if usage[f["id"]]["active"]), fallback)


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
    key = str(field.get("input", "")).lower()
    name = str(field.get("name", "")).lower()
    raw = workflow.get(str(field.get("node", "")), {}).get("inputs", {}).get(field.get("input"))
    if key == "filename_prefix" or type(raw) in {bool, int, float} or field.get("type") in {"image", "video", "audio", "number", "slider", "boolean", "dropdown"}:
        return "parameter"
    if field.get("role"):
        return field["role"]
    if "negative" in key or "negative" in name or "负向" in name or "负面" in name:
        return "negative"
    if "system" in key or "system" in name or "系统" in name:
        return "system"
    if key in {"prompt", "positive_prompt", "text"}:
        return "prompt"
    if key not in {"value", "string", "on_false", "on_true"}:
        return "parameter"
    node_id = str(field.get("node", ""))
    destinations, pending, seen = [], [node_id], set()
    if key in {"on_false", "on_true"} and workflow.get(node_id, {}).get("class_type") == "ComfySwitchNode":
        pending.append(node_id)
    while pending:
        source = pending.pop()
        if source in seen:
            continue
        seen.add(source)
        for target, node in workflow.items():
            for dest, link in node.get("inputs", {}).items():
                if workflow_link(workflow, link) and str(link[0]) == source and link[1] == 0:
                    destinations.append(dest.lower())
                    if node.get("class_type") in {"PreviewAny", "Reroute", "ComfySwitchNode"}:
                        pending.append(target)
    if "system_prompt" in destinations:
        return "system"
    if any(dest in {"negative", "negative_prompt"} for dest in destinations):
        return "negative"
    if any(key in {"prompt", "positive_prompt", "text", "positive"} for key in destinations):
        return "prompt"
    return "prompt" if key in {"prompt", "positive_prompt", "text"} else "parameter"


def apply_workflow_values(workflow, config, values, *, prompt=""):
    """Construct one request graph, retaining the original loaders/ordering where possible."""
    graph = deepcopy(workflow)
    if prompt:
        prompt_fields = [field for field in config.get("fields", []) if field_role(workflow, field) == "prompt"]
        if not prompt_fields:
            raise ValueError("此工作流未配置创作提示词映射；请在工作流设置中暴露实际指令字段，并将输入用途设为“创作提示词”。")
        values = {**values, **{field["id"]: prompt for field in prompt_fields}}
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
        original = graph[node_id]["inputs"][key]
        if workflow_link(graph, original):
            raise ValueError(f"参数 #{node_id}.{key} 已改为节点连线，请重新选择上游的实际输入字段")
        value = values.get(field["id"], field.get("default"))
        graph[node_id]["inputs"][key] = coerce_field_value(field, value, original)
    prompt_fields = [f for f in config.get("fields", []) if field_role(workflow, f) == "prompt"
                     and values.get(f["id"], f.get("default"))]
    usage = field_activity(graph, prompt_fields)
    active_prompts = {str(values.get(f["id"], f.get("default"))) for f in prompt_fields if usage[f["id"]]["active"]}
    ignored = [f for f in prompt_fields if not usage[f["id"]]["active"]
               and values.get(f["id"], f.get("default")) != f.get("default")
               and str(values.get(f["id"])) not in active_prompts]
    if prompt_fields and (not active_prompts or ignored):
        field = (ignored or prompt_fields)[0]
        gate = usage[field["id"]]["gate"]
        hint = f"；请将 #{gate['node']}.{gate['input']} 设为 {'开启' if gate['value'] else '关闭'}，或映射当前分支的提示词" if gate else "；请映射连接到输出的提示词输入"
        raise ValueError(f"创作提示词未进入当前执行分支：{field.get('name') or field['input']}{hint}")
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


def workflow_media_names(workflow, config, values):
    """Names actually applied by the trusted field mapping, excluding output labels."""
    names = []
    groups = config.get("image_groups") or []
    grouped = {node for group in groups for node in group["source_nodes"]}
    for group in groups:
        names.extend(values.get(group["id"]) or [])
    for field in config.get("fields") or []:
        if field.get("input") == "filename_prefix" or (field.get("node") in grouped and field.get("input") == "image"):
            continue
        media_input = field.get("input") in {"image", "video", "audio", "mask", "file", "filename", "filepath"}
        if field.get("type") not in {"image", "video", "audio", "file"} and not media_input:
            continue
        value = workflow[field["node"]]["inputs"][field["input"]]
        if not isinstance(value, str) or not value.strip():
            raise ValueError("工作流媒体输入必须是已上传的文件名")
        names.append(value)
    return names


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
