import { useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { ArrowDown, ArrowRight, Boxes, Loader2, Sparkles } from "lucide-react";
import { api } from "../api";
import { useAction } from "../hooks";
import { Empty, ErrorBox } from "../components/ui";
import "../model.css";

/* ---------- Static architecture model (mirrors training/model.py) ---------- */

const CROP_INPUT: Record<string, number | null> = {
  fixed_160: 160,
  fixed_256: 256,
  fixed_320: 320,
  adaptive: null, // output_size
};
const STRIDE = 4;

type Layer = {
  name: string;
  kind: "input" | "conv" | "pool" | "gap" | "norm";
  channels: number;
  size: number;
  params: number;
  rf: number;
  jump: number;
  note: string;
};

/** Walk the encoder and record shape, receptive field and parameter count per layer. */
function architecture(input: number, dim: number): Layer[] {
  const layers: Layer[] = [];
  let size = input;
  let channels = 1;
  let rf = 1;
  let jump = 1;
  layers.push({
    name: "입력",
    kind: "input",
    channels,
    size,
    params: 0,
    rf,
    jump,
    note: "grayscale / 255",
  });
  const conv = (name: string, out: number, note: string) => {
    const params = channels * out * 9 + out;
    rf += 2 * jump; // 3x3, pad 1
    layers.push({
      name,
      kind: "conv",
      channels: out,
      size,
      params,
      rf,
      jump,
      note,
    });
    channels = out;
  };
  const pool = (name: string) => {
    rf += jump;
    jump *= 2;
    size = Math.floor(size / 2);
    layers.push({
      name,
      kind: "pool",
      channels,
      size,
      params: 0,
      rf,
      jump,
      note: "AvgPool 2×2",
    });
  };
  conv("Conv1 3×3 + ReLU", 16, "저수준 엣지·질감");
  pool("Pool1");
  conv("Conv2 3×3 + ReLU", 32, "국소 패턴 조합");
  pool("Pool2");
  conv("Conv3 3×3 + ReLU", dim, "descriptor 채널");
  layers.push({
    name: "Global Average Pool",
    kind: "gap",
    channels: dim,
    size: 1,
    params: 0,
    rf,
    jump,
    note: "공간 평균 → 벡터",
  });
  layers.push({
    name: "L2 정규화",
    kind: "norm",
    channels: dim,
    size: 1,
    params: 0,
    rf,
    jump,
    note: "단위 벡터 · cosine 비교",
  });
  return layers;
}

const fmt = (n: number) => n.toLocaleString("ko-KR");
const f3 = (n: number | undefined) => (n == null ? "—" : n.toFixed(3));

/* ---------- Experiment-backed visualisation types ---------- */

type Experiment = {
  id: string;
  status: string;
  version: number;
  created_at: string;
  config: {
    crop_mode: string;
    modality?: string;
    embedding_dim: number;
    output_size: number;
    epochs: number;
    fold: number;
  };
  metrics: Record<string, { median_error: number | null }> | null;
};
type Detail = Experiment & {
  manifest?: {
    pairs: {
      pair_id: string;
      folder: string;
      pattern_type: string;
      query_size: number[];
      query_gt: number[];
    }[];
  };
  split?: { validation: string[] };
  predictions?: {
    pair_id: string;
    prediction: number[];
    gt: number[];
    error: number;
    score: number;
  }[];
};
type Viz = {
  pair_id: string;
  folder: string;
  checkpoint: string;
  epoch: number;
  split: string;
  crop_mode: string;
  native_size: number;
  input_size: number;
  channels_shown: number;
  stages: {
    stage: number;
    channels: number;
    height: number;
    width: number;
    mean: number;
    sparsity: number;
  }[];
  layers: {
    name: string;
    in: number;
    out: number;
    params: number;
    weight_mean: number;
    weight_std: number;
    weight_abs_max: number;
  }[];
  descriptor: { anchor: number[]; positive: number[]; negative: number[] };
  cosine: {
    anchor_positive: number;
    anchor_negative: number;
    triplet_margin_gap: number;
    margin: number;
  };
};

const vizFile = (id: string, pair: string, name: string) =>
  `/api/experiments/${id}/files/viz/${pair}/${name}`;
const file = (id: string, kind: string, name: string) =>
  `/api/experiments/${id}/files/${kind}/${name}`;

/** 256-dim descriptor as a colour strip: blue negative, white zero, green positive. */
function Strip({ values, label }: { values: number[]; label: string }) {
  const max = Math.max(1e-6, ...values.map((v) => Math.abs(v)));
  return (
    <div className="strip">
      <span>{label}</span>
      <svg
        viewBox={`0 0 ${values.length} 12`}
        preserveAspectRatio="none"
        role="img"
        aria-label={`${label} descriptor`}
      >
        {values.map((v, i) => {
          const t = v / max;
          const fill =
            t >= 0
              ? `rgba(22,132,107,${0.15 + 0.85 * t})`
              : `rgba(58,112,210,${0.15 - 0.85 * t})`;
          return <rect key={i} x={i} y={0} width={1} height={12} fill={fill} />;
        })}
      </svg>
    </div>
  );
}

export function ModelPage({ projectId }: { projectId: string }) {
  const [crop, setCrop] = useState("fixed_160");
  const [outputSize, setOutputSize] = useState(320);
  const [dim, setDim] = useState(256);
  const input = CROP_INPUT[crop] ?? outputSize;
  const layers = useMemo(() => architecture(input, dim), [input, dim]);
  const total = layers.reduce((s, l) => s + l.params, 0);
  const poolKernel = Math.floor(input / STRIDE);

  const experiments = useQuery({
    queryKey: ["experiments", projectId],
    queryFn: () => api<Experiment[]>(`/projects/${projectId}/experiments`),
  });
  const trained = (experiments.data ?? []).filter((e) => e.metrics);
  const [selected, setSelected] = useState("");
  const experimentId = selected || trained[0]?.id || "";
  const detail = useQuery({
    queryKey: ["experiment", experimentId],
    queryFn: () => api<Detail>(`/experiments/${experimentId}`),
    enabled: !!experimentId,
  });
  const [pairId, setPairId] = useState("");
  const [checkpoint, setCheckpoint] = useState<"best" | "last">("best");
  const pairs = detail.data?.manifest?.pairs ?? [];
  const activePair =
    pairs.find((p) => p.pair_id === pairId)?.pair_id ??
    detail.data?.predictions?.[0]?.pair_id ??
    pairs[0]?.pair_id ??
    "";
  const { busy, error, run } = useAction();
  const [viz, setViz] = useState<Viz | null>(null);
  const prediction = detail.data?.predictions?.find(
    (p) => p.pair_id === viz?.pair_id,
  );
  const row = pairs.find((p) => p.pair_id === viz?.pair_id);

  return (
    <div className="model-page">
      {/* ---------------- Architecture ---------------- */}
      <section className="panel model-section">
        <div className="section-title">
          <div>
            <div className="eyebrow">METRIC PATCH V1</div>
            <h2>Encoder 구조</h2>
          </div>
          <div className="model-controls">
            <label>
              Crop
              <select
                aria-label="구조 보기 crop"
                value={crop}
                onChange={(e) => setCrop(e.target.value)}
              >
                {Object.keys(CROP_INPUT).map((m) => (
                  <option key={m}>{m}</option>
                ))}
              </select>
            </label>
            {crop === "adaptive" && (
              <label>
                Input
                <input
                  aria-label="adaptive 입력 크기"
                  type="number"
                  min={32}
                  max={512}
                  step={4}
                  value={outputSize}
                  onChange={(e) => setOutputSize(Number(e.target.value))}
                />
              </label>
            )}
            <label>
              Embedding
              <input
                aria-label="embedding 차원"
                type="number"
                min={16}
                max={512}
                value={dim}
                onChange={(e) => setDim(Number(e.target.value))}
              />
            </label>
          </div>
        </div>
        <p className="section-description model-desc">
          REF crop과 Query crop이 <strong>같은 encoder</strong>를 통과합니다.
          층마다 출력 크기(C × H × W), 한 셀이 보는 원본 범위(receptive field),
          파라미터 수를 표시합니다. 총 stride {STRIDE}, 파라미터 {fmt(total)}개.
        </p>
        <div className="arch-flow">
          {layers.map((l, i) => (
            <div key={l.name} className={`arch-layer ${l.kind}`}>
              <div className="arch-name">{l.name}</div>
              <div className="arch-shape">
                {l.kind === "gap" || l.kind === "norm" ? (
                  <span className="mono">{l.channels}-d</span>
                ) : (
                  <span className="mono">
                    {l.channels} × {l.size} × {l.size}
                  </span>
                )}
              </div>
              <div className="arch-meta">
                <span>RF {l.rf}px</span>
                <span>stride {l.jump}</span>
                {l.params > 0 && <span>{fmt(l.params)} p</span>}
              </div>
              <div className="arch-note">{l.note}</div>
              {i < layers.length - 1 && (
                <ArrowDown className="arch-arrow" size={14} />
              )}
            </div>
          ))}
        </div>
      </section>

      <section className="panel model-section experiment-purpose">
        <div className="section-title">
          <h2>160×160을 기준으로 무엇을 더 실험하나요?</h2>
        </div>
        <div className="experiment-purpose-body">
          <p>
            <strong>먼저 볼 것은 입력 주변 범위의 효과입니다.</strong> 160×160은
            현재 기준 crop 크기입니다. 같은 CNN과 Triplet 학습을 유지하면서
            256×256, 320×320, ROI 크기에 맞춘 Adaptive를 각각 학습해,
            작은 crop에서 놓친 주변 구조가 위치 찾기에 도움이 되는지 비교합니다.
            위 Crop 선택은 구조 설명만 바꾸며, 실제 실험은 Training에서 준비합니다.
          </p>
          <div className="experiment-table-scroll">
            <table>
              <caption>현재 실행 가능한 crop 비교 · Adaptive 수치는 기본 설정</caption>
              <thead>
                <tr><th>실험</th><th>원본에서 자르는 범위 → 모델 입력</th><th>확인하려는 것</th></tr>
              </thead>
              <tbody>
                <tr><th>Fixed 160 · 기준</th><td>160×160 → 160×160</td><td>국소 질감만으로 정답과 비슷한 오답 위치를 구분할 수 있는가?</td></tr>
                <tr><th>Fixed 256</th><td>256×256 → 256×256</td><td>주변 구조를 조금 더 보면 반복 패턴 오인이 줄어드는가?</td></tr>
                <tr><th>Fixed 320</th><td>320×320 → 320×320</td><td>더 넓은 배치 정보의 이득이 불필요한 배경과 계산량 증가보다 큰가?</td></tr>
                <tr><th>Adaptive</th><td>ROI 최대 변 × 1.5를 192~384px로 제한 → 320×320</td><td>패턴 크기별로 보는 범위를 맞추면 고정 crop보다 일관적인가? 리사이즈로 미세 질감이 손실되는가?</td></tr>
              </tbody>
            </table>
          </div>
          <p>
            <strong>비교 방법:</strong> OM과 SEM은 각각 실험합니다. 같은 데이터
            버전·Train/Validation 그룹·seed·epoch·학습률·모델 차원을 유지하고
            crop 정책을 바꿉니다. Median/Mean 위치 오차는 낮을수록,
            Acc@5·10·20은 높을수록 좋습니다. 처리 시간도 함께 확인합니다.
            Adaptive는 주변 범위와 리사이즈 효과가 함께 바뀌므로 Fixed 320과
            비교해 해석합니다. 큰 crop이 더 좋다는 결론은 아직 없습니다.
          </p>
          <p>
            <strong>새 이미지에서 보고 싶은 결과:</strong> s 이미지는 기존
            성공 위치의 십자선을 읽고 사람이 확인한 GT로 정확도를 평가합니다.
            e 이미지는 십자선이 없어도 대응 REF와 수동 GT를 지정하면 기존
            실패 사례를 얼마나 찾는지 평가할 수 있습니다. 표시는 입력에서
            제거한 Clean을 사용해 표시 자체가 정답 단서가 되지 않게 준비합니다.
            s/e별 지표는 GT가 준비된 표본에서 해석하며, 현재 비교 화면은
            주로 Overall과 Pattern별 결과를 보여 줍니다.
          </p>
          <details>
            <summary>기존 방식과의 비교, 이후 모델 실험</summary>
            <p>
              현재 Metric Patch v1은 새로 만든 기준 모델입니다. 회사의 기존
              모델 코드·가중치를 연결해 같은 조건으로 재현한 상태는 아닙니다.
              기존 방식보다 개선됐는지는 동일 Query·검수 GT에서 기존 예측과
              새 예측을 비교해야 합니다. s/e 표기만으로 정밀도 개선을 증명할 수는 없습니다.
            </p>
            <ul>
              <li><strong>큰 crop이 유리하면:</strong> 160의 미세 질감과 320 이상 범위의 주변 구조를 함께 보는 Local + Context 두 경로를 검토합니다.</li>
              <li><strong>반복 패턴을 계속 혼동하면:</strong> 모델이 높은 점수를 준 오답 위치를 학습하는 hard negative와 밝기·블러 증강을 검토합니다.</li>
              <li><strong>위치는 근처인데 오차가 남으면:</strong> 현재 4px 탐색 격자에서 얻은 후보를 세밀하게 보정하는 offset 모델을 검토합니다.</li>
              <li><strong>클래스 검수가 충분해지면:</strong> 클래스 라벨을 활용하는 SupCon·Prototype과 기존 모델 연결을 검토합니다. 현재 Triplet loss에는 클래스 라벨이 들어가지 않습니다.</li>
            </ul>
            <p>위 네 가지는 후속 계획이며 현재 실행 가능한 모델 옵션은 아닙니다.</p>
          </details>
        </div>
      </section>

      {/* ---------------- Training & inference flow ---------------- */}
      <div className="model-columns">
        <section className="panel model-section">
          <div className="section-title">
            <h2>학습 · Triplet</h2>
          </div>
          <div className="flow">
            <div className="flow-row">
              <div className="flow-box ref">
                Anchor
                <br />
                <small>REF · ROI 중심 crop</small>
              </div>
              <div className="flow-box pos">
                Positive
                <br />
                <small>Query · GT 중심 crop</small>
              </div>
              <div className="flow-box neg">
                Negative
                <br />
                <small>Query · GT에서 ≥ 최소 거리 무작위</small>
              </div>
            </div>
            <ArrowDown size={16} className="flow-arrow" />
            <div className="flow-box wide">
              공유 encoder → GAP → L2 정규화 → a, p, n
            </div>
            <ArrowDown size={16} className="flow-arrow" />
            <div className="flow-box wide formula">
              L = max( (1 − a·p) − (1 − a·n) + margin, 0 )
              <small>
                cosine distance Triplet · margin 기본 0.5 · AdamW, 고정 LR
              </small>
            </div>
          </div>
          <p className="section-description">
            클래스 라벨과 Pattern Type은 손실에 들어가지 않습니다. best epoch는
            validation median error 기준으로 고릅니다.
          </p>
        </section>
        <section className="panel model-section">
          <div className="section-title">
            <h2>추론 · Dense context pooling</h2>
          </div>
          <div className="flow">
            <div className="flow-box wide">
              Query 전체를 REF와 같은 배율로 resample → encoder → {dim} × H/
              {STRIDE} × W/{STRIDE}
            </div>
            <ArrowDown size={16} className="flow-arrow" />
            <div className="flow-box wide">
              avg_pool2d(kernel {poolKernel} × {poolKernel}, stride 1)
              <small>
                REF crop({input}px)과 같은 범위를 위치마다 평균 → 위치별
                descriptor
              </small>
            </div>
            <ArrowDown size={16} className="flow-arrow" />
            <div className="flow-box wide">
              L2 정규화 · REF descriptor와 cosine → 점수 맵 → 원본 좌표로 remap
            </div>
            <ArrowDown size={16} className="flow-arrow" />
            <div className="flow-box wide formula">
              argmax on 4px grid → (x, y)
              <small>
                모든 crop 모드에서 최종 격자 4px · offset refinement 없음
                (MODEL.md 4.2)
              </small>
            </div>
          </div>
        </section>
      </div>

      {/* ---------------- Trained checkpoint ---------------- */}
      <section className="panel model-section">
        <div className="section-title">
          <div>
            <div className="eyebrow">TRAINED CHECKPOINT</div>
            <h2>학습된 모델이 보는 것</h2>
          </div>
          <div className="model-controls">
            <label>
              실험
              <select
                aria-label="시각화 실험"
                value={experimentId}
                onChange={(e) => {
                  setSelected(e.target.value);
                  setPairId("");
                  setViz(null);
                }}
                disabled={!trained.length}
              >
                {trained.map((e) => (
                  <option key={e.id} value={e.id}>
                    {e.id.slice(0, 8)} · v{e.version} ·{" "}
                    {e.config.modality ?? "all"} · {e.config.crop_mode} · fold{" "}
                    {e.config.fold} · med{" "}
                    {f3(e.metrics?.Overall?.median_error ?? undefined)}
                  </option>
                ))}
              </select>
            </label>
            <label>
              Pair
              <select
                aria-label="시각화 Pair"
                value={activePair}
                onChange={(e) => setPairId(e.target.value)}
                disabled={!pairs.length}
              >
                {pairs.map((p) => (
                  <option key={p.pair_id} value={p.pair_id}>
                    {p.folder} · {p.pattern_type}
                    {detail.data?.split?.validation.includes(p.pair_id)
                      ? " · Val"
                      : " · Train"}
                  </option>
                ))}
              </select>
            </label>
            <label>
              체크포인트
              <select
                aria-label="체크포인트"
                value={checkpoint}
                onChange={(e) =>
                  setCheckpoint(e.target.value as typeof checkpoint)
                }
              >
                <option value="best">best</option>
                <option value="last">last</option>
              </select>
            </label>
            <button
              className="button primary"
              disabled={busy || !experimentId || !activePair}
              onClick={() =>
                run(async () => {
                  setViz(
                    await api<Viz>(
                      `/experiments/${experimentId}/visualize`,
                      "POST",
                      { pair_id: activePair, checkpoint },
                    ),
                  );
                })
              }
            >
              {busy ? (
                <Loader2 className="spin" size={15} />
              ) : (
                <Sparkles size={15} />
              )}{" "}
              시각화 생성
            </button>
          </div>
        </div>
        <ErrorBox error={error || experiments.error || detail.error} />
        {!trained.length ? (
          <Empty icon={<Boxes size={28} />} title="완료된 실험이 없습니다.">
            <p>
              Training에서 학습을 완료하면 체크포인트의 필터·특징
              맵·descriptor를 여기서 볼 수 있습니다.
            </p>
          </Empty>
        ) : !viz ? (
          <p className="section-description model-desc">
            실험과 Pair를 고르고 <strong>시각화 생성</strong>을 누르세요. 학습
            Python(ALIGNFAIL_TRAINING_PYTHON)으로 체크포인트를 CPU에서
            실행합니다.
          </p>
        ) : (
          <div className="viz">
            <div className="viz-summary">
              <span>
                <strong>{viz.folder}</strong> · {viz.split} · {viz.checkpoint}{" "}
                (epoch {viz.epoch})
              </span>
              <span>
                {viz.crop_mode} · native {viz.native_size} → input{" "}
                {viz.input_size}
              </span>
            </div>

            <h3>모델 입력 3장</h3>
            <div className="viz-triplet">
              {(["anchor", "positive", "negative"] as const).map((name) => (
                <figure key={name} className={name}>
                  <img
                    src={vizFile(experimentId, viz.pair_id, `${name}.png`)}
                    alt={name}
                  />
                  <figcaption>
                    {name === "anchor"
                      ? "Anchor · REF"
                      : name === "positive"
                        ? "Positive · Query GT"
                        : "Negative · Query 원거리"}
                  </figcaption>
                </figure>
              ))}
              <div className="viz-cosine">
                <div>
                  <span>cos(a, p)</span>
                  <strong className="good">
                    {f3(viz.cosine.anchor_positive)}
                  </strong>
                </div>
                <div>
                  <span>cos(a, n)</span>
                  <strong className="bad">
                    {f3(viz.cosine.anchor_negative)}
                  </strong>
                </div>
                <div>
                  <span>d(a,p) − d(a,n)</span>
                  <strong>{f3(viz.cosine.triplet_margin_gap)}</strong>
                  <small>
                    {viz.cosine.triplet_margin_gap + viz.cosine.margin <= 0
                      ? "margin 만족 · loss 0"
                      : `margin ${viz.cosine.margin} 미달 · loss ${f3(viz.cosine.triplet_margin_gap + viz.cosine.margin)}`}
                  </small>
                </div>
              </div>
            </div>

            <h3>Descriptor ({viz.descriptor.anchor.length}-d, L2 정규화)</h3>
            <div className="viz-strips">
              <Strip values={viz.descriptor.anchor} label="Anchor" />
              <Strip values={viz.descriptor.positive} label="Positive" />
              <Strip values={viz.descriptor.negative} label="Negative" />
              <p className="subtle">
                초록은 양수, 파랑은 음수. Anchor와 Positive의 패턴이 닮을수록
                cos(a,p)가 높습니다.
              </p>
            </div>

            <h3>Conv1 필터 (3×3 × {viz.layers[0]?.out})</h3>
            <div className="viz-filters">
              <img
                src={vizFile(experimentId, viz.pair_id, "conv1_filters.png")}
                alt="conv1 filters"
              />
              <table>
                <thead>
                  <tr>
                    <th>층</th>
                    <th>in → out</th>
                    <th>params</th>
                    <th>weight mean</th>
                    <th>std</th>
                    <th>|max|</th>
                  </tr>
                </thead>
                <tbody>
                  {viz.layers.map((l) => (
                    <tr key={l.name}>
                      <td>{l.name}</td>
                      <td>
                        {l.in} → {l.out}
                      </td>
                      <td>{fmt(l.params)}</td>
                      <td>{l.weight_mean.toFixed(4)}</td>
                      <td>{l.weight_std.toFixed(4)}</td>
                      <td>{l.weight_abs_max.toFixed(3)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>

            <h3>특징 맵 (각 stage의 앞 {viz.channels_shown} 채널)</h3>
            <div className="viz-stages">
              {viz.stages.map((s) => (
                <div key={s.stage} className="viz-stage">
                  <div className="viz-stage-title">
                    Stage {s.stage} · {s.channels} × {s.height} × {s.width}
                    <small>
                      mean {s.mean.toFixed(3)} · 0 비율{" "}
                      {(s.sparsity * 100).toFixed(0)}%
                    </small>
                  </div>
                  <div className="viz-stage-pair">
                    <figure>
                      <img
                        src={vizFile(
                          experimentId,
                          viz.pair_id,
                          `anchor_stage${s.stage}.png`,
                        )}
                        alt={`anchor stage ${s.stage}`}
                      />
                      <figcaption>Anchor</figcaption>
                    </figure>
                    <figure>
                      <img
                        src={vizFile(
                          experimentId,
                          viz.pair_id,
                          `positive_stage${s.stage}.png`,
                        )}
                        alt={`positive stage ${s.stage}`}
                      />
                      <figcaption>Positive</figcaption>
                    </figure>
                  </div>
                </div>
              ))}
            </div>

            {row && prediction && (
              <>
                <h3>Validation 예측 · cosine heatmap</h3>
                <div className="viz-heat">
                  <div
                    className="prediction-canvas"
                    style={{
                      aspectRatio: `${row.query_size[0]}/${row.query_size[1]}`,
                    }}
                  >
                    <img
                      src={file(
                        experimentId,
                        "preview",
                        `${row.pair_id}_query.png`,
                      )}
                      alt="Query"
                    />
                    <img
                      className="prediction-heat"
                      src={file(experimentId, "heatmaps", `${row.pair_id}.png`)}
                      alt="heatmap"
                    />
                    <svg viewBox={`0 0 ${row.query_size.join(" ")}`}>
                      {(() => {
                        const r = Math.max(
                          4,
                          Math.min(row.query_size[0], row.query_size[1]) / 60,
                        );
                        return (
                          <>
                            <circle
                              cx={prediction.gt[0]}
                              cy={prediction.gt[1]}
                              r={r}
                              stroke="#40ff93"
                              fill="none"
                              strokeWidth={2}
                              vectorEffect="non-scaling-stroke"
                            />
                            <circle
                              cx={prediction.prediction[0]}
                              cy={prediction.prediction[1]}
                              r={r}
                              stroke="#ff4040"
                              fill="none"
                              strokeWidth={2}
                              vectorEffect="non-scaling-stroke"
                            />
                          </>
                        );
                      })()}
                    </svg>
                  </div>
                  <p className="subtle">
                    초록 GT · 빨강 예측 · error {prediction.error.toFixed(2)} px
                    · score {f3(prediction.score)} <ArrowRight size={12} /> 4px
                    격자 argmax
                  </p>
                </div>
              </>
            )}
          </div>
        )}
      </section>
    </div>
  );
}
