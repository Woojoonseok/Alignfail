"""Reference -> Template retrieval and reviewed open-set dataset ingestion.

Run ``python -m template_bank --help``. No model is downloaded on import.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import os
import shutil
import tempfile
from collections import defaultdict
from pathlib import Path

import numpy as np
from PIL import Image

EXTENSIONS = {".png", ".jpg", ".jpeg", ".bmp", ".tif", ".tiff", ".webp"}
DEFAULT_MODEL = "Qwen/Qwen3-VL-Embedding-2B"


def images_in(root: Path):
    """Yield real image files, excluding symlinks and symlinked directories."""
    for directory, folders, files in os.walk(root, followlinks=False):
        folders[:] = sorted(f for f in folders if not (Path(directory) / f).is_symlink())
        for name in sorted(files):
            p = Path(directory) / name
            if p.suffix.lower() in EXTENSIONS and not p.is_symlink():
                yield p.resolve()


def checksum(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def unit(array):
    v = np.asarray(array, dtype=np.float32)
    if v.ndim == 1:
        v = v[None, :]
    norms = np.linalg.norm(v, axis=1, keepdims=True)
    if np.any(~np.isfinite(v)) or np.any(norms < 1e-10):
        raise ValueError("Invalid or zero embedding")
    return v / norms


class QwenEncoder:
    """Official Qwen multimodal sentence-transformers image input interface."""

    def __init__(self, model: str = DEFAULT_MODEL, device: str = "cuda"):
        try:
            import torch
            from sentence_transformers import SentenceTransformer
        except ImportError as e:
            raise RuntimeError("Install template_bank/requirements.txt in a CUDA PyTorch environment") from e
        if device.startswith("cuda") and not torch.cuda.is_available():
            raise RuntimeError("CUDA not available: select --device cpu or install CUDA PyTorch")
        self.model_id = model
        # BF16 keeps a 2B VLM practical on the 24GB RTX 4090.
        # Do not force BF16 on CPU-only development machines.
        kwargs = {"model_kwargs": {"torch_dtype": torch.bfloat16}} if device.startswith("cuda") else {}
        self.model = SentenceTransformer(model, device=device, **kwargs)

    def encode(self, paths: list[Path], rois: list[tuple[int, int, int, int] | None] | None = None,
               batch_size: int = 2) -> np.ndarray:
        vectors = []
        rois = rois if rois is not None else [None] * len(paths)
        for start in range(0, len(paths), batch_size):
            batch = []
            for path, roi in zip(paths[start:start + batch_size], rois[start:start + batch_size]):
                with Image.open(path) as opened:
                    image = opened.convert("RGB")
                    if roi is not None:
                        x0, y0, x1, y1 = roi
                        if not (0 <= x0 < x1 <= image.width and 0 <= y0 < y1 <= image.height):
                            raise ValueError(f"ROI outside image {path}: {roi}")
                        image = image.crop(roi)
                    batch.append({"image": image})
            result = self.model.encode(batch, batch_size=batch_size, convert_to_numpy=True,
                                       normalize_embeddings=True, show_progress_bar=False)
            vectors.append(unit(result))
        return np.vstack(vectors) if vectors else np.empty((0, 0), np.float32)


def save_bank(root: Path, output: Path, encoder, batch_size: int = 2):
    if not root.is_dir():
        raise ValueError(f"Class folder does not exist: {root}")
    if output.resolve().is_relative_to(root.resolve()):
        raise ValueError("Bank output must not be within class image folders")
    paths, labels, hashes = [], [], []
    for folder in sorted(root.iterdir()):
        if folder.is_symlink() or not folder.is_dir():
            continue
        for path in images_in(folder):
            paths.append(path)
            labels.append(folder.name)
            hashes.append(checksum(path))
    if not paths:
        raise ValueError("No class images found (expected classes/ClassName/image.png)")
    # Don't index a duplicate image under two distinct labels.
    owner = {}
    for hash_value, label in zip(hashes, labels):
        if hash_value in owner and owner[hash_value] != label:
            raise ValueError(f"Image SHA256 assigned to multiple classes: {owner[hash_value]} / {label}")
        owner[hash_value] = label
    vectors = unit(encoder.encode(paths, batch_size=batch_size))
    if len(vectors) != len(paths):
        raise ValueError("Encoder returned the wrong number of vectors")
    output.mkdir(parents=True, exist_ok=True)
    npz = output / "bank.npz"
    with tempfile.NamedTemporaryFile(dir=output, suffix=".npz", delete=False) as f:
        tmp = Path(f.name)
    try:
        np.savez_compressed(tmp, embeddings=vectors, labels=np.asarray(labels),
                            paths=np.asarray([str(p) for p in paths]), hashes=np.asarray(hashes))
        os.replace(tmp, npz)
    finally:
        tmp.unlink(missing_ok=True)
    metadata = {"schema": "alignfail.template-bank.v1", "model": encoder.model_id,
                "count": len(paths), "classes": sorted(set(labels)), "vector_dim": vectors.shape[1],
                "class_root": str(root.resolve())}
    write_json(output / "metadata.json", metadata)
    return metadata


def write_json(path: Path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=path.parent,
                                     suffix=".json", delete=False) as f:
        tmp = Path(f.name)
        json.dump(data, f, ensure_ascii=False, indent=2)
        f.write("\n")
    os.replace(tmp, path)


def load_bank(root: Path, model: str | None = None):
    meta = json.loads((root / "metadata.json").read_text(encoding="utf-8"))
    if meta.get("schema") != "alignfail.template-bank.v1":
        raise ValueError("Unsupported template bank schema")
    if model is not None and meta["model"] != model:
        raise ValueError(f"Model mismatch: indexed={meta['model']}, requested={model}")
    with np.load(root / "bank.npz", allow_pickle=False) as f:
        embeddings = unit(f["embeddings"])
        paths, labels, hashes = [f[key].astype(str).tolist() for key in ("paths", "labels", "hashes")]
    if not (len(paths) == len(labels) == len(hashes) == len(embeddings) == meta["count"]):
        raise ValueError("Inconsistent bank metadata")
    return meta, embeddings, paths, labels, hashes


def rank(vector, bank_embeddings, paths, labels, topk: int = 5, class_neighbors: int = 3):
    scores = bank_embeddings @ unit(vector)[0]
    buckets = defaultdict(list)
    for index, label in enumerate(labels):
        buckets[label].append((float(scores[index]), index))
    classes = []
    for label, values in buckets.items():
        values.sort(reverse=True)
        k = min(class_neighbors, len(values))
        classes.append({"label": label, "score": float(np.mean([x[0] for x in values[:k]])),
                        "nearest_template": paths[values[0][1]]})
    classes.sort(key=lambda row: (-row["score"], row["label"]))
    templates = sorted(((float(score), paths[i], labels[i]) for i, score in enumerate(scores)), reverse=True)
    return classes[:topk], [{"score": score, "path": path, "label": label}
                             for score, path, label in templates[:topk]]


def read_csv(path: Path):
    with path.open(newline="", encoding="utf-8-sig") as f:
        yield from csv.DictReader(f)


def write_csv(path: Path, rows: list[dict]):
    path.parent.mkdir(parents=True, exist_ok=True)
    if not rows:
        path.write_text("", encoding="utf-8")
        return
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def csv_image(csv_path: Path, name: str) -> Path:
    if not name:
        raise ValueError("Missing image filename in CSV")
    path = Path(name)
    return (csv_path.parent / path).resolve() if not path.is_absolute() else path.resolve()


def roi_from_row(row):
    keys = ("roi_x0", "roi_y0", "roi_x1", "roi_y1")
    if all(not (row.get(key) or "").strip() for key in keys):
        return None
    if any(not (row.get(key) or "").strip() for key in keys):
        raise ValueError("Either all ROI coordinates or none must be supplied")
    return tuple(int(row[key]) for key in keys)


def match_test(csv_path: Path, bank_dir: Path, output: Path, encoder, topk: int = 5,
               batch_size: int = 2):
    meta, bank_vec, paths, labels, hashes = load_bank(bank_dir, encoder.model_id)
    rows = list(read_csv(csv_path))
    if not rows:
        raise ValueError("Empty Test CSV")
    ids = [row.get("pair_id", "").strip() for row in rows]
    if any(not x for x in ids) or len(set(ids)) != len(ids):
        raise ValueError("Test pair_id values must be unique and non-empty")
    references, rois, fingerprints = [], [], []
    for row in rows:
        reference, fail = csv_image(csv_path, row.get("reference", "")), csv_image(csv_path, row.get("fail", ""))
        if not reference.is_file() or not fail.is_file():
            raise ValueError(f"Missing Reference/Fail for {row['pair_id']}")
        fp = [checksum(reference), checksum(fail)]
        if any(h in set(hashes) for h in fp):
            raise ValueError(f"Train/Test SHA leakage at {row['pair_id']}")
        references.append(reference)
        rois.append(roi_from_row(row))
        fingerprints.append(fp)
    queries = unit(encoder.encode(references, rois=rois, batch_size=batch_size))
    results = []
    for row, ref, vec, fp in zip(rows, references, queries, fingerprints):
        classes, templates = rank(vec, bank_vec, paths, labels, topk=topk)
        results.append({"pair_id": row["pair_id"], "reference": str(ref),
                        "fail": str(csv_image(csv_path, row["fail"])), "reference_sha256": fp[0],
                        "fail_sha256": fp[1], "reference_roi": roi_from_row(row),
                        "expected_class": row.get("expected_class", ""),
                        "topk_classes": classes, "topk_templates": templates,
                        "retrieval_only": True})
    write_json(output, {"schema": "alignfail.template-test.v1", "bank_model": meta["model"],
                        "test_pair_count": len(rows), "matches": results})
    return results


def safe_stage(src: Path, target_folder: Path, digest: str) -> Path:
    target_folder.mkdir(parents=True, exist_ok=True)
    target = target_folder / f"{digest[:16]}{src.suffix.lower()}"
    if target.exists():
        if checksum(target) != digest:
            raise ValueError(f"Staging collision: {target}")
    else:
        shutil.copy2(src, target)  # source is never moved or overwritten
    return target


def ingest(incoming: Path, bank_dir: Path, stage: Path, encoder,
           accept_score: float | None = None, accept_margin: float | None = None,
           topk: int = 5, batch_size: int = 2):
    meta, bank_vec, paths, labels, hashes = load_bank(bank_dir, encoder.model_id)
    if not incoming.is_dir():
        raise ValueError("Incoming folder does not exist")
    if stage.resolve().is_relative_to(incoming.resolve()):
        raise ValueError("Stage output must be outside incoming folder")
    if (accept_score is None) != (accept_margin is None):
        raise ValueError("Provide both --accept-score and --accept-margin or neither")
    files = list(images_in(incoming))
    seen = set(hashes)
    ledger_path = stage / "decisions.json"
    ledger = json.loads(ledger_path.read_text(encoding="utf-8")) if ledger_path.exists() else []
    existing = {r["sha256"] for r in ledger}
    new_files, new_hashes = [], []
    for src in files:
        digest = checksum(src)
        if digest not in seen and digest not in existing and digest not in new_hashes:
            new_files.append(src)
            new_hashes.append(digest)
    vectors = unit(encoder.encode(new_files, batch_size=batch_size)) if new_files else []
    for src, digest, vec in zip(new_files, new_hashes, vectors):
        classes, templates = rank(vec, bank_vec, paths, labels, topk=topk)
        best = classes[0]
        margin = best["score"] - classes[1]["score"] if len(classes) > 1 else 0.0
        if accept_score is None:
            decision = "review_required"
        elif best["score"] < accept_score:
            decision = "novel_candidate"
        elif len(classes) > 1 and margin < accept_margin:
            decision = "ambiguous"
        else:
            decision = "existing_candidate"
        folder = stage / decision / (best["label"] if decision == "existing_candidate" else "_review")
        staged = safe_stage(src, folder, digest)
        ledger.append({"source": str(src), "sha256": digest, "staged": str(staged),
                       "status": decision, "suggested_class": best["label"],
                       "topk_classes": classes, "topk_templates": templates})
        # Save after each staged image so interrupted runs are resumable.
        write_json(ledger_path, ledger)
    return {"new_images": len(new_files), "previously_reviewed_or_indexed": len(files) - len(new_files),
            "decisions_file": str(ledger_path)}


def evaluate(matches_path: Path, predictions_path: Path, output: Path):
    matches = json.loads(matches_path.read_text(encoding="utf-8"))["matches"]
    preds = list(read_csv(predictions_path))
    by_id = {r["pair_id"]: r for r in matches}
    seen, retrieval = set(), []
    distances = []
    for pred in preds:
        pair_id = pred.get("pair_id", "")
        if pair_id in seen or pair_id not in by_id:
            raise ValueError(f"Duplicate/unknown pair_id: {pair_id}")
        seen.add(pair_id)
        row = by_id[pair_id]
        expected = row.get("expected_class")
        if expected:
            retrieval.append((row["topk_classes"][0]["label"] == expected,
                              expected in [c["label"] for c in row["topk_classes"]]))
        if all(pred.get(k) not in (None, "") for k in ("pred_x", "pred_y", "gt_x", "gt_y")):
            dx = float(pred["pred_x"]) - float(pred["gt_x"])
            dy = float(pred["pred_y"]) - float(pred["gt_y"])
            distances.append(math.hypot(dx, dy))
    metrics = {"total_test_pairs": len(matches), "prediction_rows": len(preds),
               "retrieval_labeled_pairs": len(retrieval),
               "retrieval_top1_accuracy": sum(a for a, _ in retrieval) / len(retrieval) if retrieval else None,
               "retrieval_topk_recall": sum(b for _, b in retrieval) / len(retrieval) if retrieval else None,
               "localization_gt_count": len(distances),
               "localization_median_error_px": float(np.median(distances)) if distances else None,
               "localization_mean_error_px": float(np.mean(distances)) if distances else None,
               "localization_within_5px": sum(x <= 5 for x in distances) / len(distances) if distances else None,
               "localization_within_10px": sum(x <= 10 for x in distances) / len(distances) if distances else None}
    write_json(output, metrics)
    return metrics


def cli():
    parser = argparse.ArgumentParser(description="AlignFail Reference↔Template and Open-set Dataset tool")
    sub = parser.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("index", help="Build class image feature bank")
    p.add_argument("--classes", required=True, type=Path)
    p.add_argument("--bank", required=True, type=Path)
    p = sub.add_parser("match-test", help="Match Test References to existing templates")
    p.add_argument("--pairs", required=True, type=Path)
    p.add_argument("--bank", required=True, type=Path)
    p.add_argument("--output", required=True, type=Path)
    p.add_argument("--topk", type=int, default=5)
    p = sub.add_parser("ingest", help="Stage incoming images; never mutates source/class folders")
    p.add_argument("--incoming", required=True, type=Path)
    p.add_argument("--bank", required=True, type=Path)
    p.add_argument("--stage", required=True, type=Path)
    p.add_argument("--accept-score", type=float)
    p.add_argument("--accept-margin", type=float)
    p.add_argument("--topk", type=int, default=5)
    p = sub.add_parser("evaluate", help="Evaluate retrieval and provided localization predictions")
    p.add_argument("--matches", required=True, type=Path)
    p.add_argument("--predictions", required=True, type=Path)
    p.add_argument("--output", required=True, type=Path)
    for name in ("index", "match-test", "ingest"):
        p = sub.choices[name]
        p.add_argument("--model", default=DEFAULT_MODEL, help="HF model id or pre-downloaded local path")
        p.add_argument("--device", default="cuda")
        p.add_argument("--batch-size", type=int, default=2)
    args = parser.parse_args()
    if args.cmd == "evaluate":
        result = evaluate(args.matches, args.predictions, args.output)
    else:
        if args.batch_size < 1 or (hasattr(args, "topk") and args.topk < 1):
            parser.error("batch-size and topk must be >= 1")
        if args.cmd == "ingest" and args.accept_score is not None and not (-1 <= args.accept_score <= 1):
            parser.error("accept-score must be in [-1,1]")
        if args.cmd == "ingest" and args.accept_margin is not None and not (0 <= args.accept_margin <= 2):
            parser.error("accept-margin must be in [0,2]")
        encoder = QwenEncoder(args.model, args.device)
        if args.cmd == "index":
            result = save_bank(args.classes, args.bank, encoder, args.batch_size)
        elif args.cmd == "match-test":
            result = {"matches": len(match_test(args.pairs, args.bank, args.output, encoder,
                                                   args.topk, args.batch_size)), "output": str(args.output)}
        else:
            result = ingest(args.incoming, args.bank, args.stage, encoder,
                            args.accept_score, args.accept_margin, args.topk, args.batch_size)
    print(json.dumps(result, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    cli()
