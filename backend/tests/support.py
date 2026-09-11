"""Synthetic test images shared by the cleaning and batch API tests."""

import numpy as np


def marked_image(box=False, cross=False, rgb=False):
    rng = np.random.default_rng(5)
    pixels = np.clip(rng.normal(85, 12, (160, 192)), 0, 180).astype(np.uint8)
    if box:
        pixels[30, 40:151] = 255
        pixels[125, 40:151] = 255
        pixels[30:126, 40] = 255
        pixels[30:126, 150] = 255
        # Dark sections must still be removed by the full geometric mask.
        pixels[30, 55:75] = 190
    if cross:
        pixels[82:84, :] = 255
        pixels[:, 95:97] = 255
    return np.repeat(pixels[:, :, None], 3, axis=2) if rgb else pixels
