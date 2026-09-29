import base64
import hashlib
import io
from pathlib import Path

import numpy as np
import pytest
from PIL import Image
from support import marked_image

from app.cleaning import clean_pixels, create_masks, detect_markings, png_bytes
from app.schemas import CleanupInput


def config(**changes):
    return CleanupInput(source_hash="a" * 64, **changes)


def test_box_detection_and_geometric_mask_preserve_interior():
    source = marked_image(box=True)
    detected = detect_markings(source)
    assert detected["box"] == {"x0": 40, "y0": 30, "x1": 150, "y1": 125}
    assert detected["cross"] is None  # A box corner is not a cross.
    options = config(box=detected["box"], padding=0)
    clean, _, info = clean_pixels(source, options)
    result = np.array(Image.open(io.BytesIO(clean)))
    mask, _ = create_masks(source, options)
    assert np.array_equal(source[mask == 0], result[mask == 0])
    assert np.array_equal(source[31:125, 41:150], result[31:125, 41:150])
    assert result[30, 55:75].max() < 160
    assert np.median(result[mask > 0]) < 130
    assert info["masked_pixels"] == int((mask > 0).sum())


@pytest.mark.parametrize("rgb", [False, True])
def test_cross_removal_is_deterministic_and_preserves_unmasked_pixels(rgb):
    source = marked_image(cross=True, rgb=rgb)
    detected = detect_markings(source)
    assert detected["cross"] == {"x0": 95, "x1": 96, "y0": 82, "y1": 83}
    options = config(cross=detected["cross"])
    clean, mask_png, info = clean_pixels(source, options)
    assert clean_pixels(source, options)[0] == clean
    result = np.array(Image.open(io.BytesIO(clean)))
    mask = np.array(Image.open(io.BytesIO(mask_png)))
    assert result.shape == source.shape
    assert np.array_equal(source[mask == 0], result[mask == 0])
    assert info["noise_sigma"] == 0
    assert np.median(result[mask > 0]) < 130


def test_scalebar_is_not_a_cross_and_unmarked_image_returns_no_candidates():
    source = marked_image()
    assert detect_markings(source)["box"] is None
    assert detect_markings(source)["cross"] is None
    source[150:152, 35:145] = 255
    source[145:155, 35:37] = 255
    source[145:155, 143:145] = 255
    assert detect_markings(source)["cross"] is None


@pytest.mark.parametrize("rgb", [False, True])
def test_dim_residue_removed_inside_band_but_real_patterns_preserved(rgb):
    source = np.full((160, 192), 60, dtype=np.uint8)
    source[30, :] = source[:, 90] = 255
    source[30, 25:50] = 223  # compressed line missed by absolute threshold
    source[15:60, 55:65] = 220  # genuine structure crossing the band
    source[30, 70:75] = 50  # dark structure must not be masked
    source[28, 25:50] = 223  # outside band: must remain untouched
    if rgb:
        source = np.repeat(source[:, :, None], 3, axis=2)
    original = source.copy()
    options = config(cross=dict(x0=90, x1=90, y0=30, y1=30))
    clean, mask_png, info = clean_pixels(source, options)
    result = np.array(Image.open(io.BytesIO(clean)))
    mask = np.array(Image.open(io.BytesIO(mask_png)))
    assert mask[30, 35] == 255 and np.all(result[30, 35] == 60)
    assert mask[30, 60] == 0 and np.all(result[30, 60] == 220)
    assert mask[30, 72] == 0 and np.all(result[30, 72] == 50)
    assert mask[28, 35] == 0 and np.all(result[28, 35] == 223)
    assert np.all(result[30, 90] == 60)  # intersection uses repaired horizontal neighbors
    assert np.array_equal(result[mask == 0], source[mask == 0])
    assert np.array_equal(source, original)
    assert info["residue_added_pixels"] == 25
    assert clean_pixels(source, options)[0] == clean
    # Legacy clients may still submit padding/noise; neither affects cross pixels.
    assert clean_pixels(source, options.model_copy(update={"padding": 5, "cross_noise": True}))[0] == clean


def test_cross_defaults_and_horizontal_mask_survives_vertical_or():
    source = np.full((80, 80), 60, np.uint8)
    source[39, :] = 223
    source[:, 40] = 223
    options = config(cross=dict(x0=40, x1=40, y0=39, y1=39))
    assert options.padding == 0 and options.cross_noise is False
    mask, cross = create_masks(source, options)
    assert mask[39, 40] == 0  # neighbors on both axes are also 223
    assert cross[39, 10] == 255 and cross[10, 40] == 255
    source[38, 40] = source[40, 40] = 60
    mask, _ = create_masks(source, options)
    assert mask[39, 40] == 255  # horizontal gate true, vertical false: OR retains it


