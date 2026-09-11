# AlignFail Dataset Studio · 프로젝트 노트

2026-09-11 기준, 코드 분석·리팩토링·기능 추가 작업에서 파악한 내용을 정리한 문서입니다. README는 사용법, TRAINING.md는 학습 절차, MODEL.md는 모델 구조와 로드맵, VALIDATION.md는 검증 기록이고, 이 문서는 **코드를 이어서 만지는 사람을 위한 구조·설계·미완 항목 메모**입니다.

## 1. 한눈에 보는 구조

```text
backend/app/
  main.py              FastAPI 앱 생성, 프로젝트·Pair·GT·버전·이미지 서빙 라우트
  cleanup_api.py       흰 네모·십자선 제거(검출/미리보기/저장/초기화) 라우트
  grouping.py          일괄 클래스·그룹 지정, 외형 K-means 클러스터 후보
  training_api.py      REF ROI 저장, 실험 준비·시작·중단·파일 서빙
  experiment_service.py 실험 디렉터리 구성(prepare)과 학습 subprocess 큐(ExperimentManager)
  services.py          폴더 스캔(import), 이미지 검사, Audit, pair_dict 직렬화
  cleaning.py          검출·마스크·TELEA inpaint 알고리즘 (순수 함수)
  storage.py           해시·경로 포함 검사·검증 읽기·active_cleanup 공용 헬퍼
  database.py          SQLite 엔진, 수동 컬럼 마이그레이션, session_dependency
  models.py / schemas.py  SQLAlchemy 모델 / Pydantic 입력 스키마(extra=forbid)
training/              crop·diagnostics·group split·Triplet 모델·학습 스크립트 (backend가 import하며, 실험마다 복사됨)
frontend/src/
  App.tsx              셸(사이드바·헤더·라우팅·토스트·미저장 차단)
  pages/               Overview, PairExplorer, PairEditor, ClassesPage, AuditPage, VersionsPage, Workflow, Settings
  components/          ui.tsx(ErrorBox·Empty·Modal·Status·Thumb), ImageViewer, ProjectModals
  BatchTools.tsx       일괄 제거·그룹/클래스 지정·클러스터링 모달
  ImageCleaner.tsx     표시 제거 모달 · ReferenceROI.tsx REF ROI 모달 · TrainingPage.tsx
  api.ts               fetch 래퍼와 타입 · hooks.ts(useAction, useBeforeUnload) · coords.ts(pixelFromEvent) · types.ts
scripts/               WSL/Windows 실행, 합성 데이터 생성, 릴리스 zip
```

단일 로컬 사용자, Uvicorn worker 1개를 전제로 합니다. 쓰기 라우트는 프로세스 내 `RLock`으로 직렬화합니다.

## 2. 지켜야 하는 설계 원칙

코드 전반에 일관되게 깔려 있는 규칙입니다. 기능을 추가할 때도 이 규칙을 깨지 않아야 합니다.

- **원본 이미지는 절대 수정·복사·삭제하지 않습니다.** Clean 이미지와 마스크는 `.studio/clean/<image_id>/<cleanup_id>/`에 별도 PNG로 저장합니다. 프로젝트 삭제도 DB 등록 정보만 지웁니다.
- **모든 파일 접근은 SHA256로 검증합니다.** 썸네일 서빙, GT 저장, 제거, 클러스터링, 학습 준비 모두 디스크의 해시가 DB에 등록된 해시와 다르면 409로 거부합니다. `storage.read_verified()`와 `digest()`를 쓰세요.
- **데이터 루트 밖의 경로는 서빙하지 않습니다.** `storage.inside(path, root)`로 검사합니다. Clean 캐시는 `.studio/clean` 아래인지 검사합니다.
- **Pair 수정은 revision 낙관적 락입니다.** 클라이언트가 보낸 revision이 다르면 409. Clean 저장·초기화처럼 화면에 영향을 주는 변경도 관련 Pair의 revision을 올립니다(`update_pairs`).
- **GT는 원본 픽셀 좌표, 좌상단 (0,0), EXIF 회전 미적용.** 마우스 클릭은 `pixelFromEvent()`로 변환하고 정수로 반올림합니다. 숫자 입력으로는 소수도 허용합니다.
- **GT 변경은 전부 이력(GTHistory)에 남습니다.** Query 파일이 바뀌면 재검색 시 GT를 비우고 이유를 이력에 기록합니다.
- **group_key와 class_label은 서로 다른 개념입니다.** `group_key`는 학습/검증 Split 분리용(같은 촬영 묶음이 양쪽에 섞이지 않게), `class_label`은 의미 라벨입니다. 자동 클러스터링은 둘 중 어디에 쓸지 사용자가 고릅니다.
- **자동 처리 결과는 후보일 뿐이며 사용자가 적용 버튼을 눌러야 저장됩니다.** 검출, 클러스터링 모두 같은 패턴입니다.
- **데이터 버전은 불변 JSON 스냅샷입니다.** 생성 시 Audit를 다시 실행하고 통과해야 합니다. 학습은 버전의 manifest만 입력으로 받습니다.
- **학습 재현성.** 실험 디렉터리에 입력 이미지 바이트, 설정, split, 학습 코드 복사본과 해시(integrity.json)를 고정하고, 학습 프로세스가 시작할 때 다시 검증합니다.

