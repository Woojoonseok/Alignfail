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
    payload = {
        k: pair[k] for k in ["revision", "gt_x", "gt_y", "group_key", "tier", "notes", "enabled", "exclude_reason"]
    }
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


@pytest.mark.parametrize(
    "coords", [{"gt_x": 120, "gt_y": 0}, {"gt_x": 0, "gt_y": 80}, {"gt_x": -1, "gt_y": 0}, {"gt_x": 1, "gt_y": None}]
)
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
    assert (
        client.post(f"/api/projects/{pid}/import", json={"root_directory": str(tmp_path / "missing")}).status_code
        == 422
    )
    assert client.post("/api/projects", json={"name": " "}).status_code == 422
    assert (
        client.post("/api/projects", json={"name": "B"}, headers={"origin": "https://unrelated.example"}).status_code
        == 403
    )
    assert (
        client.post("/api/projects", json={"name": "B"}, headers={"origin": "http://localhost:8000"}).status_code == 201
    )


def test_non_finite_gt_rejected_cleanly(client, tmp_path):
    root = tmp_path / "Dada"
    make_pair(root)
    pid = project(client, root)
    pair = pairs(client, pid)[0]
    result = client.put(
        f"/api/pairs/{pair['id']}",
        content='{"revision":2,"gt_x":1e400,"gt_y":5}',
        headers={"Content-Type": "application/json"},
    )
    assert result.status_code == 422
    assert result.json()["detail"][0]["type"] == "finite_number"


def test_image_endpoint_rejects_unknown_host(client):
    assert client.get("/api/projects", headers={"host": "unrelated.example"}).status_code == 400


def upload_images(client, pid, names, **options):
    content = io.BytesIO()
    Image.new("RGB", (64, 48), (60, 80, 120)).save(content, format="PNG")
    return client.post(
        f"/api/projects/{pid}/upload",
        files=[("files", (name, content.getvalue(), "image/png")) for name in names],
        params=options,
    )


def test_browser_folder_upload_reads_nested_images_and_pairs(client):
    pid = client.post("/api/projects", json={"name": "Uploads"}).json()["id"]
    response = upload_images(
        client,
        pid,
        [
            "사진/s_OM.png",
            "사진/deep/e_SEM.png",
            "사진/deep/second.png",
            "사진/pair/REF.png",
            "사진/pair/query.png",
        ],
    )
    assert response.status_code == 200, response.text
    assert response.json() == {"new_pairs": 4, "updated_pairs": 0, "images": 5, "invalid_pairs": 0}
    rows = {p["folder"]: p for p in pairs(client, pid)}
    assert set(rows) == {"s_OM.png", "deep/e_SEM.png", "deep/second.png", "pair"}
    assert rows["pair"]["reference"] is not None
    assert rows["deep/second.png"]["reference"] is None
    for row in rows.values():
        assert client.get(f"/api/images/{row['query']['id']}").status_code == 200


def test_upload_appends_same_named_folder_preserving_existing_gt(client, tmp_path):
    root = tmp_path / "original"
    make_pair(root)
    pid = project(client, root)
    first = save(client, pairs(client, pid)[0], gt_x=10, gt_y=12, group_key="capture").json()
    for _ in range(2):
        response = upload_images(client, pid, ["images/query.png"])
        assert response.status_code == 200, response.text
    rows = pairs(client, pid)
    assert len(rows) == 3
    original = next(p for p in rows if p["id"] == first["id"])
    assert original == first
    assert len({p["folder"] for p in rows}) == 3
    assert len(client.get("/api/projects").json()[0]["data_directories"]) == 3
    for p in rows:
        assert client.get(f"/api/images/{p['query']['id']}").status_code == 200
    assert (root / "pair_001" / "query.bmp").is_file()


def test_import_second_source_and_rescan_only_that_source(client, tmp_path):
    root = tmp_path / "first"
    make_pair(root)
    pid = project(client, root)
    first = save(client, pairs(client, pid)[0], gt_x=10, gt_y=12).json()
    other = tmp_path / "second"
    folder = make_pair(other)
    response = client.post(f"/api/projects/{pid}/import", json={"root_directory": str(other)})
    assert response.status_code == 200
    second = next(p for p in pairs(client, pid) if p["id"] != first["id"])
    second = save(client, second, gt_x=2, gt_y=3).json()
    Image.new("RGB", (120, 80), "white").save(folder / "query.bmp")
    client.post(f"/api/projects/{pid}/import", json={"root_directory": str(other)})
    after = {p["id"]: p for p in pairs(client, pid)}
    assert after[first["id"]] == first
    assert after[second["id"]]["gt_x"] is None
    shutil.rmtree(folder)
    client.post(f"/api/projects/{pid}/import", json={"root_directory": str(other)})
    after = {p["id"]: p for p in pairs(client, pid)}
    assert after[first["id"]] == first
    assert after[second["id"]]["import_issues"]


