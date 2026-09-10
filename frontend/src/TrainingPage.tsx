import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { api, type Version } from "./api";
import "./training.css";

type Config = {
  crop_mode: string;
  folds: number;
  fold: number;
  epochs: number;
  batch_size: number;
  lr: number;
  seed: number;
  device: string;
  context_ratio: number;
  min_crop: number;
  max_crop: number;
  output_size: number;
  negative_min_distance: number;
  margin: number;
  weight_decay: number;
  embedding_dim: number;
  near_black_mean: number;
  low_std: number;
  low_edge_density: number;
};
type Score = {
  count: number;
  median_error: number | null;
  mean_error: number | null;
  "acc@5": number | null;
  "acc@10": number | null;
  "acc@20": number | null;
};
type Row = {
  pair_id: string;
  folder: string;
  pattern_type: string;
  ref_center: number[];
  query_gt: number[];
  query_size: number[];
  crops: Record<
    string,
    {
      native_size: number;
      input_size: number;
      mean: number;
      std: number;
      min: number;
      max: number;
      edge_density: number;
      resize_scale: number;
    }
  >;
};
type Prediction = {
  pair_id: string;
  folder: string;
  error: number;
  score: number;
  prediction: number[];
  gt: number[];
  pattern_type: string;
};
type Experiment = {
  id: string;
  version: number;
  version_id: string;
  status: string;
  config: Config;
  split_hash: string;
  comparison_hash: string;
  error?: string;
  metrics: Record<string, Score> | null;
  manifest?: { pairs: Row[] };
  split?: {
    train: string[];
    validation: string[];
    train_groups: string[];
    validation_groups: string[];
    leakage: string;
  };
  diagnostics?: Record<string, Record<string, number>>;
  history?: {
    epoch: number;
    train_loss: number;
    val_loss: number;
    lr: number;
    metrics: Record<string, Score>;
  }[];
  predictions?: Prediction[];
  log?: string;
};
const modes = ["fixed_160", "fixed_256", "fixed_320", "adaptive"];
const defaults: Config = {
  crop_mode: "fixed_160",
  folds: 5,
  fold: 0,
  epochs: 100,
  batch_size: 8,
  lr: 0.0001,
  seed: 42,
  device: "cuda",
  context_ratio: 1.5,
  min_crop: 192,
  max_crop: 384,
  output_size: 320,
  negative_min_distance: 64,
  margin: 0.5,
  weight_decay: 0.0001,
  embedding_dim: 256,
  near_black_mean: 15,
  low_std: 5,
  low_edge_density: 0.01,
};
const format = (n: number | null | undefined, d = 3) =>
  n == null ? "—" : n.toFixed(d);
const file = (id: string, kind: string, name: string) =>
  `/api/experiments/${id}/files/${kind}/${name}`;