def test_both_markings_can_be_removed_together():
    source = marked_image(box=True, cross=True)
    found = detect_markings(source)
    assert found["box"] is not None and found["cross"] is not None
    options = config(box=found["box"], cross=found["cross"])
    clean, mask_png, _ = clean_pixels(source, options)
    mask = np.array(Image.open(io.BytesIO(mask_png)))
    result = np.array(Image.open(io.BytesIO(clean)))
    assert np.array_equal(source[mask == 0], result[mask == 0])
    assert np.percentile(result[mask > 0], 99) < 200


@pytest.mark.parametrize(
    "changes",
    [
        {},
        {"box": {"x0": 4, "y0": 5, "x1": 200, "y1": 80}},
        {"box": {"x0": 4, "y0": 5, "x1": 5, "y1": 6}},
        {"cross": {"x0": 0, "y0": 0, "x1": 100, "y1": 100}},
    ],
)
def test_invalid_removal_regions_are_rejected(changes):
    with pytest.raises(ValueError):
        clean_pixels(marked_image(), config(**changes))


def test_preview_save_reset_and_snapshot_keep_original_and_gt(cleanup_client):
    client, pid, pair, folder = cleanup_client
    image = pair["query"]
    original = (folder / "image.png").read_bytes()
    detected = client.get(f"/api/images/{image['id']}/clean/detect").json()
    body = {"source_hash": image["file_hash"], "cross": detected["cross"]}
    preview = client.post(f"/api/images/{image['id']}/clean/preview", json=body)
    assert preview.status_code == 200, preview.text
    saved = client.post(f"/api/images/{image['id']}/clean", json=body)
    assert saved.status_code == 201, saved.text
    cid = saved.json()["id"]
    clean = client.get(f"/api/cleanups/{cid}/image").content
    assert base64.b64decode(preview.json()["preview_url"].split(",")[1]) == clean
    assert hashlib.sha256(clean).hexdigest() == saved.json()["clean_hash"]
    assert (folder / "image.png").read_bytes() == original
    after = client.get(f"/api/projects/{pid}/pairs").json()[0]
    assert (after["gt_x"], after["gt_y"]) == (70, 60)
    assert after["revision"] > pair["revision"]
    assert after["query"]["cleanup"]["id"] == cid
    version = client.post(f"/api/projects/{pid}/versions", json={"description": "cleaned"}).json()
    assert "id" in version
    assert (
        client.post(f"/api/images/{image['id']}/clean/reset", json={"source_hash": image["file_hash"]}).status_code
        == 200
    )
    assert client.get(f"/api/projects/{pid}/pairs").json()[0]["query"]["cleanup"] is None
    manifest = client.get(f"/api/versions/{version['id']}/manifest").json()
    assert manifest["pairs"][0]["query"]["cleanup"]["id"] == cid
    assert client.get(f"/api/cleanups/{cid}/image?download=true").status_code == 200


def test_changed_source_and_missing_cache_cannot_pass_audit(cleanup_client):
    client, pid, pair, folder = cleanup_client
    image = pair["reference"]
    body = {"source_hash": image["file_hash"], "box": {"x0": 40, "y0": 30, "x1": 150, "y1": 125}}
    saved = client.post(f"/api/images/{image['id']}/clean", json=body).json()
    after = client.get(f"/api/projects/{pid}/pairs").json()[0]
    Path(after["reference"]["cleanup"]["mask_path"]).unlink()
    assert "BROKEN_CLEAN" in [i["code"] for i in client.post(f"/api/projects/{pid}/audit").json()["issues"]]
    (folder / "image_REF.png").write_bytes(png_bytes(marked_image()))
    assert client.post(f"/api/images/{image['id']}/clean/preview", json=body).status_code == 409
    assert client.get(f"/api/cleanups/{saved['id']}/image").status_code == 409
    assert client.post(f"/api/projects/{pid}/versions", json={"description": "invalid"}).status_code == 422
    assert client.post(f"/api/projects/{pid}/import", json={"root_directory": str(folder.parent)}).status_code == 200
    after = client.get(f"/api/projects/{pid}/pairs").json()[0]
    assert after["reference"]["cleanup"]["stale"]


def test_unsupported_bit_depth_is_not_silently_changed(cleanup_client):
    client, pid, pair, folder = cleanup_client
    Image.new("I;16", (192, 160), 2048).save(folder / "image_REF.png")
    client.post(f"/api/projects/{pid}/import", json={"root_directory": str(folder.parent)})
    result = client.get(f"/api/images/{pair['reference']['id']}/clean/detect")
    assert result.status_code == 422
    assert "8-bit" in result.json()["detail"]
