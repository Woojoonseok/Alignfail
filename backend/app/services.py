import re
from collections import defaultdict
from pathlib import Path

from fastapi import HTTPException
from PIL import Image, UnidentifiedImageError
from sqlalchemy import select

from .models import GTHistory, ImageRecord, Pair, Project, ReferenceAnnotation, now
from .storage import active_cleanup, digest, project_directories

IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".bmp", ".tif", ".tiff", ".webp"}
# "OM" as its own token in the file name (sample_OM_01, OM-3, om.png); anything else is SEM.
OM_TOKEN = re.compile(r"(?<![A-Za-z])OM(?![A-Za-z])", re.IGNORECASE)


def modality_of(*names: str) -> str:
    """OM when any given file or folder name carries the OM token, otherwise SEM."""
    return "OM" if any(OM_TOKEN.search(name) for name in names) else "SEM"


def match_result_of(file_name: str) -> str:
    """Production exports start with s (matched, cross drawn) or e (failed, no cross)."""
    first = file_name[:1].lower()
    return {"s": "success", "e": "fail"}.get(first, "unknown")


def is_ref(file_name: str) -> bool:
    return "ref" in file_name.lower()


def checked_pairs(db, project_id, requests):
    """Resolve (id, revision) requests to Pair rows of the project, rejecting stale revisions."""
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


def inspect_image(path: Path):
    try:
        file_hash = digest(path)
        with Image.open(path) as image:
            image.load()
            width, height = image.size
            mode = image.mode
        return dict(file_hash=file_hash, width=width, height=height, mode=mode, error=None)
    except (OSError, ValueError, UnidentifiedImageError, Image.DecompressionBombError) as exc:
        return dict(file_hash=None, width=None, height=None, mode=None, error=f"이미지 읽기 실패: {type(exc).__name__}")


def gt_value(pair):
    return {"x": pair.gt_x, "y": pair.gt_y, "source": pair.gt_source}


def clear_gt(db, pair, reason):
    if pair.gt_x is not None or pair.gt_y is not None:
        before = gt_value(pair)
        pair.gt_x = pair.gt_y = None
        pair.gt_source = "none"
        db.add(GTHistory(pair_id=pair.id, before=before, after=gt_value(pair), reason=reason))


def directory_items(root: Path, paired_folders: set[Path]):
    """Keep REF folders together; otherwise import each image as a Query."""
    entries = sorted((p for p in root.iterdir() if not p.is_symlink()), key=lambda p: p.name.lower())
    files = [p for p in entries if p.is_file() and p.suffix.lower() in IMAGE_SUFFIXES]
    if root in paired_folders or any(is_ref(p.name) for p in files):
        yield root, files, True
    else:
        for path in files:
            yield path, [path], False
    for folder in entries:
        if folder.is_dir():
            yield from directory_items(folder, paired_folders)


