"""Deterministic, non-destructive removal of axis-aligned annotation lines."""

import hashlib
import io
import json

import cv2
import numpy as np
from PIL import Image

from .schemas import CleanupInput

ALGORITHM = "telea-cross-texture-v1"


def load_pixels(content: bytes):
    with Image.open(io.BytesIO(content)) as image:
        image.load()
        if image.mode not in {"L", "RGB"}:
            raise ValueError(
                "표시 제거는 8-bit grayscale 또는 RGB 이미지를 지원합니다. 원본 bit depth를 자동 변환하지 않습니다."
            )
        return np.array(image)


def png_bytes(pixels):
    output = io.BytesIO()
    Image.fromarray(pixels).save(output, format="PNG")
    return output.getvalue()


def grayscale(pixels):
    return cv2.cvtColor(pixels, cv2.COLOR_RGB2GRAY) if pixels.ndim == 3 else pixels


def band(projection, peak):
    low = high = int(peak)
    cutoff = projection[peak] * 0.45
    while low > 0 and projection[low - 1] >= cutoff:
        low -= 1
    while high + 1 < len(projection) and projection[high + 1] >= cutoff:
        high += 1
    return low, high


def two_peaks(values, separation=15):
    first = int(np.argmax(values))
    remaining = values.copy()
    remaining[max(0, first - separation) : first + separation + 1] = -1
    second = int(np.argmax(remaining))
    return sorted([first, second])


def detect_markings(pixels):
    gray = grayscale(pixels)
    height, width = gray.shape
    white = gray >= 245
    rows, cols = white.mean(axis=1), white.mean(axis=0)
    y, x = int(np.argmax(rows)), int(np.argmax(cols))
    cross = None
    # Require both axes and support on both sides, rejecting scale bars and box corners.
    if rows[y] >= 0.30 and cols[x] >= 0.30 and 2 <= x < width - 2 and 2 <= y < height - 2:
        support = [white[y, :x].mean(), white[y, x + 1 :].mean(), white[:y, x].mean(), white[y + 1 :, x].mean()]
        x0, x1 = band(cols, x)
        y0, y1 = band(rows, y)
        if min(support) >= 0.25 and x1 - x0 <= 10 and y1 - y0 <= 10:
            cross = dict(x0=x0, x1=x1, y0=y0, y1=y1)
    bright = gray >= 250
    if cross:
        bright[max(0, cross["y0"] - 1) : cross["y1"] + 2, :] = False
        bright[:, max(0, cross["x0"] - 1) : cross["x1"] + 2] = False
    x0, x1 = two_peaks(bright.sum(axis=0).astype(float))
    y0, y1 = two_peaks(bright.sum(axis=1).astype(float))
    box, coverage = None, 0.0
    if 2 <= x0 < x1 < width - 2 and 2 <= y0 < y1 < height - 2 and x1 - x0 >= 16 and y1 - y0 >= 16:
        g = gray.astype(float)
        scores = []
        for yy in [y0, y1]:
            ridge = g[yy, x0 : x1 + 1] - (g[yy - 2, x0 : x1 + 1] + g[yy + 2, x0 : x1 + 1]) / 2
            scores.append(float((ridge >= 40).mean()))
        for xx in [x0, x1]:
            ridge = g[y0 : y1 + 1, xx] - (g[y0 : y1 + 1, xx - 2] + g[y0 : y1 + 1, xx + 2]) / 2
            scores.append(float((ridge >= 40).mean()))
        coverage = min(scores)
        if coverage >= 0.8:
            box = dict(x0=x0, y0=y0, x1=x1, y1=y1)
    return {
        "box": box,
        "cross": cross,
        "box_coverage": round(coverage, 4),
        "message": "자동 검출은 후보입니다. 제거 영역을 확인한 뒤 저장하세요.",
    }


def create_masks(shape, config: CleanupInput):
    height, width = shape[:2]
    mask = np.zeros((height, width), dtype=np.uint8)
    cross_mask = np.zeros_like(mask)
    if config.box is None and config.cross is None:
        raise ValueError("제거할 네모 또는 십자선 영역을 지정하세요.")
    for rect in [config.box, config.cross]:
        if rect and (rect.x1 >= width or rect.y1 >= height):
            raise ValueError("제거 영역이 원본 이미지 범위를 벗어났습니다.")
    if config.box:
        b = config.box
        if b.x1 - b.x0 <= 2 * config.padding + 2 or b.y1 - b.y0 <= 2 * config.padding + 2:
            raise ValueError("네모가 너무 작습니다. 테두리 좌표나 제거 여유 폭을 확인하세요.")
        # Mask the entire geometric perimeter, including dimmer sections of a white line.
        mask[b.y0, b.x0 : b.x1 + 1] = 255
        mask[b.y1, b.x0 : b.x1 + 1] = 255
        mask[b.y0 : b.y1 + 1, b.x0] = 255
        mask[b.y0 : b.y1 + 1, b.x1] = 255
    if config.cross:
        c = config.cross
        cross_mask[c.y0 : c.y1 + 1, :] = 255
        cross_mask[:, c.x0 : c.x1 + 1] = 255
    if config.padding:
        kernel = np.ones((2 * config.padding + 1, 2 * config.padding + 1), dtype=np.uint8)
        mask = cv2.dilate(mask, kernel)
        cross_mask = cv2.dilate(cross_mask, kernel)
    mask = np.maximum(mask, cross_mask)
    if np.count_nonzero(mask) / mask.size > 0.25:
        raise ValueError("제거 영역이 이미지의 25%를 넘습니다. 좌표와 선 폭을 확인하세요.")
    return mask, cross_mask


def clean_pixels(pixels, config: CleanupInput):
    mask, cross_mask = create_masks(pixels.shape, config)
    cleaned = cv2.inpaint(pixels, mask, config.radius, cv2.INPAINT_TELEA)
    seed_material = json.dumps({"algorithm": ALGORITHM, **config.model_dump()}, sort_keys=True).encode()
    seed = int.from_bytes(hashlib.sha256(seed_material).digest()[:8], "big")
    sigma = 0.0
    if config.cross and config.cross_noise:
        gray = grayscale(pixels).astype(np.float32)
        highpass = gray - cv2.GaussianBlur(gray, (0, 0), 1.2)
        # Keep annotation edges out of the texture estimate as well as the masked pixels.
        excluded = cv2.dilate(mask, np.ones((9, 9), np.uint8))
        sample = highpass[excluded == 0]
        sigma = float(np.std(sample)) if sample.size else 0.0
        noise = np.random.default_rng(seed).normal(0, sigma, mask.shape)
        selected = cross_mask > 0
        values = cleaned[selected].astype(float)
        values += noise[selected, None] if pixels.ndim == 3 else noise[selected]
        cleaned[selected] = np.clip(np.rint(values), 0, 255).astype(np.uint8)
    # Unmasked original pixels are always preserved, including the box interior.
    cleaned[mask == 0] = pixels[mask == 0]
    info = {
        "algorithm": ALGORITHM,
        "parameters": config.model_dump(),
        "seed": seed,
        "noise_sigma": sigma,
        "masked_pixels": int(np.count_nonzero(mask)),
        "masked_fraction": float(np.count_nonzero(mask) / mask.size),
        "opencv_version": cv2.__version__,
        "numpy_version": np.__version__,
    }
    return png_bytes(cleaned), png_bytes(mask), info
