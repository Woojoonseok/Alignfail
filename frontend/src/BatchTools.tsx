import { useEffect, useRef, useState } from "react";
import { api, draftOf, imageUrl, cleanImageUrl, type Pair } from "./api";
import { useAction, useBeforeUnload } from "./hooks";
import "./batch.css";

type Proposal = {
  clusters: number;
  assignments: {
    id: string;
    revision: number;
    folder: string;
    cluster: number;
    image_source: string;
  }[];
  skipped: { id: string; folder: string; reason: string }[];
};
type Result = { name: string; status: string; reason: string };

export default function BatchTools({
  projectId,
  pairs,
  refresh,
  close,
  onBusy,
}: {
  projectId: string;
  pairs: Pair[];
  refresh: () => Promise<void>;
  close: () => void;
  onBusy: (value: boolean) => void;
}) {
  const dialog = useRef<HTMLDialogElement>(null);
  const stop = useRef(false);
  const [selected, setSelected] = useState(new Set<string>());
  const [search, setSearch] = useState("");
  const [groupFilter, setGroupFilter] = useState("*");
  const [classFilter, setClassFilter] = useState("*");
  const [includeExcluded, setIncludeExcluded] = useState(false);
  const [page, setPage] = useState(0);
  const [tab, setTab] = useState("clean");
  const { busy, error, run } = useAction();
  const [message, setMessage] = useState("");
  const [role, setRole] = useState("both");
  const [box, setBox] = useState(true);
  const [cross, setCross] = useState(true);
  const [replace, setReplace] = useState(false);
  const [markRoi, setMarkRoi] = useState(true);
  const [markGt, setMarkGt] = useState(true);
  const [markReplace, setMarkReplace] = useState(false);
  const [results, setResults] = useState<Result[]>([]);
  const [total, setTotal] = useState(0);
  const [field, setField] = useState("group_key");
  const [value, setValue] = useState("");
  const [clusterRole, setClusterRole] = useState("reference");
  const [clusterTarget, setClusterTarget] = useState<
    "group_key" | "class_label"
  >("group_key");
  const [count, setCount] = useState(Math.max(2, Math.min(8, pairs.length)));
  const [proposal, setProposal] = useState<Proposal | null>(null);
  const [names, setNames] = useState<Record<number, string>>({});
  const groups = [
    ...new Set(pairs.map((p) => p.group_key).filter(Boolean)),
  ].sort();
  const classes = [
    ...new Set(pairs.map((p) => p.class_label).filter(Boolean)),
  ].sort();
  const filtered = pairs.filter(
    (p) =>
      (includeExcluded || p.enabled) &&
      (groupFilter === "*" || p.group_key === groupFilter) &&
      (classFilter === "*" || p.class_label === classFilter) &&
      `${p.folder} ${p.group_key} ${p.class_label}`
        .toLowerCase()
        .includes(search.toLowerCase()),
  );
  const chosen = pairs.filter((p) => selected.has(p.id));
  const pages = Math.max(1, Math.ceil(filtered.length / 60));
  const visible = filtered.slice(
    Math.min(page, pages - 1) * 60,
    (Math.min(page, pages - 1) + 1) * 60,
  );
  useEffect(() => {
    dialog.current?.showModal();
  }, []);
  useEffect(() => {
    onBusy(busy);
    return () => onBusy(false);
  }, [busy, onBusy]);
  useBeforeUnload(busy);
  function selection(ids: Set<string>) {
    setSelected(ids);
    setProposal(null);
  }
  async function work(action: () => Promise<void>) {
    setMessage("");
    await run(action);
  }
  async function cleanBatch() {
    const images = chosen.flatMap((p) =>
      [p.reference, p.query]
        .filter((i) => i && (role === "both" || i.role.toLowerCase() === role))
        .map((i) => ({ image: i!, folder: p.folder })),
    );
    const unique = [
      ...new Map(images.map((item) => [item.image.id, item])).values(),
    ];
    stop.current = false;
    setResults([]);
    setTotal(unique.length);
    setProposal(null);
    await work(async () => {
      let processed = 0;
      for (const { image, folder } of unique) {
        if (stop.current) break;
        let result: Result;
        try {
          if (!image.file_hash || image.error)
            throw new Error("이미지 읽기 오류: 폴더 재검색 필요");
          const response = await api<{ status: string; reason: string }>(
            `/images/${image.id}/clean/auto`,
            "POST",
            {
              source_hash: image.file_hash,
              box,
              cross,
              replace_existing: replace,
            },
          );
          result = { name: `${folder} / ${image.role}`, ...response };
        } catch (e) {
          result = {
            name: `${folder} / ${image.role}`,
            status: "failed",
            reason: e instanceof Error ? e.message : String(e),
          };
        }
        processed++;
        setResults((old) => [...old, result]);
      }
      await refresh();
      setMessage(
        `${stop.current ? "중단" : "완료"}: ${processed} / ${unique.length} 이미지 처리. 저장된 결과는 유지됩니다.`,
      );
    });
  }
  async function applyMarkings() {
    setResults([]);
    await work(async () => {
      const response = await api<{
        results: { folder: string; roi: string; gt: string }[];
      }>(`/projects/${projectId}/markings/apply`, "POST", {
        pairs: chosen.map((p) => ({ id: p.id, revision: p.revision })),
        roi: markRoi,
        gt: markGt,
        replace_existing: markReplace,
      });
      const label = (v: string) =>
        v === "saved"
          ? "저장"
          : v === "kept"
            ? "기존 유지"
            : v === "none"
              ? "후보 없음"
              : v === "skipped"
                ? "건너뜀"
                : v;
      setResults(
        response.results.map((r) => ({
          name: r.folder,
          status:
            r.roi === "saved" || r.gt === "saved"
              ? "saved"
              : r.roi.startsWith("error") || r.gt.startsWith("error")
                ? "failed"
                : "skipped",
          reason: `ROI ${label(r.roi)} · GT ${label(r.gt)}`,
        })),
      );
      await refresh();
      const saved = response.results.filter(
        (r) => r.roi === "saved" || r.gt === "saved",
      ).length;
      setMessage(
        `${saved} / ${response.results.length} Pair에 표시에서 읽은 ROI·GT를 저장했습니다. 자동 GT는 Pair Explorer에서 확인해야 학습에 사용됩니다.`,
      );
    });
  }
  async function confirmAutoGt() {
    const targets = chosen.filter((p) => p.gt_source === "auto_cross");
    await work(async () => {
      let done = 0;
      for (const p of targets) {
        await api(`/pairs/${p.id}`, "PUT", { ...draftOf(p), confirm_gt: true });
        done++;
      }
      await refresh();
      setMessage(`${done}개 Pair의 자동 GT를 확인 완료로 표시했습니다.`);
    });
  }
  async function applyGroups() {
    await work(async () => {
      const result = await api<{ updated: number }>(
        `/projects/${projectId}/groups/bulk`,
        "POST",
        {
          assignments: chosen.map((p) => ({
            id: p.id,
            revision: p.revision,
            [field]: value,
          })),
        },
      );
      setProposal(null);
      await refresh();
      setMessage(
        `${result.updated}개 Pair의 ${field === "group_key" ? "그룹" : "클래스"}를 저장했습니다.`,
      );
    });
  }
  async function cluster() {
    setProposal(null);
    await work(async () => {
      const result = await api<Proposal>(
        `/projects/${projectId}/clusters/preview`,
        "POST",
        {
          pairs: chosen.map((p) => ({ id: p.id, revision: p.revision })),
          clusters: count,
          role: clusterRole,
        },
      );
      const prefix = `${clusterTarget === "class_label" ? "class" : "cluster"}-${new Date().toISOString().replace(/\D/g, "").slice(0, 17)}`;
      setNames(
        Object.fromEntries(
          result.assignments.map((p) => [
            p.cluster,
            `${prefix}-${String(p.cluster).padStart(2, "0")}`,
          ]),
        ),
      );
      setProposal(result);
      setMessage(
        `${result.clusters}개 그룹 후보. 검토 후 적용하세요. 동일한 특징은 같은 그룹으로 유지합니다.`,
      );
    });
  }
  async function applyClusters() {
    if (!proposal) return;
    await work(async () => {
      const result = await api<{ updated: number }>(
        `/projects/${projectId}/groups/bulk`,
        "POST",
        {
          assignments: proposal.assignments.map((p) => ({
            id: p.id,
            revision: p.revision,
            [clusterTarget]: names[p.cluster],
          })),
        },
      );
      setProposal(null);
      await refresh();
      setMessage(
        `${result.updated}개 Pair에 클러스터 결과를 ${clusterTarget === "class_label" ? "클래스" : "그룹"}(으)로 적용했습니다.`,
      );
    });
  }
  return (
    <dialog
      ref={dialog}
      className="modal batch-modal"
      onCancel={(e) => {
        e.preventDefault();
        if (!busy) close();
      }}
    >
      <div className="modal-title">
        <div>
          <h2>일괄 제거 · 그룹화</h2>
          <p>원본과 GT 보존 · 선택한 Pair에만 적용</p>
        </div>
        <button
          className="icon-button"
          aria-label="일괄 작업 닫기"
          disabled={busy}
          onClick={close}
        >
          ✕
        </button>
      </div>
      <div className="batch-body">
        <fieldset disabled={busy} className="batch-fieldset">
          <div className="batch-filters">
            <input
              aria-label="일괄 Pair 검색"
              placeholder="폴더 · 클래스 · 그룹 검색"
              value={search}
              onChange={(e) => {
                setSearch(e.target.value);
                setPage(0);
              }}
            />
            <select
              aria-label="그룹 필터"
              value={groupFilter}
              onChange={(e) => {
                setGroupFilter(e.target.value);
                setPage(0);
              }}
            >
              <option value="*">모든 그룹</option>
              <option value="">그룹 미지정</option>
              {groups.map((g) => (
                <option key={g}>{g}</option>
              ))}
            </select>
            <select
              aria-label="클래스 필터"
              value={classFilter}
              onChange={(e) => {
                setClassFilter(e.target.value);
                setPage(0);
              }}
            >
              <option value="*">모든 클래스</option>
              <option value="">클래스 미지정</option>
              {classes.map((c) => (
                <option key={c}>{c}</option>
              ))}
            </select>
            <label className="batch-check">
              <input
                type="checkbox"
                checked={includeExcluded}
                onChange={(e) => {
                  setIncludeExcluded(e.target.checked);
                  selection(new Set());
                }}
              />
              제외 Pair 포함
            </label>
          </div>
          <div className="batch-selection">
            <button
              className="button secondary small"
              onClick={() => selection(new Set(filtered.map((p) => p.id)))}
            >
              검색 결과 전체 선택 ({filtered.length})
            </button>
            <button
              className="button secondary small"
              onClick={() => selection(new Set())}
            >
              선택 해제
            </button>
            <strong>{chosen.length}개 선택</strong>
            <span>
              필터 밖 선택{" "}
              {
                chosen.filter((p) => !filtered.some((f) => f.id === p.id))
                  .length
              }
              개 포함
            </span>
          </div>
          <nav className="batch-tabs">
            {[
              ["clean", "흰 표시 일괄 제거"],
              ["markings", "표시에서 ROI · GT"],
              ["groups", "클래스 · 그룹 지정"],
              ["clusters", "자동 클러스터링"],
            ].map(([id, label]) => (
              <button
                key={id}
                className={tab === id ? "active" : ""}
                onClick={() => setTab(id)}
              >
                {label}
              </button>
            ))}
          </nav>
          {tab === "clean" && (
            <section className="batch-settings">
              <p>
                자동으로 찾은 표시를 제거해 별도 Clean 이미지로 저장합니다.
                후보가 없으면 건너뜁니다. 실행 중 이 창을 열어 두세요.
              </p>
              <div className="batch-controls">
                <select
                  aria-label="일괄 제거 이미지 대상"
                  value={role}
                  onChange={(e) => setRole(e.target.value)}
                >
                  <option value="both">REF + Query</option>
                  <option value="ref">REF만</option>
                  <option value="query">Query만</option>
                </select>
                <label className="batch-check">
                  <input
                    type="checkbox"
                    checked={box}
                    onChange={(e) => setBox(e.target.checked)}
                  />
                  흰 네모
                </label>
                <label className="batch-check">
                  <input
                    type="checkbox"
                    checked={cross}
                    onChange={(e) => setCross(e.target.checked)}
                  />
                  십자선
                </label>
                <label className="batch-check">
                  <input
                    type="checkbox"
                    checked={replace}
                    onChange={(e) => setReplace(e.target.checked)}
                  />
                  기존 Clean도 다시 생성
                </label>
                <button
                  className="button primary"
                  disabled={!chosen.length || (!box && !cross)}
                  onClick={cleanBatch}
                >
                  선택 Pair 일괄 제거
                </button>
              </div>
            </section>
          )}
          {tab === "markings" && (
            <section className="batch-settings">
              <p>
                REF의 흰 네모 중심을 ROI로, Query의 흰 십자선 교차점을 GT로 읽어
                저장합니다. 십자선에서 온 GT는 "자동 · 확인 필요"로 표시되며,
                확인 전에는 학습에 사용되지 않습니다. 검출 실패는 결과 상세에
                표시됩니다.
              </p>
              <div className="batch-controls">
                <label className="batch-check">
                  <input
                    type="checkbox"
                    checked={markRoi}
                    onChange={(e) => setMarkRoi(e.target.checked)}
                  />{" "}
                  REF 네모 → ROI
                </label>
                <label className="batch-check">
                  <input
                    type="checkbox"
                    checked={markGt}
                    onChange={(e) => setMarkGt(e.target.checked)}
                  />{" "}
                  Query 십자선 → 자동 GT
                </label>
                <label className="batch-check">
                  <input
                    type="checkbox"
                    checked={markReplace}
                    onChange={(e) => setMarkReplace(e.target.checked)}
                  />{" "}
                  기존 ROI·GT도 덮어쓰기
                </label>
                <button
                  className="button primary"
                  disabled={!chosen.length || (!markRoi && !markGt)}
                  onClick={applyMarkings}
                >
                  선택 {chosen.length}개에서 읽기
                </button>
                <button
                  className="button secondary"
                  disabled={!chosen.some((p) => p.gt_source === "auto_cross")}
                  onClick={confirmAutoGt}
                >
                  선택 중 자동 GT{" "}
                  {chosen.filter((p) => p.gt_source === "auto_cross").length}개
                  확인 완료
                </button>
              </div>
            </section>
          )}
          {tab === "groups" && (
            <section className="batch-settings">
              <p>
                클래스는 의미를 나타내는 이름, 그룹은 비슷한 이미지나 같은 촬영
                묶음의 이름입니다. 기존 이름을 고르거나 새 이름을 입력하세요. 빈
                이름을 적용하면 해제됩니다.
              </p>
              <div className="batch-controls">
                <select
                  aria-label="지정 항목"
                  value={field}
                  onChange={(e) => {
                    setField(e.target.value);
                    setValue("");
                  }}
                >
                  <option value="group_key">그룹</option>
                  <option value="class_label">클래스</option>
                </select>
                <input
                  aria-label="클래스 또는 그룹 이름"
                  list="batch-existing-names"
                  maxLength={200}
                  value={value}
                  onChange={(e) => setValue(e.target.value)}
                  placeholder="이름 입력 또는 기존 이름 선택"
                />
                <datalist id="batch-existing-names">
                  {(field === "group_key" ? groups : classes).map((n) => (
                    <option key={n} value={n} />
                  ))}
                </datalist>
                <button
                  className="button primary"
                  disabled={!chosen.length}
                  onClick={applyGroups}
                >
                  {value.trim()
                    ? "선택 Pair에 이름 적용"
                    : "선택 Pair 이름 해제"}
                </button>
              </div>
            </section>
          )}
          {tab === "clusters" && (
            <section className="batch-settings">
              <p>
                밝기·윤곽 특징으로 비슷한 후보를 묶습니다. 의미 분류나 학습용
                데이터 분할을 확정하지 않습니다. 유효한 Clean을 우선 사용합니다.
                한 번에 최대 2,000 Pair.
              </p>
              <div className="batch-controls">
                <select
                  aria-label="클러스터 기준 이미지"
                  value={clusterRole}
                  onChange={(e) => {
                    setClusterRole(e.target.value);
                    setProposal(null);
                  }}
                >
                  <option value="reference">REF 기준</option>
                  <option value="query">Query 기준</option>
                </select>
                <select
                  aria-label="클러스터 결과 적용 대상"
                  value={clusterTarget}
                  onChange={(e) => {
                    setClusterTarget(e.target.value as typeof clusterTarget);
                    setProposal(null);
                  }}
                >
                  <option value="group_key">
                    데이터 그룹(group_key)으로 적용
                  </option>
                  <option value="class_label">
                    클래스(class_label)로 적용
                  </option>
                </select>
                <label>
                  묶음 수
                  <input
                    aria-label="클러스터 수"
                    type="number"
                    min={2}
                    max={Math.min(50, chosen.length)}
                    value={count}
                    onChange={(e) => {
                      setCount(Number(e.target.value));
                      setProposal(null);
                    }}
                  />
                </label>
                <button
                  className="button primary"
                  disabled={
                    chosen.length < 2 ||
                    chosen.length > 2000 ||
                    count < 2 ||
                    count > Math.min(50, chosen.length)
                  }
                  onClick={cluster}
                >
                  클러스터 후보 만들기
                </button>
              </div>
              {proposal && (
                <div className="cluster-proposals">
                  {Object.keys(names)
                    .map(Number)
                    .map((id) => (
                      <section key={id}>
                        <label>
                          그룹 {id} ·{" "}
                          {
                            proposal.assignments.filter((p) => p.cluster === id)
                              .length
                          }{" "}
                          Pair
                          <input
                            aria-label={`클러스터 ${id} 이름`}
                            maxLength={200}
                            value={names[id]}
                            onChange={(e) =>
                              setNames({ ...names, [id]: e.target.value })
                            }
                          />
                        </label>
                        <div className="cluster-thumbs">
                          {proposal.assignments
                            .filter((p) => p.cluster === id)
                            .map((item) => {
                              const p = pairs.find((p) => p.id === item.id)!;
                              const im =
                                clusterRole === "reference"
                                  ? p.reference
                                  : p.query;
                              return (
                                <figure key={item.id}>
                                  {im && (
                                    <img
                                      loading="lazy"
                                      src={
                                        item.image_source === "clean"
                                          ? cleanImageUrl(im)
                                          : imageUrl(im, true)
                                      }
                                      alt={p.folder}
                                    />
                                  )}
                                  <figcaption>{p.folder}</figcaption>
                                  <select
                                    aria-label={`${p.folder} 후보 그룹`}
                                    value={item.cluster}
                                    onChange={(e) =>
                                      setProposal({
                                        ...proposal,
                                        assignments: proposal.assignments.map(
                                          (a) =>
                                            a.id === item.id
                                              ? {
                                                  ...a,
                                                  cluster: Number(
                                                    e.target.value,
                                                  ),
                                                }
                                              : a,
                                        ),
                                      })
                                    }
                                  >
                                    {Object.keys(names).map((key) => (
                                      <option key={key} value={key}>
                                        그룹 {key}
                                      </option>
                                    ))}
                                  </select>
                                </figure>
                              );
                            })}
                        </div>
                      </section>
                    ))}
                  {proposal.skipped.map((p) => (
                    <p key={p.id}>
                      {p.folder}: {p.reason}
                    </p>
                  ))}
                  <button
                    className="button primary"
                    disabled={Object.values(names).some((n) => !n.trim())}
                    onClick={applyClusters}
                  >
                    {clusterTarget === "class_label"
                      ? "검토한 클러스터를 클래스로 적용"
                      : "검토한 클러스터를 그룹으로 적용"}
                  </button>
                </div>
              )}
            </section>
          )}
        </fieldset>
        {busy && (
          <div className="batch-progress" role="status">
            {tab === "clean" ? (
              <>
                <progress value={results.length} max={total || 1} />{" "}
                {results.length} / {total}
                <button
                  className="button secondary small"
                  onClick={() => {
                    stop.current = true;
                    setMessage("현재 이미지 처리 후 중단합니다.");
                  }}
                >
                  일괄 제거 중단
                </button>
              </>
            ) : (
              "처리 중…"
            )}
          </div>
        )}
        {message && (
          <p className="batch-message" role="status">
            {message}
          </p>
        )}
        {error && (
          <p className="error-box" role="alert">
            {error}
          </p>
        )}
        {!!results.length && (
          <details
            className="batch-results"
            open={results.some((r) => r.status === "failed")}
          >
            <summary>
              저장 {results.filter((r) => r.status === "saved").length} · 건너뜀{" "}
              {results.filter((r) => r.status === "skipped").length} · 실패{" "}
              {results.filter((r) => r.status === "failed").length} — 결과 상세
            </summary>
            {results.map((r, i) => (
              <p key={i}>
                {r.name} — {r.reason}
              </p>
            ))}
          </details>
        )}
        <div className="batch-gallery">
          {visible.map((p) => (
            <label
              key={p.id}
              className={`batch-card ${selected.has(p.id) ? "selected" : ""}`}
            >
              <span>
                <input
                  disabled={busy}
                  type="checkbox"
                  aria-label={`${p.folder} 선택`}
                  checked={selected.has(p.id)}
                  onChange={(e) => {
                    const next = new Set(selected);
                    e.target.checked ? next.add(p.id) : next.delete(p.id);
                    selection(next);
                  }}
                />
                {p.folder}
              </span>
              <div>
                {[p.reference, p.query].map((im, i) =>
                  im ? (
                    <img
                      loading="lazy"
                      key={im.id}
                      src={imageUrl(im, true)}
                      alt={`${p.folder} ${i === 0 ? "REF" : "Query"}`}
                    />
                  ) : (
                    <span key={i}>이미지 없음</span>
                  ),
                )}
              </div>
              <small>
                클래스: {p.class_label || "미지정"} · 그룹:{" "}
                {p.group_key || "미지정"}
              </small>
            </label>
          ))}
        </div>
        <div className="batch-pagination">
          <button
            className="button secondary small"
            disabled={busy || page === 0}
            onClick={() => setPage(Math.max(0, page - 1))}
          >
            이전
          </button>
          <span>
            {Math.min(page, pages - 1) + 1} / {pages} 페이지 · {filtered.length}{" "}
            Pair
          </span>
          <button
            className="button secondary small"
            disabled={busy || page >= pages - 1}
            onClick={() => setPage(page + 1)}
          >
            다음
          </button>
        </div>
      </div>
    </dialog>
  );
}
