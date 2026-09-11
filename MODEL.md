# AlignFail 모델 노트 · 현재 모델과 다음 단계

이 문서는 딥러닝 모델 관점에서 AlignFail 학습 파이프라인을 설명합니다. **무엇을 푸는 문제인지, 지금 모델(Metric Patch v1)이 어떻게 생겼고 왜 그렇게 설계했는지, 어디가 약한지, 다음에 무엇을 바꾸려는지**를 다룹니다. 설치·실행 절차는 TRAINING.md, 코드 구조는 PROJECT_NOTES.md를 보세요.

---

## 1. 풀고 있는 문제

입력은 REF 이미지와 Query 이미지 한 쌍입니다. REF에는 사람이 지정한 **ROI(사각형)** 가 있고, Query에는 그 ROI의 패턴이 위치한 **정답 좌표 (gt_x, gt_y)** 가 있습니다. 모델은 Query 안에서 REF ROI 패턴이 있는 위치를 찍어야 합니다.

- 출력은 Query 원본 픽셀 좌표 하나와 위치별 유사도 heatmap입니다.
- 평가는 예측과 GT 사이의 **유클리드 거리(px)** 입니다. 지표는 median error, mean error, Acc@5 / Acc@10 / Acc@20(오차가 각 임계값 이하인 비율)입니다.
- 따라서 분류 문제가 아니라 **템플릿 정합(template localization)** 문제입니다. 클래스 라벨은 학습 신호로 쓰지 않고 Pattern Type(A/B/unknown)은 평가를 나눠 보는 용도로만 씁니다.

이 문제의 어려운 점은 세 가지입니다. 패턴이 반복되어 비슷한 후보가 여러 개 나올 수 있고, REF와 Query 사이에 밝기·초점·미세한 배율 차이가 있으며, 학습 데이터가 Pair 단위로 적습니다. 설계는 전반적으로 "적은 데이터로도 과적합 없이, 재현 가능하게" 쪽에 맞춰져 있습니다.

---

## 2. 현재 모델 · Metric Patch v1

코드: `training/model.py`, `training/train.py`, `training/data.py`. 회사의 기존 SupCon / Prototype / Sliding-window 코드나 가중치를 재현한 것이 아니라 명세를 바탕으로 새로 구현한 기준 모델(baseline)입니다.

### 2.1 네트워크

하나의 작은 fully convolutional encoder를 REF와 Query가 **공유**합니다(siamese).

```text
입력  1×H×W (grayscale, /255)
Conv 3×3, 1→16,  pad 1  → ReLU → AvgPool 2     stride 2
Conv 3×3, 16→32, pad 1  → ReLU → AvgPool 2     stride 4
Conv 3×3, 32→D,  pad 1  → ReLU                 D = embedding_dim (기본 256)
Global Average Pooling → L2 정규화 → D차원 단위 벡터
```

| 항목 | 값 |
|---|---|
| 총 stride | 4 |
| 특징 셀 하나의 receptive field | 약 18×18 원본 픽셀 |
| 파라미터 수 | 약 7.9만 개 (D=256 기준) |
| 사전학습 | 없음 (외부 가중치 다운로드 없음) |

의도적으로 작게 만들었습니다. 데이터가 적고, 먼저 "crop 크기(160/256/320/Adaptive)에 따라 정보가 부족한지"를 같은 모델로 비교하는 것이 이 단계의 목적이기 때문입니다. 모델이 크면 crop 차이가 모델 용량에 묻힙니다.

### 2.2 학습 신호 · Triplet

한 Pair에서 세 개의 crop을 만듭니다.

| 역할 | 어디서 | 중심 |
|---|---|---|
| Anchor | REF | ROI 중심 (두 모서리 평균, 소수 가능) |
| Positive | Query | GT 좌표 |
| Negative | Query | GT에서 `negative_min_distance`(기본 64px) 이상 떨어진 무작위 위치 |

