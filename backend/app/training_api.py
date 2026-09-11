import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Literal

from fastapi import Depends, HTTPException
from fastapi.responses import FileResponse
from pydantic import Field

from training.config import TrainingConfig
from training.data import load_json, sha, write_json

from .database import session_dependency
from .experiment_service import ROOT, ExperimentManager, prepare
from .models import DatasetVersion, ImageRecord, Pair, ReferenceAnnotation, now, uid
from .schemas import StrictModel
from .services import pair_dict
from .storage import digest


class PrepareInput(StrictModel):
    version_id: str
    config: TrainingConfig = Field(default_factory=TrainingConfig)


class VisualizeInput(StrictModel):
    pair_id: str
    checkpoint: Literal["best", "last"] = "best"


class ReferenceInput(StrictModel):
    revision: int = Field(ge=1)
    image_hash: str = Field(pattern=r"^[a-f0-9]{64}$")
    box: list[float] = Field(min_length=4, max_length=4)
    source: Literal["ref_box_manual", "ref_box_auto"] = "ref_box_manual"


def register_training_routes(app, factory, write_lock):
    manager = ExperimentManager(app.state.state_dir)
    app.state.experiments = manager

    session = session_dependency(factory)

    def path_for(experiment_id):
        try:
            return manager.path(experiment_id)
        except ValueError as exc:
            raise HTTPException(404, str(exc)) from exc

    @app.put("/api/pairs/{pair_id}/reference-annotation")
    def annotate(pair_id: str, data: ReferenceInput, db=Depends(session)):
        with write_lock:
            pair = db.get(Pair, pair_id)
            if not pair:
                raise HTTPException(404, "Pair 없음")
            if data.revision != pair.revision:
                raise HTTPException(409, "Pair가 변경되었습니다. 새로고침하세요.")
            record = db.get(ImageRecord, pair.reference_image_id) if pair.reference_image_id else None
            try:
                valid = (
                    record and record.file_hash == data.image_hash and digest(Path(record.file_path)) == data.image_hash
                )
            except OSError:
                valid = False
            if not valid or record.error:
                raise HTTPException(409, "REF가 변경되었거나 읽을 수 없습니다. 재검색하세요.")
            x0, y0, x1, y1 = data.box
            if not (0 <= x0 < x1 < record.width and 0 <= y0 < y1 < record.height):
                raise HTTPException(422, "ROI는 이미지 내 두 모서리 좌표여야 합니다 (x0<x1, y0<y1).")
            pair.revision += 1
            pair.updated_at = now()
            db.add(
                ReferenceAnnotation(
                    pair_id=pair_id,
                    image_hash=data.image_hash,
                    box=data.box,
                    center=[(x0 + x1) / 2, (y0 + y1) / 2],
                    source=data.source,
                    revision=pair.revision,
                )
            )
            db.commit()
            return pair_dict(db, pair)

    @app.get("/api/training/environment")
    def environment():
        return {
            "python": os.getenv("ALIGNFAIL_TRAINING_PYTHON", sys.executable),
            "model": "metric_patch_v1",
            "baseline": "New Triplet CNN baseline; not a reproduction of legacy code",
        }

    @app.post("/api/training/prepare", status_code=201)
    def prepare_experiment(data: PrepareInput, db=Depends(session)):
        with write_lock:
            version = db.get(DatasetVersion, data.version_id)
            if not version:
                raise HTTPException(404, "Dataset Version 없음")
            experiment_id = uid()
            directory = manager.root / experiment_id
            try:
                manifest, split, stats = prepare(version, data.config.model_dump(), directory)
            except (OSError, ValueError) as exc:
                if directory.resolve().parent == manager.root and directory.name == experiment_id:
                    shutil.rmtree(directory, ignore_errors=True)
                raise HTTPException(422, str(exc)) from exc
            comparison_config = data.config.model_dump(
                exclude={
                    "crop_mode",
                    "context_ratio",
                    "min_crop",
                    "max_crop",
                    "output_size",
                    "near_black_mean",
                    "low_std",
                    "low_edge_density",
                }
            )
            code = {
                key: value for key, value in load_json(directory / "integrity.json").items() if key.startswith("code")
            }
            comparison_hash = sha(
                json.dumps(
                    {"version": version.id, "split": split["hash"], "config": comparison_config, "code": code},
                    sort_keys=True,
                ).encode()
            )
            state = {
                "id": experiment_id,
                "project_id": version.project_id,
                "version_id": version.id,
                "version": version.number,
                "status": "prepared",
                "created_at": now(),
                "config": data.config.model_dump(),
                "split_hash": split["hash"],
                "comparison_hash": comparison_hash,
            }
            write_json(directory / "experiment.json", state)
            return {**state, "manifest": manifest, "split": split, "diagnostics": stats}

    @app.get("/api/projects/{project_id}/experiments")
    def experiments(project_id: str):
        values = [load_json(p) for p in manager.root.glob("*/experiment.json")]
        result = []
        for value in sorted(values, key=lambda v: v["created_at"], reverse=True):
            if value["project_id"] == project_id:
                metrics = manager.root / value["id"] / "metrics.json"
                result.append({**value, "metrics": load_json(metrics) if metrics.exists() else None})
        return result

    @app.get("/api/experiments/{experiment_id}")
    def detail(experiment_id: str):
        path = path_for(experiment_id)
        state = load_json(path / "experiment.json")
        for key, filename in [
            ("manifest", "dataset_manifest.json"),
            ("split", "split_manifest.json"),
            ("diagnostics", "diagnostics.json"),
            ("history", "history.json"),
            ("metrics", "metrics.json"),
            ("predictions", "predictions.json"),
        ]:
            state[key] = load_json(path / filename) if (path / filename).exists() else None
        log = path / "train.log"
        if log.exists():
            with log.open("rb") as f:
                f.seek(max(0, log.stat().st_size - 24000))
                state["log"] = f.read().decode("utf-8", errors="replace")
        else:
            state["log"] = ""
        return state

    @app.post("/api/experiments/{experiment_id}/start")
    def start(experiment_id: str):
        try:
            manager.start(path_for(experiment_id))
        except ValueError as exc:
            raise HTTPException(409, str(exc)) from exc
        return {"queued": True}

    @app.post("/api/experiments/{experiment_id}/stop")
    def stop(experiment_id: str):
        manager.stop(path_for(experiment_id))
        return {"stop_requested": True}

    @app.post("/api/experiments/{experiment_id}/visualize")
    def visualize(experiment_id: str, data: VisualizeInput):
        """Run training.visualize in the training Python and return its summary JSON."""
        path = path_for(experiment_id)
        if not (path / f"{data.checkpoint}.pt").is_file():
            raise HTTPException(404, "체크포인트가 없습니다. 학습을 먼저 완료하세요.")
        if not re.fullmatch(r"[a-f0-9-]{36}", data.pair_id):
            raise HTTPException(422, "잘못된 Pair id")
        # Experiments prepared before visualize.py existed have no copy of it; fall back to current code.
        code = path / "code" if (path / "code" / "training" / "visualize.py").is_file() else ROOT
        python = os.getenv("ALIGNFAIL_TRAINING_PYTHON", sys.executable)
        flags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
        try:
            result = subprocess.run(
                [
                    python,
                    "-m",
                    "training.visualize",
                    "--experiment",
                    str(path),
                    "--pair",
                    data.pair_id,
                    "--checkpoint",
                    data.checkpoint,
                ],
                cwd=code,
                capture_output=True,
                text=True,
                timeout=180,
                creationflags=flags,
                env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"},
            )
        except (OSError, subprocess.SubprocessError) as exc:
            raise HTTPException(500, f"시각화 실행 실패: {type(exc).__name__}") from exc
        if result.returncode:
            raise HTTPException(500, "시각화 실패: " + (result.stderr or result.stdout).strip()[-1500:])
        return load_json(path / "viz" / data.pair_id / "viz.json")

    @app.get("/api/experiments/{experiment_id}/files/viz/{pair_id}/{name}")
    def visualization_file(experiment_id: str, pair_id: str, name: str):
        root = path_for(experiment_id)
        if not (re.fullmatch(r"[a-f0-9-]{36}", pair_id) and re.fullmatch(r"[a-z0-9_]+\.png", name)):
            raise HTTPException(404, "지원하지 않는 파일")
        path = root / "viz" / pair_id / name
        if not path.is_file():
            raise HTTPException(404, "파일 없음")
        return FileResponse(path, media_type="image/png", headers={"Cache-Control": "no-store"})

    @app.get("/api/experiments/{experiment_id}/files/{kind}/{name}")
    def artifact(experiment_id: str, kind: str, name: str):
        root = path_for(experiment_id)
        if kind in {"preview", "heatmaps"} and re.fullmatch(r"[a-zA-Z0-9_-]+\.png", name):
            path = root / kind / name
        elif kind == "artifacts" and name in {
            "config.json",
            "dataset_manifest.json",
            "split_manifest.json",
            "environment.json",
            "train.log",
            "metrics.json",
            "history.json",
            "predictions.json",
            "best.pt",
            "last.pt",
        }:
            path = root / name
        else:
            raise HTTPException(404, "지원하지 않는 파일")
        if not path.is_file():
            raise HTTPException(404, "파일 없음")
        return FileResponse(
            path,
            media_type="image/png" if path.suffix == ".png" else None,
            filename=None if path.suffix == ".png" else name,
            headers={"Cache-Control": "no-store"},
        )
