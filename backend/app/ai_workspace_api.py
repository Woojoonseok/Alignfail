"""Local-only AI Dataset workbench: paired Test import, incoming registration, VLM jobs.

Human confirmation is mandatory for template GT, class changes and Test ground truth.
The regular Studio Pair APIs remain the annotation/audit source of truth.
"""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import tempfile
import sys
import threading
from pathlib import Path
from uuid import uuid4

from fastapi import Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select

from .cleaning import detect_markings, load_pixels
from .database import session_dependency
from .models import GTHistory, ImageRecord, Pair, Project, ReferenceAnnotation, now
from .services import IMAGE_SUFFIXES, clear_gt, gt_value, inspect_image, modality_of, pair_dict
from .storage import active_cleanup, digest, inside, project_directories, read_verified


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)


class FolderInput(Strict):
    root_directory: str = Field(min_length=1, max_length=4000)


class StartInput(Strict):
    model: str = Field(default="Qwen/Qwen3-VL-Embedding-2B", min_length=1, max_length=400)
    batch_size: int = Field(default=1, ge=1, le=8)
    top_k: int = Field(default=5, ge=1, le=20)
    patch_size: int = Field(default=160, ge=48, le=512)


class AcceptInput(Strict):
    job_id: str
    pair_id: str
    revision: int = Field(ge=1)
    class_label: str = Field(min_length=1, max_length=200)


class PublishInput(Strict):
    pair_id: str
    revision: int = Field(ge=1)
    class_label: str = Field(min_length=1, max_length=200)


def _state(app, project_id):
    return (app.state.state_dir / "ai_workspace" / project_id).resolve()


def _read_status(directory):
    f = directory / "status.json"
    return json.loads(f.read_text(encoding="utf-8")) if f.is_file() else {"status": "not_started"}


def _write_status(directory, payload):
    directory.mkdir(parents=True, exist_ok=True)
    t = directory / "status.json.tmp"
    t.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(t, directory / "status.json")


