import io
import shutil

import pytest
from fastapi.testclient import TestClient
from PIL import Image

from app.main import create_app


@pytest.fixture
def client(tmp_path):
    app = create_app(tmp_path / "state")
    with TestClient(app) as client:
        yield client
    app.state.engine.dispose()


def make_pair(root, name="pair_001", ref_name="sample_rEf.png", query_name="query.bmp", color=70):
    folder = root / name
    folder.mkdir(parents=True)
    Image.new("RGB", (64, 48), (color, 30, 40)).save(folder / ref_name)
    Image.new("RGB", (120, 80), (color, 80, 90)).save(folder / query_name)
    return folder


def project(client, root):
    result = client.post("/api/projects", json={"name": "검증 프로젝트", "description": "test"})
    assert result.status_code == 201, result.text
    pid = result.json()["id"]
    result = client.post(f"/api/projects/{pid}/import", json={"root_directory": str(root)})
    assert result.status_code == 200, result.text
    return pid


def pairs(client, pid):
    return client.get(f"/api/projects/{pid}/pairs").json()


def save(client, pair, **changes):
    payload = {k: pair[k] for k in ["revision", "gt_x", "gt_y", "group_key", "tier", "notes", "enabled", "exclude_reason"]}
    payload.update(changes)
    return client.put(f"/api/pairs/{pair['id']}", json=payload)


def test_import_case_insensitive_and_idempotent(client, tmp_path):
    root = tmp_path / "Dada"
    folder = make_pair(root)
    (folder / "notes.json").write_text("{}")
    pid = project(client, root)
    first = pairs(client, pid)[0]
    assert first["reference"]["file_name"] == "sample_rEf.png"
    assert first["query"]["width"] == 120
    assert first["gt_x"] is None
    assert first["group_key"] == ""
    client.post(f"/api/projects/{pid}/import", json={"root_directory": str(root)})
    result = pairs(client, pid)
    assert len(result) == 1
    assert result[0]["id"] == first["id"]
    assert result[0]["reference"]["id"] == first["reference"]["id"]


def test_manual_gt_history_metadata_and_optimistic_lock(client, tmp_path):
    root = tmp_path / "Dada"
    make_pair(root)
    pid = project(client, root)
    first = pairs(client, pid)[0]
    result = save(client, first, gt_x=119.5, gt_y=79, group_key=" capture-1 ")
    assert result.status_code == 200, result.text
    updated = result.json()
    assert updated["gt_source"] == "manual"
    assert updated["group_key"] == "capture-1"
    assert save(client, first, gt_x=1, gt_y=1).status_code == 409
    assert save(client, updated, notes="반복 패턴").status_code == 200
    history = client.get(f"/api/pairs/{first['id']}/history").json()
    assert len(history) == 1
    assert history[0]["before"]["x"] is None
    assert history[0]["after"]["x"] == 119.5


@pytest.mark.parametrize("coords", [{"gt_x": 120, "gt_y": 0}, {"gt_x": 0, "gt_y": 80}, {"gt_x": -1, "gt_y": 0}, {"gt_x": 1, "gt_y": None}])
def test_gt_rejects_out_of_bounds_and_partial(client, tmp_path, coords):
    root = tmp_path / "Dada"
    make_pair(root)
    pid = project(client, root)
    assert save(client, pairs(client, pid)[0], **coords).status_code == 422


def test_changed_file_blocks_save_and_snapshot_rescan_clears_gt(client, tmp_path):
    root = tmp_path / "Dada"
    folder = make_pair(root)
    pid = project(client, root)
    pair = save(client, pairs(client, pid)[0], gt_x=23, gt_y=40).json()
    Image.new("RGB", (120, 80), "white").save(folder / "query.bmp")
    assert save(client, pair, gt_x=24).status_code == 409
    assert client.get(f"/api/images/{pair['query']['id']}").status_code == 409
    audit = client.post(f"/api/projects/{pid}/audit").json()
    assert not audit["passed"]
    assert "FILE_CHANGED" in [i["code"] for i in audit["issues"]]
    assert client.post(f"/api/projects/{pid}/versions", json={"description": "bad"}).status_code == 422
    client.post(f"/api/projects/{pid}/import", json={"root_directory": str(root)})
    after = pairs(client, pid)[0]
    assert after["gt_x"] is None
    assert after["gt_source"] == "none"
    assert len(client.get(f"/api/pairs/{pair['id']}/history").json()) == 2


def test_unchanged_rescan_keeps_annotation(client, tmp_path):
    root = tmp_path / "Dada"
    make_pair(root)
    pid = project(client, root)
    save(client, pairs(client, pid)[0], gt_x=42, gt_y=31)
    client.post(f"/api/projects/{pid}/import", json={"root_directory": str(root)})
    assert pairs(client, pid)[0]["gt_x"] == 42


def test_ambiguous_files_never_guessed(client, tmp_path):
    root = tmp_path / "Dada"
    folder = make_pair(root)
    Image.new("RGB", (20, 20)).save(folder / "another_query.png")
    pid = project(client, root)
    pair = pairs(client, pid)[0]
    assert pair["query"] is None
    assert "2장" in pair["import_issues"][0]
    assert save(client, pair, gt_x=2, gt_y=3).status_code == 422
    assert client.post(f"/api/projects/{pid}/audit").json()["errors"] > 0


