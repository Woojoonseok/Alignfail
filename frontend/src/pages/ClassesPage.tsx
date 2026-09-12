import { useMemo, useState, type CSSProperties } from "react";
import { useNavigate } from "react-router-dom";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import {
  ArrowRight,
  Check,
  Link2,
  Loader2,
  Pencil,
  Sparkles,
  Star,
  Tags,
  X,
} from "lucide-react";
import {
  api,
  cleanImageUrl,
  imageUrl,
  type ClassSummary,
  type ImageRecord,
  type MatchResult,
  type Pair,
} from "../api";
import type { PageProps } from "../types";
import { useAction } from "../hooks";
import { Empty, ErrorBox } from "../components/ui";
import "../classes.css";

const UNASSIGNED = "";
const SIZES = { small: 72, medium: 110, large: 160 } as const;
type Size = keyof typeof SIZES;

function imageSrc(image: ImageRecord | null) {
  if (!image || image.error) return null;
  return image.cleanup && !image.cleanup.stale
    ? cleanImageUrl(image)
    : imageUrl(image);
}

/** Every pair grouped by class label; unassigned pairs come last. */
function groupByClass(pairs: Pair[]) {
  const groups = new Map<string, Pair[]>();
  for (const pair of pairs) {
    const key = pair.class_label.trim();
    groups.set(key, [...(groups.get(key) ?? []), pair]);
  }
  const named = [...groups.keys()]
    .filter((k) => k !== UNASSIGNED)
    .sort((a, b) => a.localeCompare(b, "ko"));
  const keys = groups.has(UNASSIGNED) ? [...named, UNASSIGNED] : named;
  return keys.map((key) => ({ key, pairs: groups.get(key)! }));
}

