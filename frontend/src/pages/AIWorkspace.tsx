import { useEffect, useState, type CSSProperties } from "react";
import { Link } from "react-router-dom";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { BrainCircuit, CheckCircle2, Crosshair, FolderInput, Loader2, Play, RefreshCcw } from "lucide-react";
import { api, imageUrl, type ImageRecord, type Pair, type Project } from "../api";
import { pixelFromEvent } from "../coords";
import { ErrorBox } from "../components/ui";
import "../ai-workspace.css";

type ClassCandidate = { label: string; score: number; nearest_template: string };
type Localization = {
  status: string;
  x: number | null;
  y: number | null;
  score: number | null;
  class_label: string;
  template_pair_id: string;
};
type Proposal = {
  pair_id: string;
  revision: number;
  kind: "test" | "incoming";
  error?: string;
  classes: ClassCandidate[];
  localization: Localization | null;
  gt_status?: string;
  embedding_scope?: string;
};
type Job = {
  job_id?: string;
  status: string;
  error?: string;
  count?: number;
  results?: { model: string; matches: Proposal[]; warning: string } | null;
};
type Overview = {
  train: number;
  test_pairs: number;
  templates_ready: number;
  incoming: number;
  pairs: Pair[];
  active_job: { job_id?: string };
};

function Annotate({
  pair,
  image,
  prediction,
  refresh,
  notify,
}: {
  pair: Pair;
  image: ImageRecord | null;
  prediction?: Localization | null;
  refresh: () => Promise<void>;
  notify: (s: string) => void;
}) {
  const [draft, setDraft] = useState<{ x: number; y: number } | null>(null);
  const [newClass, setNewClass] = useState(pair.class_label);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");
  useEffect(() => {
    setDraft(null);
    setNewClass(pair.class_label);
  }, [pair.id, pair.class_label, pair.gt_x, pair.gt_y]);
  const point = draft ?? (pair.gt_x !== null && pair.gt_y !== null
    ? { x: pair.gt_x, y: pair.gt_y } : null);
  const percent = (x: number, total: number) => (100 * x / total).toFixed(3) + "%";
  const marker = (x: number, y: number, color: string): CSSProperties => ({
    position: "absolute",
    left: percent(x, image?.width || 1),
    top: percent(y, image?.height || 1),
    transform: "translate(-50%, -50%)",
    width: 13, height: 13, borderRadius: "50%",
    border: "2px solid " + color, background: "#101418",
    pointerEvents: "none", boxShadow: "0 0 0 1px #fff",
  });
  const save = async (confirm = false) => {
    if (!point && !newClass.trim()) return;
    setSaving(true);
    setError("");
    try {
      await api(`/pairs/${pair.id}`, "PUT", {
        revision: pair.revision, gt_x: point?.x ?? null, gt_y: point?.y ?? null,
        group_key: pair.group_key, class_label: newClass.trim(),
        pattern_type: pair.pattern_type, modality: pair.modality, tier: pair.tier,
        notes: pair.notes, enabled: pair.enabled, exclude_reason: pair.exclude_reason,
        confirm_gt: confirm
      });
      await refresh();
      notify("GT 및 클래스 정보를 저장했습니다.");
    } catch (e) { setError(e instanceof Error ? e.message : String(e)); }
    finally { setSaving(false); }
  };
  return <div className="ai-annotation">
    <div className="ai-image">
      {image ? <div className="ai-image-inner">
        <img src={imageUrl(image)} alt={image.file_name} draggable={false} />
        {image.width && image.height && <div
          className="ai-coordinate-layer" aria-label="이미지를 클릭하여 GT 지정"
          onClick={(e) => setDraft(pixelFromEvent(e, image.width!, image.height!))}
        >
          {prediction?.x !== null && prediction?.x !== undefined &&
            prediction.y !== null && prediction.y !== undefined &&
            <span style={marker(prediction.x, prediction.y, "#54c5f8")} title="Localization candidate" />}
          {point && <span style={marker(point.x, point.y, "#ffd166")} title="Confirmed/edited GT" />}
        </div>}
      </div> : <p>이미지 없음</p>}
    </div>
    <div className="ai-gt-fields">
      <span>GT: {point ? `(${point.x}, ${point.y})` : "미지정"}</span>
      <span>출처: {draft ? "수동 수정 중" : pair.gt_source}</span>
      <span>파랑: 예측 / 노랑: GT</span>
    </div>
    <div className="ai-edit-row">
      <input aria-label="클래스 이름" value={newClass}
        placeholder="클래스 이름(신규 가능)" onChange={(e) => setNewClass(e.target.value)} />
      <button className="button secondary" disabled={saving || !point} onClick={() => save(false)}>GT 저장</button>
      {pair.gt_source === "auto_cross" && !draft &&
        <button className="button primary" disabled={saving} onClick={() => save(true)}>자동 GT 확인</button>}
    </div>
    <ErrorBox error={error} />
  </div>;
}

