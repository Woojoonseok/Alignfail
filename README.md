# AlignFail Dataset Studio

회사 Windows + WSL 환경에서 로컬로 실행하는 AlignFail 데이터 검수 도구입니다. 현재 **Phase 1: Dataset Studio**를 구현합니다. 실제 학습·GPU 작업·모델 성능 평가는 아직 연결하지 않았습니다.

## 현재 지원

- 프로젝트 생성·수정·삭제. 삭제는 등록 정보만 지우며 원본 이미지는 보존합니다.
- `Dada/<Pair 폴더>/<REF 이미지, Query 이미지>` 일괄 등록·재검색.
- 이미지 파일명에 `REF`가 포함되면 REF(대소문자 무관), 나머지 이미지 파일은 Query. 각각 정확히 한 장이어야 합니다.
- PNG, JPEG, BMP, TIFF, WebP. 하위 Pair 폴더 바로 아래의 파일만 검색하며 심볼릭 링크는 제외합니다.
- Pair 검색·상태 필터, REF/Query 나란히 보기, 독립 확대와 스크롤, 클릭 GT·숫자 좌표 편집.
- GT 수정 이력, 데이터 그룹·Tier·메모·제외 사유.
- 흰 네모·십자선 자동 후보 검출/직접 지정, 제거 미리보기, Clean PNG·제거 마스크 저장, 원본/Clean 전환.
- 파일 누락·손상·변경·동일 SHA256, 잘못된 Pair, GT 누락·범위 검사.
- 데이터 버전(immutable manifest), 버전 비교, GT JSON 및 Manifest 다운로드.
- 단계별 데이터 준비 안내와 진행 화면. 학습 기능을 실행하는 가짜 버튼이나 가짜 학습 결과는 없습니다.

## 회사 WSL 설치 / 실행

WSL 내부에 Python **3.12**와 venv, Node.js **22.12 이상** 및 npm을 준비합니다. 이 릴리스의 데이터 도구에는 CUDA나 PyTorch 설치가 필요하지 않습니다. 향후 학습 Adapter는 기존 WSL CUDA/PyTorch 환경의 Python 실행 경로를 별도로 사용합니다.

가능하면 프로젝트와 `.studio` DB는 WSL Linux 파일시스템(예: `~/alignfail`)에 두고, 실제 이미지는 Windows 디스크를 참조하세요.

```bash
cd ~/alignfail
bash scripts/setup-wsl.sh
bash scripts/start-wsl.sh
```

Windows 브라우저에서 **http://localhost:8000** 에 접속합니다. 기본 WSL localhost 전달이 활성화된 환경을 전제로 합니다. 포트 연결은 회사 WSL 환경에서 확인해야 합니다.

1. 프로젝트를 만듭니다.
2. **데이터 가져오기**에서 `/mnt/d/Dada`처럼 WSL에서 접근 가능한 경로를 입력합니다.
3. **Pair Explorer**에서 Query를 클릭하거나 X/Y를 입력하고 **변경 저장**을 누릅니다.
4. 관련 Pair에는 동일한 데이터 그룹을 입력합니다. 제품 코드는 필수가 아닙니다.
5. **Dataset Audit → 검사 실행**으로 오류를 수정합니다.
6. **Versions**에서 변경 설명을 입력하고 버전을 생성합니다.

등록된 프로젝트는 하나의 데이터 루트만 사용합니다. 다른 루트는 새 프로젝트로 등록하세요. 루트 하위의 Pair 폴더 이름은 해당 프로젝트에서 Pair 식별자로 사용하므로, 이름을 변경하면 새 Pair로 인식합니다. 이전 Pair는 누락으로 표시되어 사용자가 검토·제외할 수 있습니다.

### 회사 컴퓨터로 전달

소스 코드, `frontend/package-lock.json`, 실행 스크립트와 이 문서를 전달하세요. **Windows에서 만든 `.venv`나 `node_modules`는 WSL로 복사하지 않습니다.** WSL에서 새로 설치합니다.

`python scripts/package_release.py`는 소스와 빌드된 UI를 `artifacts/alignfail-dataset-studio-v0.1.1.zip`으로 묶습니다. 원본 이미지, 합성 이미지, 프로젝트 DB와 로컬 Python/Node 환경은 포함하지 않습니다. Python 의존성은 직접 버전과 `backend/constraints.txt`의 간접 버전을 함께 고정합니다.

`frontend/dist`는 여기서 빌드한 결과를 전달해도 됩니다. 빌드 결과를 전달한 경우 회사에서는 Node.js 없이 Python 의존성 설치와 `start-wsl.sh` 실행만으로 운영할 수 있습니다.

인터넷이 차단된 회사 환경에서는 동일한 Linux/Python 환경에서 Python wheel을 미리 준비해야 합니다. Windows wheel은 WSL에 설치할 수 없습니다. `frontend/dist`와 호환되는 wheel 묶음을 함께 전달하고 다음처럼 설치합니다.

