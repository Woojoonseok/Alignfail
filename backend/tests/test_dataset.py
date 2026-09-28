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
    updated = create_app(state)
    with TestClient(updated) as client:
        assert pairs(client, pid)[0] == first
        assert client.get("/api/projects").json()[0]["data_directories"] == [str(root.resolve())]
        assert upload_images(client, pid, ["more/query.png"]).status_code == 200
        assert next(p for p in pairs(client, pid) if p["id"] == first["id"]) == first
        assert client.post(f"/api/projects/{pid}/import", json={"root_directory": str(root)}).status_code == 200
        assert next(p for p in pairs(client, pid) if p["id"] == first["id"])["gt_x"] == 10
    updated.state.engine.dispose()


def test_upload_group_folders_become_classes_for_images_and_pairs(client):
    pid = client.post("/api/projects", json={"name": "Group classes"}).json()["id"]
    response = upload_images(
        client,
        pid,
        [
            "dataset/Group_001/a.png",
            "dataset/Group_001/deeper/b.png",
            "dataset/Group_002/pair/REF.png",
            "dataset/Group_002/pair/query.png",
            "dataset/Group_001/Group_003/c.png",
            "dataset/ordinary/Group_004.png",
            "dataset/Group_/d.png",
        ],
    )
    assert response.status_code == 200, response.text
    rows = {p["folder"]: p for p in pairs(client, pid)}
    assert rows["Group_001/a.png"]["class_label"] == "Group_001"
    assert rows["Group_001/deeper/b.png"]["class_label"] == "Group_001"
    assert rows["Group_002/pair"]["class_label"] == "Group_002"
    assert rows["Group_002/pair"]["reference"] is not None
    assert rows["Group_001/Group_003/c.png"]["class_label"] == "Group_003"
    assert rows["ordinary/Group_004.png"]["class_label"] == ""
    assert rows["Group_/d.png"]["class_label"] == ""
    assert all(p["group_key"] == "" for p in rows.values())
    summary = client.get(f"/api/projects/{pid}/classes").json()
    assert {c["class_label"]: c["count"] for c in summary["classes"]} == {
        "Group_001": 2,
        "Group_002": 1,
        "Group_003": 1,
    }
    assert summary["unassigned"] == 2


@pytest.mark.parametrize("enabled", [True, False])
def test_upload_selected_group_root_and_class_option(client, enabled):
    pid = client.post("/api/projects", json={"name": "Group classes"}).json()["id"]
    for _ in range(2):
        response = upload_images(client, pid, ["gRoUp_007/a.png"], group_folders_as_classes=enabled)
        assert response.status_code == 200, response.text
    rows = pairs(client, pid)
    assert len(rows) == 2
    assert all(p["class_label"] == ("gRoUp_007" if enabled else "") for p in rows)
    summary = client.get(f"/api/projects/{pid}/classes").json()
    assert len(summary["classes"]) == (1 if enabled else 0)
    if enabled:
        assert summary["classes"][0]["count"] == 2


def test_group_rescan_fills_unclassified_preserving_existing_class_gt_and_group(client, tmp_path):
    root = tmp_path / "dataset"
    make_pair(root / "Group_001", "pair_a")
    make_pair(root / "Group_002", "pair_b")
    pid = client.post("/api/projects", json={"name": "Group classes"}).json()["id"]
    response = client.post(
        f"/api/projects/{pid}/import",
        json={
            "root_directory": str(root),
            "group_folders_as_classes": False,
        },
    )
    assert response.status_code == 200
    first, second = pairs(client, pid)
    assert first["class_label"] == second["class_label"] == ""
    first = save(client, first, class_label="Reviewed", gt_x=4, gt_y=5, group_key="capture-1").json()
    second = save(client, second, gt_x=6, gt_y=7, group_key="capture-2").json()
    response = client.post(f"/api/projects/{pid}/import", json={"root_directory": str(root)})
    assert response.status_code == 200
    after = {p["id"]: p for p in pairs(client, pid)}
    assert after[first["id"]]["class_label"] == "Reviewed"
    assert after[second["id"]]["class_label"] == "Group_002"
    for before in (first, second):
        for key in ("gt_x", "gt_y", "gt_source", "group_key"):
            assert after[before["id"]][key] == before[key]
        assert len(client.get(f"/api/pairs/{before['id']}/history").json()) == 1
    client.post(
        f"/api/projects/{pid}/import",
        json={
            "root_directory": str(root),
            "group_folders_as_classes": False,
        },
    )
    assert [p["class_label"] for p in pairs(client, pid)] == ["Reviewed", "Group_002"]