## 3. 주요 흐름

**폴더 등록(import).** 루트 바로 아래 폴더 하나 = Pair 하나. 파일명에 `ref`(대소문자 무관)가 있으면 REF, 나머지는 Query. 각각 정확히 1장이 아니면 `import_issues`에 기록하고 해당 역할 image_id를 비웁니다. 사라진 폴더의 Pair는 누락 이슈로 표시만 합니다.

**Audit.** 모든 이미지를 다시 읽어 해시 비교(BROKEN_FILE, FILE_CHANGED), Clean 캐시 검증(STALE_CLEAN, BROKEN_CLEAN), GT 누락·범위(MISSING_GT, INVALID_GT), 동일 파일(DUPLICATE_FILE, 경고), 그룹 미지정(GROUP_UNASSIGNED, 경고). 제외된 Pair의 오류는 경고로 낮춥니다. `passed`는 오류 0건이면서 활성 Pair가 1개 이상일 때입니다.

**표시 제거.** `detect_markings()`가 밝기 투영으로 십자선과 네모 후보를 찾고, `create_masks()`가 기하학적 테두리 전체를 마스크로 만들어 `cv2.inpaint(TELEA)`로 채웁니다. 십자선에는 주변 고주파 표준편차 크기의 노이즈를 시드 고정으로 더할 수 있습니다. 8-bit L/RGB만 지원합니다.

**클러스터링.** 16×16 명암 구조 + 8×8 Sobel 윤곽 + 평균·표준편차를 특징으로, farthest-first 초기화 K-means(결정적)입니다. 유효한 Clean을 우선 사용합니다. 회전·배율 불변성은 없습니다.

**학습.** `prepare()`가 버전 manifest에서 활성 Pair의 REF ROI·수동 GT를 검증하고 crop 진단과 group split(hash 누수 검사 포함)을 만든 뒤 `ExperimentManager`가 별도 Python(`ALIGNFAIL_TRAINING_PYTHON`)으로 `training.train`을 실행합니다. heartbeat 파일과 stop.request 파일로 감시·중단합니다. 서버 재시작 시 running/queued 실험은 failed로 표시됩니다.

## 4. 이번에 바꾼 것 (2026-09-11)