export default function TrainingPage({ projectId }: { projectId: string }) {
  const [config, setConfig] = useState(defaults);
  const [versionId, setVersionId] = useState("");
  const [selected, setSelected] = useState("");
  const [pairId, setPairId] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const versions = useQuery({
    queryKey: ["training-versions", projectId],
    queryFn: () => api<Version[]>(`/projects/${projectId}/versions`),
  });
  const env = useQuery({
    queryKey: ["training-env"],
    queryFn: () => api<{ python: string }>("/training/environment"),
  });
  const experiments = useQuery({
    queryKey: ["experiments", projectId],
    queryFn: () => api<Experiment[]>(`/projects/${projectId}/experiments`),
    refetchInterval: 2500,
  });
  const detail = useQuery({
    queryKey: ["experiment", selected],
    queryFn: () => api<Experiment>(`/experiments/${selected}`),
    enabled: !!selected,
    refetchInterval: 2500,
  });
  const exp = detail.data;
  const row =
    exp?.manifest?.pairs.find((p) => p.pair_id === pairId) ??
    exp?.manifest?.pairs.find((p) => p.pair_id === exp.predictions?.[0]?.pair_id) ??
    exp?.manifest?.pairs[0];
  const prediction = exp?.predictions?.find((p) => p.pair_id === row?.pair_id);
  const activeVersion = versionId || versions.data?.[0]?.id || "";
  const comparisons = (experiments.data ?? []).filter(
    (e) => e.metrics && (!exp || e.comparison_hash === exp.comparison_hash),
  );
  const field = (key: keyof Config, value: string | number) =>
    setConfig((c) => ({ ...c, [key]: value }));
  async function action(fn: () => Promise<void>) {
    setBusy(true);
    setError("");
    try {
      await fn();
      await experiments.refetch();
      if (selected) await detail.refetch();
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  }
  const numeric = (key: keyof Config, label: string, step = 1) => (
    <label key={key}>
      {label}
      <input
        type="number"
        aria-label={label}
        step={step}
        value={config[key]}
        onChange={(e) => field(key, Number(e.target.value))}
      />
    </label>
  );
  return (
    <div className="training-page">
      <section className="panel training-body">
        <h2>학습 입력 준비</h2>
        <p>
          새 Triplet 기준 모델 · 같은 모델에서 crop context만 비교합니다.
          Pattern Type은 평가 구분에만 사용합니다.
        </p>
        <p className="training-note">
          학습 Python: {env.data?.python ?? "확인 중"} · 서버의
          ALIGNFAIL_TRAINING_PYTHON으로 지정
        </p>
        <fieldset disabled={busy}>
          <div className="training-controls">
            <label>
              Dataset Version
              <select
                aria-label="학습 Dataset Version"
                value={activeVersion}
                onChange={(e) => setVersionId(e.target.value)}
              >
                {versions.data?.map((v) => (
                  <option key={v.id} value={v.id}>
                    v{v.number} · {v.description}
                  </option>
                ))}
              </select>
            </label>
            <label>
              모델
              <select>
                <option>Metric Patch · Shared CNN / Triplet v1</option>
              </select>
            </label>
            <label>
              Crop Mode
              <select
                aria-label="학습 Crop Mode"
                value={config.crop_mode}
                onChange={(e) => field("crop_mode", e.target.value)}
              >
                {modes.map((m) => (
                  <option key={m}>{m}</option>
                ))}
              </select>
            </label>
            <label>
              Device
              <select
                aria-label="학습 Device"
                value={config.device}
                onChange={(e) => field("device", e.target.value)}
              >
                <option value="cuda">CUDA</option>
                <option value="cpu">CPU · 기능 검증</option>
              </select>
            </label>
          </div>
          <div className="training-controls">
            {numeric("folds", "Folds")}
            {numeric("fold", "Fold (0부터)")}
            {numeric("epochs", "Epochs")}
            {numeric("batch_size", "Batch Size")}
            {numeric("lr", "Learning Rate", 0.0001)}
            {numeric("seed", "Seed")}
          </div>
          <details>
            <summary>Crop · 진단 · 학습 상세 설정</summary>
            <div className="training-controls">
              {numeric("context_ratio", "Context Ratio", 0.1)}
              {numeric("min_crop", "Min Crop")}
              {numeric("max_crop", "Max Crop")}
              {numeric("output_size", "Adaptive Input Size")}
              {numeric("negative_min_distance", "Negative Min Distance")}
              {numeric("margin", "Triplet Margin", 0.1)}
              {numeric("weight_decay", "Weight Decay", 0.0001)}
              {numeric("embedding_dim", "Embedding Dim")}
              {numeric("near_black_mean", "Near Black Mean")}
              {numeric("low_std", "Low Std")}
              {numeric("low_edge_density", "Low Edge Density", 0.001)}
            </div>
          </details>
          <button
            className="button primary"
            disabled={!activeVersion}
            onClick={() =>
              action(async () => {
                const result = await api<Experiment>(
                  "/training/prepare",
                  "POST",
                  { version_id: activeVersion, config },
                );
                setSelected(result.id);
                setPairId("");
              })
            }
          >
            {busy ? "준비 중…" : "입력 고정 · Split 검사 · Crop Preview"}
          </button>
        </fieldset>
        {!activeVersion && (
          <p>
            REF ROI·수동 Query GT·group_key·Pattern Type을 검수하고 Versions에서
            버전을 생성하세요.
          </p>
        )}
        {(error || versions.error || experiments.error || detail.error) && (
          <p className="error-box" role="alert">
            {error ||
              String(versions.error || experiments.error || detail.error)}
          </p>
        )}
      </section>
      <section className="panel training-body">
        <h2>실험 목록</h2>
        <div className="training-scroll">
          <table>
            <thead>
              <tr>
                <th>실험</th>
                <th>Version / Fold</th>
                <th>Crop</th>
                <th>상태</th>
                <th>학습 설정</th>
              </tr>
            </thead>
            <tbody>
              {experiments.data?.map((e) => (
                <tr
                  key={e.id}
                  className={e.id === selected ? "training-selected" : ""}
                >
                  <td>
                    <button
                      className="button secondary small"
                      onClick={() => {
                        setSelected(e.id);
                        setPairId("");
                      }}
                    >
                      {e.id.slice(0, 8)}
                    </button>
                  </td>
                  <td>
                    v{e.version} / {e.config.fold}
                  </td>
                  <td>{e.config.crop_mode}</td>
                  <td>{e.status}</td>
                  <td>
                    {e.config.epochs} epochs · LR {e.config.lr} · seed{" "}
                    {e.config.seed}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>
      {exp && (
        <section className="panel training-body">
          <div className="training-controls">
            <h2>
              실험 {exp.id.slice(0, 8)} · {exp.config.crop_mode}
            </h2>
            <strong>{exp.status}</strong>
            {exp.status === "prepared" && (
              <button
                disabled={busy}
                className="button primary"
                onClick={() =>
                  action(async () => {
                    await api(`/experiments/${exp.id}/start`, "POST");
                  })
                }
              >
                이 입력으로 학습 시작
              </button>
            )}
            {["running", "queued"].includes(exp.status) && (
              <button
                disabled={busy}
                className="button secondary"
                onClick={() =>
                  action(async () => {
                    await api(`/experiments/${exp.id}/stop`, "POST");
                  })
                }
              >
                학습 중단
              </button>
            )}
            <button
              className="button secondary"
              onClick={() => {
                setConfig(exp.config);
                setVersionId(exp.version_id);
              }}
            >
              이 설정을 새 실험 설정으로 복사
            </button>
          </div>
          <p>
            이 실험의 입력과 설정은 고정되었습니다. 상단 설정 변경은 새로
            준비하는 실험에만 적용됩니다.
          </p>
          {exp.error && <p className="error-box">{exp.error}</p>}
          {exp.split && (
            <>
              <div className="training-split">
                <strong>Group / Hash Leakage {exp.split.leakage}</strong>
                <span>
                  Train {exp.split.train.length} Pair /{" "}
                  {exp.split.train_groups.length} Groups
                </span>
                <span>
                  Validation {exp.split.validation.length} Pair /{" "}
                  {exp.split.validation_groups.length} Groups
                </span>
              </div>
              <table>
                <thead>
                  <tr>
                    <th>Pattern</th>
                    <th>Train</th>
                    <th>Validation</th>
                  </tr>
                </thead>
                <tbody>
                  {["A", "B", "unknown"].map((p) => (
                    <tr key={p}>
                      <td>{p}</td>
                      <td>
                        {
                          exp.manifest?.pairs.filter(
                            (r) =>
                              r.pattern_type === p &&
                              exp.split!.train.includes(r.pair_id),
                          ).length
                        }
                      </td>
                      <td>
                        {
                          exp.manifest?.pairs.filter(
                            (r) =>
                              r.pattern_type === p &&
                              exp.split!.validation.includes(r.pair_id),
                          ).length
                        }
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </>
          )}
          <h3>Crop Diagnostics · 경고만 표시하며 자동 제외하지 않습니다</h3>
          <div className="training-scroll">
            <table>
              <thead>
                <tr>
                  <th>Mode</th>
                  <th>Total</th>
                  <th>Near Black</th>
                  <th>Low Std</th>
                  <th>Low Edge</th>
                  <th>Problematic</th>
                </tr>
              </thead>
              <tbody>
                {Object.entries(exp.diagnostics ?? {}).map(([mode, s]) => (
                  <tr key={mode}>
                    <td>{mode}</td>
                    <td>{s.total}</td>
                    <td>{s.near_black}</td>
                    <td>{s.low_std}</td>
                    <td>{s.low_edge_density}</td>
                    <td>{s.problematic}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <label>
            입력 Pair
            <select
              aria-label="Crop Preview Pair"
              value={row?.pair_id ?? ""}
              onChange={(e) => setPairId(e.target.value)}
            >
              {exp.manifest?.pairs.map((p) => (
                <option key={p.pair_id} value={p.pair_id}>
                  {p.folder} · {p.pattern_type}
                  {exp.split?.validation.includes(p.pair_id) ? " · Validation" : " · Train"}
                </option>
              ))}
            </select>
          </label>
          {row && (
            <div className="crop-gallery">
              <figure>
                <img
                  src={file(exp.id, "preview", `${row.pair_id}_ref.png`)}
                  alt="학습 REF 원본"
                />
                <figcaption>
                  선택 REF (유효한 Clean 우선)
                  <br />
                  Center {row.ref_center.join(", ")}
                </figcaption>
              </figure>
              {modes.map((mode) => (
                <figure
                  key={mode}
                  className={
                    mode === exp.config.crop_mode ? "training-selected" : ""
                  }
                >
                  <img
                    src={file(exp.id, "preview", `${row.pair_id}_${mode}.png`)}
                    alt={`${mode} 실제 입력`}
                  />
                  <figcaption>
                    <strong>{mode}</strong>
                    <br />
                    {row.crops[mode].native_size} crop →{" "}
                    {row.crops[mode].input_size} input
                    <br />
                    Mean {format(row.crops[mode].mean, 1)} · Std{" "}
                    {format(row.crops[mode].std, 1)}
                    <br />
                    Min {row.crops[mode].min} · Max {row.crops[mode].max}
                    <br />
                    Edge {format(row.crops[mode].edge_density)}
                    <br />
                    Scale {format(row.crops[mode].resize_scale)}
                  </figcaption>
                </figure>
              ))}
            </div>
          )}
          {!!exp.history?.length && (
            <>
              <h3>학습 곡선</h3>
              <LossChart history={exp.history} />
              <div className="training-scroll">
                <table>
                  <thead>
                    <tr>
                      <th>Epoch</th>
                      <th>Train Loss</th>
                      <th>Val Loss</th>
                      <th>LR</th>
                      <th>Median Error</th>
                      <th>Acc@10</th>
                    </tr>
                  </thead>
                  <tbody>
                    {exp.history.map((h) => (
                      <tr key={h.epoch}>
                        <td>{h.epoch}</td>
                        <td>{format(h.train_loss)}</td>
                        <td>{format(h.val_loss)}</td>
                        <td>{h.lr}</td>
                        <td>{format(h.metrics.Overall.median_error)}</td>
                        <td>{format(h.metrics.Overall["acc@10"])}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </>
          )}
          {exp.metrics && (
            <>
              <h3>Best checkpoint · Validation 결과</h3>
              <table>
                <thead>
                  <tr>
                    <th>Pattern</th>
                    <th>N</th>
                    <th>Acc@5</th>
                    <th>Acc@10</th>
                    <th>Acc@20</th>
                    <th>Median px</th>
                  </tr>
                </thead>
                <tbody>
                  {Object.entries(exp.metrics).map(([p, m]) => (
                    <tr key={p}>
                      <td>{p}</td>
                      <td>{m.count}</td>
                      <td>{format(m["acc@5"])}</td>
                      <td>{format(m["acc@10"])}</td>
                      <td>{format(m["acc@20"])}</td>
                      <td>{format(m.median_error)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </>
          )}
          {row && prediction && (
            <>
              <h3>{row.folder} · Validation 예측</h3>
              <div
                className="prediction-canvas"
                style={{
                  aspectRatio: `${row.query_size[0]}/${row.query_size[1]}`,
                }}
              >
                <img
                  src={file(exp.id, "preview", `${row.pair_id}_query.png`)}
                  alt="평가 Query"
                />
                <img
                  className="prediction-heat"
                  src={file(exp.id, "heatmaps", `${row.pair_id}.png`)}
                  alt="Cosine Similarity Heatmap"
                />
                <svg viewBox={`0 0 ${row.query_size.join(" ")}`}>
                  <circle
                    cx={prediction.gt[0]}
                    cy={prediction.gt[1]}
                    r={5}
                    stroke="#40ff93"
                    fill="none"
                    strokeWidth={2}
                  />
                  <circle
                    cx={prediction.prediction[0]}
                    cy={prediction.prediction[1]}
                    r={5}
                    stroke="#ff4040"
                    fill="none"
                    strokeWidth={2}
                  />
                </svg>
              </div>
              <p>
                초록 GT · 빨강 예측 · Error {format(prediction.error, 2)} px ·
                Cosine score {format(prediction.score)} (보정된 확률이 아님)
              </p>
            </>
          )}
          <details>
            <summary>학습 로그 / Traceback</summary>
            <pre className="training-log">
              {exp.log || "아직 실행 로그가 없습니다."}
            </pre>
          </details>
          <div className="training-downloads">
            {[
              "config.json",
              "dataset_manifest.json",
              "split_manifest.json",
              "environment.json",
              ...(exp.history?.length ? ["history.json", "last.pt"] : []),
              ...(exp.metrics
                ? ["metrics.json", "predictions.json", "best.pt"]
                : []),
            ].map((name) => (
              <a key={name} href={file(exp.id, "artifacts", name)}>
                {name}
              </a>
            ))}
          </div>
        </section>
      )}
      <section className="panel training-body">
        <h2>Crop 비교 · 동일 Version / Split</h2>
        <p>
          선택한 실험과 Version·Split·학습 코드·Crop 외 학습 설정이 모두 같은
          결과만 표시합니다. Validation 결과이며 최종 Test 성능은 아닙니다.
        </p>
        <div className="training-scroll">
          <table>
            <thead>
              <tr>
                <th>실험 / Crop</th>
                <th>Pattern A Acc@10</th>
                <th>Pattern B Acc@10</th>
                <th>Overall Acc@10</th>
                <th>Median px</th>
              </tr>
            </thead>
            <tbody>
              {comparisons.map((e) => (
                <tr key={e.id}>
                  <td>
                    {e.id.slice(0, 8)} / {e.config.crop_mode}
                  </td>
                  <td>{format(e.metrics?.A["acc@10"])}</td>
                  <td>{format(e.metrics?.B["acc@10"])}</td>
                  <td>{format(e.metrics?.Overall["acc@10"])}</td>
                  <td>{format(e.metrics?.Overall.median_error)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>
    </div>
  );
}

function LossChart({
  history,
}: {
  history: NonNullable<Experiment["history"]>;
}) {
  const max = Math.max(
    0.001,
    ...history.flatMap((h) => [h.train_loss, h.val_loss]),
  );
  const points = (key: "train_loss" | "val_loss") =>
    history
      .map(
        (h, i) =>
          `${30 + (i / Math.max(1, history.length - 1)) * 650},${170 - (h[key] / max) * 145}`,
      )
      .join(" ");
  return (
    <div className="loss-chart">
      <p>초록 Train · 주황 Validation · X: Epoch / Y: Loss (0–{format(max)})</p>
      <svg
        viewBox="0 0 710 200"
        role="img"
        aria-label="Train Validation Loss 곡선"
      >
        <path d="M30 15V170H690" stroke="#b3c8bc" fill="none" />
        <polyline
          points={points("train_loss")}
          fill="none"
          stroke="#248b69"
          strokeWidth={2}
        />
        <polyline
          points={points("val_loss")}
          fill="none"
          stroke="#d79a43"
          strokeWidth={2}
        />
        {history.map((h, i) => (
          <circle
            key={h.epoch}
            cx={30 + (i / Math.max(1, history.length - 1)) * 650}
            cy={170 - (h.train_loss / max) * 145}
            r={3}
            fill="#248b69"
          />
        ))}
        <text x={30} y={190}>
          1
        </text>
        <text x={665} y={190}>
          {history.length}
        </text>
      </svg>
    </div>
  );
}