@pytest.mark.parametrize(
    "names",
    [
        ["../escape.png"],
        ["images/../../escape.png"],
        ["/images/a.png"],
        ["C:/images/a.png"],
        ["images/a.png", "images/A.png"],
        ["a/image.png", "b/image.png"],
        ["images/CON.png"],
        ["images/a:b.png"],
    ],
)
def test_upload_rejects_invalid_paths_without_registration(client, names):
    pid = client.post("/api/projects", json={"name": "Uploads"}).json()["id"]
    response = upload_images(client, pid, names)
    assert response.status_code == 422, response.text
    assert pairs(client, pid) == []
    assert client.get("/api/projects").json()[0]["data_directories"] == []
    assert not list((client.app.state.state_dir / "uploads").rglob("*.png"))


def test_upload_single_pair_folder_and_ambiguous_ref(client):
    pid = client.post("/api/projects", json={"name": "Uploads"}).json()["id"]
    result = upload_images(client, pid, ["pair/REF.png", "pair/query.png"])
    assert result.status_code == 200
    row = pairs(client, pid)[0]
    assert row["reference"] is not None and row["query"] is not None
    assert result.json()["new_pairs"] == 1
    result = upload_images(client, pid, ["bad/REF.png", "bad/a.png", "bad/b.png"])
    assert result.status_code == 200 and result.json()["invalid_pairs"] == 1
    assert next(p for p in pairs(client, pid) if p["id"] != row["id"])["query"] is None


def test_upload_no_images_unknown_project_and_external_origin(client):
    pid = client.post("/api/projects", json={"name": "Uploads"}).json()["id"]
    assert upload_images(client, pid, ["folder/notes.txt"]).status_code == 422
    assert upload_images(client, "missing", ["folder/image.png"]).status_code == 404
    response = client.post(f"/api/projects/{pid}/upload", headers={"origin": "https://example.com"})
    assert response.status_code == 403


def test_import_rejects_overlapping_sources_and_blank_path(client, tmp_path):
    root = tmp_path / "images"
    folder = make_pair(root)
    pid = project(client, root)
    for path, status in [(folder, 409), (tmp_path, 409), (" ", 422)]:
        response = client.post(f"/api/projects/{pid}/import", json={"root_directory": str(path)})
        assert response.status_code == status
    assert len(pairs(client, pid)) == 1


def test_ref_removed_on_rescan_keeps_pair_identity(client, tmp_path):
    root = tmp_path / "images"
    folder = make_pair(root)
    pid = project(client, root)
    first = save(client, pairs(client, pid)[0], gt_x=2, gt_y=3).json()
    (folder / "sample_rEf.png").unlink()
    response = client.post(f"/api/projects/{pid}/import", json={"root_directory": str(root)})
    assert response.status_code == 200
    after = pairs(client, pid)
    assert len(after) == 1 and after[0]["id"] == first["id"]
    assert after[0]["gt_x"] == 2 and after[0]["reference"] is None


def test_existing_database_upgrade_preserves_pairs_and_gt(tmp_path):
    import sqlite3

    root = tmp_path / "images"
    make_pair(root)
    state = tmp_path / "legacy-state"
    app = create_app(state)
    with TestClient(app) as client:
        pid = project(client, root)
        first = save(client, pairs(client, pid)[0], gt_x=10, gt_y=12).json()
    app.state.engine.dispose()
    with sqlite3.connect(state / "studio.db") as db:
        db.execute("ALTER TABLE projects DROP COLUMN data_directories")
        db.execute("ALTER TABLE pairs DROP COLUMN source_directory")
        db.execute("ALTER TABLE pairs DROP COLUMN dataset_split")
    updated = create_app(state)
    with TestClient(updated) as client:
        assert pairs(client, pid)[0] == first
        assert client.get("/api/projects").json()[0]["data_directories"] == [str(root.resolve())]
        assert upload_images(client, pid, ["more/query.png"]).status_code == 200
        assert next(p for p in pairs(client, pid) if p["id"] == first["id"]) == first
        assert client.post(f"/api/projects/{pid}/import", json={"root_directory": str(root)}).status_code == 200
        assert next(p for p in pairs(client, pid) if p["id"] == first["id"])["gt_x"] == 10
    updated.state.engine.dispose()


