"""Offline cross-only acceptance report. Never overwrites input or registers Clean images."""

import argparse
import ast
import io
import json
import sys
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path

import cv2
import numpy as np
from PIL import Image, ImageDraw

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))
from app.cleaning import clean_pixels, detect_markings, grayscale, interpolate_cross, load_pixels
from app.schemas import CleanupInput


def reference_functions(path):
    # Execute only the reviewed standalone cross functions, never torch/model code.
    names = {"to_gray", "ensure_color", "CrossInfo", "_band", "detect_cross", "remove_cross"}
    tree = ast.parse(path.read_text(encoding="utf-8-sig"))
    tree.body = [n for n in tree.body if isinstance(n, (ast.FunctionDef, ast.ClassDef)) and n.name in names]
    if {n.name for n in tree.body} != names:
        raise ValueError("Reference file lacks the expected cross functions")
    scope = dict(np=np, cv2=cv2, dataclass=dataclass, __name__=__name__, DETECT_WHITE_THRESHOLD=245,
                 REMOVE_WHITE_THRESHOLD=235, RESIDUE_MARGIN=80, MIN_AXIS_WHITE_FRACTION=0.30,
                 BAND_RELATIVE_THRESHOLD=0.45)
    exec(compile(tree, str(path), "exec"), scope)
    return scope


def panel(pixels, title, center):
    image = Image.fromarray(pixels).convert("RGB")
    canvas = Image.new("RGB", (256, 480), "#20252b")
    thumb = image.copy()
    thumb.thumbnail((256, 256))
    canvas.paste(thumb, (0, 22))
    if center:
        x, y = center
        zoom = image.crop((x - 32, y - 32, x + 32, y + 32)).resize((192, 192), Image.Resampling.NEAREST)
        canvas.paste(zoom, (0, 286))
    ImageDraw.Draw(canvas).text((4, 3), title, fill="white")
    return canvas


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--reference", type=Path)
    args = parser.parse_args()
    root, output = args.input.resolve(), args.output.resolve()
    if output == root or root in output.parents or output in root.parents:
        raise ValueError("Input and output trees must be separate")
    files = sorted(p for p in root.rglob("*") if p.suffix.lower() in {".png", ".jpg", ".jpeg", ".bmp", ".tif", ".tiff"})
    if not files:
        raise ValueError("No input images found")
    output.mkdir(parents=True, exist_ok=True)
    reference = reference_functions(args.reference) if args.reference else None
    rows, sheets = [], defaultdict(list)
    for index, path in enumerate(files):
        content = path.read_bytes()
        source = load_pixels(content)
        untouched = source.copy()
        found = detect_markings(source)["cross"]
        row = {"file": str(path.relative_to(root)), "cross": found, "additional_pixels": 0,
               "before_residue": 0, "after_residue": 0, "reference_equal": None}
        old = new = source.copy()
        center = None
        if found:
            config = CleanupInput(source_hash="a" * 64, cross=found)
            clean, mask_bytes, info = clean_pixels(source, config)
            assert clean_pixels(source, config)[0] == clean
            new = np.array(Image.open(io.BytesIO(clean)))
            mask = np.array(Image.open(io.BytesIO(mask_bytes)))
            gray = grayscale(source)
            band = np.zeros(gray.shape, bool)
            band[found["y0"] : found["y1"] + 1, :] = True
            band[:, found["x0"] : found["x1"] + 1] = True
            absolute_mask = (band & (gray >= 235)).astype(np.uint8) * 255
            old = interpolate_cross(source, config.cross, absolute_mask)
            # Fixed outside-band source median makes before/after directly comparable.
            threshold = float(np.median(gray[~band])) + 80
            row.update(additional_pixels=info["residue_added_pixels"],
                       before_residue=int(np.count_nonzero(band & (grayscale(old) >= threshold))),
                       after_residue=int(np.count_nonzero(band & (grayscale(new) >= threshold))))
            assert np.array_equal(source[mask == 0], new[mask == 0])
            center = ((found["x0"] + found["x1"]) // 2, (found["y0"] + found["y1"]) // 2)
            if reference:
                ref_source = cv2.cvtColor(source, cv2.COLOR_RGB2BGR) if source.ndim == 3 else source
                cross = reference["detect_cross"](ref_source)
                same_band = all(getattr(cross, key) == value for key, value in found.items())
                ref_result = reference["remove_cross"](ref_source, cross)
                ref_result = cv2.cvtColor(ref_result, cv2.COLOR_BGR2RGB) if source.ndim == 3 else ref_result[:, :, 0]
                row["reference_equal"] = bool(same_band and np.array_equal(mask, cross.remove_mask) and np.array_equal(new, ref_result))
        else:
            row["unchanged_max_difference"] = int(np.abs(new.astype(int) - source.astype(int)).max())
        assert np.array_equal(source, untouched) and path.read_bytes() == content
        Image.fromarray(new).save(output / f"{index:03d}-clean.png")
        group = path.relative_to(root).parts[0] if path.parent != root else "root"
        sheet = Image.new("RGB", (768, 480))
        for i, (pixels, title) in enumerate([(source, "Original"), (old, "Absolute only"), (new, "v3")]):
            sheet.paste(panel(pixels, f"{index:03d} {title} / cross zoom 3x", center), (256 * i, 0))
        sheets[group].append(sheet)
        rows.append(row)
    for group, panels in sheets.items():
        sheet = Image.new("RGB", (768, 480 * len(panels)))
        for i, item in enumerate(panels):
            sheet.paste(item, (0, 480 * i))
        sheet.save(output / f"{group}-comparison.png")
    added = sum(r["additional_pixels"] for r in rows)
    before, after = (sum(r[key] for r in rows) for key in ("before_residue", "after_residue"))
    reduction = before - after
    worse = sum(r["after_residue"] > r["before_residue"] for r in rows)
    ratio = added / reduction if reduction > 0 else None
    summary = dict(images=len(rows), no_cross=sum(r["cross"] is None for r in rows), before=before, after=after,
                   additional_pixels=added, reduction=reduction, additional_to_reduction=ratio, worsened=worse,
                   reference_mismatches=sum(r["reference_equal"] is False for r in rows),
                   numerical_pass=bool(reduction > 0 and worse == 0 and ratio <= 2),
                   visual_review="Required; numerical pass is not visual acceptance")
    (output / "report.json").write_text(json.dumps(dict(summary=summary, images=rows), ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False))
    return 0 if summary["numerical_pass"] and not summary["reference_mismatches"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