세 crop을 같은 encoder에 통과시켜 단위 벡터 a, p, n을 얻고, cosine distance `d(x,y) = 1 - x·y`로 Triplet loss를 계산합니다.

```text
L = mean( max( d(a,p) - d(a,n) + margin, 0 ) )      margin 기본 0.5
```

즉 "REF 패턴은 정답 위치와 가깝고, 오답 위치와는 margin 이상 멀어야 한다"는 것만 가르칩니다. 클래스 라벨, Pattern Type, 다른 Pair의 이미지는 학습 신호에 들어가지 않습니다.

최적화는 AdamW(lr 1e-4, weight decay 1e-4), 고정 학습률, batch 8, 기본 100 epoch입니다. 데이터 증강은 없습니다. 시드를 고정하고 `torch.use_deterministic_algorithms(True)`, cudnn deterministic을 켜서 같은 입력이면 같은 결과가 나오게 합니다.

### 2.3 Crop 정책 (모델 입력이 결정되는 곳)

| Mode | Native crop | 모델 입력 |
|---|---|---|
| fixed_160 / 256 / 320 | 해당 크기 정사각형 | 그대로 |
| adaptive | ROI 최대 변 × context_ratio(1.5), [192, 384] clamp | output_size(320)로 bilinear resize |

샘플링은 `cv2.remap`으로 하고, 픽셀 중심이 annotation 중심에 대해 대칭이 되게 좌표를 잡습니다(center 79.5, native 160이면 0~159). 경계는 `BORDER_REFLECT_101`입니다. Adaptive에서는 Query의 positive/negative도 REF에서 정한 native/output 크기를 그대로 씁니다. 학습, 미리보기, 추론이 같은 `crop()` 함수를 써서 입력 불일치가 생기지 않습니다.

진단(mean, std, min, max, Canny edge density)은 최종 모델 입력에서 측정해 near-black / low-std / low-edge 경고를 냅니다. 경고는 자동 제외 사유가 아닙니다.

### 2.4 추론 · Dense context pooling

학습은 crop 단위지만 추론은 Query 전체에서 위치를 찾아야 합니다. 단순히 Query 전체를 encoder에 넣고 각 특징 셀(receptive field 18px)을 REF descriptor(crop 전체를 평균한 것)와 비교하면 비교 대상의 크기가 맞지 않습니다. 그래서 다음 순서로 처리합니다.

1. Query를 REF crop과 같은 배율(`scale = native/input`)로 resample하고, 특징 격자가 원본 (0,0)에 정렬되도록 좌표를 잡습니다.
2. encoder를 통과시켜 stride 4 특징 맵을 얻습니다.
3. `avg_pool2d(kernel = input_size / 4, stride 1)`로 **REF crop과 같은 공간 범위**를 평균한 descriptor를 위치마다 만듭니다. 이것이 "dense context pooling"입니다. REF의 GAP과 같은 연산을 Query의 모든 위치에서 수행하는 셈입니다.
4. L2 정규화 후 REF descriptor와 cosine similarity를 구해 위치별 점수를 얻습니다.
5. 점수 맵을 Query 원본 좌표로 remap해 heatmap을 만들고, 모든 crop 모드에서 **4px 격자**로 통일해 argmax를 예측 좌표로 삼습니다.

Patch를 단독으로 encoding한 것과 전체 영상에서 잘라 본 것은 convolution 경계 조건 때문에 완전히 같지 않습니다(reflect padding 대 실제 이웃 픽셀). 현재는 이 차이를 감수합니다. 메모리 보호를 위해 resample 후 한 변이 4096px를 넘으면 실패 처리하며 타일 추론은 없습니다.

### 2.5 Split과 모델 선택