export function AIWorkspace({
  project, pairs, refresh, notify,
}: {
  project: Project;
  pairs: Pair[];
  refresh: () => Promise<void>;
  notify: (message: string) => void;
}) {
  const client = useQueryClient();
  const [paths, setPaths] = useState({ train: "", test: "", incoming: "" });
  const [busy, setBusy] = useState("");
  const [error, setError] = useState("");
  const [jobId, setJobId] = useState("");
  const [selected, setSelected] = useState("");
  const [topK, setTopK] = useState(5);
  const overview = useQuery({
    queryKey: ["ai-overview", project.id],
    queryFn: () => api<Overview>(`/projects/${project.id}/ai/overview`),
  });
  const latest = jobId || overview.data?.active_job?.job_id || "";
  const job = useQuery({
    queryKey: ["ai-job", project.id, latest],
    queryFn: () => api<Job>(`/projects/${project.id}/ai/jobs/${latest}`),
    enabled: !!latest,
    refetchInterval: (query) => query.state.data?.status === "running" ? 3000 : false,
  });
  const candidates = job.data?.results?.matches ?? [];
  const specialPairs = overview.data?.pairs ?? [];
  const selectedPair = specialPairs.find((p) => p.id === selected) ?? specialPairs[0];
  const currentProposal = candidates.find((m) => m.pair_id === selectedPair?.id);
  const chosenImage = selectedPair?.dataset_split === "test"
    ? selectedPair.query : selectedPair?.reference;
  const perform = async (key: string, action: () => Promise<unknown>) => {
    setBusy(key); setError("");
    try {
      await action();
      await refresh();
      await client.invalidateQueries({ queryKey: ["ai-overview", project.id] });
    } catch (e) { setError(e instanceof Error ? e.message : String(e)); }
    finally { setBusy(""); }
  };
  const importFolder = (type: "train" | "test" | "incoming") => perform(type, async () => {
    const inputPath = paths[type].trim();
    if (!inputPath) throw new Error("서버 폴더 경로를 입력하세요.");
    const endpoint = type === "train"
      ? `/projects/${project.id}/import` : `/projects/${project.id}/ai/import/${type}`;
    const result = await api<Record<string, unknown>>(endpoint, "POST",
      type === "train" ? { root_directory: inputPath, dataset_split: "train" }
        : { root_directory: inputPath });
    notify(`${type} 폴더 등록 완료: ${JSON.stringify(result)}`);
  });
  const autoMarks = (kind: "train" | "test") => perform("markings", async () => {
    const list = pairs.filter((p) => kind === "train"
      ? p.dataset_split === "train" && p.sample_role === "reference" &&
        (p.gt_x === null || p.gt_source === "none")
      : p.dataset_split === "test" && p.sample_role === "pair" &&
        p.reference_annotation === null);
    if (!list.length) throw new Error("자동 검출할 대상이 없습니다.");
    const result = await api<{ results: { roi: string; gt: string }[] }>(
      `/projects/${project.id}/markings/apply`, "POST", {
        pairs: list.map((p) => ({ id: p.id, revision: p.revision })),
        gt: kind === "train", roi: kind === "test", replace_existing: false,
      });
    notify(`표시 검출 완료: ${result.results.length}개 확인 (자동 GT는 수동 승인 필요)`);
  });
  const runAI = () => perform("run", async () => {
    const result = await api<{ job_id: string }>(`/projects/${project.id}/ai/run`, "POST", {
      model: "Qwen/Qwen3-VL-Embedding-2B", batch_size: 1, top_k: topK, patch_size: 160,
    });
    setJobId(result.job_id);
    notify("VLM 검색 및 Localization 후보 생성 작업을 시작했습니다.");
  });
  const approve = (p: Pair, label: string) => perform("approve", async () => {
    await api(`/projects/${project.id}/ai/approve`, "POST", {
      job_id: latest, pair_id: p.id, revision: p.revision, class_label: label,
    });
    notify(`승인 완료: ${label} (Test Set은 Train에 편입되지 않음)`);
  });
  return <div className="ai-workspace">
    <section className="panel ai-setup">
      <div className="ai-heading"><FolderInput size={19} /><h2>1. 데이터 등록</h2></div>
      <p>WSL / 서버에서 접근 가능한 폴더 경로를 입력하세요. 실제 이미지 파일은 이동하지 않습니다.</p>
      {([
        ["train", "기존 Template (Class별 폴더)", "/mnt/d/Alignfail/Template"],
        ["test", "REF–FAIL Test (케이스별 폴더)", "/mnt/d/Alignfail/TestPairs"],
        ["incoming", "공정 완료 신규 이미지", "/mnt/d/Alignfail/Incoming"],
      ] as const).map(([key, label, placeholder]) =>
        <div className="ai-form-row" key={key}>
          <label htmlFor={`ai-${key}`}>{label}</label>
          <input id={`ai-${key}`} value={paths[key]} placeholder={placeholder}
            onChange={(e) => setPaths((v) => ({ ...v, [key]: e.target.value }))} />
          <button className="button secondary" disabled={!!busy} onClick={() => importFolder(key)}>
            {busy === key ? <Loader2 className="spin" size={15} /> : <FolderInput size={15} />} 등록
          </button>
        </div>
      )}
      <div className="ai-stats">
        <span>Train: {overview.data?.train ?? 0}</span>
        <span>Test Pair: {overview.data?.test_pairs ?? 0}</span>
        <span>GT 검수: {overview.data?.templates_ready ?? 0}</span>
        <span>Incoming: {overview.data?.incoming ?? 0}</span>
      </div>
      <ErrorBox error={error || overview.error || job.error} />
    </section>
    <section className="panel ai-setup">
      <div className="ai-heading"><Crosshair size={19} /><h2>2. GT 및 Reference ROI 검수</h2></div>
      <p>Train: 십자선 자동 검출 → 수동 승인 → 흰 표시 제거(Clean). 십자선이 없으면 이미지를 클릭하여 GT를 지정하세요. Test: REF의 흰 네모 ROI를 검출합니다. Fail 기존 십자선은 정답으로 사용하지 않습니다.</p>
      <div className="ai-actions">
        <button className="button secondary" disabled={!!busy} onClick={() => autoMarks("train")}>Train 십자선 GT 후보 생성</button>
        <button className="button secondary" disabled={!!busy} onClick={() => autoMarks("test")}>Test REF ROI 자동 검출</button>
        <Link className="button secondary" to="/pairs?split=train">Clean 이미지 생성 및 전체 검수</Link>
      </div>
      <p className="ai-warning">VLM 템플릿 인덱스에는 확인된 GT와 Clean 이미지가 있는 Train 데이터만 사용합니다. Test 쌍은 학습에서 제외합니다.</p>
    </section>
    <section className="panel ai-setup">
      <div className="ai-heading"><BrainCircuit size={19} /><h2>3. VLM 검색 및 Localization</h2></div>
      <div className="ai-actions">
        <label>Top-K <input type="number" min={1} max={20} value={topK}
          onChange={(e) => setTopK(Math.min(20, Math.max(1, +e.target.value || 1)))} /></label>
        <button className="button primary" disabled={!!busy || job.data?.status === "running"} onClick={runAI}>
          {job.data?.status === "running" ? <Loader2 className="spin" size={16} /> : <Play size={16} />} VLM 매칭 실행
        </button>
        {latest && <button className="button secondary" onClick={() => job.refetch()}><RefreshCcw size={15} /> 결과 새로고침</button>}
      </div>
      {latest && <p>Job: <code>{latest}</code> · {job.data?.status ?? "조회 중"}
        {job.data?.error && <span className="ai-warning"> · {job.data.error}</span>}
      </p>}
      <p className="ai-warning">VLM Embedding으로 클래스를 추천하고, GT 중심 패치 NCC로 위치 후보를 생성합니다. NCC 좌표는 최종 Localization 정답이 아니며 반드시 검증해야 합니다.</p>
    </section>
    <section className="panel ai-setup">
      <div className="ai-heading"><CheckCircle2 size={19} /><h2>4. 이미지별 승인 및 수동 GT 지정</h2></div>
      <div className="ai-result-grid">
        <div className="ai-items">
          {specialPairs.length === 0 && <p>등록된 Test Pair / Incoming 이미지가 없습니다.</p>}
          {specialPairs.map((p) => <button
            key={p.id} className={`ai-item ${selectedPair?.id === p.id ? "chosen" : ""}`}
            onClick={() => setSelected(p.id)}>
            <strong>{p.folder.split(":").at(-1)}</strong>
            <span>{p.dataset_split} · {p.class_label || "미분류"} · GT {p.gt_source}</span>
          </button>)}
        </div>
        <div className="ai-details">
          {selectedPair && <>
            <div className="ai-two-images">
              {selectedPair.dataset_split === "test" && selectedPair.reference &&
                <div><strong>Test Reference</strong><img src={imageUrl(selectedPair.reference)}
                  alt="Reference" /><span>ROI: {selectedPair.reference_annotation?.box.join(", ") ?? "미지정"}</span></div>}
              <div>
                <strong>{selectedPair.dataset_split === "test" ? "Fail Query" : "신규 이미지"}</strong>
                <Annotate key={selectedPair.id} pair={selectedPair} image={chosenImage}
                  prediction={currentProposal?.localization} refresh={refresh} notify={notify}/>
              </div>
            </div>
            {currentProposal?.error && <p className="ai-warning">{currentProposal.error}</p>}
            {(currentProposal?.classes?.length ?? 0) > 0 && <>
              <h3>VLM 추천 클래스</h3>
              {currentProposal!.classes.map((c) => <div className="ai-candidate" key={c.label}>
                <span>{c.label} · cosine {c.score.toFixed(3)}</span>
                <button className="button secondary" disabled={!!busy}
                  onClick={() => approve(selectedPair, c.label)}>클래스 승인</button>
              </div>)}
              <p>Localization 후보: {currentProposal?.localization?.x != null
                ? `(${currentProposal.localization.x.toFixed(1)}, ${currentProposal.localization.y?.toFixed(1)})`
                : "없음"}</p>
            </>}
            <Link className="button secondary" to={`/pairs?pair=${selectedPair.id}`}>Pair Explorer에서 상세 검수</Link>
          </>}
        </div>
      </div>
    </section>
  </div>;
}