export function ClassesPage({ project, pairs, refresh, notify }: PageProps) {
  const navigate = useNavigate();
  const client = useQueryClient();
  const { busy, error, run } = useAction();
  const [role, setRole] = useState<"reference" | "query">("reference");
  const [size, setSize] = useState<Size>("medium");
  const [search, setSearch] = useState("");
  const [modality, setModality] = useState("");
  const [onlyUnlinked, setOnlyUnlinked] = useState(false);
  const [includeExcluded, setIncludeExcluded] = useState(false);
  const [selected, setSelected] = useState(new Set<string>());
  const [target, setTarget] = useState("");
  const [newName, setNewName] = useState("");
  const [renaming, setRenaming] = useState<string | null>(null);
  const [renameValue, setRenameValue] = useState("");
  const [matches, setMatches] = useState<Record<string, MatchResult>>({});

  const summary = useQuery({
    queryKey: ["classes", project.id],
    queryFn: () => api<ClassSummary>(`/projects/${project.id}/classes`),
  });
  const templates = useMemo(
    () =>
      new Map(
        (summary.data?.classes ?? []).map((c) => [c.class_label, c.template]),
      ),
    [summary.data],
  );

  const visible = useMemo(
    () =>
      pairs.filter(
        (p) =>
          (includeExcluded || p.enabled) &&
          (!modality || p.modality === modality) &&
          (!onlyUnlinked || !p.reference) &&
          `${p.folder} ${p.class_label} ${p.group_key}`
            .toLowerCase()
            .includes(search.toLowerCase()),
      ),
    [pairs, includeExcluded, modality, onlyUnlinked, search],
  );
  const groups = useMemo(() => groupByClass(visible), [visible]);
  const classNames = useMemo(
    () =>
      [
        ...new Set([
          ...pairs.map((p) => p.class_label.trim()).filter(Boolean),
          ...templates.keys(),
        ]),
      ].sort((a, b) => a.localeCompare(b, "ko")),
    [pairs, templates],
  );
  const chosen = pairs.filter((p) => selected.has(p.id));
  const unassignedCount = pairs.filter(
    (p) => p.enabled && !p.class_label.trim(),
  ).length;

  async function reload() {
    await refresh();
    await client.invalidateQueries({ queryKey: ["classes", project.id] });
  }
  function toggle(id: string) {
    setSelected((s) => {
      const next = new Set(s);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  }
  function selectClass(key: string, on: boolean) {
    const ids = groups.find((g) => g.key === key)?.pairs.map((p) => p.id) ?? [];
    setSelected((s) => {
      const next = new Set(s);
      ids.forEach((id) => (on ? next.add(id) : next.delete(id)));
      return next;
    });
  }
  /** Attach pairs to a class: sets class_label and links the template REF to REF-less pairs. */
  async function attach(items: Pair[], label: string) {
    await run(async () => {
      const result = await api<{ updated: number; linked: number }>(
        `/projects/${project.id}/classes/attach`,
        "POST",
        {
          pairs: items.map((p) => ({ id: p.id, revision: p.revision })),
          class_label: label,
        },
      );
      setSelected(new Set());
      setNewName("");
      setMatches((m) => {
        const next = { ...m };
        items.forEach((p) => delete next[p.id]);
        return next;
      });
      await reload();
      notify(
        `${result.updated}개 Pair → '${label}'${result.linked ? ` · REF ${result.linked}개 연결` : ""}`,
      );
    });
  }
  async function clearClass(items: Pair[]) {
    await run(async () => {
      const result = await api<{ updated: number }>(
        `/projects/${project.id}/groups/bulk`,
        "POST",
        {
          assignments: items.map((p) => ({
            id: p.id,
            revision: p.revision,
            class_label: "",
          })),
        },
      );
      setSelected(new Set());
      await reload();
      notify(`${result.updated}개 Pair · 클래스 해제`);
    });
  }
  async function rename(from: string, to: string) {
    await run(async () => {
      await api(`/projects/${project.id}/classes/rename`, "POST", {
        pairs: pairs
          .filter((p) => p.class_label === from)
          .map((p) => ({ id: p.id, revision: p.revision })),
        class_label: from,
        new_label: to,
      });
      setRenaming(null);
      await reload();
      notify(`'${from}' → '${to}' 이름 변경`);
    });
  }
  async function setTemplate(label: string, image: ImageRecord) {
    await run(async () => {
      await api(
        `/projects/${project.id}/classes/${encodeURIComponent(label)}/template`,
        "PUT",
        { image_id: image.id },
      );
      await reload();
      notify(`'${label}' 대표 REF: ${image.file_name}`);
    });
  }
  async function findCandidates(items: Pair[]) {
    await run(async () => {
      const result = await api<{ results: MatchResult[] }>(
        `/projects/${project.id}/classes/match`,
        "POST",
        {
          pairs: items.map((p) => ({ id: p.id, revision: p.revision })),
          top_k: 3,
        },
      );
      setMatches((m) => ({
        ...m,
        ...Object.fromEntries(result.results.map((r) => [r.id, r])),
      }));
      notify(`${result.results.length}개 Pair의 클래스 후보를 계산했습니다.`);
    });
  }
  const moveLabel = newName.trim() || target;
  const templateCount = [...templates.values()].filter((t) => t?.image).length;

  if (!pairs.length)
    return (
      <section className="panel">
        <Empty title="먼저 데이터 폴더를 연결하세요.">
          <p>Pair가 등록되면 클래스별로 모아 볼 수 있습니다.</p>
        </Empty>
      </section>
    );

  return (
    <div className="classes-page">
      <section className="panel classes-toolbar">
        <div className="classes-summary">
          <Tags size={18} />
          <strong>{classNames.length}개 클래스</strong>
          <span>
            대표 REF {templateCount} · 미분류 {unassignedCount} · REF 미연결{" "}
            {project.unlinked_count} · OM {project.modalities.OM} / SEM{" "}
            {project.modalities.SEM}
          </span>
        </div>
        <div className="classes-controls">
          <input
            aria-label="클래스 · Pair 검색"
            placeholder="클래스 · Pair · 그룹 검색"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
          />
          <select
            aria-label="모달리티 필터"
            value={modality}
            onChange={(e) => setModality(e.target.value)}
          >
            <option value="">OM + SEM</option>
            <option value="OM">OM만</option>
            <option value="SEM">SEM만</option>
          </select>
          <select
            aria-label="썸네일 기준 이미지"
            value={role}
            onChange={(e) => setRole(e.target.value as typeof role)}
          >
            <option value="reference">REF 썸네일</option>
            <option value="query">Query 썸네일</option>
          </select>
          <select
            aria-label="썸네일 크기"
            value={size}
            onChange={(e) => setSize(e.target.value as Size)}
          >
            <option value="small">작게</option>
            <option value="medium">보통</option>
            <option value="large">크게</option>
          </select>
          <label className="checkbox-label">
            <input
              type="checkbox"
              checked={onlyUnlinked}
              onChange={(e) => setOnlyUnlinked(e.target.checked)}
            />{" "}
            REF 미연결만
          </label>
          <label className="checkbox-label">
            <input
              type="checkbox"
              checked={includeExcluded}
              onChange={(e) => setIncludeExcluded(e.target.checked)}
            />{" "}
            제외 포함
          </label>
        </div>
      </section>
      <p className="classes-hint">
        클래스는 <strong>템플릿 유형</strong>입니다. 클래스마다 대표 REF(★)를
        지정하면, REF 없이 들어온 이미지를 그 클래스에 붙일 때 대표 REF가
        자동으로 연결됩니다. "클래스 후보 찾기"는 외형 유사도로 대표 REF와
        비교해 같은 모달리티 안에서 상위 3개를 제안합니다.
      </p>
      {chosen.length > 0 && (
        <section className="panel classes-selection" aria-live="polite">
          <strong>{chosen.length}개 선택</strong>
          <select
            aria-label="이동할 클래스"
            value={target}
            disabled={busy || !!newName.trim()}
            onChange={(e) => setTarget(e.target.value)}
          >
            <option value="">기존 클래스 선택</option>
            {classNames.map((name) => (
              <option key={name} value={name}>
                {name}
                {templates.get(name)?.image ? " ★" : ""}
              </option>
            ))}
          </select>
          <span>또는</span>
          <input
            aria-label="새 클래스 이름"
            placeholder="새 클래스 이름"
            maxLength={200}
            value={newName}
            disabled={busy}
            onChange={(e) => setNewName(e.target.value)}
          />
          <button
            className="button primary"
            disabled={busy || !moveLabel}
            onClick={() => attach(chosen, moveLabel)}
          >
            {busy ? (
              <Loader2 className="spin" size={15} />
            ) : (
              <Check size={15} />
            )}{" "}
            클래스에 붙이기
          </button>
          <button
            className="button secondary"
            disabled={busy || !templateCount}
            onClick={() => findCandidates(chosen)}
          >
            <Sparkles size={14} /> 클래스 후보 찾기
          </button>
          <button
            className="button secondary"
            disabled={busy}
            onClick={() => clearClass(chosen)}
          >
            클래스 해제
          </button>
          <button
            className="button secondary"
            disabled={busy}
            onClick={() => setSelected(new Set())}
          >
            <X size={14} /> 선택 취소
          </button>
        </section>
      )}
      <ErrorBox error={error || summary.error} />
      {!groups.length ? (
        <section className="panel">
          <Empty title="검색 결과가 없습니다.">
            <p>검색어나 필터를 바꿔 보세요.</p>
          </Empty>
        </section>
      ) : (
        groups.map(({ key, pairs: members }) => {
          const allSelected = members.every((p) => selected.has(p.id));
          const someSelected = members.some((p) => selected.has(p.id));
          const template = key ? templates.get(key) : null;
          const templateSrc = template?.image ? imageSrc(template.image) : null;
          return (
            <section
              key={key || "__unassigned"}
              className={`panel class-card ${key ? "" : "unassigned"}`}
            >
              <header className="class-card-header">
                <label className="checkbox-label">
                  <input
                    type="checkbox"
                    aria-label={`${key || "미분류"} 전체 선택`}
                    checked={allSelected}
                    ref={(el) => {
                      if (el) el.indeterminate = someSelected && !allSelected;
                    }}
                    onChange={(e) => selectClass(key, e.target.checked)}
                  />
                </label>
                {key && (
                  <div
                    className={`class-template ${templateSrc ? "" : "missing"}`}
                    title={
                      template?.image
                        ? `대표 REF: ${template.image.file_name}`
                        : "대표 REF 미지정 · 썸네일의 ★로 지정"
                    }
                  >
                    {templateSrc ? (
                      <img src={templateSrc} alt="대표 REF" />
                    ) : (
                      <Star size={14} />
                    )}
                  </div>
                )}
                {renaming === key ? (
                  <form
                    className="class-rename"
                    onSubmit={(e) => {
                      e.preventDefault();
                      const label = renameValue.trim();
                      if (label && label !== key) rename(key, label);
                      else setRenaming(null);
                    }}
                  >
                    <input
                      autoFocus
                      aria-label="클래스 이름"
                      maxLength={200}
                      value={renameValue}
                      disabled={busy}
                      onChange={(e) => setRenameValue(e.target.value)}
                    />
                    <button className="button primary small" disabled={busy}>
                      저장
                    </button>
                    <button
                      type="button"
                      className="button secondary small"
                      disabled={busy}
                      onClick={() => setRenaming(null)}
                    >
                      취소
                    </button>
                  </form>
                ) : (
                  <h2>
                    {key || <span className="subtle">미분류</span>}
                    <span className="count-label">{members.length}</span>
                    {key && (
                      <button
                        className="icon-button"
                        aria-label={`${key} 이름 변경`}
                        disabled={busy}
                        onClick={() => {
                          setRenaming(key);
                          setRenameValue(key);
                        }}
                      >
                        <Pencil size={13} />
                      </button>
                    )}
                  </h2>
                )}
                <span className="class-card-meta">
                  {!key && templateCount > 0 && (
                    <button
                      type="button"
                      className="button secondary small"
                      disabled={busy}
                      onClick={() => findCandidates(members)}
                    >
                      <Sparkles size={12} /> 전체 클래스 후보 찾기
                    </button>
                  )}
                  GT 완료 {members.filter((p) => p.gt_x !== null).length} · REF
                  미연결 {members.filter((p) => !p.reference).length} · OM{" "}
                  {members.filter((p) => p.modality === "OM").length} / SEM{" "}
                  {members.filter((p) => p.modality === "SEM").length}
                </span>
              </header>
              <div
                className="class-grid"
                style={{ "--thumb": `${SIZES[size]}px` } as CSSProperties}
              >
                {members.map((p) => {
                  const url = imageSrc(p[role]);
                  const on = selected.has(p.id);
                  const ownRef = !!p.reference && !p.reference_shared;
                  const match = matches[p.id];
                  return (
                    <figure
                      key={p.id}
                      className={`class-thumb ${on ? "selected" : ""} ${p.enabled ? "" : "excluded"}`}
                    >
                      <button
                        type="button"
                        aria-pressed={on}
                        aria-label={`${p.folder} 선택`}
                        onClick={() => toggle(p.id)}
                      >
                        {url ? (
                          <img loading="lazy" src={url} alt={p.folder} />
                        ) : (
                          <span className="class-thumb-empty">
                            {role === "reference" && !p.reference
                              ? "REF 미연결"
                              : "이미지 없음"}
                          </span>
                        )}
                        {on && (
                          <span className="class-thumb-check">
                            <Check size={12} />
                          </span>
                        )}
                        <span className="class-thumb-tags">
                          {p.modality && <em>{p.modality}</em>}
                          {p.match_result === "success" && <em>s</em>}
                          {p.match_result === "fail" && <em>e</em>}
                          {p.reference_shared && (
                            <em title="템플릿 REF 연결됨">
                              <Link2 size={9} />
                            </em>
                          )}
                        </span>
                        {p.gt_x === null && p.enabled && (
                          <span className="class-thumb-flag">GT 없음</span>
                        )}
                        {p.gt_source === "auto_cross" && (
                          <span className="class-thumb-flag auto">자동 GT</span>
                        )}
                      </button>
                      <figcaption>
                        <span title={p.folder}>{p.folder}</span>
                        {key && ownRef && (
                          <button
                            type="button"
                            className={`icon-button star ${template?.image?.id === p.reference!.id ? "active" : ""}`}
                            aria-label={`${p.folder}의 REF를 ${key} 대표로 지정`}
                            disabled={busy}
                            onClick={() => setTemplate(key, p.reference!)}
                          >
                            <Star size={12} />
                          </button>
                        )}
                        <button
                          type="button"
                          className="icon-button"
                          aria-label={`${p.folder} 열기`}
                          onClick={() => navigate(`/pairs?pair=${p.id}`)}
                        >
                          <ArrowRight size={12} />
                        </button>
                      </figcaption>
                      {match && (
                        <div className="class-candidates">
                          {match.error ? (
                            <span className="subtle">{match.error}</span>
                          ) : !match.candidates.length ? (
                            <span className="subtle">
                              같은 모달리티의 대표 REF 없음
                            </span>
                          ) : (
                            match.candidates.map((c) => (
                              <button
                                type="button"
                                key={c.class_label}
                                disabled={busy}
                                title={`유사도 ${c.score.toFixed(3)}`}
                                onClick={() => attach([p], c.class_label)}
                              >
                                <span>{c.class_label}</span>
                                <i
                                  style={{
                                    width: `${Math.max(4, Math.round(((c.score + 1) / 2) * 100))}%`,
                                  }}
                                />
                                <small>{c.score.toFixed(2)}</small>
                              </button>
                            ))
                          )}
                        </div>
                      )}
                    </figure>
                  );
                })}
              </div>
            </section>
          );
        })
      )}
    </div>
  );
}
