import json
import os
import queue
import shutil
import subprocess
import sys
import threading
from pathlib import Path

import cv2

from training.data import MODES, crop, crop_spec, diagnostics, group_split, read_image, sha

from .models import now

ROOT = Path(__file__).resolve().parents[2]


def write_json(path, value):
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False), encoding="utf-8")
    temp.replace(path)


def load_json(path):
    return json.loads(path.read_text(encoding="utf-8"))


def prepare(version, config, directory):
    rows, stats = (
        [],
        {mode: {"total": 0, "near_black": 0, "low_std": 0, "low_edge_density": 0, "problematic": 0} for mode in MODES},
    )
    directory.mkdir(parents=True)
    (directory / "data").mkdir()
    (directory / "preview").mkdir()
    for pair in version.manifest["pairs"]:
        if not pair["enabled"]:
            continue
        annotation = pair.get("reference_annotation")
        if pair["import_issues"] or pair["gt_source"] != "manual" or pair["gt_x"] is None or pair["gt_y"] is None:
            raise ValueError(f"{pair['folder']}: 파일 오류 없는 Pair와 수동 Query GT가 필요합니다.")
        if not annotation or annotation["image_hash"] != pair["reference"]["file_hash"]:
            raise ValueError(f"{pair['folder']}: 유효한 REF ROI가 포함된 새 Dataset Version을 생성하세요.")
        row = {
            "pair_id": pair["id"],
            "folder": pair["folder"],
            "group_key": pair["group_key"],
            "ref_box": annotation["box"],
            "ref_center": annotation["center"],
            "reference_annotation": annotation,
            "query_gt": [pair["gt_x"], pair["gt_y"]],
            "pattern_type": pair.get("pattern_type", "unknown"),
            "tier": pair["tier"],
            "class_label": pair.get("class_label", ""),
        }
        for role, field in [("ref", "reference"), ("query", "query")]:
            record = pair[field]
            if not record:
                raise ValueError(f"{pair['folder']}: {role} 이미지 없음")
            # Validate original even when using Clean, then snapshot the selected input bytes.
            source = Path(record["file_path"])
            original = source.read_bytes()
            if sha(original) != record["file_hash"]:
                raise ValueError(f"{pair['folder']}: 원본 hash 변경")
            cleanup = record.get("cleanup")
            content, actual_hash = original, record["file_hash"]
            if cleanup:
                if cleanup["source_hash"] != record["file_hash"]:
                    raise ValueError(f"{pair['folder']}: stale Clean")
                content = Path(cleanup["clean_path"]).read_bytes()
                actual_hash = cleanup["clean_hash"]
                if sha(Path(cleanup["mask_path"]).read_bytes()) != cleanup["mask_hash"]:
                    raise ValueError(f"{pair['folder']}: mask hash 변경")
            if sha(content) != actual_hash:
                raise ValueError(f"{pair['folder']}: Clean hash 변경")
            dest = directory / "data" / f"{actual_hash}.bin"
            if not dest.exists():
                dest.write_bytes(content)
            image = read_image(dest, actual_hash)
            center = row["ref_center"] if role == "ref" else row["query_gt"]
            if not (0 <= center[0] < image.shape[1] and 0 <= center[1] < image.shape[0]):
                raise ValueError(f"{pair['folder']}: {role} 좌표 범위 오류")
            if role == "query":
                corners = [
                    (0, 0),
                    (0, image.shape[0] - 1),
                    (image.shape[1] - 1, 0),
                    (image.shape[1] - 1, image.shape[0] - 1),
                ]
                if (
                    max(((x - center[0]) ** 2 + (y - center[1]) ** 2) ** 0.5 for x, y in corners)
                    < config["negative_min_distance"]
                ):
                    raise ValueError(f"{pair['folder']}: negative_min_distance를 충족하는 위치 없음")
            row.update(
                {
                    f"{role}_path": str(dest.resolve()),
                    f"{role}_hash": actual_hash,
                    f"{role}_original_hash": record["file_hash"],
                    f"{role}_cleanup": cleanup,
                    f"{role}_size": [image.shape[1], image.shape[0]],
                }
            )
            cv2.imwrite(str(directory / "preview" / f"{pair['id']}_{role}.png"), image)
        reference = read_image(row["ref_path"], row["ref_hash"])
        row["crops"] = {}
        for mode in MODES:
            native, output = crop_spec(row["ref_box"], mode, config)
            pixels, metadata = crop(reference, row["ref_center"], native, output)
            quality = diagnostics(pixels, config)
            row["crops"][mode] = {**metadata, **quality}
            cv2.imwrite(str(directory / "preview" / f"{pair['id']}_{mode}.png"), pixels)
            stats[mode]["total"] += 1
            for key in ["near_black", "low_std", "low_edge_density", "problematic"]:
                stats[mode][key] += int(quality[key])
        rows.append(row)
    split = group_split(rows, config)
    manifest = {
        "schema": "alignfail.training.v1",
        "dataset_version_id": version.id,
        "dataset_version": version.number,
        "project_id": version.project_id,
        "crop_mode": config["crop_mode"],
        "pairs": rows,
    }
    write_json(directory / "config.json", config)
    write_json(directory / "dataset_manifest.json", manifest)
    write_json(directory / "split_manifest.json", split)
    write_json(directory / "diagnostics.json", stats)
    shutil.copytree(
        ROOT / "training", directory / "code" / "training", ignore=shutil.ignore_patterns("__pycache__", "*.pyc")
    )
    try:
        commit = subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=ROOT, text=True, stderr=subprocess.DEVNULL
        ).strip()
    except (OSError, subprocess.SubprocessError):
        commit = "unknown"
    files = [p for p in (directory / "code").rglob("*") if p.is_file()]
    checks = {
        str(p.relative_to(directory)): sha(p.read_bytes())
        for p in files + [directory / n for n in ["config.json", "dataset_manifest.json", "split_manifest.json"]]
    }
    write_json(directory / "integrity.json", checks)
    write_json(
        directory / "environment.json",
        {
            "git_commit": commit,
            "dataset_version": version.number,
            "seed": config["seed"],
            "code_hash": sha(json.dumps(checks, sort_keys=True).encode()),
        },
    )
    return manifest, split, stats