def import_directory(db, project, root: Path, *, dataset_split: str | None = None):
    source_pairs = list(
        db.scalars(select(Pair).where(Pair.project_id == project.id, Pair.source_directory == str(root)))
    )
    existing_splits = {p.dataset_split for p in source_pairs}
    if dataset_split is not None and existing_splits and existing_splits != {dataset_split}:
        raise HTTPException(409, "이미 다른 용도로 등록한 폴더입니다. 재검색은 기존 Train/Test 구분을 유지합니다.")
    selected_split = dataset_split or next(iter(existing_splits), "train")
    roots = project_directories(project)
    if str(root) not in roots:
        if any(root.is_relative_to(Path(p)) or Path(p).is_relative_to(root) for p in roots):
            raise HTTPException(409, "이미 등록한 폴더의 상위/하위 경로입니다. 등록한 폴더를 재검색하세요.")
        roots.append(str(root))
    index = roots.index(str(root))
    prefix = "" if index == 0 else f"{root.name} [{index + 1}]/"
    if dataset_split is not None or any(p.sample_role != "pair" for p in source_pairs):
        return import_samples(db, project, root, selected_split, roots, prefix, source_pairs)
    images = {i.file_path: i for i in db.scalars(select(ImageRecord).where(ImageRecord.project_id == project.id))}
    pairs = {p.folder: p for p in db.scalars(select(Pair).where(Pair.project_id == project.id))}
    # Preserve existing folder-pair IDs even when their REF has since disappeared.
    paired_folders = {
        root / p.folder.removeprefix(prefix)
        for p in pairs.values()
        if (p.source_directory or project.root_directory) == str(root)
        and (root / p.folder.removeprefix(prefix)).is_dir()
    }
    counts = {"new_pairs": 0, "updated_pairs": 0, "images": 0, "invalid_pairs": 0}
    seen_folders = set()
    for entry, files, paired in directory_items(root, paired_folders):
        relative_folder = (entry if paired else entry.parent).relative_to(root)
        class_label = (relative_folder.parts[0] if relative_folder.parts else root.name).strip()
        if not class_label or len(class_label) > 200:
            raise HTTPException(422, "클래스로 사용할 폴더 이름은 1~200자여야 합니다.")
        name = prefix + (entry.relative_to(root).as_posix() if entry != root else ".")
        seen_folders.add(name)
        pair = pairs.get(name)
        if pair is not None and (pair.source_directory or project.root_directory) != str(root):
            raise HTTPException(409, "등록 항목 이름이 충돌합니다. 폴더 이름을 변경해 다시 가져오세요.")
        if pair is None:
            pair = Pair(project_id=project.id, folder=name, source_directory=str(root), dataset_split=selected_split)
            db.add(pair)
            db.flush()
            counts["new_pairs"] += 1
        else:
            counts["updated_pairs"] += 1
        if not pair.class_label:
            pair.class_label = class_label
        old_query_id = pair.query_image_id
        old_query = db.get(ImageRecord, old_query_id) if old_query_id else None
        old_hash = old_query.file_hash if old_query else None
        roles = {"REF": [], "QUERY": []}
        for path in files:
            if path.is_symlink() or path.suffix.lower() not in IMAGE_SUFFIXES:
                continue
            key = str(path.resolve())
            record = images.get(key)
            if record is None:
                record = ImageRecord(
                    project_id=project.id,
                    folder=name,
                    file_path=key,
                    file_name=path.name,
                    role="REF" if paired and is_ref(path.name) else "QUERY",
                )
                db.add(record)
                db.flush()
                images[key] = record
            record.folder = name
            record.role = "REF" if paired and is_ref(path.name) else "QUERY"
            for attr, value in inspect_image(path).items():
                setattr(record, attr, value)
            roles[record.role].append(record)
            counts["images"] += 1
        issues = []
        queries = roles["QUERY"]
        pair.query_image_id = queries[0].id if len(queries) == 1 else None
        if len(queries) != 1:
            issues.append(f"QUERY 이미지가 {len(queries)}장입니다. 정확히 1장이 필요합니다.")
        refs = roles["REF"]
        if len(refs) == 1:
            pair.reference_image_id = refs[0].id
        elif len(refs) > 1:
            pair.reference_image_id = None
            issues.append(f"REF 이미지가 {len(refs)}장입니다. 최대 1장이어야 합니다.")
        else:
            # No REF of its own: keep a REF linked from a class template, otherwise stay unlinked.
            linked = db.get(ImageRecord, pair.reference_image_id) if pair.reference_image_id else None
            if linked is None or linked.folder == name:
                pair.reference_image_id = None
        for record in refs + queries:
            if record.error:
                issues.append(f"{record.file_name}: {record.error}")
        if not pair.modality:
            pair.modality = modality_of(name, *(r.file_name for r in refs + queries))
        # The s*/e* convention belongs to production exports, which arrive as loose files; folder
        # pairs keep "unknown" so a query called sample.png is not mistaken for a success.
        pair.match_result = match_result_of(queries[0].file_name) if len(queries) == 1 and not paired else "unknown"
        current_query = db.get(ImageRecord, pair.query_image_id) if pair.query_image_id else None
        if old_query_id != pair.query_image_id or old_hash != (current_query.file_hash if current_query else None):
            clear_gt(db, pair, "QUERY 파일 변경으로 GT 재검토 필요")
        pair.import_issues = issues
        pair.revision += 1
        pair.updated_at = now()
        counts["invalid_pairs"] += bool(issues)
    for name, pair in pairs.items():
        if (pair.source_directory or project.root_directory) == str(root) and name not in seen_folders:
            pair.import_issues = ["Pair 폴더가 없습니다. 원본 경로를 확인하거나 Pair를 제외하세요."]
            pair.revision += 1
            pair.updated_at = now()
    if not project.root_directory:
        project.root_directory = str(root)
    project.data_directories = roots
    db.flush()
    return counts