@pytest.mark.parametrize("split", ["train", "test"])
def test_upload_folder_is_one_class_for_all_nested_images_and_pairs(client, split):
    pid = client.post("/api/projects", json={"name": "Folder classes"}).json()["id"]
    response = upload_images(
        client,
        pid,
        [
            "결함A/Group (1)/a.png",
            "결함A/Group_002/b.png",
            "결함A/pair/이미지_REF.png",
            "결함A/pair/이미지.png",
            "결함A/deep/nested/c.png",
        ],
        dataset_split=split,
    )
    assert response.status_code == 200, response.text
    assert response.json()["new_pairs"] == 4 and response.json()["invalid_pairs"] == 0
    rows = pairs(client, pid)
    assert {p["class_label"] for p in rows} == {"결함A"}
    assert {p["dataset_split"] for p in rows} == {split}
    assert all(p["group_key"] == "" for p in rows)
    assert sum(p["reference"] is not None for p in rows) == 1
    summary = client.get(f"/api/projects/{pid}/classes").json()
    assert [(c["class_label"], c["count"]) for c in summary["classes"]] == [("결함A", 4)]
    registered = client.get("/api/projects").json()[0]
    assert registered[f"{split}_count"] == 4


def test_train_and_test_uploads_share_class_name_but_keep_separate_membership(client):
    pid = client.post("/api/projects", json={"name": "Split classes"}).json()["id"]
    for split in ["train", "test"]:
        assert upload_images(client, pid, ["결함A/query.png"], dataset_split=split).status_code == 200
    assert upload_images(client, pid, ["결함B/query.png"], dataset_split="train").status_code == 200
    rows = pairs(client, pid)
    assert {(p["class_label"], p["dataset_split"]) for p in rows} == {
        ("결함A", "train"),
        ("결함A", "test"),
        ("결함B", "train"),
    }
    assert len({p["query"]["file_path"] for p in rows}) == 3
    registered = client.get("/api/projects").json()[0]
    assert (registered["train_count"], registered["test_count"], registered["class_count"]) == (2, 1, 2)
    assert upload_images(client, pid, ["bad/a.png"], dataset_split="invalid").status_code == 422
    assert len(pairs(client, pid)) == 3


def test_source_rescan_preserves_split_class_and_gt_for_new_and_existing_items(client, tmp_path):
    root = tmp_path / "아무폴더"
    make_pair(root, "first")
    pid = client.post("/api/projects", json={"name": "Rescan"}).json()["id"]
    response = client.post(f"/api/projects/{pid}/import", json={"root_directory": str(root), "dataset_split": "test"})
    assert response.status_code == 200
    first = save(client, pairs(client, pid)[0], class_label="Reviewed", gt_x=10, gt_y=12, group_key="capture").json()
    make_pair(root, "second")
    response = client.post(f"/api/projects/{pid}/import", json={"root_directory": str(root)})
    assert response.status_code == 200
    rows = pairs(client, pid)
    assert {p["dataset_split"] for p in rows} == {"test"}
    after = next(p for p in rows if p["id"] == first["id"])
    assert (after["class_label"], after["gt_x"], after["gt_y"], after["group_key"]) == ("Reviewed", 10, 12, "capture")
    assert next(p for p in rows if p["id"] != first["id"])["class_label"] == root.name
    response = client.post(f"/api/projects/{pid}/import", json={"root_directory": str(root), "dataset_split": "train"})
    assert response.status_code == 409
    assert {p["dataset_split"] for p in pairs(client, pid)} == {"test"}


def test_versions_export_split_and_unannotated_test_does_not_block_train(client, tmp_path):
    root = tmp_path / "train-class"
    make_pair(root)
    pid = project(client, root)
    save(client, pairs(client, pid)[0], gt_x=2, gt_y=3, group_key="capture")
    assert upload_images(client, pid, ["test-class/a.png"], dataset_split="test").status_code == 200
    result = client.post(f"/api/projects/{pid}/versions", json={"description": "with held-out test"})
    assert result.status_code == 201, result.text
    manifest = client.get(f"/api/versions/{result.json()['id']}/manifest").json()
    assert {p["dataset_split"] for p in manifest["pairs"]} == {"train", "test"}
    exported = client.get(f"/api/projects/{pid}/annotations").json()
    assert {p["dataset_split"] for p in exported["pairs"]} == {"train", "test"}
    audit = client.post(f"/api/projects/{pid}/audit").json()
    assert audit["passed"]
    assert any(i["code"] == "MISSING_GT" and i["severity"] == "warning" for i in audit["issues"])
