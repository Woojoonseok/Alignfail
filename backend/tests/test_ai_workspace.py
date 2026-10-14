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
    assert crop.shape == (45, 45)
    assert crop.max() == 0


def test_manual_gt_publishes_incoming_into_class_folder_without_moving_original(tmp_path):
    folder = tmp_path / "incoming"
    original = folder / "unmarked.png"
    save_image(original, 99)
    original_bytes = original.read_bytes()
    app = create_app(tmp_path / "state")
    with TestClient(app) as client:
        project = client.post("/api/projects", json={"name": "Publish workflow"}).json()
        pid = project["id"]
        assert client.post(f"/api/projects/{pid}/ai/import/incoming",
                           json={"root_directory": str(folder)}).status_code == 200
        pair = client.get(f"/api/projects/{pid}/pairs").json()[0]
        updated = client.put(f"/api/pairs/{pair['id']}", json={
            "revision": pair["revision"], "gt_x": 45.0, "gt_y": 60.0, "class_label": "Class_A",
        })
        assert updated.status_code == 200, updated.text
        current = updated.json()
        assert current["gt_source"] == "manual"
        req = {"pair_id": pair["id"], "revision": current["revision"],
               "class_label": "Class_A"}
        published = client.post(f"/api/projects/{pid}/ai/publish", json=req)
        assert published.status_code == 200, published.text
        item = published.json()
        destination = Path(item["file_path"])
        assert destination.is_file() and destination.parent.name == "Class_A"
        assert original.read_bytes() == original_bytes
        assert destination.read_bytes() == original_bytes
        ledger = tmp_path / "state" / "ai_workspace" / pid / "publish_ledger.json"
        assert ledger.exists()
        assert client.post(f"/api/projects/{pid}/ai/publish", json=req).status_code == 409
    app.state.engine.dispose()


def test_test_pair_cannot_be_published_as_train(tmp_path):
    case = tmp_path / "heldout" / "case_1"
    save_image(case / "a_REF.png", 7)
    save_image(case / "a_FAIL.png", 8)
    app = create_app(tmp_path / "state")
    with TestClient(app) as client:
        pid = client.post("/api/projects", json={"name": "Held-out"}).json()["id"]
        client.post(f"/api/projects/{pid}/ai/import/test",
                    json={"root_directory": str(case.parent)})
        pair = client.get(f"/api/projects/{pid}/pairs").json()[0]
        response = client.post(f"/api/projects/{pid}/ai/publish", json={
            "pair_id": pair["id"], "revision": pair["revision"], "class_label": "Class_A"})
        assert response.status_code == 422
        assert not (tmp_path / "state" / "ai_workspace" / pid / "curated").exists()
    app.state.engine.dispose()
