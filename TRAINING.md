# Training Studio v0.2.0 — Phase A–C

160 고정 crop의 정보 부족 여부를 진단하고 동일 모델로 160 / 256 / 320 / Adaptive를 비교합니다. 이 릴리스는 실제 Triplet 학습, 체크포인트, dense inference, Validation 평가를 포함합니다. 회사 데이터 성능 개선은 아직 입증하지 않았습니다.

## 회사 WSL 설정

Dataset Studio의 `.venv`에는 PyTorch를 설치하지 않아도 됩니다. 기존 회사 CUDA 환경을 별도로 사용하세요. Backend와 training Python 모두 같은 WSL 파일 경로에 접근할 수 있어야 합니다. Windows Backend에서 Linux Python 경로를 직접 실행하는 구성은 지원하지 않습니다.

```bash
cd ~/alignfail
# Dataset Studio 업데이트 (서버를 먼저 종료하고 .studio 백업)
.venv/bin/python -m pip install -r backend/requirements.txt
npm --prefix frontend ci
npm --prefix frontend run build

# 이미 CUDA PyTorch가 설치된 학습 환경을 지정
export ALIGNFAIL_TRAINING_PYTHON=/home/user/miniconda3/envs/alignfail/bin/python
"$ALIGNFAIL_TRAINING_PYTHON" -m pip install -r training/requirements.txt
"$ALIGNFAIL_TRAINING_PYTHON" -c "import torch; print(torch.__version__, torch.cuda.is_available()); print(torch.cuda.get_device_name(0))"
bash scripts/start-wsl.sh
```