- Fold는 `group_key` 단위로 나눕니다(GroupKFold). 같은 촬영 묶음이 train/validation 양쪽에 들어가지 않습니다.
- 이미지 파일 해시(원본·Clean 모두)가 양쪽에 겹치면 학습을 차단합니다.
- epoch마다 validation에서 dense 추론을 돌려 지표를 계산하고, **validation median error가 최소인 epoch**를 best로 저장합니다. validation loss는 negative가 무작위라 노이즈가 커서 선택 기준으로 쓰지 않습니다.
- 현재는 단일 fold 실험입니다. 5-fold 통계 집계와 독립 Test는 아직 없습니다.

---

## 3. 현재 모델의 한계 (정직하게)

다음 단계를 정하기 위해 약점을 명확히 적어 둡니다.

**표현력**
- encoder가 3개 conv층, 약 8만 파라미터로 매우 작습니다. receptive field 18px은 미세 질감은 보지만 구조적 맥락은 GAP 평균에만 의존합니다.
- GAP은 공간 배치를 버립니다. "같은 부품이 좌우 대칭으로 배치된" 패턴이나 반복 격자에서는 평균 descriptor가 비슷해져 구분이 어렵습니다. 반복 패턴 문제의 핵심 약점입니다.
- 사전학습이 없어 밝기·초점 변화에 대한 일반화가 데이터 양에 전적으로 달려 있습니다.

**학습 신호**
- negative가 완전 무작위라 대부분 "쉬운" negative입니다. 학습이 진행되면 loss가 0이 되는 triplet이 많아져 신호가 약해집니다. hard negative mining이 없습니다.
- Pair 하나에서 triplet 하나만 만듭니다. 같은 이미지의 다른 위치, 다른 Pair의 REF 등은 활용하지 않습니다.
- 증강이 없어 미세한 이동·밝기 변화에 대한 불변성을 명시적으로 배우지 않습니다.
- 클래스 라벨(Classes 페이지에서 정리하는 `class_label`)을 학습에 쓰지 않습니다. 이는 의도된 보수적 선택이지만, 라벨이 믿을 만해지면 활용 여지가 큽니다.

**추론 정밀도**
- 최종 격자가 4px이고 refinement가 없어 오차 하한이 약 2px입니다. Acc@5를 높이려면 sub-grid 보정이 필요합니다.
- 점수는 cosine 값이라 보정된 확률이 아닙니다. "못 찾았다"를 판단하는 reject 기준이 없습니다.
- 회전·배율 차이에 대한 불변성이 없습니다. Adaptive crop은 REF ROI 크기에만 반응하고 Query 쪽 배율 변화는 다루지 않습니다.

**실험 운영**
- 고정 학습률, 스케줄 없음. 단일 fold. 독립 Test 없음. 실험 이름·메모가 없어 비교가 불편합니다.

---

## 4. 이후에 바꾸려는 것

TRAINING.md의 후속 범위를 모델 관점에서 구체화한 것입니다. **순서의 원칙은 "먼저 현재 모델로 160/256/320/Adaptive 비교 결과를 받아 context 부족 여부를 확인한 뒤" 모델을 키운다**입니다. 결과 없이 모델을 바꾸면 무엇이 효과였는지 알 수 없습니다.

### 4.1 Multi-scale Local + Context encoder

같은 중심에서 두 crop을 뽑아 두 branch로 인코딩합니다.

```text
Local   branch: 160 native → 그대로           (미세 질감, 정밀 위치)
Context branch: 320~384 native → 160으로 축소  (주변 배치, 반복 패턴 구분)
descriptor = L2norm( concat(local, context) ) 또는 가중 합
```

현재 crop 비교 실험이 "큰 crop이 낫지만 해상도가 아깝다"로 나오면 이 구조가 정답입니다. 기존 `crop_spec/crop` 함수를 두 번 호출하면 되므로 데이터 파이프라인 변경은 작습니다. dense 추론에서는 두 branch를 각각 pooling한 뒤 합칩니다.

### 4.2 Dense pair/offset 모델 (2단계 정밀화)

현재 구조를 Stage 1(coarse)로 두고 Stage 2(fine)를 추가합니다.

