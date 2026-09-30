import os
import time

import numpy as np
import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session
from support import marked_image

from app.cleaning import png_bytes
from app.main import create_app
from app.models import ImageRecord, Pair


@pytest.fixture
def samples(tmp_path):
    app = create_app(tmp_path / "state")
    with TestClient(app) as client:
        pid = client.post("/api/projects", json={"name": "REF roles"}).json()["id"]
        yield client, pid
    app.state.engine.dispose()


def upload(client, pid, split="train"):
    response = client.post(
        f"/api/projects/{pid}/upload?dataset_split={split}",
        files=[
            ("files", ("Data/ClassA/no_REF_in_name.png", png_bytes(marked_image(cross=True)), "image/png")),
        ],
    )
    assert response.status_code == 200, response.text
    return client.get(f"/api/projects/{pid}/pairs").json()[-1]


@pytest.mark.parametrize("split", ["train", "test"])
def test_cleanup_gt_targets_train_reference_only(samples, split):
    client, pid = samples
    row = upload(client, pid, split)
    role = "reference" if split == "train" else "query"
    assert row["sample_role"] == role
    image = row[role]
    cross = client.get(f"/api/images/{image['id']}/clean/detect").json()["cross"]
    body = dict(source_hash=image["file_hash"], cross=cross)
    assert client.post(f"/api/images/{image['id']}/clean/preview", json=body).status_code == 200
    assert client.get(f"/api/projects/{pid}/pairs").json()[0]["gt_x"] is None
    saved = client.post(f"/api/images/{image['id']}/clean", json=body)
    assert saved.status_code == 201
    after = client.get(f"/api/projects/{pid}/pairs").json()[0]
    if split == "train":
        assert (after["gt_x"], after["gt_y"], after["gt_source"]) == (95.5, 82.5, "auto_cross")
        assert after["query"] is None
        assert client.post(f"/api/projects/{pid}/audit").json()["passed"]
        manual = client.put(f"/api/pairs/{row['id']}", json=dict(revision=after["revision"], gt_x=20, gt_y=30))
        assert manual.status_code == 200
        client.post(f"/api/images/{image['id']}/clean", json=body)
        final = client.get(f"/api/projects/{pid}/pairs").json()[0]
        assert (final["gt_x"], final["gt_y"], final["gt_source"]) == (20, 30, "manual")
    else:
        assert after["gt_x"] is None and after["reference"] is None


def test_existing_clean_recovers_missing_reference_gt_without_rewriting_clean(samples):
    client, pid = samples
    row = upload(client, pid)
    image = row["reference"]
    body = dict(source_hash=image["file_hash"])
    first = client.post(f"/api/images/{image['id']}/clean/auto", json=body).json()
    with Session(client.app.state.engine) as db:
        pair = db.get(Pair, row["id"])
        pair.gt_x = pair.gt_y = None
        pair.gt_source = "none"
        db.commit()
    recovered = client.post(f"/api/images/{image['id']}/clean/auto", json=body)
    assert recovered.json()["auto_gt_count"] == 1
    after = client.get(f"/api/projects/{pid}/pairs").json()[0]
    assert after["reference"]["cleanup"]["id"] == first["cleanup_id"]
    assert after["gt_x"] == 95.5
    assert client.post(f"/api/images/{image['id']}/clean/auto", json=body).json()["status"] == "skipped"


def test_normalize_legacy_upload_keeps_ids_and_clean_and_backfills_gt(samples):
    client, pid = samples
    row = upload(client, pid)
    image = row["reference"]
    saved = client.post(f"/api/images/{image['id']}/clean/auto", json=dict(source_hash=image["file_hash"])).json()
    with Session(client.app.state.engine) as db:
        pair = db.get(Pair, row["id"])
        pair.sample_role = "pair"
        pair.query_image_id, pair.reference_image_id = image["id"], None
        pair.gt_x = pair.gt_y = None
        pair.gt_source = "none"
        db.get(ImageRecord, image["id"]).role = "QUERY"
        db.commit()
    result = client.post(f"/api/projects/{pid}/normalize-upload-roles")
    assert result.status_code == 200, result.text
    after = client.get(f"/api/projects/{pid}/pairs").json()[0]
    assert after["id"] == row["id"] and after["reference"]["id"] == image["id"]
    assert after["reference"]["cleanup"]["id"] == saved["cleanup_id"]
    assert after["gt_x"] == 95.5 and after["sample_role"] == "reference"
    assert client.post(f"/api/projects/{pid}/normalize-upload-roles").status_code == 200
    assert len(client.get(f"/api/projects/{pid}/pairs").json()) == 1


def test_reference_only_training_prepare_and_optional_run(samples, monkeypatch):
    client, pid = samples
    for i in range(4):
        pixels = np.random.default_rng(i).integers(20, 150, (256, 256), dtype=np.uint8)
        pixels[128, :] = pixels[:, 128] = 255
        response = client.post(
            f"/api/projects/{pid}/upload",
            files=[
                ("files", (f"ClassA/sample{i}.png", png_bytes(pixels), "image/png")),
            ],
        )
        assert response.status_code == 200
    for row in client.get(f"/api/projects/{pid}/pairs").json():
        image = row["reference"]
        result = client.post(f"/api/images/{image['id']}/clean/auto", json=dict(source_hash=image["file_hash"]))
        assert result.json()["auto_gt_count"] == 1
    for i, row in enumerate(client.get(f"/api/projects/{pid}/pairs").json()):
        assert (row["gt_x"], row["gt_y"]) == (128, 128)
        response = client.put(
            f"/api/pairs/{row['id']}",
            json=dict(
                revision=row["revision"],
                gt_x=128,
                gt_y=128,
                confirm_gt=True,
                class_label="ClassA",
                group_key=f"capture{i}",
            ),
        )
        assert response.status_code == 200
    version = client.post(f"/api/projects/{pid}/versions", json=dict(description="References only"))
    assert version.status_code == 201, version.text
    body = dict(version_id=version.json()["id"], config=dict(folds=2, epochs=1, device="cpu", embedding_dim=16))
    prepared = client.post("/api/training/prepare", json=body)
    assert prepared.status_code == 201, prepared.text
    rows = prepared.json()["manifest"]["pairs"]
    assert len(rows) == 4 and all(r["sample_role"] == "reference" for r in rows)
    assert all(r["ref_center"] == [128, 128] and r["ref_path"] == r["query_path"] for r in rows)
    assert all(r["reference_annotation"]["source"] == "reference_gt_fixed_crop" for r in rows)
    adaptive = client.post(
        "/api/training/prepare", json={**body, "config": {**body["config"], "crop_mode": "adaptive"}}
    )
    assert adaptive.status_code == 422 and "ROI" in adaptive.json()["detail"]
    python = os.getenv("ALIGNFAIL_TEST_TRAINING_PYTHON")
    if python:
        monkeypatch.setenv("ALIGNFAIL_TRAINING_PYTHON", python)
        eid = prepared.json()["id"]
        assert client.post(f"/api/experiments/{eid}/start").status_code == 200
        deadline = time.monotonic() + 90
        while time.monotonic() < deadline:
            state = client.get(f"/api/experiments/{eid}").json()
            if state["status"] not in {"queued", "running"}:
                break
            time.sleep(0.2)
        assert state["status"] == "completed", state
