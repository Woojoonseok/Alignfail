import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  ArrowRight,
  CheckCircle2,
  FileJson,
  Files,
  GitBranch,
  Loader2,
  Plus,
} from "lucide-react";
import {
  api,
  dateLabel,
  versionName,
  type Project,
  type Version,
} from "../api";
import type { Notify } from "../types";
import { ErrorBox, Empty } from "../components/ui";

export function VersionsPage({
  project,
  notify,
}: {
  project: Project;
  notify: Notify;
}) {
  const client = useQueryClient();
  const [description, setDescription] = useState("");
  const versions = useQuery({
    queryKey: ["versions", project.id],
    queryFn: () => api<Version[]>(`/projects/${project.id}/versions`),
  });
  const [base, setBase] = useState("");
  const [target, setTarget] = useState("");
  const create = useMutation({
    mutationFn: () =>
      api<{ number: number }>(`/projects/${project.id}/versions`, "POST", {
        description,
      }),
    onSuccess: async (r) => {
      await client.invalidateQueries({ queryKey: ["versions", project.id] });
      setDescription("");
      notify(`${versionName(r.number)} 데이터 버전을 생성했습니다.`);
    },
  });
  const diff = useQuery({
    queryKey: ["version-diff", target, base],
    queryFn: () =>
      api<{
        base: number;
        target: number;
        changes: { folder: string; fields: string[] }[];
      }>(`/versions/${target}/diff/${base}`),
    enabled: !!base && !!target && base !== target,
  });
  return (
    <>
      <section className="panel version-create">
        <div>
          <div className="eyebrow">IMMUTABLE SNAPSHOT</div>
          <h2>검수한 데이터를 하나의 버전으로</h2>
          <p>
            Pair 구성, GT, 그룹, 메타데이터와 파일 hash를 고정합니다.
            <br />
            생성할 때 파일·GT 검사를 다시 수행합니다.
          </p>
        </div>
        <form
          onSubmit={(e) => {
            e.preventDefault();
            create.mutate();
          }}
        >
          <label>
            이번 버전의 변경 내용
            <input
              required
              value={description}
              maxLength={4000}
              onChange={(e) => setDescription(e.target.value)}
              placeholder="예: 초기 GT 검수 완료, 촬영 그룹 정리"
            />
          </label>
          <button
            className="button primary"
            disabled={
              create.isPending || !description.trim() || !project.enabled_count
            }
          >
            {create.isPending ? (
              <Loader2 className="spin" size={16} />
            ) : (
              <Plus size={16} />
            )}{" "}
            버전 생성
          </button>
        </form>
      </section>
      <ErrorBox error={create.error || versions.error} />
      <div className="notice">
        <Files size={16} />
        <span>
          이미지를 복사하지 않는 스냅샷입니다. 과거 학습을 재현하려면 원본
          파일을 덮어쓰거나 삭제하지 않고 보존해야 합니다.
        </span>
      </div>
      <section className="panel">
        <div className="section-title">
          <h2>
            Dataset versions{" "}
            <span className="count-label">{versions.data?.length ?? 0}</span>
          </h2>
          <span className="subtle">JSON Manifest</span>
        </div>
        {versions.isPending ? (
          <div className="loading">버전을 불러오는 중…</div>
        ) : !versions.data?.length ? (
          <Empty
            icon={<Files size={30} />}
            title="아직 저장된 버전이 없습니다."
          >
            <p>활성 Pair의 GT를 지정하고 첫 번째 버전을 생성하세요.</p>
          </Empty>
        ) : (
          <div className="table-wrap">
            <table>
              <thead>
                <tr>
                  <th>VERSION</th>
                  <th>변경 내용</th>
                  <th>사용 / 전체 PAIRS</th>
                  <th>생성일</th>
                  <th />
                </tr>
              </thead>
              <tbody>
                {versions.data.map((v) => (
                  <tr key={v.id}>
                    <td>
                      <span className="version-tag">
                        <GitBranch size={14} />
                        {versionName(v.number)}
                      </span>
                    </td>
                    <td>{v.description}</td>
                    <td className="mono">
                      {v.enabled_count} / {v.pair_count}
                    </td>
                    <td>{dateLabel(v.created_at)}</td>
                    <td>
                      <a
                        className="button secondary small"
                        href={`/api/versions/${v.id}/manifest`}
                      >
                        <FileJson size={14} /> Manifest
                      </a>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>
      {(versions.data?.length ?? 0) >= 2 && (
        <section className="panel diff-panel">
          <div className="section-title">
            <h2>버전 변경점 비교</h2>
            <GitBranch size={20} />
          </div>
          <div className="diff-selectors">
            <label>
              기준 버전
              <select value={base} onChange={(e) => setBase(e.target.value)}>
                <option value="">선택</option>
                {versions.data?.map((v) => (
                  <option key={v.id} value={v.id}>
                    {versionName(v.number)} · {v.description}
                  </option>
                ))}
              </select>
            </label>
            <ArrowRight size={20} />
            <label>
              비교 버전
              <select
                value={target}
                onChange={(e) => setTarget(e.target.value)}
              >
                <option value="">선택</option>
                {versions.data?.map((v) => (
                  <option key={v.id} value={v.id}>
                    {versionName(v.number)} · {v.description}
                  </option>
                ))}
              </select>
            </label>
          </div>
          <ErrorBox error={diff.error} />
          {base && base === target && (
            <p className="subtle">서로 다른 버전을 선택하세요.</p>
          )}
          {diff.data && (
            <div>
              {!diff.data.changes.length ? (
                <p className="clean-message">
                  <CheckCircle2 size={18} /> 데이터 변경이 없습니다.
                </p>
              ) : (
                diff.data.changes.map((c) => (
                  <div className="diff-row" key={c.folder}>
                    <strong>{c.folder}</strong>
                    <span>{c.fields.join(" · ")}</span>
                  </div>
                ))
              )}
            </div>
          )}
        </section>
      )}
    </>
  );
}