def import_workbench_directory(db, project, root: Path, *, mode: str):
    """Test: root/case_name/{*REF*,*FAIL*}.png; incoming: recursive unlabelled images.

    Does not infer a GT from FAIL markings and never reassigns existing Train samples.
    """
    root = root.expanduser().resolve()
    if not root.is_dir():
        raise ValueError("서버에서 접근 가능한 폴더가 아닙니다.")
    if any(root == Path(p).resolve() or root.is_relative_to(Path(p).resolve())
           or Path(p).resolve().is_relative_to(root)
           for p in project_directories(project)):
        # Do not mix the normal folder importer with the special paired importer.
        existing = list(db.scalars(select(Pair).where(Pair.project_id == project.id, Pair.source_directory == str(root))))
        if not existing or any((p.dataset_split != "test" if mode == "test" else p.dataset_split != "train")
                               for p in existing):
            raise ValueError("기존에 등록된 데이터 폴더와 중첩됩니다. 분리된 Test/Incoming 폴더를 지정하세요.")
    existing_paths = {i.file_path: i for i in db.scalars(
        select(ImageRecord).where(ImageRecord.project_id == project.id))}
    existing_pairs = {p.folder: p for p in db.scalars(
        select(Pair).where(Pair.project_id == project.id))}
    prefix = f"AI:{mode}:{root.as_posix()}:"
    candidates = []
    if mode == "test":
        for case in sorted(root.iterdir()):
            if not case.is_dir() or case.is_symlink():
                continue
            files = sorted(p for p in case.iterdir() if p.is_file() and not p.is_symlink()
                           and p.suffix.lower() in IMAGE_SUFFIXES)
            refs = [p for p in files if "ref" in p.stem.lower()]
            fail = [p for p in files if "ref" not in p.stem.lower()]
            if len(refs) != 1 or len(fail) != 1:
                raise ValueError(f"{case.name}: REF 1장 + FAIL/Query 1장이 필요합니다. (검출: {len(refs)}, {len(fail)})")
            candidates.append((case.name, refs[0], fail[0]))
    else:
        for base, folders, files in os.walk(root, followlinks=False):
            folders[:] = sorted(x for x in folders if not (Path(base) / x).is_symlink())
            for name in sorted(files):
                p = Path(base) / name
                if p.suffix.lower() in IMAGE_SUFFIXES and not p.is_symlink():
                    candidates.append((p.relative_to(root).as_posix(), p, None))
    if not candidates:
        raise ValueError("등록할 이미지가 없습니다.")
    # Preflight the entire import before any DB writes.
    records = []
    for key, first, second in candidates:
        if len(key) > 800:
            raise ValueError("상대 경로가 너무 깁니다.")
        for p in (first, second):
            if p is None:
                continue
            if str(p.resolve()) in existing_paths and (not (prefix + key in existing_pairs and
                (existing_pairs[prefix + key].reference_image_id == existing_paths[str(p.resolve())].id or
                 existing_pairs[prefix + key].query_image_id == existing_paths[str(p.resolve())].id))):
                raise ValueError(f"다른 Pair에 등록된 이미지입니다: {p.name}")
        info_a = inspect_image(first)
        info_b = inspect_image(second) if second else None
        if info_a["error"] or (info_b and info_b["error"]):
            raise ValueError(f"{key}: 파일을 읽을 수 없습니다.")
        records.append((key, first, second, info_a, info_b))
    count = 0
    for key, first, second, ia, ib in records:
        pair_key = prefix + key
        # Previous prototype versions may already contain this name.
        pair = existing_pairs.get(pair_key)
        if pair is None:
            pair = Pair(project_id=project.id, folder=pair_key, source_directory=str(root))
            db.add(pair)
            db.flush()
            count += 1
        elif pair.dataset_split != ("test" if mode == "test" else "train"):
            raise ValueError("기존 Pair 용도를 덮어쓸 수 없습니다.")

        def register(p, info, role):
            path = str(p.resolve())
            rec = existing_paths.get(path)
            if rec is None:
                rec = ImageRecord(project_id=project.id, folder=pair_key, file_path=path,
                                  file_name=p.name, role=role)
                db.add(rec)
                db.flush()
                existing_paths[path] = rec
            if rec.file_hash and rec.file_hash != info["file_hash"]:
                clear_gt(db, pair, "이미지 바이트 변경: GT 재검토")
            rec.folder = pair_key
            rec.role = role
            for k, value in info.items():
                setattr(rec, k, value)
            return rec

        ref = register(first, ia, "REF")
        query = register(second, ib, "QUERY") if second else None
        pair.dataset_split = "test" if mode == "test" else "train"
        pair.sample_role = "pair" if mode == "test" else "reference"
        pair.reference_image_id = ref.id
        pair.query_image_id = query.id if query else None
        pair.class_label = pair.class_label if mode == "test" else ""
        pair.modality = modality_of(key, first.name)
        pair.match_result = "fail" if mode == "test" else "unknown"
        pair.import_issues = []
        pair.revision += 1
        pair.updated_at = now()
    roots = project_directories(project)
    if str(root) not in roots:
        roots.append(str(root))
    project.data_directories = roots
    project.root_directory = project.root_directory or str(root)
    db.flush()
    return {"registered": len(records), "created": count, "mode": mode}


def _image_source(db, app, project, image):
    if image is None or image.error:
        return None
    origin = Path(image.file_path)
    if not any(inside(origin, root) for root in project_directories(project)):
        return None
    if digest(origin) != image.file_hash:
        return None
    cleanup = active_cleanup(db, image.id)
    if cleanup is not None and cleanup.source_hash == image.file_hash:
        path = Path(cleanup.clean_path)
        if inside(path, app.state.state_dir / "clean") and path.is_file() and digest(path) == cleanup.clean_hash:
            return {"path": str(path), "sha256": cleanup.clean_hash, "raw_sha256": image.file_hash, "clean": True}
    # Auto-cross detection on original bytes; a marker-free, manually annotated
    # image may enter the bank without a fabricated cleanup cache.
    try:
        cross_present = detect_markings(load_pixels(read_verified(origin, image.file_hash)))["cross"] is not None
    except (OSError, ValueError, Image.DecompressionBombError):
        cross_present = None
    return {"path": str(origin), "sha256": image.file_hash, "raw_sha256": image.file_hash,
            "clean": False, "cross_present": cross_present}