```bash
python3.12 -m venv .venv
.venv/bin/python -m pip install --no-index --find-links ./wheels -r backend/requirements.txt
bash scripts/start-wsl.sh
```

현재 저장소에는 wheel 묶음이 포함되지 않습니다.

## 로컬 개발 / 검증

```bash
python3.12 -m venv .venv
source .venv/bin/activate
pip install -r backend/requirements-dev.txt
python -m pytest backend/tests --import-mode=importlib
```

테스트에는 backend를 Python 경로에 추가해야 합니다. 루트 `pytest.ini`에 설정되어 있으므로 저장소 루트에서 실행하세요.

```bash
# Terminal 1
python -m uvicorn app.main:app --app-dir backend --host 127.0.0.1 --port 8000 --workers 1
# Terminal 2
npm --prefix frontend ci
npm --prefix frontend run dev
```

개발 UI는 http://localhost:5173 입니다. Vite가 `/api`를 로컬 Backend로 전달합니다. 배포 빌드는 `npm --prefix frontend run build` 후 Backend를 다시 시작하면 같은 포트에서 제공됩니다.

Windows 개발 환경에서도 Python 3.12로 `.venv`를 만들고 `.venv\Scripts\python.exe`로 의존성을 설치할 수 있습니다. 빌드 후 `powershell -File scripts/start-windows.ps1`로 실행합니다.

### 합성 테스트 이미지

```bash
python scripts/create_demo.py
```

`sample-data/Dada`에 원본/Query 합성 이미지 8 Pair를 생성합니다. 기존 출력 폴더가 있으면 덮어쓰지 않고 중단합니다. UI에서 이 폴더를 **테스트 프로젝트**로 등록하세요. 합성 데이터는 기능 검증용이며 실제 localization 성능의 근거가 아닙니다.

## 좌표 · 데이터 보존 규칙

### 흰 네모 · 십자선 제거 (v0.1.1)

기존 설치를 업데이트할 때는 서버를 종료하고 코드를 받은 뒤 `python -m pip install -r backend/requirements.txt`, `npm --prefix frontend ci`, `npm --prefix frontend run build`를 실행하고 서버를 다시 시작하세요. 기존 DB에는 제거 이력 테이블이 자동 추가됩니다.

1. Pair Explorer의 각 이미지에서 **흰 표시 제거**를 누릅니다. 미저장 GT 변경이 있으면 먼저 저장하거나 되돌리세요.
2. **네모 자동 찾기 / 십자선 자동 찾기**로 후보를 찾습니다. 실패하면 **네모 직접 지정**으로 두 모서리, **십자선 직접 지정**으로 교차점을 클릭합니다. 좌표는 숫자로 보정할 수 있습니다.
3. 붉은 제거 영역과 여유 폭을 확인한 뒤 **제거 미리보기**로 전후를 비교합니다.
4. **Clean 이미지 저장**을 누르면 별도 PNG와 마스크를 `.studio/clean`에 저장합니다. Pair Viewer에서는 Clean 이미지를 기본으로 표시하며 원본으로 전환할 수 있습니다.
5. **원본 사용으로 되돌리기**는 Clean 선택만 해제합니다. 기존 버전이 참조하는 과거 캐시는 유지됩니다.

현재 제거는 **8-bit grayscale/RGB의 축과 평행한 네모 테두리 및 이미지 전체를 가로지르는 십자선 띠**를 지원합니다. 작은 국소 십자선이나 회전된 도형용 자유 마스크는 지원하지 않습니다. 네모는 밝기 250 이상 투영으로 위치를 찾고 ridge coverage 0.8 이상 후보를 제시합니다. 마스크는 밝기와 무관하게 테두리 전체를 포함합니다. 십자선은 행·열 모두 밝기 비율 0.30 이상과 양방향 지지를 요구해 가로 스케일바와 네모 모서리를 배제합니다. 자동 후보는 실제 이미지에서 직접 확인해야 합니다.

선 영역은 OpenCV TELEA(radius 기본 3)로 채웁니다. 십자선에는 옵션으로 주변 고주파 질감의 표준편차에 맞춘 노이즈를 더합니다. 이 구현은 과거 Phase 2의 선형보간 코드를 복제한 것이 아닙니다. 원본 hash·설정 기반 seed, 알고리즘·라이브러리 버전, Clean/mask hash를 기록합니다. 같은 환경과 설정에서 결과가 재현되며 마스크 밖의 픽셀은 유지합니다. 픽셀 복원은 추정이므로 가려지기 전 구조를 정확히 복구하거나 학습 누출을 제거했다고 보장하지 않습니다. 제공된 회사 데이터의 누출 검사는 아직 연결하지 않았습니다.

