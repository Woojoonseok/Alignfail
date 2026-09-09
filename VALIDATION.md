# Phase 1 검증 기록

검증일: 2026-09-08 (로컬 Windows 개발 환경)

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