def build_manifest(db, app, project):
    """Snapshot verified file paths/GT. Only reviewed Train GT contributes to bank."""
    templates, tests, incoming = [], [], []
    ledger_file = _state(app, project.id) / "publish_ledger.json"
    published = {entry["pair_id"]: entry for entry in
                 (json.loads(ledger_file.read_text(encoding="utf-8")) if ledger_file.is_file() else [])}
    for pair in db.scalars(select(Pair).where(Pair.project_id == project.id, Pair.enabled.is_(True))):
        reference = db.get(ImageRecord, pair.reference_image_id) if pair.reference_image_id else None
        source = _image_source(db, app, project, reference)
        if source is None:
            continue
        entry = {"pair_id": pair.id, "revision": pair.revision, "class_label": pair.class_label,
                 "reference": source, "gt": [pair.gt_x, pair.gt_y] if pair.gt_x is not None else None,
                 "gt_source": pair.gt_source}
        if pair.dataset_split == "test":
            query = db.get(ImageRecord, pair.query_image_id) if pair.query_image_id else None
            q = _image_source(db, app, project, query)
            if not q:
                continue
            annotation = db.scalar(select(ReferenceAnnotation).where(
                ReferenceAnnotation.pair_id == pair.id,
                ReferenceAnnotation.image_hash == reference.file_hash,
            ).order_by(ReferenceAnnotation.revision.desc()))
            entry.update(query=q, reference_roi=annotation.box if annotation else None)
            tests.append(entry)
        elif pair.dataset_split == "train":
            is_incoming = pair.folder.startswith("AI:incoming:")
            published_entry = published.get(pair.id)
            is_published = bool(published_entry and published_entry["class_label"] == pair.class_label
                                and published_entry["sha256"] == source["sha256"])
            if is_incoming and not is_published:
                incoming.append(entry)
            elif pair.class_label and pair.gt_source == "manual" and entry["gt"] and (
                source["clean"] or source.get("cross_present") is False
            ):
                templates.append(entry)
    hashes = {hash_value for x in templates for hash_value in
              (x["reference"]["sha256"], x["reference"]["raw_sha256"])}
    if any(any(hash_value in hashes for source in (t["reference"], t["query"])
               for hash_value in (source["sha256"], source["raw_sha256"])) for t in tests):
        raise ValueError("Train/Test 원본 또는 Clean SHA256 중복이 있습니다.")
    if not templates:
        raise ValueError("Train 클래스에서 검수한 GT와 Clean 이미지가 있는 템플릿이 없습니다.")
    if not tests and not incoming:
        raise ValueError("Test Pair 또는 Incoming 이미지가 없습니다.")
    return {"schema": "alignfail.ai-workspace.v1", "templates": templates, "tests": tests,
            "incoming": incoming, "created_at": now()}


