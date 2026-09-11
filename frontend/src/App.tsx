import { useEffect, useState } from "react";
import {
  NavLink,
  Route,
  Routes,
  useBlocker,
  useLocation,
} from "react-router-dom";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import {
  Activity,
  ArrowDownToLine,
  ArrowRight,
  Boxes,
  CheckCircle2,
  ChevronDown,
  ChevronRight,
  Crosshair,
  Files,
  FolderInput,
  GitBranch,
  Layers3,
  LayoutDashboard,
  Loader2,
  LockKeyhole,
  Plus,
  Settings2,
  ShieldCheck,
  Tags,
  X,
} from "lucide-react";
import { api, type Pair, type Project } from "./api";
import { ErrorBox, Empty, Modal } from "./components/ui";
import { ProjectModal, ImportModal } from "./components/ProjectModals";
import { PairExplorer } from "./pages/PairExplorer";
import { Overview } from "./pages/Overview";
import { AuditPage } from "./pages/AuditPage";
import { ClassesPage } from "./pages/ClassesPage";
import { ModelPage } from "./pages/ModelPage";
import { VersionsPage } from "./pages/VersionsPage";
import { Workflow } from "./pages/Workflow";
import { Settings } from "./pages/Settings";
import TrainingPage from "./TrainingPage";

const PAGES: Record<string, { title: string; description: string }> = {
  "/": {
    title: "Overview",
    description: "좋은 모델의 시작은, 신뢰할 수 있는 데이터입니다.",
  },
  "/pairs": {
    title: "Pair Explorer",
    description: "REF와 Query를 비교하고, 정확한 정답 좌표를 기록하세요.",
  },
  "/classes": {
    title: "Classes",
    description:
      "비슷한 Pair를 클래스로 모아 한눈에 보고, 썸네일을 골라 옮기세요.",
  },
  "/audit": {
    title: "Dataset Audit",
    description: "학습에 앞서 파일, Pair 구성, GT의 품질을 확인하세요.",
  },
  "/versions": {
    title: "Dataset Versions",
    description: "검수한 데이터를 고정하고, 변경 내용을 추적하세요.",
  },
  "/training": {
    title: "Training",
    description: "입력을 비교하고, 같은 조건에서 모델을 학습·평가하세요.",
  },
  "/model": {
    title: "Model",
    description:
      "Encoder 구조와 학습·추론 흐름, 학습된 체크포인트가 보는 것을 확인하세요.",
  },
  "/workflow": {
    title: "Workflow",
    description: "데이터 준비부터 모델 개선까지, 한 단계씩 진행합니다.",
  },
  "/settings": {
    title: "Project Settings",
    description: "프로젝트 정보와 데이터 저장 위치를 관리하세요.",
  },
};

