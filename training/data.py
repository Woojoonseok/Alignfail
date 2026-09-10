import hashlib
import io
import json
from pathlib import Path

import cv2
import numpy as np
from PIL import Image

MODES = ("fixed_160", "fixed_256", "fixed_320", "adaptive")


def sha(content):
    return hashlib.sha256(content).hexdigest()


def read_image(path, expected_hash):
    content = Path(path).read_bytes()
    if sha(content) != expected_hash:
        raise ValueError(f"Image hash mismatch: {Path(path).name}")
    with Image.open(io.BytesIO(content)) as image:
        image.load()
        if image.mode not in {"L", "RGB"}:
            raise ValueError("Training currently requires 8-bit L/RGB images.")
        return np.array(image.convert("L"))


def crop_spec(box, mode, config):
    if mode.startswith("fixed_"):
        size = int(mode.split("_")[1])
        return size, size
    size = int(np.floor(np.clip(max(box[2]-box[0], box[3]-box[1]) * config["context_ratio"], config["min_crop"], config["max_crop"]) + .5))
    return size, config["output_size"]


def crop(image, center, native_size, output_size):
    # Symmetric pixel centers, including subpixel annotation centers, with reflect-101 padding.
    axis = np.arange(native_size, dtype=np.float32) - (native_size-1)/2
    xx, yy = np.meshgrid(axis + center[0], axis + center[1])
    native = cv2.remap(image, xx, yy, cv2.INTER_LINEAR, borderMode=cv2.BORDER_REFLECT_101)
    result = native if output_size == native_size else cv2.resize(native, (output_size, output_size), interpolation=cv2.INTER_LINEAR)
    return result, {"native_size":native_size, "input_size":output_size, "center":list(center),
                    "padding":"reflect101", "interpolation":"bilinear", "resize_scale":output_size/native_size,
                    "sample_origin":[center[0]-(native_size-1)/2, center[1]-(native_size-1)/2]}


def diagnostics(image, config):
    edge = float(np.mean(cv2.Canny(image, 50, 100) > 0))
    mean, std = float(image.mean()), float(image.std())
    flags = {"near_black":mean < config["near_black_mean"], "low_std":std < config["low_std"], "low_edge_density":edge < config["low_edge_density"]}
    return {"mean":mean, "std":std, "min":int(image.min()), "max":int(image.max()), "edge_density":edge,
            **flags, "problematic":any(flags.values())}


def group_split(pairs, config):
    groups = sorted({p["group_key"].strip() for p in pairs})
    if "" in groups or len(groups) < config["folds"]:
        raise ValueError("모든 Pair에 group_key가 필요하며 그룹 수는 folds 이상이어야 합니다.")
    np.random.default_rng(config["seed"]).shuffle(groups)
    val_groups = set(groups[config["fold"]::config["folds"]])
    train = [p for p in pairs if p["group_key"] not in val_groups]
    val = [p for p in pairs if p["group_key"] in val_groups]
    if not train or not val or {p["group_key"] for p in train} & {p["group_key"] for p in val}:
        raise ValueError("Group leakage or empty split: training blocked")
    def hashes(rows):
        return {p[key] for p in rows for key in ("ref_hash", "query_hash", "ref_original_hash", "query_original_hash")}
    if hashes(train) & hashes(val):
        raise ValueError("동일 이미지 hash가 Train/Validation에 중복됩니다. 연관 Pair를 같은 그룹으로 묶으세요.")
    split = {"train":[p["pair_id"] for p in train], "validation":[p["pair_id"] for p in val],
             "train_groups":sorted({p["group_key"] for p in train}), "validation_groups":sorted(val_groups),
             "fold":config["fold"], "folds":config["folds"], "seed":config["seed"], "leakage":"PASS"}
    split["hash"] = sha(json.dumps(split, sort_keys=True).encode())
    return split


def metrics(rows):
    def aggregate(items):
        errors = [r["error"] for r in items]
        return {"count":len(items), "median_error":float(np.median(errors)) if errors else None,
                "mean_error":float(np.mean(errors)) if errors else None,
                **{f"acc@{k}":sum(e<=k for e in errors)/len(errors) if errors else None for k in [5,10,20]}}
    return {"Overall":aggregate(rows), **{p:aggregate([r for r in rows if r["pattern_type"]==p]) for p in ["A","B","unknown"]}}
