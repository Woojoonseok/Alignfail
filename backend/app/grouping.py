"""Local appearance-based cluster proposals; labels are assigned only on explicit apply."""

import io
from pathlib import Path

import cv2
import numpy as np
from fastapi import Depends, HTTPException
from PIL import Image
from sqlalchemy import select

from .database import session_dependency
from .models import ImageRecord, Pair, Project, now
from .schemas import BulkGroupsInput, ClusterInput
from .storage import HIGH_DEPTH_MODES, active_cleanup, inside, sha


def appearance_features(content):
    with Image.open(io.BytesIO(content)) as image:
        image.load()
        if image.mode in HIGH_DEPTH_MODES:
            pixels = np.asarray(image, dtype=np.float32)
            pixels = (pixels - pixels.min()) / max(float(np.ptp(pixels)), 1) * 255
        else:
            pixels = np.asarray(image.convert("L"), dtype=np.float32)
    small = cv2.resize(pixels, (16, 16), interpolation=cv2.INTER_AREA) / 255
    mean, std = float(small.mean()), float(small.std())
    structure = (small - mean) / max(std, 0.05)
    edges = cv2.magnitude(cv2.Sobel(small, cv2.CV_32F, 1, 0), cv2.Sobel(small, cv2.CV_32F, 0, 1))
    edges = cv2.resize(edges, (8, 8), interpolation=cv2.INTER_AREA)
    return np.concatenate([structure.ravel() / 16, edges.ravel() / 8, [mean, std]]).astype(np.float32)


def cluster_features(features, count):
    """Deterministic farthest-first initialization, then Lloyd iterations."""
    features = np.asarray(features, dtype=np.float32)
    centers = [features[0]]
    for _ in range(1, count):
        distances = np.min(np.stack([np.sum((features - c) ** 2, axis=1) for c in centers]), axis=0)
        index = int(distances.argmax())
        if distances[index] < 1e-10:
            break  # Identical features remain in the same cluster.
        centers.append(features[index])
    centers = np.asarray(centers)
    previous = None
    for _ in range(40):
        distances = np.stack([np.sum((features - c) ** 2, axis=1) for c in centers], axis=1)
        labels = distances.argmin(axis=1)
        if previous is not None and np.array_equal(labels, previous):
            break
        previous = labels.copy()
        for index in range(len(centers)):
            if np.any(labels == index):
                centers[index] = features[labels == index].mean(axis=0)
    mapping = {value: index + 1 for index, value in enumerate(sorted(set(labels.tolist())))}
    return [mapping[int(value)] for value in labels]


def register_group_routes(app, factory, write_lock):
    session = session_dependency(factory)

    def checked_pairs(db, project_id, requests):
        project = db.get(Project, project_id)
        if not project:
            raise HTTPException(404, "프로젝트를 찾을 수 없습니다.")
        ids = [item.id for item in requests]
        if len(set(ids)) != len(ids):
            raise HTTPException(422, "중복 Pair 지정입니다.")
        pairs = {p.id: p for p in db.scalars(select(Pair).where(Pair.project_id == project_id, Pair.id.in_(ids)))}
        for item in requests:
            if item.id not in pairs:
                raise HTTPException(404, "프로젝트에 없는 Pair입니다.")
            if pairs[item.id].revision != item.revision:
                raise HTTPException(409, "Pair가 변경되었습니다. 새로고침 후 다시 실행하세요.")
        return project, pairs

    @app.post("/api/projects/{project_id}/groups/bulk")
    def bulk_groups(project_id: str, data: BulkGroupsInput, db=Depends(session)):
        with write_lock:
            _, pairs = checked_pairs(db, project_id, data.assignments)
            changed = 0
            for item in data.assignments:
                pair = pairs[item.id]
                values = {
                    key: value.strip()
                    for key, value in item.model_dump().items()
                    if key in {"group_key", "class_label"} and value is not None
                }
                if any(getattr(pair, key) != value for key, value in values.items()):
                    for key, value in values.items():
                        setattr(pair, key, value)
                    pair.revision += 1
                    pair.updated_at = now()
                    changed += 1
            db.commit()
            return {"updated": changed}

    @app.post("/api/projects/{project_id}/clusters/preview")
    def cluster_preview(project_id: str, data: ClusterInput, db=Depends(session)):
        with write_lock:
            project, pairs = checked_pairs(db, project_id, data.pairs)
            if data.clusters > len(pairs):
                raise HTTPException(422, "클러스터 수는 선택 Pair 수 이하여야 합니다.")
            features, accepted, skipped = [], [], []
            for pair in sorted(pairs.values(), key=lambda p: (p.folder, p.id)):
                try:
                    image_id = pair.reference_image_id if data.role == "reference" else pair.query_image_id
                    record = db.get(ImageRecord, image_id) if image_id else None
                    if not record or record.error:
                        raise ValueError("이미지 없음 또는 읽기 오류")
                    if not inside(record.file_path, project.root_directory):
                        raise ValueError("프로젝트 외부 경로")
                    content = Path(record.file_path).read_bytes()
                    if sha(content) != record.file_hash:
                        raise ValueError("원본 변경: 폴더 재검색 필요")
                    cleanup = active_cleanup(db, image_id)
                    if cleanup:
                        if cleanup.source_hash != record.file_hash or not inside(
                            cleanup.clean_path, app.state.state_dir / "clean"
                        ):
                            raise ValueError("Clean 원본/경로 불일치")
                        content = Path(cleanup.clean_path).read_bytes()
                        if sha(content) != cleanup.clean_hash:
                            raise ValueError("Clean 캐시 변경")
                    features.append(appearance_features(content))
                    accepted.append(
                        {
                            "id": pair.id,
                            "revision": pair.revision,
                            "folder": pair.folder,
                            "image_source": "clean" if cleanup else "original",
                        }
                    )
                except (OSError, ValueError, Image.DecompressionBombError) as exc:
                    skipped.append({"id": pair.id, "folder": pair.folder, "reason": str(exc)})
            if len(accepted) < 2:
                raise HTTPException(422, "사용 가능한 이미지가 2개 이상 필요합니다.")
            labels = cluster_features(features, min(data.clusters, len(features)))
            return {
                "algorithm": "appearance-kmeans-v1",
                "role": data.role,
                "clusters": len(set(labels)),
                "skipped": skipped,
                "assignments": [{**pair, "cluster": label} for pair, label in zip(accepted, labels, strict=True)],
            }