리팩토링 브랜치 `refactor/structure`(PR #1, 병합됨)과 기능 브랜치 `feature/class-gallery`입니다.

- **포맷터·린터 도입.** `pyproject.toml`(ruff, line-length 120, E/F/I/B/UP), `frontend/.prettierrc`. 전체 소스를 한 번 포맷했습니다. tsconfig에 `noUnusedLocals`를 켰습니다.
- **테스트 구조.** test_batch가 test_cleaning의 픽스처를 import하던 것을 `conftest.py`(픽스처)와 `support.py`(합성 이미지 헬퍼)로 분리. `pytest.ini`의 pythonpath에 `backend/tests` 추가. README의 `--import-mode=importlib` 명령이 실제로는 실패했던 문제가 이것으로 해결됐습니다.
- **백엔드 중복 통합.** `storage.py` 신설(digest, inside, read_verified/HashMismatch, active_cleanup, HIGH_DEPTH_MODES), `database.session_dependency()`, JSON 원자적 저장/로드를 `training/data.py`로 통합, 버전 문자열을 `app/__init__.py`로 단일화.
- **프런트엔드 분리.** 2,300줄 App.tsx를 pages/·components/로 분리. `useAction`(busy/error 래퍼), `useBeforeUnload`, `pixelFromEvent` 공용화. 페이지 제목·설명은 `PAGES` 라우트 테이블.
- **Classes 페이지 신설.** 클래스별 카드(썸네일 격자, 개수, 이름 변경, 미분류 카드), 썸네일 선택 후 기존/새 클래스로 이동·해제. 기존 `groups/bulk` API만 사용.
- **클러스터 적용 대상 선택.** BatchTools 클러스터 탭에서 group_key / class_label 중 선택.
- **Pair Explorer.** "클래스별로 묶어 보기"(접히는 섹션, localStorage 기억). Fit 배율에서 이미지 전체가 스크롤 없이 보이도록 뷰어 변경. 저장·되돌리기 버튼을 상단 고정 헤더로 이동, Ctrl+S 저장.
- **문서.** README 테스트 절·코드 스타일 절·구조 절 갱신, 릴리스 zip 이름을 패키지 버전에서 읽도록 수정, VALIDATION.md 재검증 기록.

## 5. 개발 환경 메모

- 운영 기준은 Python 3.12이지만 고정된 의존성은 **3.13에서도 설치·테스트 통과**했습니다(Windows).
- 전체 테스트는 56개. PyTorch 의존 6개는 `ALIGNFAIL_TEST_TRAINING_PYTHON=<torch 있는 python>`을 지정해야 실행되고, 없으면 skip됩니다. CPU 전용 torch(`--index-url https://download.pytorch.org/whl/cpu`)로 충분합니다.
- 실행: `python -m uvicorn app.main:app --app-dir backend --port 8000 --workers 1`. `frontend/dist`가 있으면 같은 포트에서 UI를 서빙하며, **빌드만 다시 하면 서버 재시작 없이 새 번들이 반영**됩니다(StaticFiles가 요청 시 디렉터리를 읽음).
- 상태 디렉터리는 `ALIGNFAIL_STATE_DIR`(기본 `.studio`). 테스트·데모는 임시 폴더를 지정해 격리하세요.
- 합성 데이터: `python scripts/create_demo.py --output <폴더> --markings`.
- FastAPI TestClient가 "httpx 대신 httpx2" deprecation 경고를 냅니다. 다음 starlette 메이저에서 테스트가 깨질 수 있으니 requirements-dev 갱신 시 확인이 필요합니다.

## 6. 남은 개선 제안

### 구조·성능

- `list_pairs`가 Pair마다 이미지 2건·cleanup 2건·annotation 1건을 개별 조회합니다(Pair 2,000개면 쿼리 약 1만 건). join 또는 일괄 조회로 바꾸면 목록 로딩이 크게 빨라집니다.
- 썸네일 요청마다 파일 전체를 읽어 SHA256을 다시 계산하고 `Cache-Control: no-store`입니다. URL에 이미 해시가 붙어 있으니 캐시 허용, 또는 mtime·size가 같으면 해시 계산 생략을 고려하세요.
- Pair 목록·클래스 갤러리에 가상화(react-window 등)가 없어 수천 Pair에서 DOM이 무거워집니다.
- 일괄 제거가 브라우저에서 이미지 1장씩 순차 요청합니다. `ExperimentManager`와 같은 백엔드 작업 큐로 옮기면 창을 닫아도 이어집니다.
- TrainingPage의 `Config` 타입·기본값이 백엔드 `TrainingConfig`의 복사본입니다. 필드를 추가하면 양쪽을 맞춰야 합니다. `/api/training/environment`에서 기본값을 내려주는 방식을 권합니다.
- 모달 구현이 두 가지(App의 `Modal`, 각 모달의 `<dialog>` + `showModal`)입니다. 하나로 통일할 수 있습니다.
- 라우트가 `create_app` 내부 클로저로 등록되어 단위 테스트가 어렵습니다. APIRouter 전환은 중간 규모 작업입니다.
- 수동 `ALTER TABLE` 마이그레이션이 늘어나면 Alembic 도입을 검토하세요.
- CI가 없습니다. pytest와 `tsc -b`만 돌리는 GitHub Actions 하나면 회귀를 잡을 수 있습니다.

### 검수 UX

- 키보드 단축키: 좌우 화살표로 이전/다음, 방향키로 GT 1px 미세 조정, Enter로 저장 후 다음 이동. (Ctrl+S 저장만 구현됨)
- 커서 위치 기준 휠 확대와 드래그 이동, REF/Query 스크롤 동기화.
- 저장 후 편집기가 리마운트되어 확대율이 초기화됩니다(PairEditor의 key에 revision 포함). 확대율을 상위로 올리면 유지됩니다.
- 필터·검색 상태가 URL에 없어 페이지 이동 후 초기화됩니다.
- REF 뷰어에 ROI 사각형·중심 오버레이가 없습니다. Pair Explorer에서 바로 보이면 검수 정확도에 도움이 됩니다.
- Pair 목록 썸네일에 GT 위치 점 표시.

### 시각화

- 학습 곡선(LossChart)에 축 눈금·값 라벨·hover 툴팁이 없고, Median Error·Acc 곡선은 표로만 제공됩니다.
- 예측 히트맵의 GT/예측 마커가 고정 5px라 큰 이미지에서 보이지 않습니다. 이미지 크기에 비례시켜야 합니다. 히트맵 투명도 조절과 컬러바도 없습니다.
- Crop 비교 표가 Acc@10만 보여 줍니다. 지표 선택 또는 전체 지표 표시가 필요합니다.
- Audit 결과에 코드별 집계·필터가 없고, 버전 diff가 바뀐 필드 이름만 보여 줍니다(이전·이후 값 없음).
- 실험에 이름·메모가 없어 uuid 8자리로만 구분됩니다.
- 폴링이 상태와 무관하게 2.5초 고정입니다. running/queued일 때만 폴링하도록 바꾸세요.
- 클래스 유사도 품질을 높이려면 사전학습 임베딩(예: DINOv2-small)이 필요하지만 검수 환경에도 PyTorch가 필요해집니다.

### 기타

- UI 문구가 한·영 혼재이고 장식성 영문 헤더가 많습니다. 사내 도구라면 정보 밀도를 높이는 쪽이 낫습니다.
- 프로젝트 삭제 확인이 `window.confirm`입니다. 나머지 UI와 같은 커스텀 모달로 바꾸고 이름 입력 확인을 두는 편이 안전합니다.
- 다크 모드가 없습니다. 검수 화면만이라도 어두운 테마가 있으면 좋습니다.