def test_duplicate_detection_and_exclusion(client, tmp_path):
    root = tmp_path / "Dada"
    make_pair(root, "a")
    make_pair(root, "b")
    pid = project(client, root)
    for pair in pairs(client, pid):
        save(client, pair, gt_x=40, gt_y=30, group_key="same-capture")
    audit = client.post(f"/api/projects/{pid}/audit").json()
    assert audit["passed"]
    assert len(audit["duplicates"]) == 2
    pair = pairs(client, pid)[0]
    assert save(client, pair, enabled=False).status_code == 422
    save(client, pair, enabled=False, exclude_reason="중복", gt_x=None, gt_y=None)
    audit = client.post(f"/api/projects/{pid}/audit").json()
    assert audit["passed"] and audit["enabled_count"] == 1
    assert len(audit["duplicates"]) == 0


def test_versions_are_immutable_and_diff_tracks_gt(client, tmp_path):
    root = tmp_path / "Dada"
    make_pair(root)
    pid = project(client, root)
    assert client.post(f"/api/projects/{pid}/versions", json={"description": "missing gt"}).status_code == 422
    pair = save(client, pairs(client, pid)[0], gt_x=30, gt_y=40, group_key="g1").json()
    first = client.post(f"/api/projects/{pid}/versions", json={"description": "initial"}).json()
    save(client, pair, gt_x=35)
    second = client.post(f"/api/projects/{pid}/versions", json={"description": "corrected"}).json()
    manifest = client.get(f"/api/versions/{first['id']}/manifest").json()
    assert manifest["pairs"][0]["gt_x"] == 30
    assert manifest["pairs"][0]["query"]["file_hash"]
    diff = client.get(f"/api/versions/{second['id']}/diff/{first['id']}").json()
    assert diff["changes"][0]["fields"] == ["gt_x"]
    exported = client.get(f"/api/projects/{pid}/annotations").json()
    assert exported["pairs"][0]["gt_x"] == 35


def test_missing_folder_and_broken_file(client, tmp_path):
    root = tmp_path / "Dada"
    folder = make_pair(root)
    pid = project(client, root)
    (folder / "query.bmp").write_bytes(b"not an image")
    audit = client.post(f"/api/projects/{pid}/audit").json()
    assert any(i["code"] == "BROKEN_FILE" for i in audit["issues"])
    shutil.rmtree(folder)
    client.post(f"/api/projects/{pid}/import", json={"root_directory": str(root)})
    assert "폴더가 없습니다" in pairs(client, pid)[0]["import_issues"][0]


def test_image_conversion_and_no_exif_rotation(client, tmp_path):
    root = tmp_path / "Dada"
    folder = make_pair(root)
    (folder / "query.bmp").unlink()
    img = Image.new("I;16", (120, 80), 2048)
    img.save(folder / "query.tiff")
    pid = project(client, root)
    query = pairs(client, pid)[0]["query"]
    result = client.get(f"/api/images/{query['id']}")
    assert result.status_code == 200
    assert Image.open(io.BytesIO(result.content)).size == (120, 80)
    result = client.get(f"/api/images/{query['id']}?size=60")
    assert Image.open(io.BytesIO(result.content)).size == (60, 40)


def test_project_delete_keeps_original_images(client, tmp_path):
    root = tmp_path / "Dada"
    folder = make_pair(root)
    pid = project(client, root)
    pair = save(client, pairs(client, pid)[0], gt_x=10, gt_y=10).json()
    version = client.post(f"/api/projects/{pid}/versions", json={"description": "snapshot"}).json()
    assert client.patch(f"/api/projects/{pid}", json={"name": "Renamed"}).status_code == 200
    assert client.delete(f"/api/projects/{pid}").status_code == 204
    assert (folder / "query.bmp").is_file()
    assert client.get(f"/api/pairs/{pair['id']}/history").status_code == 404
    assert client.get(f"/api/versions/{version['id']}/manifest").status_code == 404
    assert client.get("/api/projects").json() == []


def test_invalid_paths_and_external_origin(client, tmp_path):
    pid = client.post("/api/projects", json={"name": "A"}).json()["id"]
    assert client.post(f"/api/projects/{pid}/import", json={"root_directory": str(tmp_path / 'missing')}).status_code == 422
    assert client.post("/api/projects", json={"name": " "}).status_code == 422
    assert client.post("/api/projects", json={"name": "B"}, headers={"origin": "https://unrelated.example"}).status_code == 403
    assert client.post("/api/projects", json={"name": "B"}, headers={"origin": "http://localhost:8000"}).status_code == 201


def test_non_finite_gt_rejected_cleanly(client, tmp_path):
    root = tmp_path / "Dada"
    make_pair(root)
    pid = project(client, root)
    pair = pairs(client, pid)[0]
    result = client.put(f"/api/pairs/{pair['id']}", content='{"revision":2,"gt_x":1e400,"gt_y":5}', headers={"Content-Type": "application/json"})
    assert result.status_code == 422
    assert result.json()["detail"][0]["type"] == "finite_number"


def test_image_endpoint_rejects_unknown_host(client):
    assert client.get("/api/projects", headers={"host": "unrelated.example"}).status_code == 400