def import_samples(db, project, root, split, roots, prefix, existing):
    """One uploaded file = one REF training sample or one Query test sample."""
    role = "reference" if split == "train" else "query"
    images = {r.file_path: r for r in db.scalars(select(ImageRecord).where(ImageRecord.project_id == project.id))}
    # Query GT belongs to the original query even when converting an old paired import.
    owners = {p.query_image_id or p.reference_image_id: p for p in existing}
    ref_annotations = {
        p.reference_image_id: list(db.scalars(select(ReferenceAnnotation).where(ReferenceAnnotation.pair_id == p.id)))
        for p in existing
        if p.reference_image_id
    }
    seen = set()
    counts = dict(new_pairs=0, updated_pairs=0, images=0, invalid_pairs=0)
    for _entry, files, _ in directory_items(root, set()):
        for path in files:
            relative = path.relative_to(root)
            label = (relative.parts[0] if len(relative.parts) > 1 else root.name).strip()
            if not label or len(label) > 200:
                raise HTTPException(422, "클래스로 사용할 폴더 이름은 1~200자여야 합니다.")
            key = str(path.resolve())
            record = images.get(key)
            if record is None:
                record = ImageRecord(
                    project_id=project.id,
                    file_path=key,
                    file_name=path.name,
                    folder=prefix + relative.as_posix(),
                    role="REF" if split == "train" else "QUERY",
                )
                db.add(record)
                db.flush()
                images[key] = record
            pair = owners.get(record.id)
            if pair is None:
                pair = Pair(project_id=project.id, folder=prefix + relative.as_posix(), source_directory=str(root))
                db.add(pair)
                db.flush()
                counts["new_pairs"] += 1
            else:
                counts["updated_pairs"] += 1
            previous_hash = record.file_hash
            for attr, value in inspect_image(path).items():
                setattr(record, attr, value)
            if previous_hash and previous_hash != record.file_hash:
                clear_gt(db, pair, "학습/평가 이미지 변경으로 GT 재검토 필요")
            pair.folder = record.folder = prefix + relative.as_posix()
            pair.sample_role = role
            pair.dataset_split = split
            pair.reference_image_id = record.id if split == "train" else None
            pair.query_image_id = record.id if split == "test" else None
            record.role = "REF" if split == "train" else "QUERY"
            pair.class_label = pair.class_label or label
            pair.modality = pair.modality or modality_of(relative.as_posix())
            pair.match_result = match_result_of(path.name)
            pair.import_issues = [record.error] if record.error else []
            cleanup = active_cleanup(db, record.id)
            if (
                split == "train"
                and cleanup
                and cleanup.source_hash == record.file_hash
                and pair.gt_x is None
                and pair.gt_y is None
                and pair.gt_source != "manual"
            ):
                cross = cleanup.config.get("parameters", {}).get("cross")
                if cross:
                    before = gt_value(pair)
                    pair.gt_x = (cross["x0"] + cross["x1"]) / 2
                    pair.gt_y = (cross["y0"] + cross["y1"]) / 2
                    pair.gt_source = "auto_cross"
                    db.add(
                        GTHistory(
                            pair_id=pair.id,
                            before=before,
                            after=gt_value(pair),
                            reason="Train REF 역할 복구 · 십자선 중심 GT",
                        )
                    )
            pair.revision += 1
            pair.updated_at = now()
            # Keep old REF ROI/history on the sample that actually owns those pixels.
            if split == "train":
                for annotation in ref_annotations.get(record.id, []):
                    annotation.pair_id = pair.id
            seen.add(pair.id)
            counts["images"] += 1
            counts["invalid_pairs"] += bool(pair.import_issues)
    for pair in existing:
        if pair.id not in seen:
            pair.import_issues = ["등록한 이미지가 원본 폴더에 없습니다."]
    project.root_directory = project.root_directory or str(root)
    project.data_directories = roots
    db.flush()
    return counts


