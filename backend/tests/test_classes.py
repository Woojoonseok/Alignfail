import numpy as np
import pytest
from fastapi.testclient import TestClient
from PIL import Image

from app.cleaning import png_bytes
from app.main import create_app
from app.services import match_result_of, modality_of


@pytest.mark.parametrize(
    "name,modality",
    [
        ("sample_OM_01.png", "OM"),
        ("OM-3.bmp", "OM"),
        ("om.png", "OM"),
        ("custom.png", "SEM"),
        ("s_1234_SEM.png", "SEM"),
    ],
)
def test_modality_from_file_name_token(name, modality):
    assert modality_of(name) == modality


def test_match_result_from_prefix():
    assert match_result_of("s_001.png") == "success"
    assert match_result_of("E_001.png") == "fail"
    assert match_result_of("query.png") == "unknown"


@pytest.fixture
def template_client(tmp_path):
    root = tmp_path / "Dada"
    # Two template pairs (REF with a white box, Query with a cross) plus two loose production exports.
    vertical = np.zeros((160, 192), dtype=np.uint8)
    vertical[:, 60:100] = 150
    horizontal = np.zeros((160, 192), dtype=np.uint8)
    horizontal[60:100, :] = 150

    def with_box(pixels):  # same geometry as support.marked_image(box=True): x 40..150, y 30..125
        out = pixels.copy()
        out[30, 40:151] = out[125, 40:151] = 255
        out[30:126, 40] = out[30:126, 150] = 255
        return out

    def with_cross(pixels):  # rows 82..83, cols 95..96
        out = pixels.copy()
        out[82:84, :] = 255
        out[:, 95:97] = 255
        return out

    for name, pixels in [("pair_v_OM", vertical), ("pair_h_OM", horizontal)]:
        folder = root / name
        folder.mkdir(parents=True)
        (folder / "image_REF.png").write_bytes(png_bytes(with_box(pixels)))
        (folder / "image.png").write_bytes(png_bytes(with_cross(pixels)))
    (root / "s_export_OM.png").write_bytes(png_bytes(with_cross(vertical)))
    (root / "e_export_OM.png").write_bytes(png_bytes(horizontal))
    app = create_app(tmp_path / "state")
    with TestClient(app) as client:
        pid = client.post("/api/projects", json={"name": "Templates"}).json()["id"]
        result = client.post(f"/api/projects/{pid}/import", json={"root_directory": str(root)})
        assert result.status_code == 200, result.text
        pairs = {p["folder"]: p for p in client.get(f"/api/projects/{pid}/pairs").json()}
        yield client, pid, pairs
    app.state.engine.dispose()


def test_import_accepts_loose_queries_and_reads_modality_and_match_result(template_client):
    client, pid, pairs = template_client
    assert set(pairs) == {"pair_v_OM", "pair_h_OM", "s_export_OM.png", "e_export_OM.png"}
    loose = pairs["s_export_OM.png"]
    assert loose["reference"] is None and loose["query"]["file_name"] == "s_export_OM.png"
    assert loose["import_issues"] == [] and loose["match_result"] == "success" and loose["modality"] == "OM"
    assert pairs["e_export_OM.png"]["match_result"] == "fail"
    assert pairs["pair_v_OM"]["reference"] is not None and pairs["pair_v_OM"]["match_result"] == "unknown"
    # Folder pairs never inherit the export prefix rule, even when the query name starts with s/e.
    assert pairs["pair_h_OM"]["match_result"] == "unknown"
    audit = client.post(f"/api/projects/{pid}/audit").json()
    codes = {(i["folder"], i["code"], i["severity"]) for i in audit["issues"]}
    assert ("s_export_OM.png", "REF_UNLINKED", "warning") in codes
    assert not any(c == "MISSING_IMAGE" for _, c, _ in codes)
    project = client.get("/api/projects").json()[0]
    assert project["unlinked_count"] == 2 and project["modalities"] == {"OM": 4, "SEM": 0}