export default function App() {
  const client = useQueryClient();
  const location = useLocation();
  const projectsQuery = useQuery({
    queryKey: ["projects"],
    queryFn: () => api<Project[]>("/projects"),
  });
  const [selected, setSelected] = useState(
    () => localStorage.getItem("alignfail.project") ?? "",
  );
  const projects = projectsQuery.data ?? [];
  const project = projects.find((p) => p.id === selected) ?? projects[0];
  const pairsQuery = useQuery({
    queryKey: ["pairs", project?.id],
    queryFn: () => api<Pair[]>(`/projects/${project!.id}/pairs`),
    enabled: !!project,
  });
  const [projectModal, setProjectModal] = useState(false);
  const [importModal, setImportModal] = useState(false);
  const [toast, setToast] = useState("");
  const [unsaved, setUnsaved] = useState(false);
  const blocker = useBlocker(unsaved);
  useEffect(() => {
    if (!toast) return;
    const id = setTimeout(() => setToast(""), 4500);
    return () => clearTimeout(id);
  }, [toast]);
  const refresh = async () => {
    await Promise.all([
      client.invalidateQueries({ queryKey: ["projects"] }),
      client.invalidateQueries({ queryKey: ["pairs"] }),
      client.invalidateQueries({ queryKey: ["versions"] }),
      client.invalidateQueries({ queryKey: ["history"] }),
    ]);
    client.removeQueries({ queryKey: ["audit"] });
  };
  const chooseProject = (id: string) => {
    setSelected(id);
    localStorage.setItem("alignfail.project", id);
  };
  const { title: page, description } =
    PAGES[location.pathname] ?? PAGES["/settings"];
  return (
    <div className="app-shell">
      <aside className="sidebar">
        <a href="/" className="brand">
          <div className="brand-mark">
            <Crosshair size={25} />
          </div>
          <div>
            AlignFail<span>MLOPS STUDIO</span>
          </div>
        </a>
        <div className="workspace-caption">
          WORKSPACE <span>LOCAL</span>
        </div>
        <div className="project-picker">
          <Layers3 size={18} />
          <select
            aria-label="프로젝트 선택"
            disabled={unsaved}
            title={
              unsaved
                ? "GT 변경을 저장하거나 되돌린 후 전환하세요."
                : "프로젝트 선택"
            }
            value={project?.id ?? ""}
            onChange={(e) => chooseProject(e.target.value)}
          >
            {!projects.length && <option value="">프로젝트 없음</option>}
            {projects.map((p) => (
              <option value={p.id} key={p.id}>
                {p.name}
              </option>
            ))}
          </select>
          <ChevronDown size={14} />
        </div>
        <button
          className="new-project"
          disabled={unsaved}
          onClick={() => setProjectModal(true)}
        >
          <Plus size={14} /> 새 프로젝트
        </button>
        <div className="nav-caption">DATA WORKSPACE</div>
        <nav>
          <NavLink to="/" end>
            <LayoutDashboard size={18} /> Overview
          </NavLink>
          <NavLink to="/pairs">
            <Crosshair size={18} /> Pair Explorer{" "}
            {project && <span className="nav-count">{project.pair_count}</span>}
          </NavLink>
          <NavLink to="/classes">
            <Tags size={18} /> Classes
          </NavLink>
          <NavLink to="/audit">
            <ShieldCheck size={18} /> Dataset Audit
          </NavLink>
          <NavLink to="/versions">
            <Files size={18} /> Versions
          </NavLink>
          <div className="nav-caption">DEVELOPMENT</div>
          <NavLink to="/training">
            <Activity size={18} /> Training
          </NavLink>
          <NavLink to="/model">
            <Boxes size={18} /> Model
          </NavLink>
          <NavLink to="/workflow">
            <GitBranch size={18} /> Step-by-step
          </NavLink>
          <NavLink to="/settings">
            <Settings2 size={18} /> Project Settings
          </NavLink>
        </nav>
        <div className="sidebar-bottom">
          <div className="local-status">
            <span
              className={
                projectsQuery.isError ? "status-dot offline" : "status-dot"
              }
            />
            {projectsQuery.isError
              ? "서버 연결 확인 필요"
              : projectsQuery.isPending
                ? "서버 연결 중"
                : "Local workspace"}
          </div>
          <p>데이터는 연결된 컴퓨터에 저장됩니다.</p>
          <div className="build-label">
            ALIGNFAIL STUDIO <span>v0.2.0</span>
          </div>
        </div>
      </aside>
      <div className="main-shell">
        <header className="topbar">
          <div className="breadcrumb">
            Workspace <ChevronRight size={13} />
            <span>{page}</span>
          </div>
          <div className="topbar-right">
            <span className="phase-tag">PHASE 01</span>
            <span>Dataset Studio</span>
            <div className="avatar">AF</div>
          </div>
        </header>
        <main
          className={
            location.pathname === "/pairs"
              ? "content explorer-content"
              : "content"
          }
        >
          <div className="page-heading">
            <div>
              <div className="eyebrow">
                {project?.name ?? "YOUR LOCAL MLOPS WORKSPACE"}
              </div>
              <h1>{page}</h1>
              <p>{description}</p>
            </div>
            {project && (
              <div className="heading-actions">
                <a
                  className="button secondary"
                  href={`/api/projects/${project.id}/annotations`}
                >
                  <ArrowDownToLine size={16} /> GT 내보내기
                </a>
                <button
                  className="button primary"
                  disabled={unsaved}
                  title={
                    unsaved
                      ? "GT 변경을 저장하거나 되돌린 후 재검색하세요."
                      : undefined
                  }
                  onClick={() => setImportModal(true)}
                >
                  <FolderInput size={17} />
                  {project.root_directory ? "폴더 재검색" : "데이터 가져오기"}
                </button>
              </div>
            )}
          </div>
          <ErrorBox error={projectsQuery.error || pairsQuery.error} />
          {projectsQuery.isPending ? (
            <div className="loading">
              <Loader2 className="spin" /> 워크스페이스를 불러오는 중…
            </div>
          ) : !project ? (
            <div className="welcome">
              <div className="welcome-art">
                <Crosshair size={80} strokeWidth={1} />
                <span className="orbit orbit-one" />
                <span className="orbit orbit-two" />
                <span className="art-label">REFERENCE ↔ QUERY</span>
              </div>
              <div className="eyebrow">START WITH YOUR DATA</div>
              <h2>첫 번째 데이터셋을 만나보세요.</h2>
              <p>
                Pair 폴더를 연결하고, 이미지를 검수하고,
                <br />
                학습에 사용할 정답 좌표를 직접 지정할 수 있습니다.
              </p>
              <button
                className="button primary"
                onClick={() => setProjectModal(true)}
              >
                <Plus size={17} /> 프로젝트 만들기
              </button>
              <div className="welcome-steps">
                <span>01 프로젝트 생성</span>
                <ArrowRight size={14} />
                <span>02 Dada 폴더 연결</span>
                <ArrowRight size={14} />
                <span>03 GT 검수</span>
              </div>
            </div>
          ) : pairsQuery.isPending ? (
            <div className="loading">
              <Loader2 className="spin" /> Pair를 불러오는 중…
            </div>
          ) : (
            <Routes>
              <Route
                path="/training"
                element={
                  <TrainingPage key={project.id} projectId={project.id} />
                }
              />
              <Route
                path="/model"
                element={<ModelPage key={project.id} projectId={project.id} />}
              />
              <Route
                path="/"
                element={
                  <Overview
                    project={project}
                    pairs={pairsQuery.data ?? []}
                    importData={() => setImportModal(true)}
                  />
                }
              />
              <Route
                path="/pairs"
                element={
                  <PairExplorer
                    key={project.id}
                    project={project}
                    pairs={pairsQuery.data ?? []}
                    refresh={refresh}
                    notify={setToast}
                    reportDirty={setUnsaved}
                  />
                }
              />
              <Route
                path="/classes"
                element={
                  <ClassesPage
                    key={project.id}
                    project={project}
                    pairs={pairsQuery.data ?? []}
                    refresh={refresh}
                    notify={setToast}
                  />
                }
              />
              <Route
                path="/audit"
                element={<AuditPage project={project} notify={setToast} />}
              />
              <Route
                path="/versions"
                element={<VersionsPage project={project} notify={setToast} />}
              />
              <Route
                path="/workflow"
                element={
                  <Workflow project={project} pairs={pairsQuery.data ?? []} />
                }
              />
              <Route
                path="/settings"
                element={
                  <Settings
                    key={project.id}
                    project={project}
                    refresh={refresh}
                    notify={setToast}
                    deleted={() => chooseProject("")}
                  />
                }
              />
              <Route
                path="*"
                element={
                  <Empty title="페이지를 찾을 수 없습니다.">
                    <NavLink to="/">Overview로 돌아가기</NavLink>
                  </Empty>
                }
              />
            </Routes>
          )}
          <footer className="footer">
            <span>
              <LockKeyhole size={12} /> Local-first · 원본 이미지를 외부로
              전송하지 않습니다.
            </span>
            <span>AlignFail / Dataset Studio</span>
          </footer>
        </main>
      </div>
      {projectModal && (
        <ProjectModal
          close={() => setProjectModal(false)}
          created={async (id) => {
            await refresh();
            chooseProject(id);
            setProjectModal(false);
            setToast("프로젝트가 생성되었습니다. Dada 폴더를 연결하세요.");
          }}
        />
      )}
      {importModal && project && (
        <ImportModal
          project={project}
          close={() => setImportModal(false)}
          imported={async (message) => {
            await refresh();
            setImportModal(false);
            setToast(message);
          }}
        />
      )}
      {toast && (
        <div className="toast" role="status">
          <CheckCircle2 size={18} />
          {toast}
          <button aria-label="알림 닫기" onClick={() => setToast("")}>
            <X size={15} />
          </button>
        </div>
      )}
      {blocker.state === "blocked" && (
        <Modal
          title="저장하지 않은 변경이 있습니다."
          close={() => blocker.reset()}
        >
          <div className="unsaved-dialog">
            <p>
              현재 Pair의 GT 또는 메타데이터를 변경했습니다. 저장하려면 편집을
              계속하세요.
            </p>
            <div className="modal-actions">
              <button
                className="button secondary"
                onClick={() => blocker.reset()}
              >
                편집 계속
              </button>
              <button
                className="button primary"
                onClick={() => {
                  setUnsaved(false);
                  blocker.proceed();
                }}
              >
                변경 버리고 이동
              </button>
            </div>
          </div>
        </Modal>
      )}
    </div>
  );
}