def image_dict(db, image):
    if image is None:
        return None
    result = {
        key: getattr(image, key)
        for key in ["id", "file_name", "file_path", "role", "file_hash", "width", "height", "mode", "error"]
    }
    clean = active_cleanup(db, image.id)
    result["cleanup"] = (
        None
        if clean is None
        else {
            **{
                key: getattr(clean, key)
                for key in [
                    "id",
                    "source_hash",
                    "clean_path",
                    "clean_hash",
                    "mask_path",
                    "mask_hash",
                    "config",
                    "created_at",
                ]
            },
            "stale": clean.source_hash != image.file_hash,
        }
    )
    return result


def pair_dict(db, pair):
    result = {
        key: getattr(pair, key)
        for key in [
            "id",
            "project_id",
            "folder",
            "gt_x",
            "gt_y",
            "gt_source",
            "group_key",
            "class_label",
            "dataset_split",
            "sample_role",
            "modality",
            "match_result",
            "tier",
            "notes",
            "enabled",
            "exclude_reason",
            "import_issues",
            "revision",
            "updated_at",
        ]
    }
    result["reference"] = (
        image_dict(db, db.get(ImageRecord, pair.reference_image_id)) if pair.reference_image_id else None
    )
    result["query"] = image_dict(db, db.get(ImageRecord, pair.query_image_id)) if pair.query_image_id else None
    result["pattern_type"] = pair.pattern_type
    reference = db.get(ImageRecord, pair.reference_image_id) if pair.reference_image_id else None
    # True when the REF comes from a class template rather than this pair's own folder.
    result["reference_shared"] = bool(reference and reference.folder != pair.folder)
    annotation = db.scalar(
        select(ReferenceAnnotation)
        .where(ReferenceAnnotation.pair_id == pair.id)
        .order_by(ReferenceAnnotation.revision.desc())
    )
    result["reference_annotation"] = (
        None
        if not annotation
        else {
            key: getattr(annotation, key)
            for key in ["id", "image_hash", "box", "center", "source", "revision", "created_at"]
        }
    )
    return result


