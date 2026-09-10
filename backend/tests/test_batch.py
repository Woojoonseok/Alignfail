import sqlite3

import numpy as np
import pytest
from fastapi.testclient import TestClient

from app.cleaning import png_bytes
from app.grouping import appearance_features, cluster_features
from app.main import create_app
from test_cleaning import cleanup_client, marked_image


def test_auto_cleanup_skip_replace_and_source_guard(cleanup_client):
    client, pid, pair, folder = cleanup_client
    image = pair["reference"]
    original = (folder / "image_REF.png").read_bytes()
    body = {"source_hash": image["file_hash"], "box": True, "cross": False}
    path = f"/api/images/{image['id']}/clean/auto"
    result = client.post(path, json=body)
    assert result.status_code == 200 and result.json()["status"] == "saved"
    first = result.json()["cleanup_id"]
    assert client.post(path, json=body).json()["status"] == "skipped"
    replacement = client.post(path, json={**body, "replace_existing": True}).json()
    assert replacement["status"] == "saved" and replacement["cleanup_id"] != first
    assert client.get(f"/api/cleanups/{first}/image?download=true").status_code == 200
    assert (folder / "image_REF.png").read_bytes() == original
    after = client.get(f"/api/projects/{pid}/pairs").json()[0]
    assert (after["gt_x"], after["gt_y"]) == (70, 60)
    assert client.post(path, json={**body, "box": False}).status_code == 422
    (folder / "image_REF.png").write_bytes(png_bytes(marked_image()))
    assert client.post(path, json=body).status_code == 409


def test_auto_cleanup_no_candidate_does_not_change_revision(cleanup_client):
    client, pid, pair, _ = cleanup_client
    image = pair["query"]  # Contains only a cross, but search only for a box.
    result = client.post(f"/api/images/{image['id']}/clean/auto", json={"source_hash":image["file_hash"], "cross":False})
    assert result.json()["status"] == "skipped"
    after = client.get(f"/api/projects/{pid}/pairs").json()[0]
    assert after["revision"] == pair["revision"] and after["query"]["cleanup"] is None


@pytest.fixture
def batch_client(tmp_path):
    root = tmp_path / "Dada"
    vertical = np.zeros((64,64), dtype=np.uint8)
    vertical[:, 20:35] = 180
    horizontal = vertical.T.copy()
    for index, pixels in enumerate([vertical, vertical, horizontal, horizontal]):
        folder = root / f"pair_{index}"
        folder.mkdir(parents=True)
        for name in ["sample_REF.png", "sample.png"]:
            (folder / name).write_bytes(png_bytes(pixels))
    app = create_app(tmp_path / "state")
    with TestClient(app) as client:
        pid = client.post("/api/projects", json={"name":"Batch test"}).json()["id"]
        client.post(f"/api/projects/{pid}/import", json={"root_directory":str(root)})
        pairs = client.get(f"/api/projects/{pid}/pairs").json()
        yield client, pid, pairs, root
    app.state.engine.dispose()


def test_cluster_proposal_determinism_and_explicit_apply(batch_client):
    client, pid, pairs, _ = batch_client
    body = {"pairs":[{"id":p["id"], "revision":p["revision"]} for p in pairs], "clusters":2}
    path = f"/api/projects/{pid}/clusters/preview"
    result = client.post(path, json=body)
    assert result.status_code == 200, result.text
    proposal = result.json()
    assert client.post(path, json=body).json() == proposal
    labels = [p["cluster"] for p in proposal["assignments"]]
    assert labels[0] == labels[1] and labels[2] == labels[3] and labels[0] != labels[2]
    assert all(p["group_key"] == "" for p in client.get(f"/api/projects/{pid}/pairs").json())
    applied = client.post(f"/api/projects/{pid}/groups/bulk", json={"assignments":[
        {"id":p["id"], "revision":p["revision"], "group_key":f"cluster-{p['cluster']}", "class_label":" pattern "}
        for p in proposal["assignments"]]})
    assert applied.json()["updated"] == 4
    after = client.get(f"/api/projects/{pid}/pairs").json()
    assert all(p["class_label"] == "pattern" and p["gt_x"] is None for p in after)
    assert client.post(path, json=body).status_code == 409