CUDA PyTorch가 없다면 [공식 설치 안내](https://pytorch.org/get-started/locally/)에서 회사의 CUDA/드라이버에 맞는 wheel을 설치합니다. `training/requirements.txt`가 CPU 또는 CUDA wheel을 임의로 선택하지 않습니다. PyTorch 2.6 이상 API를 사용하며, 개발 컴퓨터에서는 **PyTorch 2.6.0+cpu / Python 3.12**로 실행 검증했습니다. 회사 RTX 4090 / WSL 검증은 별도로 필요합니다.

CPU 기능 점검용으로는 별도 venv에서 다음처럼 설치할 수 있습니다.

```bash
python3.12 -m venv .training-venv
.training-venv/bin/python -m pip install torch==2.6.0 --index-url https://download.pytorch.org/whl/cpu
.training-venv/bin/python -m pip install -r training/requirements.txt
export ALIGNFAIL_TRAINING_PYTHON="$PWD/.training-venv/bin/python"
bash scripts/start-wsl.sh
```

Windows 개발 환경은 `.training-venv\Scripts\python.exe`를 사용하고 PowerShell의 `$env:ALIGNFAIL_TRAINING_PYTHON`에 절대 경로를 지정합니다. UI에서 `CPU · 기능 검증`을 선택하세요. 학습 환경 경로를 설정하지 않으면 Backend의 Python을 사용하며, torch가 없으면 실험이 `failed`가 되고 로그에 이유를 표시합니다.

## 사용 순서

1. Pair Explorer에서 수동 Query GT와 `group_key`를 검수합니다.
2. **REF ROI 지정**에서 두 모서리를 클릭하거나 숫자를 입력합니다. 흰 네모 자동 후보도 사용할 수 있으나 저장 전에 ROI를 확인합니다. 흰 표시 제거 마스크와 REF 대상 ROI는 서로 다른 정보입니다.
3. `Pattern Type`을 A / B / unknown으로 지정하고 저장합니다. 클래스와 독립된 평가 메타데이터이며 모델의 label로 사용하지 않습니다.
4. **Versions**에서 새 버전을 만듭니다. 이전 버전에 없는 ROI를 현재 DB에서 가져와 덧붙이지 않습니다. ROI 없는 과거 버전은 학습 준비를 차단합니다.
5. **Training**에서 버전, Fold 수/번호, crop, Epoch, Batch Size, Learning Rate, Seed, Device를 고릅니다. 상세 설정에는 Adaptive 크기, 진단 임계값, negative 거리, margin, embedding 크기가 있습니다.
6. **입력 고정 · Split 검사 · Crop Preview**를 누릅니다. 이미지 복사와 전체 REF 진단을 수행하므로 데이터 수에 따라 시간이 걸릴 수 있습니다.
7. Train/Validation 그룹·Pair·Pattern 개수, Leakage PASS, 실제 REF crop과 통계를 확인합니다. 경고는 자동 제외 사유가 아닙니다.
8. **이 입력으로 학습 시작**을 누릅니다. Epoch별 loss/LR/위치 오차, 로그, 상태를 확인합니다.
9. 완료 후 best checkpoint의 Overall / A / B / unknown 결과를 봅니다. Validation Pair를 선택하면 GT·예측·Heatmap도 표시합니다. Train Pair에는 Validation 예측을 만들지 않습니다.
10. 같은 설정을 복사하고 crop만 바꿔 새 실험을 만듭니다. 비교 표에는 Version·Split·학습 코드·crop 외 학습 설정이 일치하는 결과만 포함됩니다.

Fold 번호는 **0부터 시작**합니다. 5-Fold는 동일 설정으로 Fold 0–4를 각각 실행할 수 있습니다. 자동 5개 실행 및 전체 fold 통계 집계는 아직 포함하지 않습니다. 최적 모델 선택과 결과 표는 Validation 기준이며 독립 최종 Test는 별도 단계입니다.

## 입력과 supervision

- 현재 학습 입력은 **8-bit grayscale/RGB**입니다. RGB는 Pillow로 grayscale 변환 후 `/255` 정규화합니다. 16-bit는 명시적 학습용 전처리를 추가하기 전까지 차단합니다.
- ROI는 원본 이미지 내 `(x0,y0,x1,y1)` 좌표이고 `x0<x1`, `y0<y1`입니다. 중심은 두 모서리의 평균이며 소수 좌표를 유지합니다.
- REF Annotation에는 이미지 hash, ROI, 중심, source, revision, 생성 시각을 별도 테이블에 기록합니다. 새 주석은 이전 이력을 덮어쓰지 않습니다.
- `gt_source == manual`인 Query GT만 학습합니다. Query의 legacy cross, 예측값, review ok/wrong에서 GT를 유도하지 않습니다.
- 흰 표시 제거 결과가 버전에 포함되어 있으면 유효한 Clean을 사용합니다. 원본·Clean·mask hash를 검증하고 실제 선택한 이미지 bytes를 실험 폴더에 복사합니다.
- Pattern은 평가 구분 전용입니다. 클래스/클러스터 이름을 Triplet의 정답 label로 자동 변환하지 않습니다.
- Negative는 Query 내 GT에서 `negative_min_distance` 이상 떨어진 무작위 중심입니다. 불가능한 크기/거리 조합은 준비 시 차단합니다. Hard negative는 후속 범위입니다.

## Crop 정책과 진단

| Mode | Native crop | Model input |
|---|---|---|
| fixed_160 | 160×160 | 160×160 |
| fixed_256 | 256×256 | 256×256 |
| fixed_320 | 320×320 | 320×320 |
| adaptive | ROI 최대 변 길이 × context_ratio, min/max clamp | output_size×output_size |

Adaptive 기본값은 ratio 1.5, min 192, max 384, output 320입니다. Native 크기는 clamp 후 가장 가까운 정수로 반올림합니다. Fixed 모드는 160으로 재축소하지 않습니다. Adaptive의 Query positive/negative crop도 해당 REF에서 결정한 native 크기와 output 크기를 사용합니다.

픽셀 중심이 annotation 중심에 대해 대칭이 되도록 샘플링합니다. 예를 들어 center=79.5, native=160이면 첫 샘플은 0, 마지막 샘플은 159입니다. 경계는 OpenCV `BORDER_REFLECT_101`, 소수 좌표 샘플링과 resize는 bilinear입니다. native_size/input_size/center/sample_origin/resize_scale/padding/interpolation을 manifest에 기록합니다. Preview와 학습은 같은 함수를 사용합니다.

Mean/Std/Min/Max/Edge Density는 **최종 모델 입력 grayscale 픽셀**에서 측정합니다. Edge는 Canny(50,100)의 비율입니다. near-black mean<15, low-std<5, low-edge<0.01이 기본이며 UI에서 수정 가능합니다. Problematic은 하나 이상의 조건에 해당하는 REF 수입니다. 통계가 나빠도 자동 삭제·제외하지 않습니다.

## 모델과 inference

이번 모델은 명세를 바탕으로 새로 구현한 **Metric Patch v1**입니다. 기존 회사 SupCon/Prototype/Sliding-window 코드나 가중치를 재현했다고 주장하지 않습니다.

- 하나의 shared fully convolutional CNN: Conv–ReLU–Pool → Conv–ReLU–Pool → Conv–ReLU, 총 stride 4.
- Patch 특징을 global average pooling하고 L2 정규화합니다. 기본 embedding dimension은 256입니다. 외부 pretrained 모델 다운로드는 없습니다.
- Anchor=REF crop, Positive=Query GT crop, Negative=Query 오답 crop.
- Cosine distance 기반 Triplet loss: `max(d(A,P)-d(A,N)+margin, 0)`. AdamW, 고정 학습률. 데이터 증강이나 Pattern별 별도 모델은 추가하지 않았습니다.
- Inference는 Query 전체를 encoder로 처리한 뒤 REF crop에 대응하는 범위의 **dense context pooling**을 수행합니다. 큰 REF descriptor를 작은 receptive field의 Query 한 칸과 바로 비교하지 않습니다. Adaptive는 Query sampling scale도 동일하게 조정합니다.
- Patch 단독 encoding과 전체 영상 encoding은 convolution 경계 조건 때문에 완전히 같은 연산은 아닙니다. 이 dense inference는 기존 sliding-window 코드와 별도 구현입니다.
- 각 위치의 descriptor와 REF descriptor의 cosine similarity를 구합니다. 모든 모드에서 최종 탐색 격자는 **원본 기준 4px**로 통일합니다. 이번 단계에는 offset head나 1px refinement가 없습니다.
- Heatmap은 원본 Query 좌표로 remap합니다. Cosine [-1,1]의 고정 색 범위를 쓰며 보정된 성공 확률이 아닙니다. GPU 시간 측정은 예측 연산과 CPU 결과 회수를 포함합니다.
- 메모리 폭주를 방지하기 위해 resize/padding 이후 Query 한 변이 4096px를 넘으면 실행을 실패 처리합니다. 타일 추론은 아직 없습니다.

먼저 동일 fold/seed/model/optimizer/epochs/batch 조건으로 crop만 비교하세요. Validation loss 대신 **Validation median localization error**가 가장 작은 epoch를 best로 선택합니다. unknown 또는 Pattern별 표본이 없으면 0점으로 꾸미지 않고 `—`로 표시합니다. 여러 seed/fold 결과와 충분한 학습 후에 context 부족 여부를 판단해야 합니다.

## 실험 보존과 실행 관리

```text
.studio/experiments/<uuid>/
  experiment.json          # prepared / queued / running / completed / failed / stopped
  config.json
  dataset_manifest.json    # 실제 선택 입력 hash, cleanup, ROI, GT, crop metadata
  split_manifest.json      # train/validation IDs, groups, fold, seed, hash
  integrity.json           # config/manifest/split/학습 소스 checksum
  environment.json         # Python/Torch/CUDA/GPU/NumPy/OpenCV/git/seed
  diagnostics.json
  data/                    # 선택한 원본 또는 Clean bytes의 복사본
  code/training/           # 준비 시점 학습 코드 복사본
  preview/                 # 실제 모델 입력 crop
  train.log
  history.json
  best.pt / last.pt
  predictions.json / metrics.json / heatmaps/
```

학습은 복사한 코드와 manifest만 사용하며 현재 Dataset DB를 읽지 않습니다. 원본 Dataset Version은 경로/hash 스냅샷이지만 **Training 실험은 이미지 bytes도 복사**합니다. 실험 준비 전에 원본이 바뀌면 차단하고, 이미 준비한 실험은 원본 변경 후에도 복사본으로 실행할 수 있습니다. 입력·설정·소스 hash가 바뀌면 학습을 실패 처리합니다. 절대 경로를 저장하므로 실험 폴더를 다른 경로로 이동해 실행하는 기능은 아직 지원하지 않습니다.

Backend worker 1개, 한 번에 학습 subprocess 1개입니다. 여러 실험 시작 요청은 Queue에서 순서대로 처리합니다. UI를 닫아도 Backend가 실행 중이면 학습은 계속됩니다. **학습 중단**은 배치 또는 평가 Pair 경계에서 처리하며 마지막으로 완료한 epoch의 checkpoint를 보존합니다. 중단 당시 배치/epoch를 복원하는 resume는 제공하지 않습니다.

정상 Backend 종료는 중단 요청 후 최대 10초 기다렸다가 필요하면 subprocess를 종료합니다. 비정상 종료는 heartbeat 만료와 별도 프로세스 잠금으로 중복 실행을 방지합니다. Backend 재시작 때 running/queued 상태는 failed로 기록하며 자동 재개하지 않습니다. 설정을 복사해 새 실험을 생성하세요.

## 검증과 다음 범위

```bash
# 데이터 도구 및 crop/split/manifest 테스트 (Torch 불필요)
.venv/bin/python -m pytest -q
# 별도 PyTorch 환경까지 포함한 실제 CPU 학습 테스트
ALIGNFAIL_TEST_TRAINING_PYTHON="$PWD/.training-venv/bin/python" .venv/bin/python -m pytest -q
```

회사 실제 Pattern A/B 품질, 장시간 학습, CUDA 메모리·속도는 미검증입니다. 합성 데이터 1–2 epoch 실행은 소프트웨어 기능 검증이며 모델 성능의 근거가 아닙니다.

후속 범위: Multi-scale Local+Context, dense pair/offset 모델, 원본 legacy adapter, hard negatives, 독립 Probe/Test, 자동 CV 집계, 고급 Error Browser, Model Registry. 먼저 160/256/320/Adaptive 결과를 확인한 뒤 진행합니다.
