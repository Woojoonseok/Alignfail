"""Template classes: a representative REF per class, appearance matching of REF-less
images onto classes, attaching images to a class (which links the class REF), and
deriving ROI / GT from white markings."""

from pathlib import Path

import numpy as np
from fastapi import Depends, HTTPException
from PIL import Image
from sqlalchemy import select

from .cleaning import detect_markings, load_pixels
from .database import session_dependency
from .grouping import appearance_features
from .models import ClassTemplate, GTHistory, ImageRecord, Pair, Project, ReferenceAnnotation, now
from .schemas import AttachInput, ClassTemplateInput, MarkingsInput, MatchInput
from .services import checked_pairs, gt_value, image_dict, modality_of
from .storage import HashMismatch, active_cleanup, inside, read_verified, sha


def image_bytes(db, app, project, record):
    """Verified bytes of the image, preferring a valid Clean copy. Raises ValueError."""
    if not record or record.error:
        raise ValueError("이미지 없음 또는 읽기 오류")
    if not inside(record.file_path, project.root_directory):
        raise ValueError("프로젝트 외부 경로")
    try:
        content = read_verified(record.file_path, record.file_hash)
    except HashMismatch as exc:
        raise ValueError("원본 변경: 폴더 재검색 필요") from exc
    cleanup = active_cleanup(db, record.id)
    if cleanup:
        if cleanup.source_hash != record.file_hash or not inside(cleanup.clean_path, app.state.state_dir / "clean"):
            raise ValueError("Clean 원본/경로 불일치")
        content = Path(cleanup.clean_path).read_bytes()
        if sha(content) != cleanup.clean_hash:
            raise ValueError("Clean 캐시 변경")
    return content


def cosine(a, b):
    return float(np.dot(a, b) / (np.linalg.norm(a) * np.linalg.norm(b) or 1.0))