def test_group_class_does_not_use_ancestors_outside_selected_root(client, tmp_path):
    root = tmp_path / "Group_Outside" / "selected"
    make_pair(root)
    pid = project(client, root)
    assert pairs(client, pid)[0]["class_label"] == ""


@pytest.mark.parametrize(
    "group_root", ["Group", "group", "dataset/Group", "Group (1)", "dataset/Group (2)", "gRoUp(3)", "Group ( 4 )"]
)
def test_group_container_class_covers_mixed_pair_and_image_folders(client, group_root):
    pid = client.post("/api/projects", json={"name": "Mixed Group"}).json()["id"]
    response = upload_images(
        client,
        pid,
        [
            f"{group_root}/폴더123123/이미지.png",
            f"{group_root}/폴더123123/이미지_REF.png",
            f"{group_root}/폴더2/이미지1.png",
            f"{group_root}/폴더2/이미지2.png",
            f"{group_root}/폴더3/deep/이미지3.png",
        ],
    )
    assert response.status_code == 200, response.text
    assert response.json()["new_pairs"] == 4
    assert response.json()["invalid_pairs"] == 0
    rows = pairs(client, pid)
    label = group_root.split("/")[-1]
    assert {row["class_label"] for row in rows} == {label}
    assert sum(row["reference"] is not None for row in rows) == 1
    assert all(row["query"] is not None for row in rows)
    summary = client.get(f"/api/projects/{pid}/classes").json()
    assert [(c["class_label"], c["count"]) for c in summary["classes"]] == [(label, 4)]
    assert summary["unassigned"] == 0


@pytest.mark.parametrize("group_name", ["Group", "Group (1)"])
def test_plain_group_rescan_fills_class_without_changing_pair_or_gt(client, tmp_path, group_name):
    root = tmp_path / group_name
    make_pair(root, "폴더123123")
    pid = client.post("/api/projects", json={"name": "Group rescan"}).json()["id"]
    response = client.post(
        f"/api/projects/{pid}/import",
        json={
            "root_directory": str(root),
            "group_folders_as_classes": False,
        },
    )
    assert response.status_code == 200
    first = save(client, pairs(client, pid)[0], gt_x=10, gt_y=12).json()
    assert first["class_label"] == ""
    response = client.post(f"/api/projects/{pid}/import", json={"root_directory": str(root)})
    assert response.status_code == 200
    after = pairs(client, pid)[0]
    assert after["id"] == first["id"]
    assert after["class_label"] == group_name
    assert (after["gt_x"], after["gt_y"]) == (10, 12)


def test_numbered_group_upload_keeps_sibling_classes_separate(client):
    pid = client.post("/api/projects", json={"name": "Numbered Groups"}).json()["id"]
    response = upload_images(
        client,
        pid,
        [
            "dataset/Group (1)/folder123/이미지.png",
            "dataset/Group (1)/folder123/이미지_REF.png",
            "dataset/Group (1)/more/a.png",
            "dataset/Group (1)/more/b.png",
            "dataset/Group (2)/a.png",
            "dataset/Group (2)/b.png",
            "dataset/NotGroup (3)/c.png",
            "dataset/Group (4) backup/d.png",
        ],
    )
    assert response.status_code == 200, response.text
    assert response.json()["invalid_pairs"] == 0
    summary = client.get(f"/api/projects/{pid}/classes").json()
    assert {c["class_label"]: c["count"] for c in summary["classes"]} == {"Group (1)": 3, "Group (2)": 2}
    assert summary["unassigned"] == 2
