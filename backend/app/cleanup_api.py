import base64
import hashlib
from pathlib import Path

from fastapi import Depends, HTTPException
from fastapi.responses import FileResponse
from PIL import Image
from sqlalchemy import or_, select, update

from .cleaning import clean_pixels, detect_markings, load_pixels
from .models import ImageCleanup, ImageRecord, Pair, Project, now, uid
from .schemas import CleanupInput, CleanupSource


def register_cleanup_routes(app, factory, write_lock):
    def session():
        with factory() as db:
            yield db

    def read_image(db, image_id, expected_hash=None):
        record = db.get(ImageRecord, image_id)
        if not record:
            raise HTTPException(404, "이미지를 찾을 수 없습니다.")
        project = db.get(Project, record.project_id)
        path = Path(record.file_path).resolve()
        if not path.is_relative_to(Path(project.root_directory).resolve()):
            raise HTTPException(403, "데이터 폴더 외부 이미지는 처리하지 않습니다.")
        try:
            content = path.read_bytes()
        except OSError as exc:
            raise HTTPException(422, "원본 이미지를 읽을 수 없습니다.") from exc
        current_hash = hashlib.sha256(content).hexdigest()
        if current_hash != record.file_hash or (expected_hash and expected_hash != current_hash):
            raise HTTPException(409, "원본 이미지가 변경되었습니다. 폴더를 재검색한 뒤 다시 처리하세요.")
        try:
            return record, load_pixels(content)
        except (OSError, ValueError, Image.DecompressionBombError) as exc:
            raise HTTPException(422, str(exc)) from exc

    def render(db, image_id, config):
        record, pixels = read_image(db, image_id, config.source_hash)
        try:
            clean, mask, info = clean_pixels(pixels, config)
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from exc
        return record, clean, mask, info

    def update_pairs(db, image_id):
        # Changing the displayed clean image must invalidate stale editor revisions.
        db.execute(update(Pair).where(or_(Pair.reference_image_id == image_id, Pair.query_image_id == image_id))
                   .values(revision=Pair.revision + 1, updated_at=now()))

    @app.get("/api/images/{image_id}/clean/detect")
    def detect(image_id: str, db=Depends(session)):
        record, pixels = read_image(db, image_id)
        return {"source_hash": record.file_hash, **detect_markings(pixels)}

    @app.post("/api/images/{image_id}/clean/preview")
    def preview(image_id: str, config: CleanupInput, db=Depends(session)):
        _, clean, mask, info = render(db, image_id, config)
        return {"preview_url": "data:image/png;base64," + base64.b64encode(clean).decode(),
                "mask_url": "data:image/png;base64," + base64.b64encode(mask).decode(), "info": info}

    @app.post("/api/images/{image_id}/clean", status_code=201)
    def save(image_id: str, config: CleanupInput, db=Depends(session)):
        with write_lock:
            record, clean, mask, info = render(db, image_id, config)
            cleanup_id = uid()
            directory = app.state.state_dir.resolve() / "clean" / record.id / cleanup_id
            try:
                directory.mkdir(parents=True)
                (directory / "clean.png").write_bytes(clean)
                (directory / "mask.png").write_bytes(mask)
            except OSError as exc:
                raise HTTPException(500, "정리된 이미지 저장에 실패했습니다. 저장 공간과 쓰기 권한을 확인하세요.") from exc
            db.execute(update(ImageCleanup).where(ImageCleanup.image_id == image_id).values(active=False))
            result = ImageCleanup(id=cleanup_id, image_id=image_id, source_hash=record.file_hash, config=info,
                                  clean_path=str(directory / "clean.png"), clean_hash=hashlib.sha256(clean).hexdigest(),
                                  mask_path=str(directory / "mask.png"), mask_hash=hashlib.sha256(mask).hexdigest())
            db.add(result)
            update_pairs(db, image_id)
            db.commit()
            return {"id": result.id, "clean_hash": result.clean_hash, "info": info}

    @app.post("/api/images/{image_id}/clean/reset")
    def reset(image_id: str, config: CleanupSource, db=Depends(session)):
        with write_lock:
            record = db.get(ImageRecord, image_id)
            if not record:
                raise HTTPException(404, "이미지를 찾을 수 없습니다.")
            if record.file_hash != config.source_hash:
                raise HTTPException(409, "원본 등록 정보가 변경되었습니다. 새로고침하세요.")
            db.execute(update(ImageCleanup).where(ImageCleanup.image_id == image_id).values(active=False))
            update_pairs(db, image_id)
            db.commit()
            return {"reset": True}

    @app.get("/api/cleanups/{cleanup_id}/image")
    def serve(cleanup_id: str, mask: bool = False, download: bool = False, db=Depends(session)):
        cleanup = db.get(ImageCleanup, cleanup_id)
        if not cleanup:
            raise HTTPException(404, "정리된 이미지를 찾을 수 없습니다.")
        path = Path(cleanup.mask_path if mask else cleanup.clean_path).resolve()
        if not path.is_relative_to(app.state.state_dir.resolve() / "clean"):
            raise HTTPException(403, "잘못된 캐시 경로입니다.")
        try:
            actual = hashlib.sha256(path.read_bytes()).hexdigest()
        except OSError as exc:
            raise HTTPException(404, "저장된 캐시가 없습니다. 표시 제거를 다시 실행하세요.") from exc
        if actual != (cleanup.mask_hash if mask else cleanup.clean_hash):
            raise HTTPException(409, "저장된 캐시가 변경되었습니다. 표시 제거를 다시 실행하세요.")
        record = db.get(ImageRecord, cleanup.image_id)
        if not download:
            try:
                current_hash = hashlib.sha256(Path(record.file_path).read_bytes()).hexdigest()
            except OSError:
                current_hash = None
            if current_hash != cleanup.source_hash:
                raise HTTPException(409, "원본이 바뀌어 이전 제거 결과를 표시할 수 없습니다.")
        filename = f"{Path(record.file_name).stem}_{'mask' if mask else 'clean'}.png" if download else None
        return FileResponse(path, media_type="image/png", filename=filename, headers={"Cache-Control": "no-store"})
