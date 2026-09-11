import os
import subprocess
import time
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest
from fastapi.testclient import TestClient
from PIL import Image

from app.experiment_service import prepare
from app.main import create_app
from training.config import TrainingConfig
from training.data import crop, crop_spec, diagnostics, group_split, metrics


@pytest.mark.parametrize("mode,size", [("fixed_160", 160), ("fixed_256", 256), ("fixed_320", 320)])
def test_native_crop_size_and_center(mode, size):
    config = TrainingConfig().model_dump()
    native, output = crop_spec([50, 50, 100, 100], mode, config)
    assert native == output == size
    image = np.tile(np.arange(512, dtype=np.float32), (512, 1))
    patch, meta = crop(image, [255.5, 255.5], native, output)
    assert patch.shape == (size, size) and patch.mean() == 255.5
    assert meta["resize_scale"] == 1 and meta["center"] == [255.5, 255.5]


def test_reflect_padding_and_subpixel_center():
    image = np.arange(25, dtype=np.float32).reshape(5, 5)
    patch, _ = crop(image, [0, 0], 5, 5)
    assert np.array_equal(patch, np.pad(image, 2, mode="reflect")[:5, :5])
    patch, _ = crop(image, [1.5, 1.5], 2, 2)
    assert np.array_equal(patch, image[1:3, 1:3])


def test_adaptive_clamp_rounding_and_center():
    config = TrainingConfig().model_dump()
    assert crop_spec([0, 0, 10, 10], "adaptive", config) == (192, 320)
    assert crop_spec([0, 0, 500, 500], "adaptive", config) == (384, 320)
    assert crop_spec([0, 0, 130, 130], "adaptive", config) == (195, 320)
    image = np.tile(np.arange(600, dtype=np.float32), (600, 1))
    patch, meta = crop(image, [300.25, 300.25], 195, 320)
    assert np.isclose(patch.mean(), 300.25, atol=0.01)
    assert meta["center"] == [300.25, 300.25] and meta["resize_scale"] == 320 / 195


def test_diagnostic_warning_does_not_exclude_and_context_changes_statistics():
    config = TrainingConfig().model_dump()
    image = np.zeros((400, 400), dtype=np.uint8)
    image[:80] = 180
    small, _ = crop(image, [199.5, 199.5], 160, 160)
    large, _ = crop(image, [199.5, 199.5], 320, 320)
    assert diagnostics(small, config)["near_black"] and diagnostics(small, config)["low_std"]
    assert diagnostics(large, config)["std"] > diagnostics(small, config)["std"]
    assert diagnostics(np.full((160, 160), 80, dtype=np.uint8), config)["low_std"]


