import { useEffect, useState } from "react";
import { useMutation, useQuery } from "@tanstack/react-query";
import {
  ChevronLeft,
  ChevronRight,
  Crosshair,
  History as HistoryIcon,
  Loader2,
  Save,
  SlidersHorizontal,
  Trash2,
  TriangleAlert,
  Undo2,
} from "lucide-react";
import {
  api,
  dateLabel,
  draftOf,
  type History,
  type ImageRecord,
  type Pair,
  type PairDraft,
} from "../api";
import type { Notify } from "../types";
import { ErrorBox, Status } from "../components/ui";
import { ImageViewer } from "../components/ImageViewer";
import ImageCleaner from "../ImageCleaner";
import ReferenceROI from "../ReferenceROI";

export function PairEditor({
  pair,
  refresh,
  notify,
  onDirty,
  position,
  previous,
  next,
}: {
  pair: Pair;
  refresh: () => Promise<void>;
  notify: Notify;
  onDirty: (dirty: boolean) => void;
  position: string;
  previous?: () => void;
  next?: () => void;
}) {
  const [draft, setDraft] = useState<PairDraft>(draftOf(pair));
  const [refZoom, setRefZoom] = useState(1);
  const [queryZoom, setQueryZoom] = useState(1);
  const [showGT, setShowGT] = useState(true);
  const [tab, setTab] = useState("metadata");
  const [cleaningImage, setCleaningImage] = useState<ImageRecord | null>(null);
  const [roiOpen, setRoiOpen] = useState(false);
  const dirty = JSON.stringify(draft) !== JSON.stringify(draftOf(pair));
  useEffect(() => onDirty(dirty), [dirty, onDirty]);
  // Ctrl+S / Cmd+S saves the current draft without reaching for the button.
  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "s") {
        e.preventDefault();
        if (dirty && !save.isPending) save.mutate();
      }
    };
    window.addEventListener("keydown", handler);
    return () => window.removeEventListener("keydown", handler);
  });
  const history = useQuery({
    queryKey: ["history", pair.id],
    queryFn: () => api<History[]>(`/pairs/${pair.id}/history`),
    enabled: tab === "history",
  });
  const save = useMutation({
    mutationFn: () => api<Pair>(`/pairs/${pair.id}`, "PUT", draft),
    onSuccess: async () => {
      onDirty(false);
      await refresh();
      notify(`${pair.folder} · GT와 메타데이터를 저장했습니다.`);
    },
  });
  const field = <K extends keyof PairDraft>(key: K, value: PairDraft[K]) =>
    setDraft((d) => ({ ...d, [key]: value }));
  return (
    <>
      {cleaningImage && (
        <ImageCleaner
          image={cleaningImage}
          close={() => setCleaningImage(null)}
          saved={async () => {
            setCleaningImage(null);
            await refresh();
            notify(
              "이미지 표시 제거 설정을 저장했습니다. 원본과 GT는 유지됩니다.",
            );
          }}
        />
      )}
      {roiOpen && (
        <ReferenceROI
          pair={pair}
          close={() => setRoiOpen(false)}
          saved={async () => {
            setRoiOpen(false);
            await refresh();
            notify(
              "REF ROI를 저장했습니다. 학습 전에 새 Dataset Version을 생성하세요.",
            );
          }}
        />
      )}
      <div className="pair-detail-heading">
        <div>
          <h2>{pair.folder}</h2>
          <Status pair={pair} />
          {dirty && <span className="unsaved">저장하지 않은 변경</span>}
        </div>
        <div className="pair-navigation">
          <button
            type="button"
            className="button secondary"
            disabled={!dirty || save.isPending}
            onClick={() => setDraft(draftOf(pair))}
          >
            <Undo2 size={15} /> 되돌리기
          </button>
          <button
            type="submit"
            form="pair-editor-form"
            className="button primary"
            disabled={!dirty || save.isPending}
            title="Ctrl+S"
          >
            {save.isPending ? (
              <Loader2 className="spin" size={16} />
            ) : (
              <Save size={16} />
            )}{" "}
            변경 저장
          </button>
          <span>{position}</span>
          <button
            className="icon-button"
            disabled={!previous || save.isPending}
            aria-label="이전 Pair"
            onClick={previous}
          >
            <ChevronLeft size={19} />
          </button>
          <button
            className="icon-button"
            disabled={!next || save.isPending}
            aria-label="다음 Pair"
            onClick={next}
          >
            <ChevronRight size={19} />
          </button>
        </div>
      </div>
      {pair.import_issues.length > 0 && (
        <div className="error-box">
          <TriangleAlert size={17} />
          <span>{pair.import_issues.join(" · ")}</span>
        </div>
      )}
      <div className="annotation-tip">
        <Crosshair size={16} />
        <span>
          <strong>Query 이미지에서 정답 위치를 클릭하세요.</strong> 확대 후에도
          원본 픽셀 좌표로 저장됩니다.
        </span>
        <label className="checkbox-label">
          <input
            type="checkbox"
            checked={showGT}
            onChange={(e) => setShowGT(e.target.checked)}
          />
          <i className="gt-legend" /> GT 표시
        </label>
      </div>
      <div className="viewers">
        <ImageViewer
          image={pair.reference}
          title="REF"
          zoom={refZoom}
          setZoom={setRefZoom}
          showGT={false}
          onClean={
            !dirty && !save.isPending && pair.reference
              ? () => setCleaningImage(pair.reference)
              : undefined
          }
        />
        <ImageViewer
          image={pair.query}
          title="QUERY"
          gt={{ x: draft.gt_x, y: draft.gt_y }}
          onPick={(x, y) => {
            if (!save.isPending) setDraft((d) => ({ ...d, gt_x: x, gt_y: y }));
          }}
          zoom={queryZoom}
          setZoom={setQueryZoom}
          showGT={showGT}
          onClean={
            !dirty && !save.isPending && pair.query
              ? () => setCleaningImage(pair.query)
              : undefined
          }
        />
      </div>
      <form
        id="pair-editor-form"
        onSubmit={(e) => {
          e.preventDefault();
          save.mutate();
        }}
      >
        <fieldset disabled={save.isPending} className="editor-fieldset">
          <div className="coordinate-bar">
            <div className="coordinate-title">
              <Crosshair size={19} />
              <div>
                <strong>Ground truth</strong>
                <span>원본 픽셀 · 좌상단 (0, 0)</span>
              </div>
            </div>
            <label>
              X
              <input
                aria-label="GT X"
                type="number"
                min="0"
                max={pair.query?.width ? pair.query.width - 0.001 : undefined}
                step="any"
                value={draft.gt_x ?? ""}
                onChange={(e) =>
                  field(
                    "gt_x",
                    e.target.value === "" ? null : Number(e.target.value),
                  )
                }
              />
            </label>
            <label>
              Y
              <input
                aria-label="GT Y"
                type="number"
                min="0"
                max={pair.query?.height ? pair.query.height - 0.001 : undefined}
                step="any"
                value={draft.gt_y ?? ""}
                onChange={(e) =>
                  field(
                    "gt_y",
                    e.target.value === "" ? null : Number(e.target.value),
                  )
                }
              />
            </label>
            <button
              type="button"
              className="icon-button"
              aria-label="GT 지우기"
              onClick={() =>
                setDraft((d) => ({ ...d, gt_x: null, gt_y: null }))
              }
            >
              <Trash2 size={16} />
            </button>
            <span className="coordinate-source">
              {draft.gt_x === null ? "위치 미지정" : "● Manual"}
            </span>
          </div>
          <section className="panel metadata-panel">
            <div className="metadata-tabs">
              <button
                type="button"
                className={tab === "metadata" ? "active" : ""}
                onClick={() => setTab("metadata")}
              >
                <SlidersHorizontal size={15} /> Metadata
              </button>
              <button
                type="button"
                className={tab === "history" ? "active" : ""}
                onClick={() => setTab("history")}
              >
                <HistoryIcon size={15} /> GT 이력
              </button>
              <span>{dateLabel(pair.updated_at)} 수정</span>
            </div>
            {tab === "metadata" ? (
              <div className="metadata-body">
                <div className="training-controls">
                  <button
                    type="button"
                    className="button secondary small"
                    disabled={
                      dirty || !pair.reference || !!pair.reference.error
                    }
                    onClick={() => setRoiOpen(true)}
                  >
                    REF ROI 지정
                  </button>
                  <span>
                    {pair.reference_annotation
                      ? `중심 ${pair.reference_annotation.center.join(", ")}`
                      : "REF ROI 미지정"}
                  </span>
                  <label>
                    Pattern Type
                    <select
                      value={draft.pattern_type}
                      onChange={(e) =>
                        field(
                          "pattern_type",
                          e.target.value as Pair["pattern_type"],
                        )
                      }
                    >
                      <option value="unknown">unknown</option>
                      <option>A</option>
                      <option>B</option>
                    </select>
                  </label>
                </div>
                <label>
                  클래스
                  <input
                    value={draft.class_label}
                    onChange={(e) => field("class_label", e.target.value)}
                    maxLength={200}
                    placeholder="예: connector / pad"
                  />
                </label>
                <div className="metadata-row">
                  <label>
                    데이터 그룹
                    <input
                      placeholder="예: pattern-A / capture-001"
                      value={draft.group_key}
                      onChange={(e) => field("group_key", e.target.value)}
                      maxLength={200}
                    />
                    <small>
                      같은 원본·촬영 묶음의 Pair에 동일하게 지정하세요.
                    </small>
                  </label>
                  <label>
                    Tier
                    <input
                      placeholder="예: A 또는 B"
                      value={draft.tier}
                      onChange={(e) => field("tier", e.target.value)}
                      maxLength={50}
                    />
                  </label>
                  <label>
                    데이터 사용
                    <select
                      value={draft.enabled ? "enabled" : "excluded"}
                      onChange={(e) =>
                        field("enabled", e.target.value === "enabled")
                      }
                    >
                      <option value="enabled">사용</option>
                      <option value="excluded">제외</option>
                    </select>
                  </label>
                </div>
                {!draft.enabled && (
                  <label>
                    제외 사유
                    <input
                      required
                      value={draft.exclude_reason}
                      onChange={(e) => field("exclude_reason", e.target.value)}
                      placeholder="제외 이유를 기록하세요."
                    />
                  </label>
                )}
                <label>
                  검수 메모
                  <textarea
                    rows={2}
                    value={draft.notes}
                    onChange={(e) => field("notes", e.target.value)}
                    placeholder="반복 패턴, 흐림, scale 차이 등 확인한 내용을 기록하세요."
                  />
                </label>
              </div>
            ) : (
              <div className="history-body">
                <ErrorBox error={history.error} />
                {history.isPending ? (
                  <p>이력을 불러오는 중…</p>
                ) : !history.data?.length ? (
                  <p className="subtle">아직 저장된 GT 변경 이력이 없습니다.</p>
                ) : (
                  history.data.map((h) => (
                    <div className="history-row" key={h.id}>
                      <HistoryIcon size={15} />
                      <div>
                        <strong>{h.reason}</strong>
                        <span className="mono">
                          {h.before.x === null
                            ? "미지정"
                            : `(${h.before.x}, ${h.before.y})`}{" "}
                          →{" "}
                          {h.after.x === null
                            ? "미지정"
                            : `(${h.after.x}, ${h.after.y})`}
                        </span>
                      </div>
                      <time>{dateLabel(h.created_at)}</time>
                    </div>
                  ))
                )}
              </div>
            )}
          </section>
          <ErrorBox error={save.error} />
          <div className="save-bar">
            <span>
              {dirty
                ? "변경 사항은 위쪽 '변경 저장' 또는 Ctrl+S로 저장하며 GT 이력에 기록됩니다."
                : "저장된 최신 데이터입니다."}
            </span>
          </div>
        </fieldset>
      </form>
    </>
  );
}
