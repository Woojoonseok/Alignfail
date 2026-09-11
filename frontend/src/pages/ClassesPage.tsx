import { useMemo, useState, type CSSProperties } from "react";
import { useNavigate } from "react-router-dom";
import { ArrowRight, Check, Loader2, Pencil, Tags, X } from "lucide-react";
import { api, cleanImageUrl, imageUrl, type Pair } from "../api";
import type { PageProps } from "../types";
import { useAction } from "../hooks";
import { Empty, ErrorBox } from "../components/ui";
import "../classes.css";

const UNASSIGNED = "";
const SIZES = { small: 72, medium: 110, large: 160 } as const;
type Size = keyof typeof SIZES;

function thumbUrl(pair: Pair, role: "reference" | "query") {
  const image = pair[role];
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
  const { busy, error, run } = useAction();
  const [role, setRole] = useState<"reference" | "query">("reference");
  const [size, setSize] = useState<Size>("medium");
  const [search, setSearch] = useState("");
  const [includeExcluded, setIncludeExcluded] = useState(false);
  const [selected, setSelected] = useState(new Set<string>());
  const [target, setTarget] = useState("");
  const [newName, setNewName] = useState("");
  const [renaming, setRenaming] = useState<string | null>(null);
  const [renameValue, setRenameValue] = useState("");

  const visible = useMemo(
    () =>
      pairs.filter(
        (p) =>
          (includeExcluded || p.enabled) &&
          `${p.folder} ${p.class_label} ${p.group_key}`
            .toLowerCase()
            .includes(search.toLowerCase()),
      ),
    [pairs, includeExcluded, search],
  );
  const groups = useMemo(() => groupByClass(visible), [visible]);
  const classNames = groups.map((g) => g.key).filter((k) => k !== UNASSIGNED);
  const chosen = pairs.filter((p) => selected.has(p.id));
  const unassignedCount = pairs.filter(
    (p) => p.enabled && !p.class_label.trim(),
  ).length;

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
  async function assign(items: Pair[], label: string, message: string) {
    await run(async () => {
      const result = await api<{ updated: number }>(
        `/projects/${project.id}/groups/bulk`,
        "POST",
        {
          assignments: items.map((p) => ({
            id: p.id,
            revision: p.revision,
            class_label: label,
          })),
        },
      );
      setSelected(new Set());
      setRenaming(null);
      setNewName("");
      await refresh();
      notify(`${result.updated}개 Pair · ${message}`);
    });
  }
  const moveLabel = newName.trim() || target;

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
            미분류 {unassignedCount} / 활성 {project.enabled_count} Pair
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
              checked={includeExcluded}
              onChange={(e) => setIncludeExcluded(e.target.checked)}
            />{" "}
            제외 Pair 포함
          </label>
        </div>
      </section>
      <p className="classes-hint">
        썸네일을 클릭해 선택하고 다른 클래스로 옮기세요. 클래스는 의미 라벨이며
        학습 Split용 데이터 그룹(group_key)과는 별개입니다. 자동 후보는 Pair
        Explorer의 일괄 작업에서 "클래스로 적용"을 선택해 만들 수 있습니다.
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
            onClick={() =>
              assign(chosen, moveLabel, `'${moveLabel}' 클래스로 이동`)
            }
          >
            {busy ? (
              <Loader2 className="spin" size={15} />
            ) : (
              <Check size={15} />
            )}{" "}
            클래스로 이동
          </button>
          <button
            className="button secondary"
            disabled={busy}
            onClick={() => assign(chosen, "", "클래스 해제")}
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
      <ErrorBox error={error} />
      {!groups.length ? (
        <section className="panel">
          <Empty title="검색 결과가 없습니다.">
            <p>검색어나 제외 Pair 포함 여부를 바꿔 보세요.</p>
          </Empty>
        </section>
      ) : (
        groups.map(({ key, pairs: members }) => {
          const allSelected = members.every((p) => selected.has(p.id));
          const someSelected = members.some((p) => selected.has(p.id));
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
                {renaming === key ? (
                  <form
                    className="class-rename"
                    onSubmit={(e) => {
                      e.preventDefault();
                      const label = renameValue.trim();
                      if (label && label !== key)
                        assign(members, label, `'${label}'(으)로 이름 변경`);
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
                  GT 완료 {members.filter((p) => p.gt_x !== null).length} · 그룹{" "}
                  {
                    new Set(members.map((p) => p.group_key).filter(Boolean))
                      .size
                  }
                </span>
              </header>
              <div
                className="class-grid"
                style={{ "--thumb": `${SIZES[size]}px` } as CSSProperties}
              >
                {members.map((p) => {
                  const url = thumbUrl(p, role);
                  const on = selected.has(p.id);
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
                          <span className="class-thumb-empty">이미지 없음</span>
                        )}
                        {on && (
                          <span className="class-thumb-check">
                            <Check size={12} />
                          </span>
                        )}
                        {p.gt_x === null && p.enabled && (
                          <span className="class-thumb-flag">GT 없음</span>
                        )}
                      </button>
                      <figcaption>
                        <span title={p.folder}>{p.folder}</span>
                        <button
                          type="button"
                          className="icon-button"
                          aria-label={`${p.folder} 열기`}
                          onClick={() => navigate(`/pairs?pair=${p.id}`)}
                        >
                          <ArrowRight size={12} />
                        </button>
                      </figcaption>
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
