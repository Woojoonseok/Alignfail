"""Feature contract tests for AI Dataset Workspace; do not download an actual VLM."""
from pathlib import Path

import cv2
import numpy as np
from fastapi.testclient import TestClient
from PIL import Image

from app.main import create_app
from ai_workspace.worker import ref_patch, spatial_match, target_patch


def save_image(path: Path, seed: int):
    path.parent.mkdir(parents=True, exist_ok=True)
    rng = np.random.default_rng(seed)
    Image.fromarray(rng.integers(30, 210, size=(100, 100), dtype=np.uint8)).save(path)


def test_test_pair_import_is_paired_isolated_and_repeatable(tmp_path):
    case = tmp_path / "test" / "case_A"
    save_image(case / "case_REF.png", 1)
    save_image(case / "case_FAIL.png", 2)
    app = create_app(tmp_path / "state")
    with TestClient(app) as client:
        project = client.post("/api/projects", json={"name": "AI test"}).json()
        url = f"/api/projects/{project['id']}/ai/import/test"
        response = client.post(url, json={"root_directory": str(case.parent)})
        assert response.status_code == 200, response.text
        assert response.json()["registered"] == 1
        pairs = client.get(f"/api/projects/{project['id']}/pairs").json()
        assert len(pairs) == 1
        pair = pairs[0]
        assert pair["dataset_split"] == "test"
        assert pair["sample_role"] == "pair"
        assert pair["reference"]["file_name"] == "case_REF.png"
        assert pair["query"]["file_name"] == "case_FAIL.png"
        assert pair["gt_x"] is None and pair["gt_source"] == "none"
        assert client.post(url, json={"root_directory": str(case.parent)}).status_code == 200
        assert len(client.get(f"/api/projects/{project['id']}/pairs").json()) == 1
        overview = client.get(f"/api/projects/{project['id']}/ai/overview").json()
        assert overview["test_pairs"] == 1
    app.state.engine.dispose()


def test_invalid_test_pair_does_not_write_half_pair(tmp_path):
    test = tmp_path / "test" / "incomplete"
    save_image(test / "only_REF.png", 2)
    app = create_app(tmp_path / "state")
    with TestClient(app) as client:
        project = client.post("/api/projects", json={"name": "AI test"}).json()
        response = client.post(f"/api/projects/{project['id']}/ai/import/test",
                               json={"root_directory": str(test.parent)})
        assert response.status_code == 422
        assert client.get(f"/api/projects/{project['id']}/pairs").json() == []
    app.state.engine.dispose()


def test_incoming_registration_remains_unlabelled(tmp_path):
    folder = tmp_path / "incoming"
    save_image(folder / "new.png", 5)
    app = create_app(tmp_path / "state")
    with TestClient(app) as client:
        project = client.post("/api/projects", json={"name": "AI test"}).json()
        response = client.post(f"/api/projects/{project['id']}/ai/import/incoming",
                               json={"root_directory": str(folder)})
        assert response.status_code == 200, response.text
        pair = client.get(f"/api/projects/{project['id']}/pairs").json()[0]
        assert pair["dataset_split"] == "train"
        assert pair["sample_role"] == "reference"
        assert pair["class_label"] == ""
        assert pair["gt_source"] == "none"
        assert folder.joinpath("new.png").exists()
    app.state.engine.dispose()


def test_spatial_peak_returns_original_query_coordinate():
    rng = np.random.default_rng(42)
    template = rng.integers(10, 200, (100, 100), dtype=np.uint8)
    center = (55, 45)
    patch, offset = target_patch(template, *center, 32)
    query = np.zeros((130, 140), dtype=np.uint8)
    query[40:72, 60:92] = patch
    output = spatial_match(patch, query, offset)
    assert output["status"] == "candidate"
    assert output["x"] == 76 and output["y"] == 56
    assert output["score"] > 0.99


def test_spatial_flat_template_has_no_prediction():
    patch = np.ones((20, 20), dtype=np.uint8) * 127
    result = spatial_match(patch, np.zeros((80, 80), dtype=np.uint8), (10, 10))
    assert result["status"] == "flat_template"
    assert result["x"] is None


def test_ref_roi_excludes_white_rectangle_border():
    img = np.zeros((100, 100), dtype=np.uint8)
    cv2.rectangle(img, (20, 25), (70, 75), 255, 1)
    crop = ref_patch(img, (20, 25, 70, 75))
    assert crop.shape == (46, 46)
    assert crop.max() == 0