def register_class_routes(app, factory, write_lock):
    session = session_dependency(factory)

    def get_project(db, project_id):
        project = db.get(Project, project_id)
        if not project:
            raise HTTPException(404, "프로젝트를 찾을 수 없습니다.")
        return project

    def templates_of(db, project_id):
        return {
            t.class_label: t for t in db.scalars(select(ClassTemplate).where(ClassTemplate.project_id == project_id))
        }

    def template_modality(db, image):
        """Modality of a template REF: the pair that owns the image decides, else folder/file names."""
        owner = db.scalar(select(Pair).where(Pair.reference_image_id == image.id, Pair.folder == image.folder))
        return owner.modality if owner and owner.modality else modality_of(image.folder, image.file_name)

    def template_dict(db, template):
        image = db.get(ImageRecord, template.reference_image_id) if template.reference_image_id else None
        return {
            "class_label": template.class_label,
            "image": image_dict(db, image),
            "modality": template_modality(db, image) if image else "",
            "updated_at": template.updated_at,
        }

    @app.get("/api/projects/{project_id}/classes")
    def list_classes(project_id: str, db=Depends(session)):
        get_project(db, project_id)
        pairs = list(db.scalars(select(Pair).where(Pair.project_id == project_id)))
        templates = templates_of(db, project_id)
        labels = sorted({p.class_label for p in pairs if p.class_label} | set(templates), key=str.lower)
        result = []
        for label in labels:
            members = [p for p in pairs if p.class_label == label]
            result.append(
                {
                    "class_label": label,
                    "count": len(members),
                    "enabled": sum(p.enabled for p in members),
                    "unlinked": sum(p.reference_image_id is None for p in members),
                    "modalities": {m: sum(p.modality == m for p in members) for m in ["OM", "SEM"]},
                    "template": template_dict(db, templates[label]) if label in templates else None,
                }
            )
        return {
            "classes": result,
            "unassigned": sum(not p.class_label for p in pairs),
            "unlinked": sum(p.reference_image_id is None for p in pairs),
        }

    @app.put("/api/projects/{project_id}/classes/{class_label}/template")
    def set_template(project_id: str, class_label: str, data: ClassTemplateInput, db=Depends(session)):
        with write_lock:
            get_project(db, project_id)
            label = class_label.strip()
            if not label:
                raise HTTPException(422, "클래스 이름이 비어 있습니다.")
            image = db.get(ImageRecord, data.image_id)
            if not image or image.project_id != project_id:
                raise HTTPException(404, "프로젝트에 없는 이미지입니다.")
            if image.role != "REF" or image.error:
                raise HTTPException(422, "읽을 수 있는 REF 이미지만 대표 템플릿으로 지정할 수 있습니다.")
            template = templates_of(db, project_id).get(label)
            if template is None:
                template = ClassTemplate(project_id=project_id, class_label=label)
                db.add(template)
            template.reference_image_id = image.id
            template.updated_at = now()
            db.commit()
            return template_dict(db, template)

    @app.delete("/api/projects/{project_id}/classes/{class_label}/template", status_code=204)
    def clear_template(project_id: str, class_label: str, db=Depends(session)):
        with write_lock:
            get_project(db, project_id)
            template = templates_of(db, project_id).get(class_label.strip())
            if template:
                db.delete(template)
                db.commit()
        return None

    @app.post("/api/projects/{project_id}/classes/attach")
    def attach(project_id: str, data: AttachInput, db=Depends(session)):
        """Give pairs a class; pairs without a REF of their own get the class template REF."""
        with write_lock:
            _, pairs = checked_pairs(db, project_id, data.pairs)
            label = data.class_label.strip()
            template = templates_of(db, project_id).get(label)
            template_image = (
                db.get(ImageRecord, template.reference_image_id) if template and template.reference_image_id else None
            )
            updated = linked = 0
            for item in data.pairs:
                pair = pairs[item.id]
                changed = pair.class_label != label
                pair.class_label = label
                if pair.reference_image_id is None and template_image is not None:
                    if pair.modality and template_modality(db, template_image) not in {"", pair.modality}:
                        raise HTTPException(422, f"{pair.folder}: 모달리티({pair.modality})가 템플릿 REF와 다릅니다.")
                    pair.reference_image_id = template_image.id
                    linked += 1
                    changed = True
                if changed:
                    pair.revision += 1
                    pair.updated_at = now()
                    updated += 1
            db.commit()
            return {"updated": updated, "linked": linked, "template": bool(template_image)}

    @app.post("/api/projects/{project_id}/classes/match")
    def match(project_id: str, data: MatchInput, db=Depends(session)):
        """Rank class templates by appearance similarity to each pair's Query image."""
        project, pairs = checked_pairs(db, project_id, data.pairs)
        templates = templates_of(db, project_id)
        features = {}
        for label, template in templates.items():
            image = db.get(ImageRecord, template.reference_image_id) if template.reference_image_id else None
            try:
                features[label] = (
                    appearance_features(image_bytes(db, app, project, image)),
                    template_modality(db, image),
                )
            except (OSError, ValueError, Image.DecompressionBombError):
                continue
        if not features:
            raise HTTPException(
                422, "대표 REF가 지정된 클래스가 없습니다. Classes에서 클래스마다 대표 REF를 지정하세요."
            )
        results = []
        for pair in sorted(pairs.values(), key=lambda p: (p.folder, p.id)):
            try:
                query = db.get(ImageRecord, pair.query_image_id) if pair.query_image_id else None
                vector = appearance_features(image_bytes(db, app, project, query))
            except (OSError, ValueError, Image.DecompressionBombError) as exc:
                results.append({"id": pair.id, "folder": pair.folder, "error": str(exc), "candidates": []})
                continue
            candidates = [
                {"class_label": label, "score": cosine(vector, vec), "modality": modality}
                for label, (vec, modality) in features.items()
                if not pair.modality or not modality or modality == pair.modality
            ]
            candidates.sort(key=lambda c: c["score"], reverse=True)
            results.append(
                {
                    "id": pair.id,
                    "revision": pair.revision,
                    "folder": pair.folder,
                    "modality": pair.modality,
                    "current": pair.class_label,
                    "candidates": candidates[: data.top_k],
                }
            )
        return {"algorithm": "appearance-cosine-v1", "results": results}

    @app.post("/api/projects/{project_id}/markings/apply")
    def apply_markings(project_id: str, data: MarkingsInput, db=Depends(session)):
        """REF white box → ROI annotation; Query white cross → automatic (unconfirmed) GT."""
        with write_lock:
            project, pairs = checked_pairs(db, project_id, data.pairs)
            results = []
            for item in data.pairs:
                pair = pairs[item.id]
                outcome = {"id": pair.id, "folder": pair.folder, "roi": "skipped", "gt": "skipped"}
                changed = False
                if data.roi:
                    ref = db.get(ImageRecord, pair.reference_image_id) if pair.reference_image_id else None
                    try:
                        if ref is None:
                            raise ValueError("REF 미연결")
                        existing = db.scalar(
                            select(ReferenceAnnotation)
                            .where(ReferenceAnnotation.pair_id == pair.id)
                            .order_by(ReferenceAnnotation.revision.desc())
                        )
                        if existing and existing.image_hash == ref.file_hash and not data.replace_existing:
                            outcome["roi"] = "kept"
                        else:
                            box = detect_markings(load_pixels(image_bytes(db, app, project, ref)))["box"]
                            if box is None:
                                outcome["roi"] = "none"
                            else:
                                pair.revision += 1
                                changed = True
                                db.add(
                                    ReferenceAnnotation(
                                        pair_id=pair.id,
                                        image_hash=ref.file_hash,
                                        box=[box["x0"], box["y0"], box["x1"], box["y1"]],
                                        center=[(box["x0"] + box["x1"]) / 2, (box["y0"] + box["y1"]) / 2],
                                        source="ref_box_auto",
                                        revision=pair.revision,
                                    )
                                )
                                outcome["roi"] = "saved"
                    except (OSError, ValueError, Image.DecompressionBombError) as exc:
                        outcome["roi"] = f"error: {exc}"
                if data.gt:
                    query = db.get(ImageRecord, pair.query_image_id) if pair.query_image_id else None
                    try:
                        if pair.gt_source == "manual" and not data.replace_existing:
                            outcome["gt"] = "kept"
                        elif pair.gt_x is not None and not data.replace_existing:
                            outcome["gt"] = "kept"
                        else:
                            cross = detect_markings(load_pixels(image_bytes(db, app, project, query)))["cross"]
                            if cross is None:
                                outcome["gt"] = "none"
                            else:
                                before = gt_value(pair)
                                pair.gt_x = (cross["x0"] + cross["x1"]) / 2
                                pair.gt_y = (cross["y0"] + cross["y1"]) / 2
                                pair.gt_source = "auto_cross"
                                db.add(
                                    GTHistory(
                                        pair_id=pair.id,
                                        before=before,
                                        after=gt_value(pair),
                                        reason="흰 십자선에서 자동 GT",
                                    )
                                )
                                if not changed:
                                    pair.revision += 1
                                changed = True
                                outcome["gt"] = "saved"
                    except (OSError, ValueError, Image.DecompressionBombError) as exc:
                        outcome["gt"] = f"error: {exc}"
                if changed:
                    pair.updated_at = now()
                results.append(outcome)
            db.commit()
            return {"results": results}
