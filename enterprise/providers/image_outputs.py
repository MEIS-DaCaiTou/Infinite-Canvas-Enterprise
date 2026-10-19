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
    return meta