- **Stage 1**: 지금의 dense cosine heatmap으로 상위 K개 후보(4px 격자)를 고릅니다.
- **Stage 2**: 각 후보 주변의 Query patch와 REF crop을 채널 방향으로 쌓거나 correlation volume을 만들어 작은 CNN에 넣고, **(dx, dy) offset을 회귀**합니다. 손실은 smooth L1. 동시에 "이 후보가 정답인가"를 내는 점수 head를 붙여 reject와 후보 재정렬에 씁니다.

이렇게 하면 4px 격자의 한계를 넘어 1px 이하 오차를 노릴 수 있고, Acc@5가 직접 개선됩니다. 학습 데이터는 GT 주변에서 무작위 offset을 준 patch로 자기지도적으로 무한히 만들 수 있습니다.

### 4.3 Hard negative와 학습 신호 강화

- **In-image hard negative**: 현재 모델의 heatmap에서 GT로부터 `negative_min_distance` 이상 떨어진 곳 중 점수가 가장 높은 위치를 negative로 씁니다(epoch마다 갱신). 반복 패턴 오인을 직접 공격합니다.
- **Semi-hard mining**: `d(a,p) < d(a,n) < d(a,p)+margin` 구간의 negative를 우선 선택해 학습 붕괴를 피합니다.
- **Cross-pair negative**: 다른 Pair의 REF crop을 negative로 섞어 "다른 부품"과의 구분도 배우게 합니다.
- **증강**: 밝기·대비·가우시안 노이즈·블러, sub-pixel 이동. 기하 변환(flip, 회전)은 패턴의 방향이 의미를 가질 수 있어 데이터 확인 후 결정합니다.
- 증강과 mining은 모두 manifest와 seed로 기록해 재현성을 유지합니다.

### 4.4 클래스 라벨 활용 · SupCon / Prototype 어댑터

회사의 기존 접근(SupCon, Prototype, Sliding-window)을 같은 실험 인터페이스 안에 넣는 작업입니다.

- **SupCon 보조 손실**: `class_label`이 정리된 Pair들에 대해 같은 클래스 crop은 가깝게, 다른 클래스는 멀게 하는 supervised contrastive 항을 Triplet에 더합니다. Classes 페이지에서 라벨을 검수하는 이유가 여기에 있습니다. 라벨 품질이 낮으면 오히려 해가 되므로 **옵션**으로 두고 ablation으로 효과를 확인합니다.
- **Prototype**: 클래스별 descriptor 평균(prototype)을 두고 Query 위치 descriptor를 prototype과 비교하는 방식입니다. REF 한 장 대신 클래스 전체 정보를 쓰므로 REF 품질이 나쁠 때 강합니다. REF 기반 매칭과 prototype 매칭을 점수 수준에서 결합할 수 있습니다.
- **Legacy adapter**: 기존 코드의 crop·정규화·좌표 규약을 확인한 뒤 `make_model()` 레지스트리에 `legacy_supcon`처럼 등록합니다. 입력 manifest와 출력(predictions.json, metrics.json) 형식을 맞추면 Training 화면의 비교 표에서 같은 fold·split으로 현재 모델과 직접 비교됩니다. **재현 주장을 하기 전에 기존 코드의 결과와 수치가 일치하는지 검증하는 단계가 필요합니다.**

### 4.5 백본 선택지

- 자체 학습 CNN을 조금 키운 버전(4~5층, stride 4 유지)이 첫 선택입니다. 데이터가 적어 큰 모델은 과적합 위험이 있습니다.
- ImageNet 사전학습 ResNet-18의 앞부분(stride 4~8)을 백본으로 쓰는 옵션. 산업 영상과 도메인이 다르지만 밝기·블러 불변성은 가져올 수 있습니다. 가중치는 오프라인으로 반입해야 합니다(회사 망 차단).
- DINOv2-small 같은 자기지도 모델은 패치 descriptor 품질이 좋아 클러스터링(Classes 자동 후보)과 매칭 양쪽에 쓸 수 있습니다. 다만 stride 14, 입력 크기 제약, 메모리 부담이 있어 Stage 1 후보 생성에만 쓰는 것이 현실적입니다.

