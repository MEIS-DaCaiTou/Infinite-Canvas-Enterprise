"""Bounded layer metadata from documented image outputs, with no IO or URLs."""
import math


def layer_metadata(value):
    if not isinstance(value, dict) or not isinstance(value.get("z_index"), int) or isinstance(value["z_index"], bool):
        return {}
    meta = {"z_index": value["z_index"]}
    for key, limit in (("name", 160), ("description", 1000), ("output_format", 16)):
        if isinstance(value.get(key), str):
            meta[key] = value[key][:limit]
    box = value.get("bounding_box")
    if isinstance(box, dict):
        clean = {}
        for key in ("absolute", "normalized"):
            coords = box.get(key)
            if isinstance(coords, list) and len(coords) == 4 and all(
                isinstance(n, (int, float)) and not isinstance(n, bool) and math.isfinite(n) for n in coords):
                clean[key] = list(coords)
        if clean:
            meta["bounding_box"] = clean
    recognition = value.get("text_recognition")
    if isinstance(recognition, dict) and isinstance(recognition.get("text"), str):
        lines = []
        for line in (recognition.get("lines") if isinstance(recognition.get("lines"), list) else [])[:100]:
            if not isinstance(line, dict):
                continue
            runs = []
            for run in (line.get("runs") if isinstance(line.get("runs"), list) else [])[:100]:
                if not isinstance(run, dict) or not isinstance(run.get("text"), str):
                    continue
                style = run.get("style") if isinstance(run.get("style"), dict) else {}
                runs.append({"text": run["text"][:4000], "style": {
                    key: style[key] for key in ("similar_font_family", "foreground_color", "bold", "italic",
                        "underline", "strikethrough", "shadow", "translucent")
                    if isinstance(style.get(key), (str, bool))}})
            lines.append({"bounding_box": layer_metadata({"z_index": 0,
                "bounding_box": line.get("bounding_box")}).get("bounding_box", {}), "runs": runs})
        meta["text_recognition"] = {"text": recognition["text"][:16000], "lines": lines}
    return meta