GT 좌표는 자동으로 생성·변경하지 않습니다. 원본이 변경되거나 Clean/mask 캐시가 손상되면 Audit에서 오류로 처리합니다. 기존 데이터 버전은 생성 당시의 Clean 경로와 설정을 보존합니다. `.studio` 백업에는 이 캐시도 포함해야 합니다.

흰 표시가 있는 합성 이미지는 `python scripts/create_demo.py --output sample-data/MarkedDada --markings`로 생성할 수 있습니다.

### 좌표와 보존

- GT는 **원본 이미지 픽셀 좌표**입니다. 좌상단 `(0, 0)`, X는 오른쪽, Y는 아래쪽. `0 ≤ x < width`, `0 ≤ y < height`.
- 마우스로 지정할 때 가장 가까운 정수로 기록하며 숫자 입력으로 소수 좌표도 저장할 수 있습니다. 확대율과 무관합니다.
- JPEG EXIF 자동 회전을 적용하지 않습니다. 기존 프로그램의 JSON 좌표도 같은 원본 기준인지 확인한 후 연결해야 합니다.
- TIFF는 첫 프레임을 사용합니다. 16-bit/float grayscale은 화면 표시용으로 min/max를 0–255로 정규화하며 원본은 수정하지 않습니다.
- Query의 내용이나 연결 파일이 변경되면 재검색 시 GT를 초기화하고 이전 GT를 이력에 보존합니다. 변경 전 이미지로 GT를 저장하는 요청은 차단합니다.
- 외부에서 원본을 수정하면 이미지 보기·GT 저장·Audit에서 변경을 탐지합니다. 원본 수정과 검수 작업을 동시에 진행하지 마세요.
- 프로젝트 등록만으로 원본을 복사하지 않습니다. 버전은 DB에 JSON 스냅샷을 저장하며 Manifest 버튼으로 파일을 내보낼 수 있습니다. **hash는 원본의 백업이 아닙니다.** 과거 버전 재현에는 원본 보존 또는 별도 백업이 필요합니다.
- DB와 GT 이력은 기본 `.studio/studio.db`에 있습니다. 서버를 종료한 뒤 `.studio` 전체를 백업하세요. 원본 이미지도 별도로 백업해야 합니다.
- `ALIGNFAIL_STATE_DIR`로 상태 저장 디렉터리를 바꿀 수 있습니다. DB는 SQLAlchemy 기반이며 `ALIGNFAIL_DATABASE_URL`을 설정할 수 있지만 PostgreSQL 드라이버/운영 검증은 아직 포함하지 않습니다.
- 단일 로컬 사용자, **Uvicorn worker 1개**를 전제로 합니다. 프로세스 내 잠금과 revision 검사로 동시 수정을 보호합니다. 사내 공유 서버용 인증·권한 관리는 후속 범위입니다.

## 데이터 그룹과 누수

제품 코드를 강제하지 않습니다. 같은 원본의 변형, 거의 같은 연속 촬영 등 연관된 Pair는 같은 `group_key`로 묶으세요. 완전 동일 파일은 SHA256으로 탐지해 검토 대상으로 표시합니다. 유사하다는 이유만으로 자동 삭제하거나 자동 그룹화하지 않습니다.

현재 Audit 통과는 **파일·Pair·GT 검사의 통과**이며 Train/Test 누수가 없다는 의미가 아닙니다. 그룹 미지정은 검토 항목입니다. 지각적 이미지 유사도 검색과 Group Split, Split 간 중복 검사는 다음 단계에서 구현합니다.

## 기존 JSON / 학습 코드 연결 계획

기존 외부 JSON 형식은 아직 제공되지 않아 임의로 해석하지 않습니다. 현재 GT 내보내기는 `alignfail.annotations.v1` 형식입니다. 외부 형식을 받은 뒤 `pair 폴더 이름 → GT 좌표` 매핑을 검증하고 같은 저장·이력 규칙을 사용하는 Import Adapter를 추가합니다.

후속 학습 Adapter의 공통 입력은 dataset manifest, split manifest, experiment config, output directory입니다. 출력은 실행 로그·학습 곡선·checkpoint·Pair별 예측 및 원본 좌표입니다. 기존 Metric Patch Localizer와 신규 Dense Pair Localizer를 동일한 평가 규격으로 비교할 예정입니다.

**미구현:** 외부 JSON Import, REF mask/box·Legacy 좌표 등록, 유사 이미지 검색, Split/누수 Gate, GPU Queue, Stage 1/Probe/Stage 2, 모델 학습 코드, Heatmap/평가/Champion. 회사 데이터와 기존 코드로 단계적으로 연결합니다.

## 구조

```text
backend/app/       FastAPI · SQLAlchemy · 파일 검사/GT/버전
backend/tests/     기능·데이터 무결성 API 테스트
frontend/src/      React 18 · TypeScript · TanStack Query · React Router
scripts/           WSL/Windows 실행 · 합성 이미지 생성
.studio/           로컬 DB (Git 제외)
```
