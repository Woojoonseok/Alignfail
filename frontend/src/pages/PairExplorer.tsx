import { useEffect, useState } from "react";
import { useSearchParams } from "react-router-dom";
import { CheckCircle2, Circle, Search, SlidersHorizontal } from "lucide-react";
import { type Pair } from "../api";
import type { PageProps } from "../types";
import { useBeforeUnload } from "../hooks";
import { Empty, Thumb } from "../components/ui";
import { PairEditor } from "../pages/PairEditor";
import BatchTools from "../BatchTools";

export function PairExplorer({
  project,
  pairs,
  refresh,
  notify,
  reportDirty,
}: PageProps & { reportDirty: (dirty: boolean) => void }) {
  const [params, setParams] = useSearchParams();
  const [fallbackId] = useState(pairs[0]?.id);
  const [search, setSearch] = useState("");
  const [filter, setFilter] = useState("all");
  const [dirty, setDirty] = useState(false);
  const [batchOpen, setBatchOpen] = useState(false);
  const [batchBusy, setBatchBusy] = useState(false);
  const filtered = pairs.filter(
    (p) =>
      `${p.folder} ${p.group_key} ${p.class_label} ${p.tier}`
        .toLowerCase()
        .includes(search.toLowerCase()) &&
      (filter === "all" ||
        (filter === "missing" && p.enabled && p.gt_x === null) ||
        (filter === "done" && p.enabled && p.gt_x !== null) ||
        (filter === "issues" && !!p.import_issues.length) ||
        (filter === "excluded" && !p.enabled)),
  );
  const selected =
    pairs.find((p) => p.id === params.get("pair")) ??
    pairs.find((p) => p.id === fallbackId) ??
    filtered[0];
  function select(pair: Pair) {
    setParams({ pair: pair.id });
  }
  useEffect(() => {
    reportDirty(dirty || batchBusy);
  }, [dirty, batchBusy, reportDirty]);
  useEffect(() => () => reportDirty(false), [reportDirty]);
  const index = selected ? filtered.findIndex((p) => p.id === selected.id) : -1;
  useBeforeUnload(dirty);
  if (!pairs.length)
    return (
      <section className="panel">
        <Empty title="먼저 데이터 폴더를 연결하세요.">
          <p>오른쪽 위 ‘데이터 가져오기’에서 Dada 경로를 지정하세요.</p>
        </Empty>
      </section>
    );
  return (
    <div className="explorer-layout">
      {batchOpen && (
        <BatchTools
          projectId={project.id}
          pairs={pairs}
          refresh={refresh}
          close={() => setBatchOpen(false)}
          onBusy={setBatchBusy}
        />
      )}
      <aside className="pair-list panel">
        <div className="pair-list-header">
          <strong>
            Pairs <span>{filtered.length}</span>
          </strong>
          <SlidersHorizontal size={16} />
        </div>
        <button
          className="button secondary batch-open"
          disabled={dirty}
          onClick={() => setBatchOpen(true)}
        >
          일괄 제거 · 그룹화
        </button>
        <div className="search-input">
          <Search size={15} />
          <input
            aria-label="Pair 검색"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            placeholder="Pair · 그룹 검색"
          />
        </div>
        <select
          className="filter-select"
          aria-label="Pair 상태 필터"
          value={filter}
          onChange={(e) => setFilter(e.target.value)}
        >
          <option value="all">전체 상태</option>
          <option value="missing">GT 미지정</option>
          <option value="done">GT 완료</option>
          <option value="issues">파일 확인 필요</option>
          <option value="excluded">제외됨</option>
        </select>
        <div className="pair-list-scroll">
          {filtered.map((p) => (
            <button
              key={p.id}
              className={`pair-list-item ${selected?.id === p.id ? "selected" : ""}`}
              onClick={() => select(p)}
            >
              <div className="pair-item-top">
                <strong>{p.folder}</strong>
                {p.gt_x !== null && p.enabled ? (
                  <CheckCircle2 size={14} />
                ) : (
                  <Circle size={13} />
                )}
              </div>
              <div className="pair-item-bottom">
                <div className="table-thumbs">
                  <Thumb image={p.reference} />
                  <Thumb image={p.query} />
                </div>
                <span>
                  {p.import_issues.length
                    ? "파일 확인"
                    : !p.enabled
                      ? "제외됨"
                      : p.group_key || "그룹 미지정"}
                </span>
              </div>
            </button>
          ))}
          {!filtered.length && (
            <p className="list-empty">검색 결과가 없습니다.</p>
          )}
        </div>
        <div className="list-footer">
          <span className="mini-dot" /> GT 완료{" "}
          {pairs.filter((p) => p.gt_x !== null && p.enabled).length} /{" "}
          {pairs.filter((p) => p.enabled).length}
        </div>
      </aside>
      <div className="pair-workspace">
        {selected && (
          <PairEditor
            key={`${selected.id}:${selected.revision}`}
            pair={selected}
            refresh={refresh}
            notify={notify}
            onDirty={setDirty}
            position={
              index >= 0 ? `${index + 1} / ${filtered.length}` : "필터 외 Pair"
            }
            previous={index > 0 ? () => select(filtered[index - 1]) : undefined}
            next={
              index >= 0 && index < filtered.length - 1
                ? () => select(filtered[index + 1])
                : undefined
            }
          />
        )}
      </div>
    </div>
  );
}