def test_group_split_disjoint_reproducible_and_duplicate_hash_block():
    config = TrainingConfig(folds=2).model_dump()
    rows = [
        {
            "pair_id": str(i),
            "group_key": str(i // 2),
            **{k: str(i) for k in ["ref_hash", "query_hash", "ref_original_hash", "query_original_hash"]},
        }
        for i in range(8)
    ]
    split = group_split(rows, config)
    assert set(split["train_groups"]).isdisjoint(split["validation_groups"])
    assert group_split(rows, {**config, "crop_mode": "adaptive"}) == split
    for row in rows:
        row["ref_hash"] = "shared"
    with pytest.raises(ValueError, match="hash"):
        group_split(rows, config)


def test_evaluation_zero_and_three_four_five():
    rows = [
        {"error": float(np.linalg.norm(np.subtract(a, b))), "pattern_type": p}
        for a, b, p in [([2, 3], [2, 3], "A"), ([3, 4], [0, 0], "B")]
    ]
    scores = metrics(rows)
    assert scores["A"]["median_error"] == 0 and scores["B"]["median_error"] == 5
    assert scores["Overall"]["acc@5"] == 1 and scores["unknown"]["acc@5"] is None


@pytest.fixture
def training_client(tmp_path):
    root = tmp_path / "Dada"
    rng = np.random.default_rng(123)
    for i in range(4):
        folder = root / f"pair_{i}"
        folder.mkdir(parents=True)
        for role in ["REF", "query"]:
            pixels = rng.integers(0, 90, (192, 224), dtype=np.uint8)
            pixels[70 + i : 100 + i, 85:115] = 190
            Image.fromarray(pixels).save(folder / f"{role}.png")
    app = create_app(tmp_path / "state")
    with TestClient(app) as client:
        pid = client.post("/api/projects", json={"name": "Training fixture"}).json()["id"]
        client.post(f"/api/projects/{pid}/import", json={"root_directory": str(root)})
        pairs = client.get(f"/api/projects/{pid}/pairs").json()
        for i, p in enumerate(pairs):
            response = client.put(
                f"/api/pairs/{p['id']}",
                json={
                    "revision": p["revision"],
                    "gt_x": 100,
                    "gt_y": 85,
                    "group_key": f"capture-{i}",
                    "pattern_type": "A" if i % 2 else "B",
                },
            )
            p = response.json()
            response = client.put(
                f"/api/pairs/{p['id']}/reference-annotation",
                json={"revision": p["revision"], "image_hash": p["reference"]["file_hash"], "box": [60, 45, 140, 125]},
            )
            assert response.status_code == 200, response.text
        version = client.post(f"/api/projects/{pid}/versions", json={"description": "training snapshot"}).json()
        yield client, pid, version, app.state.experiments.root
    app.state.engine.dispose()


def test_manifest_frozen_after_live_edit_and_new_version(training_client):
    client, pid, version, root = training_client
    body = {"version_id": version["id"], "config": {"folds": 2, "device": "cpu"}}
    result = client.post("/api/training/prepare", json=body)
    assert result.status_code == 201, result.text
    exp = result.json()
    path = root / exp["id"]
    before = (path / "dataset_manifest.json").read_bytes()
    pair = client.get(f"/api/projects/{pid}/pairs").json()[0]
    client.put(
        f"/api/pairs/{pair['id']}",
        json={"revision": pair["revision"], "gt_x": 90, "gt_y": 80, "group_key": "new-group", "pattern_type": "B"},
    )
    client.post(f"/api/projects/{pid}/versions", json={"description": "edited"})
    assert (path / "dataset_manifest.json").read_bytes() == before
    original = Path(pair["reference"]["file_path"])
    original.write_bytes(b"changed")
    row = exp["manifest"]["pairs"][0]
    assert Path(row["ref_path"]).is_file() and Image.open(row["ref_path"]).size == (224, 192)
    assert client.post("/api/training/prepare", json=body).status_code == 422


def test_reference_annotation_revision_and_bounds(training_client):
    client, pid, _, _ = training_client
    p = client.get(f"/api/projects/{pid}/pairs").json()[0]
    body = {"revision": p["revision"], "image_hash": p["reference"]["file_hash"], "box": [10, 10, 90, 90]}
    path = f"/api/pairs/{p['id']}/reference-annotation"
    assert client.put(path, json={**body, "box": [0, 0, 999, 999]}).status_code == 422
    after = client.put(path, json=body).json()
    assert after["reference_annotation"]["center"] == [50, 50]
    assert after["gt_x"] == p["gt_x"] and after["gt_y"] == p["gt_y"]
    assert client.put(path, json=body).status_code == 409


@pytest.mark.parametrize("invalid", ["missing_roi", "nonmanual_gt"])
def test_training_blocks_missing_roi_and_nonmanual_supervision(training_client, tmp_path, invalid):
    client, pid, version, _ = training_client
    snapshot = client.get(f"/api/versions/{version['id']}/manifest").json()
    if invalid == "missing_roi":
        snapshot["pairs"][0]["reference_annotation"] = None
    else:
        snapshot["pairs"][0]["gt_source"] = "legacy_cross"
    with pytest.raises(ValueError, match="ROI|수동 Query GT"):
        prepare(
            SimpleNamespace(manifest=snapshot, id=version["id"], number=1, project_id=pid),
            TrainingConfig(folds=2).model_dump(),
            tmp_path / "rejected",
        )


def wait_job(client, experiment_id, timeout=60):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        detail = client.get(f"/api/experiments/{experiment_id}").json()
        if detail["status"] in {"completed", "failed", "stopped"}:
            return detail
        time.sleep(0.1)
    raise AssertionError("Training timed out")


@pytest.mark.parametrize("mode", ["fixed_160", "fixed_256", "fixed_320", "adaptive"])
def test_real_cpu_training_each_crop_mode(training_client, monkeypatch, mode):
    python = os.getenv("ALIGNFAIL_TEST_TRAINING_PYTHON")
    if not python:
        pytest.skip("Set ALIGNFAIL_TEST_TRAINING_PYTHON for real PyTorch integration")
    monkeypatch.setenv("ALIGNFAIL_TRAINING_PYTHON", python)
    client, _, version, root = training_client
    result = client.post(
        "/api/training/prepare",
        json={
            "version_id": version["id"],
            "config": {"folds": 2, "device": "cpu", "epochs": 1, "embedding_dim": 16, "crop_mode": mode},
        },
    )
    assert result.status_code == 201, result.text
    experiment = result.json()["id"]
    assert client.post(f"/api/experiments/{experiment}/start").status_code == 200
    assert client.post(f"/api/experiments/{experiment}/start").status_code == 409
    finished = wait_job(client, experiment)
    assert finished["status"] == "completed", finished.get("log")
    assert len(finished["history"]) == 1 and finished["metrics"]["Overall"]["count"] == 2
    assert len(finished["predictions"]) == 2 and (root / experiment / "best.pt").stat().st_size > 1000
    assert all(0 <= p["prediction"][0] < 224 and 0 <= p["prediction"][1] < 192 for p in finished["predictions"])
    assert (
        client.get(
            f"/api/experiments/{experiment}/files/heatmaps/{finished['predictions'][0]['pair_id']}.png"
        ).status_code
        == 200
    )


def test_cpu_stop_and_tamper_failure(training_client, monkeypatch):
    python = os.getenv("ALIGNFAIL_TEST_TRAINING_PYTHON")
    if not python:
        pytest.skip("Set ALIGNFAIL_TEST_TRAINING_PYTHON for real PyTorch integration")
    monkeypatch.setenv("ALIGNFAIL_TRAINING_PYTHON", python)
    client, _, version, root = training_client
    body = {"version_id": version["id"], "config": {"folds": 2, "device": "cpu", "epochs": 1000, "embedding_dim": 16}}
    first = client.post("/api/training/prepare", json=body).json()["id"]
    client.post(f"/api/experiments/{first}/start")
    deadline = time.monotonic() + 30
    while not (root / first / "last.pt").exists() and time.monotonic() < deadline:
        time.sleep(0.1)
    assert (root / first / "last.pt").exists()
    queued = client.post("/api/training/prepare", json=body).json()["id"]
    client.post(f"/api/experiments/{queued}/start")
    assert client.get(f"/api/experiments/{queued}").json()["status"] == "queued"
    client.post(f"/api/experiments/{queued}/stop")
    assert client.get(f"/api/experiments/{queued}").json()["status"] == "stopped"
    assert not (root / queued / "last.pt").exists()
    client.post(f"/api/experiments/{first}/stop")
    assert wait_job(client, first)["status"] == "stopped"
    assert (root / first / "last.pt").is_file()
    second = client.post("/api/training/prepare", json=body).json()["id"]
    (root / second / "config.json").write_text("{}")
    client.post(f"/api/experiments/{second}/start")
    failed = wait_job(client, second)
    assert failed["status"] == "failed" and "integrity" in failed["log"]


def test_dense_prediction_grid_matches_raw_heatmap_coordinates():
    python = os.getenv("ALIGNFAIL_TEST_TRAINING_PYTHON")
    if not python:
        pytest.skip("Set ALIGNFAIL_TEST_TRAINING_PYTHON for real PyTorch integration")
    script = """
import numpy as np
import torch
from training.model import MetricPatch
class KnownFeatures(torch.nn.Module):
    def forward(self,x):
        x=torch.nn.functional.avg_pool2d(x,4)
        return torch.cat([x,1-x],dim=1)
model=MetricPatch(16)
model.encoder=KnownFeatures()
query=np.zeros((192,224),dtype=np.uint8)
query[16:176,32:192]=255
reference=np.full((160,160),255,dtype=np.uint8)
point,score,heat=model.predict(reference,query,160,160,'cpu')
assert point==[112.,96.], point
y,x=np.unravel_index(heat.argmax(),heat.shape)
assert [x,y]==[112,96], (x,y)
assert heat.shape==query.shape
"""
    result = subprocess.run([python, "-c", script], capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, result.stdout + result.stderr
