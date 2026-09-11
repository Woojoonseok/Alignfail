# Phase 1 검증 기록

## v0.2.0 Training Studio Phase A–C — 2026-09-11

- 자동 테스트 **56개 통과**(기존 deprecation warning 2건). TypeScript 검사·production build 및 Dataset/Training 두 Python 환경의 `pip check` 통과.
- 별도 PyTorch 2.6.0+cpu / Python 3.12 환경으로 실제 학습 통합 검증. Dataset Studio 환경에는 torch를 추가하지 않았습니다.
- Fixed 160/256/320 native 크기, 소수 중심·reflect padding, Adaptive min/max·반올림·중심 유지, near-black/low-std 경고, context에 따른 통계 변화 검사.
- Group Fold 재현·분리, Split 간 동일 hash 차단, Version/실제 파일 변경 후 기존 실험 복사본 보존, REF ROI revision·범위, ROI 누락/비수동 Query GT 차단 검사.
- 네 crop 모드에서 실제 CPU 1 epoch 학습·체크포인트·Validation 지표·Heatmap 생성, 중복 시작 차단, queued 작업 중단, running 작업 중단 후 checkpoint 보존, 설정 변조 실패 검사.
- 알려진 특징 지도를 사용하는 inference에서 원본 `(112,96)` 예측 및 Heatmap peak 일치, 원본 이미지 크기 유지 검사. 오차 0 및 3-4-5 거리 검사.
- 브라우저에서 합성 프로젝트 REF ROI 숫자 지정/저장, 새 버전 생성, Train/Validation 4/4 Pair 및 A/B 각 2/2 확인, 네 crop preview 확인, Fixed 160와 Adaptive 각 2 epoch 실행 완료·곡선·비교 표 확인. ROI 버튼의 의도치 않은 form submit을 발견해 수정했습니다.
- 합성 데이터의 1–2 epoch 결과는 성능 개선을 의미하지 않습니다. 회사 Pattern A/B의 실제 품질, RTX 4090/WSL CUDA, 장시간 학습은 미검증입니다.

## v0.1.2 일괄 제거 · 그룹화 — 2026-09-10

- 자동 테스트 총 **38개 통과**. 추가 검증: 일괄 제거의 기존 Clean 유지/재생성/후보 없음, 원본 변경 차단, 원본·GT 보존, 클래스/그룹 일괄 저장의 원자성·revision 충돌·프로젝트 범위·해제, 클러스터 재현성과 명시적 적용, 손상 이미지 제외, Clean 우선 사용, 동일 특징 유지, 기존 DB 마이그레이션, 클래스 버전 보존·비교.
- TypeScript 검사 및 production build 통과.
- 브라우저: 합성 8 Pair/16 이미지 일괄 처리(14 저장, 기존 Clean 2 유지, 실패 0), 재실행 중단(12/16에서 중단), 클래스 8개 일괄 저장, 3개 클러스터 후보 생성·저장, 개별 Pair 소속/그룹 이름 수정, 그룹 필터, 새로고침 후 저장 유지 확인.
- 실제 회사 데이터의 군집 품질과 대량 처리 시간, WSL 설치는 아직 검증하지 않았습니다. 현재 자동 군집화는 명암·윤곽 특징 기반이며 딥러닝 모델 학습 기능은 아닙니다.

## v0.1.1 흰 표시 제거 — 2026-09-09

- 자동 테스트 총 **29개 통과**: 네모/십자선 탐지, grayscale/RGB 처리, 재현성, 마스크 밖 픽셀 보존, 잘못된 영역 거부, 원본·GT 보존, 저장/되돌리기/버전 유지, 원본 변경·캐시 손상 차단, 16-bit 제거 거부.
- TypeScript 검사 및 production build 통과.
- 합성 이미지로 브라우저에서 REF 네모와 Query 십자선 자동 찾기, 제거 미리보기, Clean 저장, 새로고침 후 유지 및 원본/Clean 전환 확인.
- 네모 두 모서리 직접 지정과 원본 픽셀 좌표 반영, 두 이미지 전체 맞춤 표시 확인.
- 회사 실제 이미지의 자동 탐지 정확도와 복원 품질은 아직 평가하지 않았습니다.

검증일: 2026-09-08 (로컬 Windows 개발 환경) · 재검증: 2026-09-11 (리팩토링 후)

## 재검증 (2026-09-11)

- 로컬 Windows, Python 3.13.7 venv + CPU PyTorch 2.14: `python -m pytest` **56개 테스트 통과** (`--import-mode=importlib`로도 동일).
- `ruff check` / `ruff format --check` 통과, `npm run build`(tsc + Vite) 통과.
- 합성 데이터 8 Pair로 서버를 띄워 health · 프로젝트 생성 · 폴더 등록 · 썸네일 · 표시 검출 · Audit API 응답을 확인.

## 자동 검증

- `python -m pytest -q`: **17개 테스트 통과**.
- `npm --prefix frontend run build`: TypeScript 검사 및 Vite production build 통과.
- `python -m pip check`: 의존성 충돌 없음.
- npm 의존성 검사: 취약점 0건 (검증 시점).

테스트 범위: 대소문자 무관 REF 분류, 재검색 중복 방지, GT 범위/부분 입력/비유한 값 거부, GT 이력, 수정 revision 충돌, 파일 변경 차단 및 GT 재검토, 모호한 Pair, 누락/손상 파일, 동일 파일 검사, 제외 사유, 불변 버전과 GT 변경점, 16-bit TIFF 표시, 원본 보존 삭제, 로컬 API 접근 제한.

테스트 도구의 httpx/AnyIO 사용에 대한 deprecation warning 2건이 있습니다. 테스트 실패나 앱 실행 오류는 아닙니다.

## 브라우저 검증

Codex 브라우저에서 로컬 production build를 실행해 다음을 확인했습니다.

- UI에서 프로젝트 생성 및 합성 이미지 8 Pair 등록.
- REF / Query 이미지 표시와 클릭 GT 지정.
- 150% 확대에서도 동일한 위치가 원본 좌표 `(192, 208)`로 유지.
- 숫자 입력으로 GT 수정, 그룹/Tier/메모 저장, 저장 후 GT 이력 확인.
- 저장하지 않은 변경에 대한 페이지 이동 보호.
- 검색 결과 변경 중 현재 Pair와 미저장 편집 유지.
- 8개 Pair를 순서대로 저장하고 Audit 오류 0건 확인.
- `v001`, `v002` 생성 및 메모 변경점 비교.
- 서버 재시작·브라우저 새로고침 후 DB와 버전 유지.
- 브라우저 콘솔 error 0건.

## 확인하지 않은 것

- 회사 WSL 환경의 실제 설치와 Windows↔WSL localhost 전달.
- 회사 이미지 형식·크기·파일 수에 대한 호환성과 처리 시간.
- 실제 localization 성능, CUDA/PyTorch 연결, RTX 4090 사용량.
- 외부 JSON 형식, Train/Test Split과 누수 검사, 실제 모델 학습.

합성 테스트 이미지는 Tool 기능 검증용입니다. 실제 모델 성능이나 개선을 의미하지 않습니다.
