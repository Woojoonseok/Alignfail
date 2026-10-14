"""GPU worker: Qwen class retrieval + explicitly labeled NCC spatial baseline.

Only human-reviewed GT templates enter the bank. Proposed positions are NOT GT.
"""
from __future__ import annotations

import argparse
import json
import math
import os
import traceback
from pathlib import Path

import cv2
import numpy as np
from PIL import Image

from template_bank.__main__ import QwenEncoder, rank, unit


def json_write(path: Path, payload):
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    os.replace(temporary, path)


def checked_image(record):
    path = Path(record["path"])
    import hashlib
    h = hashlib.sha256()
    with path.open("rb") as f:
        for part in iter(lambda: f.read(1024 * 1024), b""):
            h.update(part)
    if h.hexdigest() != record["sha256"]:
        raise ValueError(f"Image content was changed after job submission: {path.name}")
    with Image.open(path) as original:
        original.load()
        return np.asarray(original.convert("L"))


def target_patch(gray, x, y, size):
    """Return fixed-size patch with GT at its geometric center, reflection pad if needed."""
    cx, cy = round(float(x)), round(float(y))
    half = size // 2
    top, left = cy - half, cx - half
    bottom, right = top + size, left + size
    pad = max(0, -top, -left, bottom - gray.shape[0], right - gray.shape[1])
    if pad:
        gray = cv2.copyMakeBorder(gray, pad, pad, pad, pad, cv2.BORDER_REFLECT_101)
        left += pad
        top += pad
    return np.ascontiguousarray(gray[top:top + size, left:left + size]), (cx - (left - pad), cy - (top - pad))


def ref_patch(gray, roi):
    if roi is None:
        return None
    x0, y0, x1, y1 = (int(x) for x in roi)
    # Original box includes a white border; remove it from the embedding input.
    x0, y0 = x0 + 3, y0 + 3
    x1, y1 = x1 - 2, y1 - 2
    if not (0 <= x0 < x1 <= gray.shape[1] and 0 <= y0 < y1 <= gray.shape[0]):
        raise ValueError("Reference ROI invalid or smaller than border margin")
    return np.ascontiguousarray(gray[y0:y1, x0:x1])


def spatial_match(template, query, offset):
    """Pure NCC baseline. The returned peak is NOT a calibrated confidence or GT."""
    if query.shape[0] < template.shape[0] or query.shape[1] < template.shape[1]:
        return {"status": "patch_larger_than_query", "x": None, "y": None, "score": None}
    response = cv2.matchTemplate(query, template, cv2.TM_CCOEFF_NORMED)
    # Low-contrast patterns can make normalized NCC degenerate.
    response = np.nan_to_num(response, nan=-1.0, posinf=-1.0, neginf=-1.0)
    _, maximum, _, location = cv2.minMaxLoc(response)
    if float(np.std(template)) < 1.0:
        return {"status": "flat_template", "x": None, "y": None, "score": None}
    return {"status": "candidate", "x": float(location[0] + offset[0]),
            "y": float(location[1] + offset[1]), "score": float(maximum)}


def run(job_dir):
    config = json.loads((job_dir / "config.json").read_text(encoding="utf-8"))
    manifest = json.loads((job_dir / "manifest.json").read_text(encoding="utf-8"))
    if manifest.get("schema") != "alignfail.ai-workspace.v1":
        raise ValueError("Unsupported job schema")
    patch_size = config["patch_size"]
    crops = job_dir / "crops"
    crops.mkdir(exist_ok=True)
    bank_rows, patch_paths, patches = [], [], []
    # Exact per-template clean image, reviewed GT and class label are mandatory.
    for row in manifest["templates"]:
        gray = checked_image(row["reference"])
        if row["gt_source"] != "manual" or not row["reference"]["clean"]:
            raise ValueError("Only reviewed GT + validated Clean training images are eligible")
        patch, offset = target_patch(gray, *row["gt"], patch_size)
        path = crops / f"template_{len(bank_rows)}.png"
        Image.fromarray(patch).save(path)
        bank_rows.append(row)
        patch_paths.append(path)
        patches.append((patch, offset))
    if not bank_rows:
        raise ValueError("No valid templates")
    encoder = QwenEncoder(model=config["model"], device="cuda")
    vectors = unit(encoder.encode(patch_paths, batch_size=config["batch_size"]))
    paths = [str(p) for p in patch_paths]
    labels = [r["class_label"] for r in bank_rows]
    matches = []
    for kind in ("tests", "incoming"):
        for item in manifest[kind]:
            reference = checked_image(item["reference"])
            if kind == "tests":
                cropped = ref_patch(reference, item.get("reference_roi"))
                if cropped is None:
                    matches.append({"pair_id": item["pair_id"], "revision": item["revision"],
                                    "kind": "test", "error": "Reference ROI 미지정: 흰 네모 검출 또는 수동 지정 필요",
                                    "classes": [], "templates": [], "localization": None})
                    continue
            else:
                if item.get("gt") is not None:
                    cropped, _ = target_patch(reference, *item["gt"], patch_size)
                else:
                    cropped = reference
            query_path = crops / f"{kind}_{len(matches)}.png"
            Image.fromarray(cropped).save(query_path)
            emb = unit(encoder.encode([query_path], batch_size=1))[0]
            class_scores, candidates = rank(emb, vectors, paths, labels,
                                             topk=config["top_k"], class_neighbors=3)
            # Match only the Top-K retrieved templates; no access to Test GT.
            source = item["query"] if kind == "tests" else item["reference"]
            query_gray = checked_image(source)
            spatial = []
            for hit in candidates:
                index = paths.index(hit["path"])
                patch, offset = patches[index]
                outcome = spatial_match(patch, query_gray, offset)
                spatial.append({**outcome, "template_pair_id": bank_rows[index]["pair_id"],
                                "class_label": bank_rows[index]["class_label"],
                                "retrieval_score": hit["score"]})
            plausible = [p for p in spatial if p["score"] is not None]
            plausible.sort(key=lambda row: row["score"], reverse=True)
            # Retrieval and spatial scores are independent, uncalibrated ranks.
            proposal = plausible[0] if plausible else None
            matches.append({"pair_id": item["pair_id"], "revision": item["revision"],
                            "kind": "test" if kind == "tests" else "incoming",
                            "classes": class_scores,
                            "templates": [{"class_label": p["class_label"], "template_pair_id": p["template_pair_id"],
                                           "ncc": p["score"], "x": p["x"], "y": p["y"]}
                                          for p in spatial],
                            "localization": proposal,
                            "gt_status": "unreviewed_prediction",
                            "embedding_scope": "GT-centered" if item.get("gt") is not None else
                                               ("reference_box" if kind == "tests" else "full_image_weak")})
            json_write(job_dir / "results.json", {"model": config["model"],
                                                  "matches": matches, "schema": "alignfail.ai-results.v1"})
    json_write(job_dir / "results.json", {"model": config["model"], "matches": matches,
                                          "schema": "alignfail.ai-results.v1",
                                          "warning": "NCC pixel predictions are baseline proposals, not validated GT."})
    return len(matches)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--job", type=Path, required=True)
    args = parser.parse_args()
    job_dir = args.job.resolve()
    try:
        count = run(job_dir)
        json_write(job_dir / "status.json", {"status": "completed", "job_id": job_dir.name, "count": count})
        print(f"Finished {count} classifications")
    except Exception as exc:
        traceback.print_exc()
        json_write(job_dir / "status.json", {"status": "failed", "job_id": job_dir.name,
                                              "error": f"{type(exc).__name__}: {exc}"})
        raise SystemExit(1)


if __name__ == "__main__":
    main()