def test_template_match_attach_links_ref_and_respects_modality(template_client):
    client, pid, pairs = template_client
    for folder, label in [("pair_v_OM", "vertical"), ("pair_h_OM", "horizontal")]:
        p = pairs[folder]
        client.post(
            f"/api/projects/{pid}/groups/bulk",
            json={"assignments": [{"id": p["id"], "revision": p["revision"], "class_label": label}]},
        )
        res = client.put(f"/api/projects/{pid}/classes/{label}/template", json={"image_id": p["reference"]["id"]})
        assert res.status_code == 200 and res.json()["image"]["id"] == p["reference"]["id"]
    classes = client.get(f"/api/projects/{pid}/classes").json()
    assert [c["class_label"] for c in classes["classes"]] == ["horizontal", "vertical"]
    assert classes["unlinked"] == 2 and all(c["template"] for c in classes["classes"])
    # Query-only exports rank the template whose appearance matches first.
    current = {p["folder"]: p for p in client.get(f"/api/projects/{pid}/pairs").json()}
    loose = [current["s_export_OM.png"], current["e_export_OM.png"]]
    match = client.post(
        f"/api/projects/{pid}/classes/match",
        json={"pairs": [{"id": p["id"], "revision": p["revision"]} for p in loose]},
    )
    assert match.status_code == 200, match.text
    ranked = {r["folder"]: [c["class_label"] for c in r["candidates"]] for r in match.json()["results"]}
    assert ranked["e_export_OM.png"][0] == "horizontal" and ranked["s_export_OM.png"][0] == "vertical"
    # Attaching links the template REF to the REF-less pair; own REFs are never replaced.
    s = current["s_export_OM.png"]
    attach = client.post(
        f"/api/projects/{pid}/classes/attach",
        json={"pairs": [{"id": s["id"], "revision": s["revision"]}], "class_label": "vertical"},
    )
    assert attach.status_code == 200 and attach.json() == {"updated": 1, "linked": 1, "template": True}
    after = {p["folder"]: p for p in client.get(f"/api/projects/{pid}/pairs").json()}
    assert after["s_export_OM.png"]["reference"]["id"] == current["pair_v_OM"]["reference"]["id"]
    assert after["s_export_OM.png"]["class_label"] == "vertical"
    # Rescanning keeps the linked template REF (the loose file still has none of its own).
    client.post(
        f"/api/projects/{pid}/import", json={"root_directory": client.get("/api/projects").json()[0]["root_directory"]}
    )
    again = {p["folder"]: p for p in client.get(f"/api/projects/{pid}/pairs").json()}
    assert again["s_export_OM.png"]["reference"]["id"] == current["pair_v_OM"]["reference"]["id"]
    # A SEM pair must not be attached to an OM template.
    e = again["e_export_OM.png"]
    client.put(f"/api/pairs/{e['id']}", json={"revision": e["revision"], "modality": "SEM"})
    e = {p["folder"]: p for p in client.get(f"/api/projects/{pid}/pairs").json()}["e_export_OM.png"]
    denied = client.post(
        f"/api/projects/{pid}/classes/attach",
        json={"pairs": [{"id": e["id"], "revision": e["revision"]}], "class_label": "horizontal"},
    )
    assert denied.status_code == 422


def test_markings_apply_sets_roi_and_auto_gt_then_confirm(template_client):
    client, pid, pairs = template_client
    p = pairs["pair_v_OM"]
    res = client.post(
        f"/api/projects/{pid}/markings/apply", json={"pairs": [{"id": p["id"], "revision": p["revision"]}]}
    )
    assert res.status_code == 200, res.text
    outcome = res.json()["results"][0]
    assert outcome["roi"] == "saved" and outcome["gt"] == "saved"
    after = {q["folder"]: q for q in client.get(f"/api/projects/{pid}/pairs").json()}["pair_v_OM"]
    assert after["gt_source"] == "auto_cross" and abs(after["gt_x"] - 95.5) < 1 and abs(after["gt_y"] - 82.5) < 1
    assert after["reference_annotation"]["source"] == "ref_box_auto"
    assert after["reference_annotation"]["center"] == [95, 77.5]
    audit = client.post(f"/api/projects/{pid}/audit").json()
    assert any(i["code"] == "AUTO_GT_UNCONFIRMED" and i["folder"] == "pair_v_OM" for i in audit["issues"])
    # Second run keeps existing results unless replace_existing is requested.
    again = client.post(
        f"/api/projects/{pid}/markings/apply", json={"pairs": [{"id": after["id"], "revision": after["revision"]}]}
    ).json()
    assert again["results"][0] == {"id": after["id"], "folder": "pair_v_OM", "roi": "kept", "gt": "kept"}
    # Confirming promotes the automatic GT to manual without moving it and records history.
    confirmed = client.put(
        f"/api/pairs/{after['id']}",
        json={"revision": after["revision"], "gt_x": after["gt_x"], "gt_y": after["gt_y"], "confirm_gt": True},
    ).json()
    assert confirmed["gt_source"] == "manual" and (confirmed["gt_x"], confirmed["gt_y"]) == (
        after["gt_x"],
        after["gt_y"],
    )
    history = client.get(f"/api/pairs/{after['id']}/history").json()
    assert history[0]["reason"] == "자동 GT 확인" and history[1]["reason"] == "흰 십자선에서 자동 GT"
    # A pair whose query has no cross reports none and keeps GT empty.
    e = {q["folder"]: q for q in client.get(f"/api/projects/{pid}/pairs").json()}["e_export_OM.png"]
    none = client.post(
        f"/api/projects/{pid}/markings/apply", json={"pairs": [{"id": e["id"], "revision": e["revision"]}]}
    ).json()
    assert none["results"][0]["gt"] == "none" and none["results"][0]["roi"].startswith("error")


def test_sixteen_bit_query_is_reported_not_guessed(template_client, tmp_path):
    client, pid, pairs = template_client
    root = tmp_path / "Dada"
    Image.fromarray((np.ones((64, 64)) * 4000).astype(np.uint16)).save(root / "e_deep_OM.png")
    client.post(f"/api/projects/{pid}/import", json={"root_directory": str(root)})
    deep = {q["folder"]: q for q in client.get(f"/api/projects/{pid}/pairs").json()}["e_deep_OM.png"]
    res = client.post(
        f"/api/projects/{pid}/markings/apply",
        json={"pairs": [{"id": deep["id"], "revision": deep["revision"]}], "roi": False},
    ).json()
    assert res["results"][0]["gt"].startswith("error")
