"""Deterministic CPU-only contract tests: no GPU/model download is required."""
import csv
import json
from pathlib import Path

import numpy as np
import pytest
from PIL import Image

from template_bank.__main__ import (
    evaluate,
    ingest,
    load_bank,
    match_test,
    rank,
    save_bank,
)


class FakeEncoder:
    model_id = "fake/visual"

    def encode(self, paths, rois=None, batch_size=2):
        result = []
        for path in paths:
            with Image.open(path) as image:
                avg = float(np.asarray(image.convert("L"), dtype=np.float32).mean())
            result.append([1.0, 0.0] if avg < 100 else [0.0, 1.0])
        return np.asarray(result, np.float32)


def img(path, gray):
    path.parent.mkdir(parents=True, exist_ok=True)
    Image.new("L", (12, 12), gray).save(path)
    return path


def pair_csv(path, rows):
    with path.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=rows[0])
        writer.writeheader()
        writer.writerows(rows)


def setup_data(tmp_path):
    classes = tmp_path / "classes"
    img(classes / "dark" / "a.png", 20)
    img(classes / "bright" / "b.png", 220)
    bank = tmp_path / "bank"
    save_bank(classes, bank, FakeEncoder())
    return bank


def test_rank_and_metadata(tmp_path):
    bank = setup_data(tmp_path)
    meta, vec, paths, labels, hashes = load_bank(bank, "fake/visual")
    assert meta["count"] == 2
    classes, templates = rank([1, 0], vec, paths, labels, topk=2)
    assert classes[0]["label"] == "dark"
    assert templates[0]["label"] == "dark"
    with pytest.raises(ValueError, match="Model mismatch"):
        load_bank(bank, "different/model")


def test_test_matching_separate_and_roi(tmp_path):
    bank = setup_data(tmp_path)
    test = tmp_path / "test"
    img(test / "r.png", 30)
    img(test / "q.png", 70)
    pairs = test / "pairs.csv"
    pair_csv(pairs, [{"pair_id": "P001", "reference": "r.png", "fail": "q.png",
                      "roi_x0": "1", "roi_y0": "2", "roi_x1": "9", "roi_y1": "10",
                      "expected_class": "dark"}])
    result = match_test(pairs, bank, tmp_path / "matches.json", FakeEncoder())
    assert result[0]["topk_classes"][0]["label"] == "dark"
    assert result[0]["reference_roi"] == (1, 2, 9, 10)
    assert "q.png" in result[0]["fail"]


def test_test_hash_leakage(tmp_path):
    bank = setup_data(tmp_path)
    test = tmp_path / "test"
    img(test / "q.png", 70)
    pairs = test / "pairs.csv"
    pair_csv(pairs, [{"pair_id": "P001", "reference": str(tmp_path / "classes" / "dark" / "a.png"),
                      "fail": "q.png"}])
    with pytest.raises(ValueError, match="leakage"):
        match_test(pairs, bank, tmp_path / "matches.json", FakeEncoder())


def test_ingest_non_destructive_and_repeat(tmp_path):
    bank = setup_data(tmp_path)
    incoming = tmp_path / "incoming"
    source = img(incoming / "new.png", 30)
    stage = tmp_path / "stage"
    first = ingest(incoming, bank, stage, FakeEncoder(), accept_score=0.8,
                   accept_margin=0.1)
    assert first["new_images"] == 1
    ledger = json.loads((stage / "decisions.json").read_text())
    assert ledger[0]["status"] == "existing_candidate"
    assert ledger[0]["suggested_class"] == "dark"
    assert source.exists() and Path(ledger[0]["staged"]).exists()
    assert ingest(incoming, bank, stage, FakeEncoder())["new_images"] == 0


def test_ingest_default_requires_review(tmp_path):
    bank = setup_data(tmp_path)
    incoming = tmp_path / "incoming"
    img(incoming / "new.png", 50)
    stage = tmp_path / "stage"
    ingest(incoming, bank, stage, FakeEncoder())
    record = json.loads((stage / "decisions.json").read_text())[0]
    assert record["status"] == "review_required"
    assert not any((tmp_path / "classes" / "dark").glob("new*"))


def test_evaluate_respects_missing_gt(tmp_path):
    matches = {"matches": [{"pair_id": "P001", "expected_class": "dark",
                              "topk_classes": [{"label": "dark"}]}]}
    match_file = tmp_path / "matches.json"
    match_file.write_text(json.dumps(matches))
    pred_file = tmp_path / "pred.csv"
    pair_csv(pred_file, [{"pair_id": "P001", "pred_x": "10", "pred_y": "12",
                          "gt_x": "13", "gt_y": "16"}])
    metrics = evaluate(match_file, pred_file, tmp_path / "metrics.json")
    assert metrics["localization_median_error_px"] == 5.0
    assert metrics["retrieval_top1_accuracy"] == 1.0
    pair_csv(pred_file, [{"pair_id": "P001", "pred_x": "", "pred_y": "",
                          "gt_x": "", "gt_y": ""}])
    assert evaluate(match_file, pred_file, tmp_path / "metrics.json")["localization_median_error_px"] is None