def register_ai_workspace_routes(app, factory, write_lock):
    session = session_dependency(factory)
    processes = {}
    process_guard = threading.RLock()

    def project_of(db, project_id):
        p = db.get(Project, project_id)
        if p is None:
            raise HTTPException(404, "프로젝트가 없습니다.")
        return p

    @app.post("/api/projects/{project_id}/ai/import/{mode}")
    def import_data(project_id: str, mode: str, data: FolderInput, db=Depends(session)):
        if mode not in {"test", "incoming"}:
            raise HTTPException(422, "test/incoming만 지원합니다.")
        with write_lock:
            project = project_of(db, project_id)
            try:
                result = import_workbench_directory(db, project, Path(data.root_directory), mode=mode)
                db.commit()
                return result
            except (OSError, ValueError) as error:
                db.rollback()
                raise HTTPException(422, str(error)) from error

    @app.get("/api/projects/{project_id}/ai/overview")
    def overview(project_id: str, db=Depends(session)):
        p = project_of(db, project_id)
        pairs = list(db.scalars(select(Pair).where(Pair.project_id == project_id)))
        return {"train": sum(x.dataset_split == "train" for x in pairs),
                "test_pairs": sum(x.dataset_split == "test" and x.query_image_id is not None for x in pairs),
                "templates_ready": sum(x.dataset_split == "train" and x.gt_source == "manual"
                                       and bool(x.class_label) for x in pairs),
                "incoming": sum(x.folder.startswith("AI:incoming:") for x in pairs),
                "pairs": [pair_dict(db, x) for x in pairs if
                          x.folder.startswith("AI:") or
                          (x.dataset_split == "train" and x.sample_role == "reference")],
                "active_job": _read_status(_state(app, project_id) / "latest")}

    @app.post("/api/projects/{project_id}/ai/run")
    def start(project_id: str, config: StartInput, db=Depends(session)):
        project = project_of(db, project_id)
        with process_guard:
            active = processes.get(project_id)
            if active and active.poll() is None:
                raise HTTPException(409, "이미 VLM 검색 작업이 실행 중입니다.")
            try:
                manifest = build_manifest(db, app, project)
            except (OSError, ValueError) as exc:
                raise HTTPException(422, str(exc)) from exc
            job_id = str(uuid4())
            state = _state(app, project_id)
            run_dir = state / "jobs" / job_id
            run_dir.mkdir(parents=True, exist_ok=False)
            (run_dir / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False), encoding="utf-8")
            (run_dir / "config.json").write_text(config.model_dump_json(), encoding="utf-8")
            python = os.getenv("ALIGNFAIL_VLM_PYTHON") or sys.executable
            args = [python, "-m", "ai_workspace.worker", "--job", str(run_dir)]
            try:
                with (run_dir / "worker.log").open("ab") as log:
                    child = subprocess.Popen(args, cwd=str(Path(__file__).resolve().parents[2]),
                                             stdout=log, stderr=subprocess.STDOUT)
            except OSError as exc:
                raise HTTPException(422, f"GPU Python 실행 실패: {exc}") from exc
            processes[project_id] = child
            _write_status(run_dir, {"status": "running", "job_id": job_id, "pid": child.pid})
            # Write latest pointer as a file, not a symlink.
            _write_status(state / "latest", {"job_id": job_id, "status": "running"})
            return {"job_id": job_id, "status": "running"}

    @app.get("/api/projects/{project_id}/ai/jobs/{job_id}")
    def job(project_id: str, job_id: str, db=Depends(session)):
        project_of(db, project_id)
        if not (len(job_id) == 36 and all(c in "0123456789abcdef-" for c in job_id.lower())):
            raise HTTPException(422, "잘못된 작업 ID입니다.")
        directory = _state(app, project_id) / "jobs" / job_id
        if not directory.is_dir():
            raise HTTPException(404, "작업이 없습니다.")
        state = _read_status(directory)
        proc = processes.get(project_id)
        if state.get("status") == "running" and proc and proc.poll() is not None:
            state = _read_status(directory)
            if state.get("status") == "running":
                state = {"job_id": job_id, "status": "failed", "error": "Worker exited without saving results"}
                _write_status(directory, state)
        f = directory / "results.json"
        return {**state, "results": json.loads(f.read_text(encoding="utf-8")) if
                state.get("status") == "completed" and f.is_file() else None}

    @app.post("/api/projects/{project_id}/ai/publish")
    def publish(project_id: str, data: PublishInput, db=Depends(session)):
        """Reviewer-approved, non-destructive addition to a physical curated class folder.

        Final Test pairs are never copied into Train. Existing publications are immutable:
        reclassification must be handled by an explicit future revoke/republish flow.
        """
        with write_lock:
            project = project_of(db, project_id)
            pair = db.get(Pair, data.pair_id)
            if not pair or pair.project_id != project_id:
                raise HTTPException(404, "Pair가 없습니다.")
            if not pair.folder.startswith("AI:incoming:") or pair.dataset_split != "train":
                raise HTTPException(422, "공정 완료 Incoming 이미지만 클래스 폴더로 내보낼 수 있습니다.")
            if pair.revision != data.revision:
                raise HTTPException(409, "수정된 Pair입니다. 새로고침하세요.")
            if pair.gt_source != "manual" or pair.gt_x is None or pair.gt_y is None:
                raise HTTPException(422, "사람이 확인한 GT 좌표가 필요합니다.")
            label = data.class_label.strip()
            if not re.fullmatch(r"[a-zA-Z0-9가-힣_ .()\-]{1,200}", label) or label in {".", ".."} or label.endswith("."):
                raise HTTPException(422, "클래스명에 경로 구분자 또는 특수 문자를 사용할 수 없습니다.")
            image = db.get(ImageRecord, pair.reference_image_id)
            try:
                source = _image_source(db, app, project, image)
            except OSError as exc:
                raise HTTPException(409, "원본 이미지를 다시 확인하세요.") from exc
            if not source:
                raise HTTPException(409, "원본 이미지가 변경됐거나 읽을 수 없습니다.")
            if not source["clean"] and source.get("cross_present") is not False:
                raise HTTPException(422, "십자선이 남았거나 확인할 수 없습니다. 먼저 Clean 이미지를 생성하세요.")

            root = _state(app, project_id) / "curated"
            target_dir = root / label
            target_dir.mkdir(parents=True, exist_ok=True)
            if not inside(target_dir, root):
                raise HTTPException(422, "잘못된 클래스 폴더입니다.")
            ledger_file = _state(app, project_id) / "publish_ledger.json"
            ledger = json.loads(ledger_file.read_text(encoding="utf-8")) if ledger_file.is_file() else []
            history = [p for p in ledger if p["pair_id"] == pair.id]
            if history:
                if history[-1]["class_label"] != label:
                    raise HTTPException(409, "이미 다른 클래스로 게시했습니다. 기존 게시를 검토하세요.")
                return history[-1]
            src = Path(source["path"])
            extension = src.suffix.lower()
            dest = target_dir / (pair.id + extension)
            if dest.exists():
                if digest(dest) != source["sha256"]:
                    raise HTTPException(409, "동일 이름의 다른 파일이 있습니다.")
            else:
                with tempfile.NamedTemporaryFile(dir=target_dir, delete=False) as tmp:
                    temporary = Path(tmp.name)
                try:
                    shutil.copyfile(src, temporary)
                    if digest(temporary) != source["sha256"]:
                        raise HTTPException(409, "복사하는 도중 파일 내용이 바뀌었습니다.")
                    os.replace(temporary, dest)
                finally:
                    temporary.unlink(missing_ok=True)
            record = {"pair_id": pair.id, "class_label": label, "file_path": str(dest),
                      "sha256": source["sha256"], "original_sha256": source["raw_sha256"],
                      "gt_x": pair.gt_x, "gt_y": pair.gt_y, "gt_source": "manual",
                      "published_at": now(), "source_split": "train"}
            # Ledger is a review audit trail separate from the original file and the Pair.
            tmp_ledger = ledger_file.with_suffix(".json.tmp")
            tmp_ledger.write_text(json.dumps([*ledger, record], ensure_ascii=False, indent=2), encoding="utf-8")
            os.replace(tmp_ledger, ledger_file)
            pair.class_label = label
            pair.revision += 1
            pair.updated_at = now()
            db.commit()
            return record

    @app.post("/api/projects/{project_id}/ai/approve")
    def approve(project_id: str, data: AcceptInput, db=Depends(session)):
        with write_lock:
            project_of(db, project_id)
            pair = db.get(Pair, data.pair_id)
            if not pair or pair.project_id != project_id:
                raise HTTPException(404, "Pair가 없습니다.")
            if pair.revision != data.revision:
                raise HTTPException(409, "다른 작업에서 Pair가 변경됐습니다.")
            if not (pair.dataset_split == "test" or pair.folder.startswith("AI:incoming:")):
                raise HTTPException(422, "승인 가능한 Test/Incoming Pair가 아닙니다.")
            results = _state(app, project_id) / "jobs" / data.job_id / "results.json"
            if not results.is_file():
                raise HTTPException(404, "VLM 결과가 없습니다.")
            payload = json.loads(results.read_text(encoding="utf-8"))
            proposals = {row["pair_id"]: row for row in payload["matches"]}
            result = proposals.get(pair.id)
            if not result or pair.revision != result["revision"]:
                raise HTTPException(409, "현재 Pair와 맞는 검색 결과가 아닙니다. 다시 검색하세요.")
            valid = {c["label"] for c in result["classes"]}
            if data.class_label not in valid:
                raise HTTPException(422, "추천 목록에 없는 클래스입니다. 신규 클래스는 수동 등록하세요.")
            pair.class_label = data.class_label.strip()
            pair.revision += 1
            pair.updated_at = now()
            db.commit()
            return {"id": pair.id, "class_label": pair.class_label,
                    "dataset_split": pair.dataset_split, "revision": pair.revision,
                    "note": "Test Pair는 Train으로 이동하지 않았습니다."}
