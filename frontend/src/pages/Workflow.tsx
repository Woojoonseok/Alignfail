import { NavLink } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import {
  Activity,
  ArrowRight,
  Check,
  GitBranch,
  LockKeyhole,
  Target,
} from "lucide-react";
import { api, type Audit, type Pair, type Project, type Version } from "../api";

export function Workflow({
  project,
  pairs,
}: {
  project: Project;
  pairs: Pair[];
}) {
  const versions = useQuery({
    queryKey: ["versions", project.id],
    queryFn: () => api<Version[]>(`/projects/${project.id}/versions`),
  });
  const audit = useQuery<Audit | null>({
    queryKey: ["audit", project.id],
    queryFn: async () => null,
    enabled: false,
  });
  const steps = [
    {
      title: "데이터 폴더 등록",
      text: "Dada의 하위 폴더를 REF–Query Pair로 연결합니다.",
      route: "/",
      complete: !!project.root_directory,
      label: "Overview",
    },
    {
      title: "GT 지정 · 그룹 검수",
      text: "Query에서 정답을 찍고, 연관된 Pair를 같은 그룹으로 묶습니다.",
      route: "/pairs",
      complete:
        !!project.enabled_count &&
        pairs
          .filter((p) => p.enabled)
          .every(
            (p) => p.gt_x !== null && !!p.group_key && !p.import_issues.length,
          ),
      label: "Pair Explorer",
    },
    {
      title: "품질 검사",
      text: "잘못된 Pair, 누락된 GT, 변경된 파일과 중복을 확인합니다.",
      route: "/audit",
      complete: audit.data?.passed ?? false,
      label: "Dataset Audit",
    },
    {
      title: "데이터 버전 확정",
      text: "검수 결과를 변경할 수 없는 Manifest로 보관합니다.",
      route: "/versions",
      complete: !!versions.data?.length,
      label: "Versions",
    },
    {
      title: "Crop 진단 · 학습 · 비교",
      text: "REF ROI를 포함한 버전에서 Group Split을 검증하고 160·256·320·Adaptive를 비교합니다.",
      route: "/training",
      complete: false,
      label: "Training",
    },
  ];
  return (
    <>
      <div className="workflow-banner">
        <GitBranch size={26} />
        <div>
          <h2>먼저 데이터 기반을 완성합니다.</h2>
          <p>
            데이터 준비 후 Training에서 실제 학습을 실행할 수 있습니다. 회사의
            CUDA Python 환경을 연결하고 먼저 crop 입력을 확인하세요.
          </p>
        </div>
        <span className="badge green">PHASE 01</span>
      </div>
      <div className="workflow-steps">
        {steps.map((s, i) => (
          <section className="workflow-step panel" key={s.title}>
            <span className={`step-circle ${s.complete ? "done" : ""}`}>
              {s.complete ? <Check size={18} /> : `0${i + 1}`}
            </span>
            <div>
              <h3>{s.title}</h3>
              <p>{s.text}</p>
            </div>
            <NavLink className="button secondary" to={s.route}>
              {s.label}
              <ArrowRight size={15} />
            </NavLink>
          </section>
        ))}
      </div>
      <div className="future-heading">
        <span>다음 개발 단계</span>
        <div />
      </div>
      <div className="future-grid">
        {[
          {
            title: "Probe · Final Test",
            detail: "독립 Test / 전이 성능 / 교차검증 집계",
            icon: <GitBranch />,
          },
          {
            title: "Multi-scale · Dense Pair",
            detail: "Local + Context / 기존 회사 코드 Adapter",
            icon: <Activity />,
          },
          {
            title: "Evaluation · Models",
            detail: "고급 실패 분석 / Model Registry / Champion",
            icon: <Target />,
          },
        ].map((s) => (
          <div className="future-card" key={s.title}>
            {s.icon}
            <h3>{s.title}</h3>
            <p>{s.detail}</p>
            <span>
              <LockKeyhole size={12} /> 후속 구현
            </span>
          </div>
        ))}
      </div>
    </>
  );
}
