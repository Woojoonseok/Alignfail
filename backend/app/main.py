import io
import json
import os
import threading
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import Depends, FastAPI, HTTPException, Query, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from PIL import Image, UnidentifiedImageError
from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session
from starlette.middleware.trustedhost import TrustedHostMiddleware

from . import __version__
from .cleanup_api import register_cleanup_routes
from .database import create_database, session_dependency
from .grouping import register_group_routes
from .models import DatasetVersion, GTHistory, ImageRecord, Pair, Project, now
from .schemas import ImportInput, PairInput, ProjectInput, VersionInput
from .services import audit_dataset, gt_value, import_directory, pair_dict
from .storage import HIGH_DEPTH_MODES, digest, inside
from .training_api import register_training_routes

ROOT = Path(__file__).resolve().parents[2]
LOCAL_HOSTS = ["localhost", "127.0.0.1", "[::1]"]
# Browser origins allowed to call the API: the served UI (8000) and the Vite dev server (5173).
ALLOWED_ORIGINS = {f"http://{host}:{port}" for host in LOCAL_HOSTS for port in [8000, 5173]}


def create_app(state_dir: Path | None = None):
    @asynccontextmanager
    async def lifespan(app):
        app.state.experiments.activate()
        yield
        app.state.experiments.close()

    app = FastAPI(title="AlignFail Dataset Studio", version=__version__, lifespan=lifespan)
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=[*LOCAL_HOSTS, "testserver"])
    app.state.state_dir = state_dir or Path(os.getenv("ALIGNFAIL_STATE_DIR", str(ROOT / ".studio")))
    engine, factory = create_database(app.state.state_dir)
    app.state.engine = engine
    # This local, single-worker application serializes edits/imports to avoid stale GT writes.
    write_lock = threading.RLock()
    register_cleanup_routes(app, factory, write_lock)
    register_group_routes(app, factory, write_lock)
    register_training_routes(app, factory, write_lock)

    @app.exception_handler(RequestValidationError)
    async def invalid_input(_request, exc):
        # Validation inputs may contain non-finite floats that cannot be JSON encoded.
        return JSONResponse(
            status_code=422,
            content={
                "detail": [{"loc": error["loc"], "msg": error["msg"], "type": error["type"]} for error in exc.errors()]
            },
        )

    session = session_dependency(factory)

    def get_project(db, project_id):
        project = db.get(Project, project_id)
        if not project:
            raise HTTPException(404, "프로젝트를 찾을 수 없습니다.")
        return project

    def get_pair(db, pair_id):
        pair = db.get(Pair, pair_id)
        if not pair:
            raise HTTPException(404, "Pair를 찾을 수 없습니다.")
        return pair

    def project_dict(db, project):
        pairs = list(db.scalars(select(Pair).where(Pair.project_id == project.id)))
        return {
            "id": project.id,
            "name": project.name,
            "description": project.description,
            "root_directory": project.root_directory,
            "created_at": project.created_at,
            "pair_count": len(pairs),
            "enabled_count": sum(p.enabled for p in pairs),
            "annotated_count": sum(p.enabled and p.gt_x is not None for p in pairs),
            "issue_count": sum(bool(p.import_issues) for p in pairs),
            "group_count": len({p.group_key for p in pairs if p.group_key and p.enabled}),
        }

    @app.middleware("http")
    async def local_origin_guard(request: Request, call_next):
        # Do not let an unrelated website operate this local filesystem-backed API.
        origin = request.headers.get("origin")
        if request.url.path.startswith("/api") and origin and origin not in ALLOWED_ORIGINS:
            return Response("Origin is not allowed", status_code=403)
        return await call_next(request)

    @app.get("/api/health")
    def health():
        return {"status": "ok", "version": __version__, "phase": "dataset-studio"}

    @app.get("/api/projects")
    def list_projects(db: Session = Depends(session)):
        return [project_dict(db, p) for p in db.scalars(select(Project).order_by(Project.created_at))]

    @app.post("/api/projects", status_code=201)
    def create_project(data: ProjectInput, db: Session = Depends(session)):
        with write_lock:
            project = Project(**data.model_dump())
            db.add(project)
            db.commit()
            return project_dict(db, project)

    @app.patch("/api/projects/{project_id}")
    def update_project(project_id: str, data: ProjectInput, db: Session = Depends(session)):
        with write_lock:
            project = get_project(db, project_id)
            project.name, project.description = data.name, data.description
            db.commit()
            return project_dict(db, project)

    @app.delete("/api/projects/{project_id}", status_code=204)
    def delete_project(project_id: str, db: Session = Depends(session)):
        with write_lock:
            project = get_project(db, project_id)
            # Delete DB registrations only. Original image directories are never removed.
            db.execute(delete(Pair).where(Pair.project_id == project_id))
            db.execute(delete(ImageRecord).where(ImageRecord.project_id == project_id))
            db.delete(project)
            db.commit()
        return Response(status_code=204)

    @app.post("/api/projects/{project_id}/import")
    def import_pairs(project_id: str, data: ImportInput, db: Session = Depends(session)):
        with write_lock:
            project = get_project(db, project_id)
            root = Path(data.root_directory.strip()).expanduser().resolve()
            if not root.is_dir():
                raise HTTPException(
                    422, "폴더를 찾을 수 없습니다. 서버에서 접근 가능한 경로를 입력하세요. WSL 예: /mnt/d/Dada"
                )
            if project.root_directory and Path(project.root_directory).resolve() != root:
                raise HTTPException(
                    409, "등록된 데이터 경로는 변경할 수 없습니다. 다른 폴더는 새 프로젝트로 등록하세요."
                )
            try:
                result = import_directory(db, project, root)
                db.commit()
            except OSError as exc:
                db.rollback()
                raise HTTPException(422, f"폴더 접근 실패: {type(exc).__name__}") from exc
            return result

    @app.get("/api/projects/{project_id}/pairs")
    def list_pairs(project_id: str, db: Session = Depends(session)):
        get_project(db, project_id)
        return [
            pair_dict(db, p)
            for p in db.scalars(select(Pair).where(Pair.project_id == project_id).order_by(Pair.folder))
        ]

    @app.put("/api/pairs/{pair_id}")
    def update_pair(pair_id: str, data: PairInput, db: Session = Depends(session)):
        with write_lock:
            pair = get_pair(db, pair_id)
            if data.revision != pair.revision:
                raise HTTPException(409, "다른 작업에서 Pair가 변경되었습니다. 새로고침 후 다시 저장하세요.")
            query = db.get(ImageRecord, pair.query_image_id) if pair.query_image_id else None
            if data.gt_x is not None:
                if not query or query.error or not query.width or not query.height:
                    raise HTTPException(422, "읽을 수 있는 Query 이미지가 필요합니다.")
                if not (0 <= data.gt_x < query.width and 0 <= data.gt_y < query.height):
                    raise HTTPException(422, f"GT 범위: 0 ≤ X < {query.width}, 0 ≤ Y < {query.height}")
                try:
                    unchanged = digest(Path(query.file_path)) == query.file_hash
                except OSError:
                    unchanged = False
                if not unchanged:
                    raise HTTPException(409, "Query 파일이 변경되었거나 없습니다. 폴더를 재검색하세요.")
            before = gt_value(pair)
            changed_gt = (pair.gt_x, pair.gt_y) != (data.gt_x, data.gt_y)
            for key, value in data.model_dump(exclude={"revision"}).items():
                setattr(pair, key, value)
            if changed_gt:
                pair.gt_source = "manual" if pair.gt_x is not None else "none"
                db.add(GTHistory(pair_id=pair.id, before=before, after=gt_value(pair), reason="사용자 GT 수정"))
            pair.revision += 1
            pair.updated_at = now()
            db.commit()
            return pair_dict(db, pair)

    @app.get("/api/pairs/{pair_id}/history")
    def history(pair_id: str, db: Session = Depends(session)):
        get_pair(db, pair_id)
        return [
            {"id": h.id, "before": h.before, "after": h.after, "reason": h.reason, "created_at": h.created_at}
            for h in db.scalars(
                select(GTHistory).where(GTHistory.pair_id == pair_id).order_by(GTHistory.created_at.desc())
            )
        ]

    @app.get("/api/images/{image_id}")
    def serve_image(image_id: str, size: int | None = Query(None, ge=32, le=2048), db: Session = Depends(session)):
        record = db.get(ImageRecord, image_id)
        if not record:
            raise HTTPException(404, "이미지를 찾을 수 없습니다.")
        path = Path(record.file_path)
        project = get_project(db, record.project_id)
        if not inside(path, project.root_directory):
            raise HTTPException(403, "데이터 폴더 외부의 이미지는 제공하지 않습니다.")
        try:
            if digest(path) != record.file_hash:
                raise HTTPException(409, "파일이 변경되었습니다. 폴더를 재검색하세요.")
            with Image.open(path) as original:
                original.load()
                # Coordinates refer to raw pixels; deliberately do not apply EXIF rotation.
                if original.mode in HIGH_DEPTH_MODES:
                    low, high = original.getextrema()
                    image = original.convert("F").point(lambda x: (x - low) * 255 / (high - low or 1)).convert("L")
                else:
                    image = original.convert("RGB")
                if size:
                    image.thumbnail((size, size))
                output = io.BytesIO()
                image.save(output, format="PNG")
        except (OSError, ValueError, UnidentifiedImageError, Image.DecompressionBombError) as exc:
            raise HTTPException(422, "이미지를 읽을 수 없습니다. 폴더를 재검색하세요.") from exc
        return Response(output.getvalue(), media_type="image/png", headers={"Cache-Control": "no-store"})

    @app.post("/api/projects/{project_id}/audit")
    def audit(project_id: str, db: Session = Depends(session)):
        with write_lock:
            get_project(db, project_id)
            return audit_dataset(db, project_id)

    @app.get("/api/projects/{project_id}/annotations")
    def export_annotations(project_id: str, db: Session = Depends(session)):
        get_project(db, project_id)
        # Native export schema. External legacy JSON import will be added when its schema is supplied.
        payload = {
            "schema_version": "alignfail.annotations.v1",
            "coordinate_system": "raw-image-pixels, zero-based, x-right, y-down",
            "exported_at": now(),
            "pairs": [
                pair_dict(db, p)
                for p in db.scalars(select(Pair).where(Pair.project_id == project_id).order_by(Pair.folder))
            ],
        }
        return Response(
            json.dumps(payload, ensure_ascii=False, indent=2),
            media_type="application/json",
            headers={"Content-Disposition": 'attachment; filename="annotations.json"'},
        )

    @app.get("/api/projects/{project_id}/versions")
    def list_versions(project_id: str, db: Session = Depends(session)):
        get_project(db, project_id)
        return [
            {
                "id": v.id,
                "number": v.number,
                "description": v.description,
                "created_at": v.created_at,
                "pair_count": len(v.manifest["pairs"]),
                "enabled_count": sum(p["enabled"] for p in v.manifest["pairs"]),
            }
            for v in db.scalars(
                select(DatasetVersion)
                .where(DatasetVersion.project_id == project_id)
                .order_by(DatasetVersion.number.desc())
            )
        ]

    @app.post("/api/projects/{project_id}/versions", status_code=201)
    def create_version(project_id: str, data: VersionInput, db: Session = Depends(session)):
        with write_lock:
            project = get_project(db, project_id)
            audit = audit_dataset(db, project_id)
            if not audit["passed"]:
                raise HTTPException(422, "활성 Pair의 파일·GT 오류를 해결해야 버전을 생성할 수 있습니다.")
            pairs = [
                pair_dict(db, p)
                for p in db.scalars(select(Pair).where(Pair.project_id == project_id).order_by(Pair.folder))
            ]
            number = (
                db.scalar(select(func.max(DatasetVersion.number)).where(DatasetVersion.project_id == project_id)) or 0
            ) + 1
            manifest = {
                "schema_version": "alignfail.dataset.v1",
                "created_at": now(),
                "project": project.name,
                "root_directory": project.root_directory,
                "description": data.description,
                "coordinate_system": "raw-image-pixels, zero-based, x-right, y-down",
                "pairs": pairs,
                "audit": audit,
            }
            version = DatasetVersion(
                project_id=project_id, number=number, description=data.description, manifest=manifest
            )
            db.add(version)
            db.commit()
            return {"id": version.id, "number": number}

    @app.get("/api/versions/{version_id}/manifest")
    def manifest(version_id: str, db: Session = Depends(session)):
        version = db.get(DatasetVersion, version_id)
        if not version:
            raise HTTPException(404, "버전을 찾을 수 없습니다.")
        return Response(
            json.dumps(version.manifest, ensure_ascii=False, indent=2),
            media_type="application/json",
            headers={"Content-Disposition": f'attachment; filename="dataset_v{version.number:03d}.json"'},
        )

    @app.get("/api/versions/{version_id}/diff/{other_id}")
    def version_diff(version_id: str, other_id: str, db: Session = Depends(session)):
        target, base = db.get(DatasetVersion, version_id), db.get(DatasetVersion, other_id)
        if not target or not base or target.project_id != base.project_id:
            raise HTTPException(422, "같은 프로젝트의 두 버전을 선택하세요.")
        new = {p["id"]: p for p in target.manifest["pairs"]}
        old = {p["id"]: p for p in base.manifest["pairs"]}
        changes = []
        for key in sorted(new.keys() | old.keys()):
            if key not in old:
                changes.append({"folder": new[key]["folder"], "fields": ["추가"]})
            elif key not in new:
                changes.append({"folder": old[key]["folder"], "fields": ["삭제"]})
            else:
                fields = [
                    f
                    for f in [
                        "gt_x",
                        "gt_y",
                        "gt_source",
                        "group_key",
                        "class_label",
                        "pattern_type",
                        "reference_annotation",
                        "tier",
                        "enabled",
                        "exclude_reason",
                        "notes",
                        "reference",
                        "query",
                        "import_issues",
                    ]
                    if old[key].get(f, "") != new[key].get(f, "")
                ]
                if fields:
                    changes.append({"folder": new[key]["folder"], "fields": fields})
        return {"base": base.number, "target": target.number, "changes": changes}

    dist = ROOT / "frontend" / "dist"
    if dist.is_dir():
        app.mount("/assets", StaticFiles(directory=dist / "assets"), name="assets")

        @app.get("/{path:path}")
        def frontend(path: str):
            if path.startswith("api/"):
                raise HTTPException(404, "API not found")
            return FileResponse(dist / "index.html")

    return app


app = create_app()
