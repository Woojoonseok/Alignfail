import { NavLink, useNavigate } from "react-router-dom";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  ArrowRight,
  CheckCircle2,
  Files,
  Loader2,
  RefreshCw,
  ShieldCheck,
  TriangleAlert,
} from "lucide-react";
import { api, dateLabel, type Audit, type Project } from "../api";
import type { Notify } from "../types";
import { ErrorBox, Empty } from "../components/ui";

export function AuditPage({ project }: { project: Project; notify: Notify }) {
  const client = useQueryClient();
  const navigate = useNavigate();
  const cached = useQuery<Audit | null>({
    queryKey: ["audit", project.id],
    queryFn: async () => null,
    enabled: false,
  });
  const audit = useMutation({
    mutationFn: () => api<Audit>(`/projects/${project.id}/audit`, "POST"),
    onSuccess: (data) => client.setQueryData(["audit", project.id], data),
  });
  const data = cached.data;
  return (
    <>
      <div className="audit-intro panel">
        <div className="audit-symbol">
          <ShieldCheck size={32} />
        </div>
        <div>
          <h2>Dataset quality check</h2>
          <p>
            원본 파일을 다시 읽어 등록된 hash와 비교하고, 활성 Pair의 GT와
            구성을 검사합니다.
          </p>
          <small>
            완전히 동일한 파일은 자동 탐지합니다. 육안 유사도 후보 검색과 Split
            누수 검사는 후속 단계입니다.
          </small>
        </div>
        <button
          className="button primary"
          disabled={audit.isPending || !project.pair_count}
          onClick={() => audit.mutate()}
        >
          {audit.isPending ? (
            <Loader2 className="spin" size={17} />
          ) : (
            <RefreshCw size={17} />
          )}
          {audit.isPending ? "검사 중…" : "검사 실행"}
        </button>
      </div>
      <ErrorBox error={audit.error} />
      {!data ? (
        <section className="panel">
          <Empty
            icon={<ShieldCheck size={30} />}
            title="데이터의 준비 상태를 확인하세요."
          >
            <p>검사 실행을 누르면 오류와 검토 항목이 여기에 표시됩니다.</p>
          </Empty>
        </section>
      ) : (
        <>
          <div className={`audit-result ${data.passed ? "pass" : "fail"}`}>
            <div>
              {data.passed ? (
                <CheckCircle2 size={24} />
              ) : (
                <TriangleAlert size={24} />
              )}
              <div>
                <strong>
                  {data.passed
                    ? "파일·GT 검사 통과"
                    : "확인이 필요한 항목이 있습니다."}
                </strong>
                <p>
                  {data.enabled_count}개 활성 Pair · 오류 {data.errors}건 · 검토{" "}
                  {data.warnings}건
                </p>
              </div>
            </div>
            <span>{dateLabel(data.checked_at)} 검사</span>
          </div>
          <div className="notice">
            <ShieldCheck size={16} />
            <span>{data.scope}</span>
          </div>
          <section className="panel">
            <div className="section-title">
              <h2>
                검사 결과{" "}
                <span className="count-label">{data.issues.length}</span>
              </h2>
              {data.passed && (
                <NavLink to="/versions" className="text-link">
                  버전 생성하기 <ArrowRight size={15} />
                </NavLink>
              )}
            </div>
            {!data.issues.length ? (
              <p className="clean-message">
                <CheckCircle2 size={20} /> 검사 항목에서 문제가 발견되지
                않았습니다.
              </p>
            ) : (
              <div className="table-wrap">
                <table>
                  <thead>
                    <tr>
                      <th>상태</th>
                      <th>PAIR</th>
                      <th>검사 항목</th>
                      <th>내용</th>
                      <th />
                    </tr>
                  </thead>
                  <tbody>
                    {data.issues.map((i, n) => (
                      <tr key={`${i.pair_id}-${n}`}>
                        <td>
                          <span
                            className={`badge ${i.severity === "error" ? "red" : "amber"}`}
                          >
                            {i.severity === "error" ? "오류" : "검토"}
                          </span>
                        </td>
                        <td>
                          <button
                            className="table-pair-name"
                            onClick={() => navigate(`/pairs?pair=${i.pair_id}`)}
                          >
                            {i.folder}
                          </button>
                        </td>
                        <td className="mono audit-code">{i.code}</td>
                        <td>{i.message}</td>
                        <td>
                          <button
                            className="icon-button"
                            aria-label={`${i.folder} 검토`}
                            onClick={() => navigate(`/pairs?pair=${i.pair_id}`)}
                          >
                            <ArrowRight size={15} />
                          </button>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </section>
          {data.duplicates.length > 0 && (
            <section className="panel duplicate-section">
              <div className="section-title">
                <div>
                  <h2>동일 파일 묶음</h2>
                  <p className="section-description">
                    자동 삭제하지 않습니다. 관련 Pair를 확인하고 같은 데이터
                    그룹으로 묶으세요.
                  </p>
                </div>
                <Files size={20} />
              </div>
              {data.duplicates.map((d) => (
                <div className="duplicate-row" key={d.file_hash}>
                  <code>SHA256 {d.file_hash.slice(0, 16)}…</code>
                  <div>
                    {d.occurrences.map((o, i) => (
                      <button
                        className="button secondary small"
                        key={`${o.pair_id}-${i}`}
                        onClick={() => navigate(`/pairs?pair=${o.pair_id}`)}
                      >
                        {o.folder} · {o.role}
                        <ArrowRight size={12} />
                      </button>
                    ))}
                  </div>
                </div>
              ))}
            </section>
          )}
        </>
      )}
    </>
  );
}
