"""Dump what a trained Metric Patch checkpoint sees for one pair.

Writes to <experiment>/viz/<pair_id>/:
  anchor.png, positive.png, negative.png   the three model inputs
  conv1_filters.png                        first-layer 3x3 filters as a grid
  anchor_stage{1..3}.png                   feature maps after each ReLU (first N channels)
  positive_stage{1..3}.png
  viz.json                                 shapes, layer statistics, descriptors, cosines
"""

import argparse
from pathlib import Path

import cv2
import numpy as np
import torch
from torch import nn

from .config import TrainingConfig
from .data import crop, crop_spec, load_json, read_image, write_json
from .model import make_model, tensor


def to_uint8(array):
    array = np.asarray(array, dtype=np.float32)
    low, high = float(array.min()), float(array.max())
    return np.clip((array - low) / ((high - low) or 1.0) * 255, 0, 255).astype(np.uint8)


def grid(maps, cols, cell, pad=2):
    """Tile 2-D arrays (each normalised on its own) into one uint8 image."""
    maps = list(maps)
    rows = (len(maps) + cols - 1) // cols
    canvas = np.full((rows * (cell + pad) + pad, cols * (cell + pad) + pad), 40, dtype=np.uint8)
    for index, item in enumerate(maps):
        tile = cv2.resize(to_uint8(item), (cell, cell), interpolation=cv2.INTER_NEAREST)
        y = pad + (index // cols) * (cell + pad)
        x = pad + (index % cols) * (cell + pad)
        canvas[y : y + cell, x : x + cell] = tile
    return canvas


def stages(model, pixels):
    """Run the encoder layer by layer and return the activation after every ReLU."""
    outputs = []
    value = pixels
    with torch.no_grad():
        for module in model.encoder:
            value = module(value)
            if isinstance(module, nn.ReLU):
                outputs.append(value[0].clone())
    return outputs


def far_corner(image, center, min_distance):
    """Deterministic negative: the corner farthest from the GT (mirrors train.negative_center's fallback)."""
    h, w = image.shape
    corners = [(0.0, 0.0), (w - 1.0, 0.0), (0.0, h - 1.0), (w - 1.0, h - 1.0)]
    point = max(corners, key=lambda p: np.linalg.norm(np.subtract(p, center)))
    if np.linalg.norm(np.subtract(point, center)) < min_distance:
        raise ValueError("No valid negative location")
    return list(point)


def run(directory: Path, pair_id: str, checkpoint: str = "best", channels: int = 16):
    config = TrainingConfig(**load_json(directory / "config.json")).model_dump()
    manifest = load_json(directory / "dataset_manifest.json")
    split = load_json(directory / "split_manifest.json")
    row = next((p for p in manifest["pairs"] if p["pair_id"] == pair_id), None)
    if row is None:
        raise ValueError("Pair is not part of this experiment")
    model = make_model(config)
    state = torch.load(directory / f"{checkpoint}.pt", map_location="cpu", weights_only=True)
    model.load_state_dict(state["model"])
    model.eval()

    ref = read_image(row["ref_path"], row["ref_hash"])
    query = read_image(row["query_path"], row["query_hash"])
    native, size = crop_spec(row["ref_box"], config["crop_mode"], config)
    anchor, _ = crop(ref, row["ref_center"], native, size)
    positive, _ = crop(query, row["query_gt"], native, size)
    negative_center = far_corner(query, row["query_gt"], config["negative_min_distance"])
    negative, _ = crop(query, negative_center, native, size)

    out = directory / "viz" / pair_id
    out.mkdir(parents=True, exist_ok=True)
    for name, pixels in [("anchor", anchor), ("positive", positive), ("negative", negative)]:
        cv2.imwrite(str(out / f"{name}.png"), pixels)

    convs = [m for m in model.encoder if isinstance(m, nn.Conv2d)]
    first = convs[0].weight.detach()[:, 0].numpy()
    cv2.imwrite(str(out / "conv1_filters.png"), grid(first, cols=8, cell=40))

    inputs = {name: tensor(pixels, "cpu") for name, pixels in [("anchor", anchor), ("positive", positive)]}
    shapes = []
    for name, pixels in inputs.items():
        for index, activation in enumerate(stages(model, pixels), start=1):
            maps = activation[:channels].numpy()
            cv2.imwrite(str(out / f"{name}_stage{index}.png"), grid(maps, cols=8, cell=56))
            if name == "anchor":
                shapes.append(
                    {
                        "stage": index,
                        "channels": int(activation.shape[0]),
                        "height": int(activation.shape[1]),
                        "width": int(activation.shape[2]),
                        "mean": float(activation.mean()),
                        "sparsity": float((activation == 0).float().mean()),
                    }
                )

    with torch.no_grad():
        a = model(inputs["anchor"])[0]
        p = model(inputs["positive"])[0]
        n = model(tensor(negative, "cpu"))[0]
    cos_ap = float(np.clip((a * p).sum().item(), -1.0, 1.0))
    cos_an = float(np.clip((a * n).sum().item(), -1.0, 1.0))

    layers = []
    for index, conv in enumerate(convs, start=1):
        weight = conv.weight.detach()
        layers.append(
            {
                "name": f"conv{index}",
                "in": int(conv.in_channels),
                "out": int(conv.out_channels),
                "params": int(sum(p.numel() for p in conv.parameters())),
                "weight_mean": float(weight.mean()),
                "weight_std": float(weight.std()),
                "weight_abs_max": float(weight.abs().max()),
            }
        )

    write_json(
        out / "viz.json",
        {
            "pair_id": pair_id,
            "folder": row["folder"],
            "checkpoint": checkpoint,
            "epoch": int(state.get("epoch", 0)),
            "split": "validation" if pair_id in split["validation"] else "train",
            "crop_mode": config["crop_mode"],
            "native_size": native,
            "input_size": size,
            "negative_center": negative_center,
            "channels_shown": channels,
            "stages": shapes,
            "layers": layers,
            "descriptor": {
                "anchor": [round(v, 5) for v in a.tolist()],
                "positive": [round(v, 5) for v in p.tolist()],
                "negative": [round(v, 5) for v in n.tolist()],
            },
            "cosine": {
                "anchor_positive": cos_ap,
                "anchor_negative": cos_an,
                "triplet_margin_gap": (1 - cos_ap) - (1 - cos_an),
                "margin": config["margin"],
            },
        },
    )
    return out


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--experiment", type=Path, required=True)
    parser.add_argument("--pair", required=True)
    parser.add_argument("--checkpoint", choices=["best", "last"], default="best")
    parser.add_argument("--channels", type=int, default=16)
    args = parser.parse_args()
    out = run(args.experiment.resolve(), args.pair, args.checkpoint, args.channels)
    print(out)


if __name__ == "__main__":
    main()
