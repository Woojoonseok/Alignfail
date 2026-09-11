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
    mask, _ = create_masks(source.shape, options)
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
    assert info["noise_sigma"] > 0
    assert np.median(result[mask > 0]) < 130


def test_scalebar_is_not_a_cross_and_unmarked_image_returns_no_candidates():
    source = marked_image()
    assert detect_markings(source)["box"] is None
    assert detect_markings(source)["cross"] is None
    source[150:152, 35:145] = 255
    source[145:155, 35:37] = 255
    source[145:155, 143:145] = 255
    assert detect_markings(source)["cross"] is None


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
