"""Browser folder uploads are copied into independent, managed data sources."""

import shutil
import tempfile
from pathlib import Path, PurePosixPath
from typing import Literal

from fastapi import HTTPException, Request
from starlette.concurrency import run_in_threadpool
from starlette.datastructures import UploadFile

from .models import Project
from .services import IMAGE_SUFFIXES, import_directory


def upload_path(filename: str) -> PurePosixPath:
    parts = filename.split("/")
    if len(parts) < 2 or any(
        not p
        or p in {".", ".."}
        or p.endswith((".", " "))
        or any(c in p for c in '\\:<>"|?*')
        or any(ord(c) < 32 for c in p)
        or p.split(".")[0].upper()
        in {"CON", "PRN", "AUX", "NUL", *[f"COM{i}" for i in range(1, 10)], *[f"LPT{i}" for i in range(1, 10)]}
        for p in parts
    ):
        raise HTTPException(422, "폴더 내 파일 경로가 올바르지 않습니다.")
    return PurePosixPath(*parts)


def register_upload_routes(app, factory, write_lock):
    def save_uploads(project_id, files, dataset_split):
        with write_lock, factory() as db:
            project = db.get(Project, project_id)
            if project is None:
                raise HTTPException(404, "프로젝트를 찾을 수 없습니다.")
            selected = []
            seen = set()
            folder_names = set()
            for file in files:
                path = upload_path(file.filename or "")
                if path.suffix.lower() not in IMAGE_SUFFIXES:
                    continue
                key = path.as_posix().casefold()
                if key in seen:
                    raise HTTPException(422, "중복된 파일 경로가 있습니다.")
                seen.add(key)
                folder_names.add(path.parts[0])
                selected.append((file, path))
            if not selected:
                raise HTTPException(422, "선택한 폴더에 지원하는 이미지가 없습니다.")
            if len(folder_names) != 1:
                raise HTTPException(422, "한 번에 하나의 폴더를 선택하세요.")
            upload_base = app.state.state_dir / "uploads" / project_id
            upload_base.mkdir(parents=True, exist_ok=True)
            batch = Path(tempfile.mkdtemp(prefix="batch-", dir=upload_base)).resolve()
            try:
                total = 0
                for file, relative in selected:
                    target = batch.joinpath(*relative.parts)
                    target.parent.mkdir(parents=True, exist_ok=True)
                    size = 0
                    with target.open("xb") as output:
                        while chunk := file.file.read(1024 * 1024):
                            size += len(chunk)
                            total += len(chunk)
                            if size > 256 * 1024**2 or total > 4 * 1024**3:
                                raise HTTPException(413, "이미지당 256 MB, 폴더당 4 GB까지 업로드할 수 있습니다.")
                            output.write(chunk)
                root = batch / next(iter(folder_names))
                result = import_directory(db, project, root, dataset_split=dataset_split)
                db.commit()
                return result
            except Exception:
                db.rollback()
                # Only this request's freshly created batch is removed on failure.
                shutil.rmtree(batch)
                raise

    @app.post("/api/projects/{project_id}/upload")
    async def upload_folder(project_id: str, request: Request, dataset_split: Literal["train", "test"] = "train"):
        async with request.form(max_files=10000, max_fields=0) as form:
            files = form.getlist("files")
            if not files or any(not isinstance(file, UploadFile) for file in files):
                raise HTTPException(422, "이미지 폴더를 선택하세요.")
            try:
                return await run_in_threadpool(save_uploads, project_id, files, dataset_split)
            except OSError as exc:
                raise HTTPException(422, "이미지를 저장할 수 없습니다. 저장 공간과 파일 경로를 확인하세요.") from exc