class ExperimentManager:
    def __init__(self, state_dir):
        self.root = state_dir.resolve() / "experiments"
        self.root.mkdir(parents=True, exist_ok=True)
        self.lock = threading.RLock()
        self.jobs = queue.Queue()
        self.shutdown = threading.Event()
        self.process = None
        self.worker = None

    def activate(self):
        for path in self.root.glob("*/experiment.json"):
            value = load_json(path)
            if value["status"] in {"running", "queued"}:
                value.update(status="failed", error="Backend 재시작으로 중단됨. 새 실험을 생성하세요.")
                write_json(path, value)
        self.worker = threading.Thread(target=self.run, daemon=True)
        self.worker.start()

    def path(self, experiment_id):
        from uuid import UUID

        UUID(experiment_id)
        path = self.root / experiment_id
        if not (path / "experiment.json").exists():
            raise ValueError("실험을 찾을 수 없습니다.")
        return path

    def update(self, path, **values):
        with self.lock:
            state = load_json(path / "experiment.json")
            state.update(values)
            write_json(path / "experiment.json", state)

    def start(self, path):
        with self.lock:
            if load_json(path / "experiment.json")["status"] != "prepared":
                raise ValueError("이미 시작한 실험입니다. 새 실험을 생성하세요.")
            self.update(path, status="queued")
            self.jobs.put(path)

    def stop(self, path):
        with self.lock:
            state = load_json(path / "experiment.json")
            if state["status"] in {"queued", "running"}:
                (path / "stop.request").touch()
                if state["status"] == "queued":
                    self.update(path, status="stopped")

    def run(self):
        while not self.shutdown.is_set():
            try:
                path = self.jobs.get(timeout=0.5)
            except queue.Empty:
                continue
            with self.lock:
                if load_json(path / "experiment.json")["status"] != "queued":
                    continue
                self.update(path, status="running", started_at=now())
            try:
                python = os.getenv("ALIGNFAIL_TRAINING_PYTHON", sys.executable)
                flags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
                with (path / "train.log").open("ab") as log:
                    env = {
                        **os.environ,
                        "PYTHONDONTWRITEBYTECODE": "1",
                        "PYTHONUNBUFFERED": "1",
                        "CUBLAS_WORKSPACE_CONFIG": ":4096:8",
                    }
                    (path / "heartbeat").touch()
                    self.process = subprocess.Popen(
                        [python, "-m", "training.train", "--experiment", str(path), "--managed"],
                        cwd=path / "code",
                        stdout=log,
                        stderr=subprocess.STDOUT,
                        env=env,
                        creationflags=flags,
                    )
                    while self.process.poll() is None:
                        (path / "heartbeat").touch()
                        if self.shutdown.wait(0.5):
                            (path / "stop.request").touch()
                            try:
                                self.process.wait(timeout=10)
                            except subprocess.TimeoutExpired:
                                self.process.terminate()
                            break
                    code = self.process.wait()
                result = load_json(path / "result.json") if (path / "result.json").exists() else {}
                self.update(
                    path,
                    status=result.get("status", "failed") if code == 0 else "failed",
                    finished_at=now(),
                    return_code=code,
                    error=result.get("error", "train.log를 확인하세요." if code else ""),
                )
            except Exception as exc:
                self.update(path, status="failed", error=str(exc), finished_at=now())
            finally:
                self.process = None

    def close(self):
        self.shutdown.set()
        if self.worker:
            self.worker.join(timeout=15)
