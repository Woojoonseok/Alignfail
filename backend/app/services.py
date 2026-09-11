import re
from collections import defaultdict
from pathlib import Path

from fastapi import HTTPException
from PIL import Image, UnidentifiedImageError
from sqlalchemy import select

from .models import GTHistory, ImageRecord, Pair, Project, ReferenceAnnotation, now
from .storage import active_cleanup, digest

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


def import_directory(db, project, root: Path):
    images = {i.file_path: i for i in db.scalars(select(ImageRecord).where(ImageRecord.project_id == project.id))}
    pairs = {p.folder: p for p in db.scalars(select(Pair).where(Pair.project_id == project.id))}
    counts = {"new_pairs": 0, "updated_pairs": 0, "images": 0, "invalid_pairs": 0}
    entries = sorted(
        [p for p in root.iterdir() if not p.is_symlink() and (p.is_dir() or p.suffix.lower() in IMAGE_SUFFIXES)],
        key=lambda p: p.name.lower(),
    )
    seen_folders = set()
    for entry in entries:
        # A sub-folder is one pair (REF + Query); a loose image directly under the root is a
        # Query-only pair (e.g. production exports that arrive without a REF).
        name = entry.name
        files = sorted(p for p in entry.iterdir() if p.is_file()) if entry.is_dir() else [entry]
        seen_folders.add(name)
        pair = pairs.get(name)
        if pair is None:
            pair = Pair(project_id=project.id, folder=name)
            db.add(pair)
            db.flush()
            counts["new_pairs"] += 1
        else:
            counts["updated_pairs"] += 1
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
                    role="REF" if entry.is_dir() and is_ref(path.name) else "QUERY",
                )
                db.add(record)
                db.flush()
                images[key] = record
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
        pair.match_result = (
            match_result_of(queries[0].file_name) if len(queries) == 1 and not entry.is_dir() else "unknown"
        )
        current_query = db.get(ImageRecord, pair.query_image_id) if pair.query_image_id else None
        if old_query_id != pair.query_image_id or old_hash != (current_query.file_hash if current_query else None):
            clear_gt(db, pair, "QUERY 파일 변경으로 GT 재검토 필요")
        pair.import_issues = issues
        pair.revision += 1
        pair.updated_at = now()
        counts["invalid_pairs"] += bool(issues)
    for name, pair in pairs.items():
        if name not in seen_folders:
            pair.import_issues = ["Pair 폴더가 없습니다. 원본 경로를 확인하거나 Pair를 제외하세요."]
            pair.revision += 1
            pair.updated_at = now()
    project.root_directory = str(root)
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


def audit_dataset(db, project_id):
    pairs = list(db.scalars(select(Pair).where(Pair.project_id == project_id).order_by(Pair.folder)))
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
                if role == "REF":
                    add(
                        pair,
                        "REF_UNLINKED",
                        "REF가 없습니다. Classes에서 템플릿 클래스에 붙이면 대표 REF가 연결됩니다.",
                        "warning",
                    )
                elif not pair.import_issues:
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
        query = db.get(ImageRecord, pair.query_image_id) if pair.query_image_id else None
        if pair.gt_x is None or pair.gt_y is None:
            add(pair, "MISSING_GT", "Query GT를 지정하세요.")
        elif (
            query
            and query.width
            and query.height
            and not (0 <= pair.gt_x < query.width and 0 <= pair.gt_y < query.height)
        ):
            add(pair, "INVALID_GT", "GT가 원본 이미지 범위를 벗어났습니다.")
        if pair.enabled and not pair.group_key:
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