### 4.6 평가·운영

- **5-fold 자동 실행과 집계**: 같은 설정으로 fold 0~4를 큐에 넣고 평균±표준편차를 비교 표에 표시합니다. 단일 fold 숫자로 결론 내리지 않기 위해 필수입니다.
- **독립 Probe/Test 세트**: 버전에서 일부 group을 test로 고정해 모델 선택에 전혀 쓰지 않습니다. 최종 성능 보고는 여기서만 합니다.
- **점수 보정과 reject**: validation에서 cosine 점수 대비 정답 확률을 추정해(예: isotonic), "신뢰도 낮음"을 표시하고 사람 검수로 넘기는 기준을 만듭니다.
- **실패 분석(Error Browser)**: 오차 상위 Pair를 heatmap과 함께 나열하고 Pattern·클래스·진단 플래그별로 오차 분포를 봅니다. 반복 패턴 오인인지, 초점 문제인지를 구분해야 다음 개선 방향이 정해집니다.
- **Model Registry / Champion**: 실험에 이름·메모를 붙이고, test 지표 기준으로 champion을 지정해 추론 API에서 불러 쓸 수 있게 합니다.
- **학습 안정화**: cosine LR 스케줄, warmup, mixed precision, 4096px 초과 Query의 타일 추론.

### 4.7 우선순위 요약

| 순서 | 작업 | 기대 효과 | 전제 |
|---|---|---|---|
| 1 | 현재 모델로 crop 4종 × fold 5 비교 | context 부족 여부 판단 | 회사 데이터에 ROI·GT·group_key 검수 완료 |
| 2 | Hard negative + 증강 | 반복 패턴 오인 감소, 일반화 | 1의 결과 |
| 3 | Multi-scale Local+Context | 해상도와 맥락을 동시에 | 1에서 큰 crop이 유리하다고 나올 때 |
| 4 | Stage 2 offset 회귀 | Acc@5 개선, 1px 정밀도 | Stage 1 후보 재현율 확인 |
| 5 | SupCon/Prototype 어댑터, 클래스 라벨 활용 | 기존 접근과 공정 비교, REF 품질 의존 감소 | Classes 라벨 검수, 기존 코드 규약 확인 |
| 6 | 5-fold 집계, 독립 Test, 점수 보정, Registry | 결론의 신뢰도, 운영 전환 | 1~4 진행 중 병행 가능 |

---

## 5. 새 모델을 추가할 때 지킬 것

- `training/model.py`의 `make_model(config)`에 이름으로 등록하고 `TrainingConfig.model`의 Literal에 추가합니다. `predict()`는 `(predicted_xy, score, heatmap)`을 **원본 Query 픽셀 좌표**로 반환해야 합니다.
- crop은 반드시 `training/data.py`의 `crop_spec()`/`crop()`을 쓰고, 새 전처리가 있으면 manifest에 기록합니다. 학습·미리보기·추론이 같은 입력을 봐야 합니다.
- 무작위성은 모두 `config["seed"]`에서 파생시키고, 증강·mining 설정은 `config.json`에 들어가야 합니다. 실험 폴더의 integrity 검사에 걸리지 않게 학습 중 코드를 바꾸지 않습니다.
- `group_split()`을 우회하지 않습니다. 새 sampling(cross-pair negative 등)도 train 집합 안에서만 샘플링해야 합니다.
- 비교 표의 `comparison_hash`는 crop 외 설정이 같을 때만 묶이므로, 새 하이퍼파라미터를 추가하면 `training_api.prepare_experiment`의 `exclude` 목록을 같이 검토합니다.
- 지표는 기존 `metrics()`를 그대로 쓰고, Pattern별 표본이 없으면 `—`로 둡니다. 0점으로 채우지 않습니다.
