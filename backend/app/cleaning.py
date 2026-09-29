"""Deterministic, non-destructive removal of axis-aligned annotation lines."""

import hashlib
import io
import json

import cv2
import numpy as np
from PIL import Image

from .schemas import CleanupInput

ALGORITHM = "linear-local-contrast-v3"
RESIDUE_MARGIN = 80
REMOVE_WHITE_THRESHOLD = 235


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


def create_masks(pixels, config: CleanupInput):
    height, width = pixels.shape[:2]
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
        band_height, band_width = c.y1 - c.y0 + 1, c.x1 - c.x0 + 1
        if (band_height * width + band_width * height - band_height * band_width) / (height * width) > 0.25:
            raise ValueError("십자선 지정 영역이 이미지의 25%를 넘습니다. 좌표와 선 폭을 확인하세요.")
        gray = grayscale(pixels).astype(np.float32)
        ref_h = (gray[max(0, c.y0 - 1)] + gray[min(height - 1, c.y1 + 1)]) * 0.5
        ref_v = (gray[:, max(0, c.x0 - 1)] + gray[:, min(width - 1, c.x1 + 1)]) * 0.5
        horizontal = gray[c.y0 : c.y1 + 1, :]
        vertical = gray[:, c.x0 : c.x1 + 1]
        cross_mask[c.y0 : c.y1 + 1, :] = (
            (horizontal >= REMOVE_WHITE_THRESHOLD) | (horizontal - ref_h[None, :] >= RESIDUE_MARGIN)
        ).astype(np.uint8) * 255
        cross_mask[:, c.x0 : c.x1 + 1] |= (
            (vertical >= REMOVE_WHITE_THRESHOLD) | (vertical - ref_v[:, None] >= RESIDUE_MARGIN)
        ).astype(np.uint8) * 255
    if config.padding:
        kernel = np.ones((2 * config.padding + 1, 2 * config.padding + 1), dtype=np.uint8)
        mask = cv2.dilate(mask, kernel)
    mask = np.maximum(mask, cross_mask)
    if np.count_nonzero(mask) / mask.size > 0.25:
        raise ValueError("제거 영역이 이미지의 25%를 넘습니다. 좌표와 선 폭을 확인하세요.")
    return mask, cross_mask


def interpolate_cross(pixels, cross, mask):
    """Reference two-pass interpolation; vertical neighbors include horizontal repair."""
    source = pixels.astype(np.float32)
    out = source.copy()
    height, width = pixels.shape[:2]
    top, bottom = max(0, cross.y0 - 1), min(height - 1, cross.y1 + 1)
    if bottom > top:
        for y in range(cross.y0, cross.y1 + 1):
            alpha = (y - top) / float(bottom - top)
            interpolated = (1 - alpha) * source[top] + alpha * source[bottom]
            selected = mask[y] > 0
            out[y, selected] = interpolated[selected]
    horizontal = out.copy()
    left, right = max(0, cross.x0 - 1), min(width - 1, cross.x1 + 1)
    if right > left:
        for x in range(cross.x0, cross.x1 + 1):
            alpha = (x - left) / float(right - left)
            interpolated = (1 - alpha) * horizontal[:, left] + alpha * horizontal[:, right]
            selected = mask[:, x] > 0
            out[selected, x] = interpolated[selected]
    return np.clip(out, 0, 255).astype(np.uint8)


def clean_pixels(pixels, config: CleanupInput):
    mask, cross_mask = create_masks(pixels, config)
    cleaned = pixels.copy()
    # Box geometry/padding and Telea remain independent of the cross path.
    if config.box:
        box_mask, _ = create_masks(pixels, config.model_copy(update={"cross": None}))
        cleaned = cv2.inpaint(pixels, box_mask, config.radius, cv2.INPAINT_TELEA)
    if config.cross:
        cross_cleaned = interpolate_cross(pixels, config.cross, cross_mask)
        cleaned[cross_mask > 0] = cross_cleaned[cross_mask > 0]
    added_pixels = int(np.count_nonzero((cross_mask > 0) & (grayscale(pixels) < REMOVE_WHITE_THRESHOLD)))
    seed_material = json.dumps({"algorithm": ALGORITHM, **config.model_dump()}, sort_keys=True).encode()
    seed = int.from_bytes(hashlib.sha256(seed_material).digest()[:8], "big")
    # Unmasked original pixels are always preserved, including the box interior.
    cleaned[mask == 0] = pixels[mask == 0]
    info = {
        "algorithm": ALGORITHM,
        "parameters": config.model_dump(),
        "seed": seed,
        "noise_sigma": 0.0,
        "masked_pixels": int(np.count_nonzero(mask)),
        "masked_fraction": float(np.count_nonzero(mask) / mask.size),
        "residue_margin": RESIDUE_MARGIN,
        "cross_padding_applied": 0,
        "cross_noise_applied": False,
        "remove_white_threshold": REMOVE_WHITE_THRESHOLD,
        "residue_added_pixels": added_pixels,
        "opencv_version": cv2.__version__,
        "numpy_version": np.__version__,
    }
    return png_bytes(cleaned), png_bytes(mask), info