def test_bulk_groups_are_atomic_scoped_and_clearable(batch_client):
    client, pid, pairs, _ = batch_client
    path = f"/api/projects/{pid}/groups/bulk"
    assignments = [{"id":p["id"], "revision":p["revision"], "group_key":"new"} for p in pairs]
    invalid = [{**p} for p in assignments]
    invalid[-1]["revision"] += 1
    assert client.post(path, json={"assignments":invalid}).status_code == 409
    assert all(p["group_key"] == "" for p in client.get(f"/api/projects/{pid}/pairs").json())
    assert client.post(path, json={"assignments":[assignments[0], assignments[0]]}).status_code == 422
    other = client.post("/api/projects", json={"name":"Other"}).json()["id"]
    assert client.post(f"/api/projects/{other}/groups/bulk", json={"assignments":assignments}).status_code == 404
    assert client.post(path, json={"assignments":assignments}).json()["updated"] == 4
    assert client.post(path, json={"assignments":[{**a,"revision":a["revision"]+1,"group_key":""} for a in assignments]}).json()["updated"] == 4


def test_cluster_skips_changed_sources_and_validates_count(batch_client):
    client, pid, pairs, root = batch_client
    body = {"pairs":[{"id":p["id"],"revision":p["revision"]} for p in pairs],"clusters":2}
    path = f"/api/projects/{pid}/clusters/preview"
    assert client.post(path, json={**body,"clusters":5}).status_code == 422
    (root / "pair_0/sample_REF.png").write_bytes(b"changed")
    result = client.post(path, json=body).json()
    assert len(result["skipped"]) == 1 and len(result["assignments"]) == 3


def test_identical_features_stay_together_and_features_are_finite():
    feature = appearance_features(png_bytes(np.zeros((64,64), dtype=np.uint8)))
    assert np.isfinite(feature).all()
    assert cluster_features([feature] * 4, 4) == [1,1,1,1]


def test_cluster_uses_clean_and_skips_tampered_cache(batch_client):
    client, pid, pairs, _ = batch_client
    image = pairs[0]["reference"]
    saved = client.post(f"/api/images/{image['id']}/clean", json={"source_hash":image["file_hash"],
                       "box":{"x0":10,"y0":10,"x1":40,"y1":40}})
    assert saved.status_code == 201
    current = client.get(f"/api/projects/{pid}/pairs").json()
    body = {"pairs":[{"id":p["id"],"revision":p["revision"]} for p in current],"clusters":2}
    proposal = client.post(f"/api/projects/{pid}/clusters/preview", json=body).json()
    assert proposal["assignments"][0]["image_source"] == "clean"
    from pathlib import Path
    Path(current[0]["reference"]["cleanup"]["clean_path"]).write_bytes(b"tampered")
    proposal = client.post(f"/api/projects/{pid}/clusters/preview", json=body).json()
    assert len(proposal["skipped"]) == 1 and len(proposal["assignments"]) == 3


def test_class_labels_are_preserved_in_versions_and_diff(batch_client):
    client, pid, pairs, _ = batch_client
    for p in pairs:
        assert client.put(f"/api/pairs/{p['id']}", json={"revision":p["revision"],"gt_x":20,"gt_y":20,"group_key":"capture","class_label":"before"}).status_code == 200
    first = client.post(f"/api/projects/{pid}/versions", json={"description":"before"}).json()
    pairs = client.get(f"/api/projects/{pid}/pairs").json()
    assert client.post(f"/api/projects/{pid}/groups/bulk", json={"assignments":[{"id":p["id"],"revision":p["revision"],"class_label":"after"} for p in pairs]}).status_code == 200
    second = client.post(f"/api/projects/{pid}/versions", json={"description":"after"}).json()
    assert all(p["class_label"] == "before" for p in client.get(f"/api/versions/{first['id']}/manifest").json()["pairs"])
    assert all(p["class_label"] == "after" for p in client.get(f"/api/versions/{second['id']}/manifest").json()["pairs"])
    diff = client.get(f"/api/versions/{second['id']}/diff/{first['id']}").json()
    assert len(diff["changes"]) == 4 and all(p["fields"] == ["class_label"] for p in diff["changes"])


def test_existing_database_migrates_class_without_losing_pairs(batch_client, tmp_path):
    _, _, pairs, _ = batch_client
    database = tmp_path / "state/studio.db"
    with sqlite3.connect(database) as connection:
        connection.execute("ALTER TABLE pairs DROP COLUMN class_label")
    app = create_app(tmp_path / "state")
    with TestClient(app) as client:
        after = client.get(f"/api/projects/{pairs[0]['project_id']}/pairs").json()
        assert len(after) == 4 and all(p["class_label"] == "" for p in after)
    app.state.engine.dispose()
