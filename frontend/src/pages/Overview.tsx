import { NavLink, useNavigate } from "react-router-dom";
import {
  ArrowRight,
  Check,
  Crosshair,
  Database,
  FolderInput,
  GitBranch,
  Layers3,
  ShieldCheck,
  Target,
} from "lucide-react";
import { type Pair, type Project } from "../api";
import { Empty, Status, Thumb } from "../components/ui";

export function Overview({
  project,
  pairs,
  importData,
}: {
  project: Project;
  pairs: Pair[];
  importData: () => void;
}) {
  const navigate = useNavigate();
  const progress = project.enabled_count
    ? Math.round((project.annotated_count / project.enabled_count) * 100)
    : 0;
  const next = pairs.find(
    (p) => p.enabled && p.gt_x === null && !p.import_issues.length,
  );
  return (
    <>
      <div className="stat-grid">
        {[
          {
            title: "전체 Pair",
            value: project.pair_count,
            subtitle: "Reference + Query",
            icon: <Layers3 size={20} />,
          },
          {
            title: "GT 지정 완료",
            value: project.annotated_count,
            subtitle: `활성 ${project.enabled_count}개 중 ${progress}% 완료`,
            icon: <Crosshair size={20} />,
          },
          {
            title: "데이터 그룹",
            value: project.group_count,
            subtitle: "연관 Pair를 묶는 기준",
            icon: <GitBranch size={20} />,
          },
          {
            title: "파일 확인 필요",
            value: project.issue_count,
            subtitle: "가져오기 검사 기준",
            icon: <ShieldCheck size={20} />,
          },
        ].map((s, i) => (
          <div className="stat-card" key={s.title}>
            <div className="stat-top">
              {s.title}
              <div className={`stat-icon stat-${i}`}>{s.icon}</div>
            </div>
            <div className="stat-value">
              {s.value}
              <span>{i === 1 ? "PAIRS" : i === 2 ? "GROUPS" : "PAIRS"}</span>
            </div>
            <div className="stat-bottom">
              {i === 1 && <span className="mini-dot" />}
              {s.subtitle}
            </div>
          </div>
        ))}
      </div>
      <div className="overview-columns">
        <section className="panel getting-started">
          <div className="section-title">
            <div>
              <div className="eyebrow">DATA READINESS</div>
              <h2>학습을 위한 준비</h2>
            </div>
            <span className="badge green">Dataset Studio</span>
          </div>
          <p className="section-description">
            데이터를 연결하고, 정답을 확인하고, 재현 가능한 버전으로 남기세요.
          </p>
          <div className="readiness-progress">
            <span>GT annotation</span>
            <strong>{progress}%</strong>
          </div>
          <div className="progress-track">
            <div style={{ width: `${progress}%` }} />
          </div>
          <div className="readiness-steps">
            {[
              {
                name: "데이터 폴더 연결",
                detail: "Pair 구조와 이미지를 자동으로 검사합니다.",
                done: !!project.root_directory,
                action: importData,
              },
              {
                name: "Pair 검수 · GT 지정",
                detail: "Query의 정답 위치를 클릭하고 저장합니다.",
                done: !!project.enabled_count && progress === 100,
                action: () => navigate("/pairs"),
              },
              {
                name: "품질 검사 · 버전 생성",
                detail: "파일과 GT를 검사한 후 스냅샷을 만듭니다.",
                done: false,
                action: () => navigate("/audit"),
              },
            ].map((s, i) => (
              <button
                className="readiness-step"
                key={s.name}
                onClick={s.action}
              >
                <span className={`step-circle ${s.done ? "done" : ""}`}>
                  {s.done ? (
                    <Check size={16} />
                  ) : (
                    String(i + 1).padStart(2, "0")
                  )}
                </span>
                <span>
                  <strong>{s.name}</strong>
                  <small>{s.detail}</small>
                </span>
                <ArrowRight size={17} />
              </button>
            ))}
          </div>
        </section>
        <section className="focus-card">
          <div className="focus-icon">
            <Target size={27} />
          </div>
          <div className="eyebrow">PRECISION STARTS HERE</div>
          <h2>
            작은 좌표 차이까지,
            <br />
            직접 확인하세요.
          </h2>
          <p>
            두 이미지를 나란히 비교하고
            <br />
            원본 해상도 기준으로 GT를 기록합니다.
          </p>
          <div className="focus-pair">
            <div>
              <span>REF</span>
              <div className="pattern-mini" />
            </div>
            <ArrowRight size={18} />
            <div>
              <span>QUERY</span>
              <div className="pattern-mini query-mini">
                <span className="target-dot" />
              </div>
            </div>
          </div>
          <button
            className="button focus-button"
            onClick={() => navigate(next ? `/pairs?pair=${next.id}` : "/pairs")}
          >
            Pair Explorer 열기 <ArrowRight size={16} />
          </button>
        </section>
      </div>
      <section className="panel">
        <div className="section-title">
          <div>
            <h2>등록된 Pair</h2>
            <p className="section-description">
              검수를 시작할 Pair를 선택하세요.
            </p>
          </div>
          <NavLink className="text-link" to="/pairs">
            전체 보기 <ArrowRight size={15} />
          </NavLink>
        </div>
        {!pairs.length ? (
          <Empty title="연결된 데이터가 없습니다.">
            <p>Dada 폴더를 연결하면 Pair 목록이 여기에 표시됩니다.</p>
            <button className="button secondary" onClick={importData}>
              <FolderInput size={16} /> 데이터 가져오기
            </button>
          </Empty>
        ) : (
          <div className="table-wrap">
            <table>
              <thead>
                <tr>
                  <th>PAIR</th>
                  <th>REFERENCE / QUERY</th>
                  <th>GROUP</th>
                  <th>GT (X, Y)</th>
                  <th>STATUS</th>
                  <th />
                </tr>
              </thead>
              <tbody>
                {pairs.slice(0, 6).map((p) => (
                  <tr key={p.id}>
                    <td>
                      <button
                        className="table-pair-name"
                        onClick={() => navigate(`/pairs?pair=${p.id}`)}
                      >
                        {p.folder}
                      </button>
                    </td>
                    <td>
                      <div className="table-thumbs">
                        <Thumb image={p.reference} />
                        <Thumb image={p.query} />
                      </div>
                    </td>
                    <td>
                      {p.group_key || <span className="subtle">미지정</span>}
                    </td>
                    <td className="mono">
                      {p.gt_x === null ? "—" : `${p.gt_x}, ${p.gt_y}`}
                    </td>
                    <td>
                      <Status pair={p} />
                    </td>
                    <td>
                      <button
                        className="icon-button"
                        aria-label={`${p.folder} 열기`}
                        onClick={() => navigate(`/pairs?pair=${p.id}`)}
                      >
                        <ArrowRight size={16} />
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>
      <div className="path-bar">
        <Database size={15} />
        <span>DATA ROOT</span>
        <code>{project.root_directory || "아직 연결되지 않았습니다."}</code>
        <span className="path-end">원본 파일 참조</span>
      </div>
    </>
  );
}