def audit_dataset(db, project_id, dataset_split=None):
    statement = select(Pair).where(Pair.project_id == project_id)
    if dataset_split:
        statement = statement.where(Pair.dataset_split == dataset_split)
    pairs = list(db.scalars(statement.order_by(Pair.folder)))
    issues = []
    hashes = defaultdict(list)
    checked = {}

    def add(pair, code, message, severity="error"):
        issues.append(
            {
                "pair_id": pair.id,
                "folder": pair.folder,
                "code": code,
                "message": message,
                "severity": severity if pair.enabled else "warning",
            }
        )

    for pair in pairs:
        for issue in pair.import_issues:
            add(pair, "INVALID_PAIR", issue)
        for role, image_id in [("REF", pair.reference_image_id), ("QUERY", pair.query_image_id)]:
            if not image_id:
                if role == "REF" and pair.sample_role != "query":
                    add(
                        pair,
                        "REF_UNLINKED",
                        "REF가 없습니다. Classes에서 템플릿 클래스에 붙이면 대표 REF가 연결됩니다.",
                        "warning",
                    )
                elif role == "QUERY" and pair.sample_role != "reference" and not pair.import_issues:
                    add(pair, "MISSING_IMAGE", f"{role} 이미지가 없습니다.")
                continue
            image = db.get(ImageRecord, image_id)
            if image_id not in checked:
                checked[image_id] = inspect_image(Path(image.file_path))
            current = checked[image_id]
            if current["error"]:
                add(pair, "BROKEN_FILE", f"{role}: 파일이 없거나 읽을 수 없습니다.")
            elif image.file_hash != current["file_hash"]:
                add(pair, "FILE_CHANGED", f"{role}: 등록 후 파일이 바뀌었습니다. 폴더를 재검색하세요.")
            clean = active_cleanup(db, image.id)
            if clean:
                if clean.source_hash != current["file_hash"]:
                    add(
                        pair,
                        "STALE_CLEAN",
                        f"{role}: 원본이 변경되어 표시 제거를 다시 실행하거나 원본 사용으로 되돌려야 합니다.",
                    )
                for field in ["clean", "mask"]:
                    try:
                        valid = digest(Path(getattr(clean, f"{field}_path"))) == getattr(clean, f"{field}_hash")
                    except OSError:
                        valid = False
                    if not valid:
                        add(
                            pair,
                            "BROKEN_CLEAN",
                            f"{role}: {field} 캐시가 없거나 변경되었습니다. 표시 제거를 다시 실행하세요.",
                        )
            if pair.enabled and current["file_hash"]:
                hashes[current["file_hash"]].append(
                    {"pair_id": pair.id, "folder": pair.folder, "role": role, "group_key": pair.group_key}
                )
        target_id = pair.reference_image_id if pair.sample_role == "reference" else pair.query_image_id
        query = db.get(ImageRecord, target_id) if target_id else None
        if pair.gt_x is None or pair.gt_y is None:
            add(
                pair,
                "MISSING_GT",
                "REF 기준 GT를 지정하세요." if pair.sample_role == "reference" else "Query GT를 지정하세요.",
                "warning" if pair.dataset_split == "test" else "error",
            )
        elif (
            query
            and query.width
            and query.height
            and not (0 <= pair.gt_x < query.width and 0 <= pair.gt_y < query.height)
        ):
            add(pair, "INVALID_GT", "GT가 원본 이미지 범위를 벗어났습니다.")
        if pair.enabled and pair.dataset_split == "train" and not pair.group_key:
            add(pair, "GROUP_UNASSIGNED", "데이터 그룹 미지정: Split 생성 전에 연관 Pair를 묶어야 합니다.", "warning")
        if pair.enabled and pair.gt_source == "auto_cross":
            add(
                pair, "AUTO_GT_UNCONFIRMED", "흰 십자선에서 자동 지정한 GT입니다. 확인 후 학습에 사용하세요.", "warning"
            )
    duplicates = []
    for file_hash, occurrences in hashes.items():
        if len(occurrences) < 2:
            continue
        duplicates.append({"file_hash": file_hash, "occurrences": occurrences})
        for occurrence in occurrences:
            pair = next(p for p in pairs if p.id == occurrence["pair_id"])
            add(pair, "DUPLICATE_FILE", f"동일 파일 {len(occurrences)}건: 촬영 출처와 그룹을 확인하세요.", "warning")
    enabled = sum(p.enabled for p in pairs)
    errors = sum(i["severity"] == "error" for i in issues)
    return {
        "checked_at": now(),
        "pair_count": len(pairs),
        "enabled_count": enabled,
        "errors": errors,
        "warnings": len(issues) - errors,
        "passed": errors == 0 and enabled > 0,
        "issues": issues,
        "duplicates": duplicates,
        "scope": "파일·Pair·GT 검사입니다. Split 간 누수 검사는 아직 수행하지 않습니다.",
    }
