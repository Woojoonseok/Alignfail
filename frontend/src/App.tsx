import { useEffect, useRef, useState, type ReactNode } from "react";
import {
  NavLink,
  Route,
  Routes,
  useBlocker,
  useLocation,
  useNavigate,
  useSearchParams,
} from "react-router-dom";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  Activity,
  ArrowDownToLine,
  ArrowRight,
  Check,
  CheckCircle2,
  ChevronDown,
  ChevronLeft,
  ChevronRight,
  Circle,
  Crosshair,
  Database,
  Eraser,
  FileJson,
  Files,
  FolderInput,
  GitBranch,
  History as HistoryIcon,
  Image as ImageIcon,
  Layers3,
  LayoutDashboard,
  Loader2,
  LockKeyhole,
  Maximize,
  Minus,
  Plus,
  RefreshCw,
  Save,
  Search,
  Settings2,
  ShieldCheck,
  SlidersHorizontal,
  Target,
  Trash2,
  TriangleAlert,
  Undo2,
  X,
} from "lucide-react";
import {
  api,
  dateLabel,
  draftOf,
  imageUrl,
  cleanImageUrl,
  versionName,
  type Audit,
  type History,
  type ImageRecord,
  type Pair,
  type PairDraft,
  type Project,
  type Version,
} from "./api";
import ImageCleaner from "./ImageCleaner";
import BatchTools from "./BatchTools";

type Notify = (message: string) => void;
type PageProps = {
  project: Project;
  pairs: Pair[];
  refresh: () => Promise<void>;
  notify: Notify;
};

function ErrorBox({ error }: { error: unknown }) {
  return error ? (
    <div className="error-box" role="alert">
      <TriangleAlert size={17} />
      <span>{error instanceof Error ? error.message : String(error)}</span>
    </div>
  ) : null;
}
function Empty({
  icon = <Database size={28} />,
  title,
  children,
}: {
  icon?: ReactNode;
  title: string;
  children: ReactNode;
}) {
  return (
    <div className="empty">
      <div className="empty-icon">{icon}</div>
      <h3>{title}</h3>
      <div>{children}</div>
    </div>
  );
}
function Modal({
  title,
  close,
  children,
}: {
  title: string;
  close: () => void;
  children: ReactNode;
}) {
  const ref = useRef<HTMLDialogElement>(null);
  useEffect(() => {
    ref.current?.showModal();
  }, []);
  return (
    <dialog
      ref={ref}
      aria-label={title}
      onCancel={(event) => {
        event.preventDefault();
        close();
      }}
      className="modal"
    >
      <div className="modal-title">
        <h2>{title}</h2>
        <button className="icon-button" aria-label="닫기" onClick={close}>
          <X size={20} />
        </button>
      </div>
      {children}
    </dialog>
  );
}
function Status({ pair }: { pair: Pair }) {
  return !pair.enabled ? (
    <span className="badge muted">제외됨</span>
  ) : pair.import_issues.length ? (
    <span className="badge red">파일 확인</span>
  ) : pair.gt_x === null ? (
    <span className="badge amber">
      <Circle size={10} /> GT 미지정
    </span>
  ) : (
    <span className="badge green">
      <Check size={12} /> GT 완료
    </span>
  );
}
function Thumb({ image }: { image: ImageRecord | null }) {
  const [failed, setFailed] = useState(false);
  useEffect(() => setFailed(false), [image?.file_hash]);
  return (
    <div className="thumb">
      {image && !image.error && !failed ? (
        <img
          src={imageUrl(image, true)}
          alt={image.file_name}
          loading="lazy"
          onError={() => setFailed(true)}
        />
      ) : (
        <ImageIcon size={16} />
      )}
    </div>
  );
}

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
  const page =
    location.pathname === "/"
      ? "Overview"
      : location.pathname === "/pairs"
        ? "Pair Explorer"
        : location.pathname === "/audit"
          ? "Dataset Audit"
          : location.pathname === "/versions"
            ? "Dataset Versions"
            : location.pathname === "/workflow"
              ? "Workflow"
              : "Project Settings";
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
          <NavLink to="/audit">
            <ShieldCheck size={18} /> Dataset Audit
          </NavLink>
          <NavLink to="/versions">
            <Files size={18} /> Versions
          </NavLink>
          <div className="nav-caption">DEVELOPMENT</div>
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
            DATASET STUDIO <span>v0.1</span>
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
              <p>
                {
                  (
                    {
                      Overview:
                        "좋은 모델의 시작은, 신뢰할 수 있는 데이터입니다.",
                      "Pair Explorer":
                        "REF와 Query를 비교하고, 정확한 정답 좌표를 기록하세요.",
                      "Dataset Audit":
                        "학습에 앞서 파일, Pair 구성, GT의 품질을 확인하세요.",
                      "Dataset Versions":
                        "검수한 데이터를 고정하고, 변경 내용을 추적하세요.",
                      Workflow:
                        "데이터 준비부터 모델 개선까지, 한 단계씩 진행합니다.",
                      "Project Settings":
                        "프로젝트 정보와 데이터 저장 위치를 관리하세요.",
                    } as Record<string, string>
                  )[page]
                }
              </p>
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

function ProjectModal({
  close,
  created,
}: {
  close: () => void;
  created: (id: string) => void;
}) {
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const mutation = useMutation({
    mutationFn: () => api<Project>("/projects", "POST", { name, description }),
    onSuccess: (p) => created(p.id),
  });
  return (
    <Modal title="새 프로젝트" close={close}>
      <form
        onSubmit={(e) => {
          e.preventDefault();
          mutation.mutate();
        }}
      >
        <label>
          프로젝트 이름
          <input
            autoFocus
            required
            maxLength={120}
            placeholder="예: AlignFail Localization"
            value={name}
            onChange={(e) => setName(e.target.value)}
          />
        </label>
        <label>
          설명
          <textarea
            placeholder="데이터셋과 개발 목적을 간단히 기록하세요."
            value={description}
            onChange={(e) => setDescription(e.target.value)}
          />
        </label>
        <ErrorBox error={mutation.error} />
        <div className="modal-actions">
          <button type="button" className="button secondary" onClick={close}>
            취소
          </button>
          <button
            disabled={mutation.isPending || !name.trim()}
            className="button primary"
          >
            {mutation.isPending ? (
              <Loader2 className="spin" size={16} />
            ) : (
              <Plus size={16} />
            )}{" "}
            프로젝트 생성
          </button>
        </div>
      </form>
    </Modal>
  );
}
function ImportModal({
  project,
  close,
  imported,
}: {
  project: Project;
  close: () => void;
  imported: (message: string) => Promise<void>;
}) {
  const [path, setPath] = useState(project.root_directory);
  const mutation = useMutation({
    mutationFn: () =>
      api<{ new_pairs: number; updated_pairs: number; invalid_pairs: number }>(
        `/projects/${project.id}/import`,
        "POST",
        { root_directory: path },
      ),
    onSuccess: (r) =>
      imported(
        `새 Pair ${r.new_pairs}개 · 재검색 ${r.updated_pairs}개 · 파일 확인 필요 ${r.invalid_pairs}개`,
      ),
  });
  return (
    <Modal
      title={project.root_directory ? "데이터 폴더 재검색" : "Dada 폴더 연결"}
      close={() => {
        if (!mutation.isPending) close();
      }}
    >
      <form
        onSubmit={(e) => {
          e.preventDefault();
          mutation.mutate();
        }}
      >
        <p className="modal-description">
          각 하위 폴더를 하나의 Pair로 등록합니다. 이미지 파일명에 REF가
          포함되면 Reference, 나머지는 Query입니다.
        </p>
        <div className="folder-example">
          <FolderInput size={18} />
          <code>
            Dada / pair_001 / <strong>sample_REF.bmp</strong>
            <br />
            <span>　　　　　　　　sample.bmp</span>
          </code>
        </div>
        <label>
          서버에서 접근 가능한 폴더 경로
          <input
            autoFocus
            required
            value={path}
            readOnly={!!project.root_directory}
            placeholder="/mnt/d/Dada"
            onChange={(e) => setPath(e.target.value)}
          />
        </label>
        <p className="field-hint">
          WSL 예: D:\Dada → /mnt/d/Dada
          <br />
          PNG · JPG · BMP · TIFF · WebP 지원. 원본 이미지는 복사하지 않습니다.
        </p>
        {project.root_directory && (
          <div className="notice">
            <RefreshCw size={16} />
            <span>
              변경된 Query의 GT는 초기화하고 이전 좌표는 이력에 보관합니다.
            </span>
          </div>
        )}
        <ErrorBox error={mutation.error} />
        <div className="modal-actions">
          <button
            type="button"
            className="button secondary"
            disabled={mutation.isPending}
            onClick={close}
          >
            취소
          </button>
          <button
            className="button primary"
            disabled={mutation.isPending || !path.trim()}
          >
            {mutation.isPending ? (
              <Loader2 size={16} className="spin" />
            ) : (
              <FolderInput size={16} />
            )}
            {mutation.isPending ? "파일 검사 및 등록 중…" : "폴더 검사 · 등록"}
          </button>
        </div>
      </form>
    </Modal>
  );
}

function Overview({
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

function PairExplorer({
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
  useEffect(() => {
    const handler = (e: BeforeUnloadEvent) => {
      if (dirty) {
        e.preventDefault();
        e.returnValue = "";
      }
    };
    window.addEventListener("beforeunload", handler);
    return () => window.removeEventListener("beforeunload", handler);
  }, [dirty]);
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
      {batchOpen && <BatchTools projectId={project.id} pairs={pairs} refresh={refresh} close={() => setBatchOpen(false)} onBusy={setBatchBusy} />}
      <aside className="pair-list panel">
        <div className="pair-list-header">
          <strong>
            Pairs <span>{filtered.length}</span>
          </strong>
          <SlidersHorizontal size={16} />
        </div>
        <button className="button secondary batch-open" disabled={dirty} onClick={() => setBatchOpen(true)}>일괄 제거 · 그룹화</button>
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

function ImageViewer({
  image,
  title,
  gt,
  onPick,
  zoom,
  setZoom,
  showGT,
  onClean,
}: {
  image: ImageRecord | null;
  title: string;
  gt?: { x: number | null; y: number | null };
  onPick?: (x: number, y: number) => void;
  zoom: number;
  setZoom: (n: number) => void;
  showGT: boolean;
  onClean?: () => void;
}) {
  const [failed, setFailed] = useState(false);
  const [hover, setHover] = useState<{ x: number; y: number } | null>(null);
  const [loaded, setLoaded] = useState(false);
  const [cleanView, setCleanView] = useState(
    !!image?.cleanup && !image.cleanup.stale,
  );
  useEffect(() => {
    setFailed(false);
    setLoaded(false);
  }, [cleanView]);
  const markerSize = image?.width ? Math.max(5, image.width / 65 / zoom) : 6;
  return (
    <section className="viewer">
      <div className="viewer-heading">
        <span>
          <span className={`viewer-role ${onPick ? "query" : ""}`}>
            {title}
          </span>
          {onPick ? "정답 위치 지정" : "기준 이미지"}
        </span>
        <span>{image?.width && `${image.width} × ${image.height}`}</span>
      </div>
      <div className="viewer-clean-controls">
        <button
          disabled={!onClean || !image || !!image.error}
          onClick={onClean}
          aria-label={`${title} 흰 표시 제거`}
        >
          <Eraser size={13} /> 흰 표시 제거
        </button>
        {image?.cleanup && !image.cleanup.stale && (
          <button
            className={`clean-toggle ${cleanView ? "active" : ""}`}
            onClick={() => setCleanView((v) => !v)}
            aria-label={`${title} 원본 Clean 전환`}
          >
            {cleanView ? "Clean · 원본 보기" : "원본 · Clean 보기"}
          </button>
        )}
        {image?.cleanup?.stale && <span>제거 결과 재생성 필요</span>}
      </div>
      <div className="image-viewport">
        {!image || image.error || failed ? (
          <div className="viewer-empty">
            <ImageIcon size={30} />
            <strong>
              {image?.error ||
                (failed
                  ? "이미지를 불러올 수 없습니다."
                  : `${title} 이미지가 없습니다.`)}
            </strong>
            <span>파일과 폴더 재검색 결과를 확인하세요.</span>
          </div>
        ) : (
          <div className="image-stage" style={{ width: `${zoom * 100}%` }}>
            <img
              src={
                cleanView && image.cleanup
                  ? cleanImageUrl(image)
                  : imageUrl(image)
              }
              alt={`${title}: ${image.file_name}`}
              draggable={false}
              onLoad={() => setLoaded(true)}
              onError={() => setFailed(true)}
            />
            {loaded && image.width && image.height && (
              <svg
                aria-label={
                  onPick ? "Query GT 지정 영역" : "Reference 이미지 영역"
                }
                className={onPick ? "image-overlay editable" : "image-overlay"}
                viewBox={`0 0 ${image.width} ${image.height}`}
                onMouseMove={(e) => {
                  const rect = e.currentTarget.getBoundingClientRect();
                  setHover({
                    x: Math.max(
                      0,
                      Math.min(
                        image.width! - 1,
                        Math.round(
                          ((e.clientX - rect.left) / rect.width) * image.width!,
                        ),
                      ),
                    ),
                    y: Math.max(
                      0,
                      Math.min(
                        image.height! - 1,
                        Math.round(
                          ((e.clientY - rect.top) / rect.height) *
                            image.height!,
                        ),
                      ),
                    ),
                  });
                }}
                onMouseLeave={() => setHover(null)}
                onClick={(e) => {
                  if (!onPick) return;
                  const rect = e.currentTarget.getBoundingClientRect();
                  const x = Math.max(
                    0,
                    Math.min(
                      image.width! - 1,
                      Math.round(
                        ((e.clientX - rect.left) / rect.width) * image.width!,
                      ),
                    ),
                  );
                  const y = Math.max(
                    0,
                    Math.min(
                      image.height! - 1,
                      Math.round(
                        ((e.clientY - rect.top) / rect.height) * image.height!,
                      ),
                    ),
                  );
                  onPick(x, y);
                }}
              >
                {showGT &&
                  gt?.x !== null &&
                  gt?.x !== undefined &&
                  gt.y !== null && (
                    <g
                      transform={`translate(${gt.x},${gt.y})`}
                      pointerEvents="none"
                    >
                      <circle
                        r={markerSize}
                        fill="rgba(255,216,78,.14)"
                        stroke="#ffdf5c"
                        strokeWidth={2}
                        vectorEffect="non-scaling-stroke"
                      />
                      <circle r={markerSize / 4} fill="#ffdf5c" />
                      <path
                        d={`M ${-markerSize * 1.65} 0 H ${-markerSize * 0.65} M ${markerSize * 0.65} 0 H ${markerSize * 1.65} M 0 ${-markerSize * 1.65} V ${-markerSize * 0.65} M 0 ${markerSize * 0.65} V ${markerSize * 1.65}`}
                        stroke="#ffdf5c"
                        strokeWidth={1.5}
                        vectorEffect="non-scaling-stroke"
                      />
                    </g>
                  )}
              </svg>
            )}
          </div>
        )}
      </div>
      <div className="viewer-toolbar">
        <span className="viewer-filename" title={image?.file_name}>
          {hover
            ? `X ${hover.x} · Y ${hover.y}`
            : (image?.file_name ?? "No image")}
        </span>
        <div>
          <button
            className="icon-button"
            disabled={zoom <= 1}
            aria-label={`${title} 축소`}
            onClick={() => setZoom(Math.max(1, zoom - 0.5))}
          >
            <Minus size={14} />
          </button>
          <span className="zoom-label">
            {zoom === 1 ? "Fit" : `${Math.round(zoom * 100)}%`}
          </span>
          <button
            className="icon-button"
            disabled={zoom >= 6}
            aria-label={`${title} 확대`}
            onClick={() => setZoom(Math.min(6, zoom + 0.5))}
          >
            <Plus size={14} />
          </button>
          <button
            className="icon-button"
            aria-label={`${title} 화면 맞춤`}
            onClick={() => setZoom(1)}
          >
            <Maximize size={14} />
          </button>
        </div>
      </div>
    </section>
  );
}

function PairEditor({
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
  const dirty = JSON.stringify(draft) !== JSON.stringify(draftOf(pair));
  useEffect(() => onDirty(dirty), [dirty, onDirty]);
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
      <div className="pair-detail-heading">
        <div>
          <h2>{pair.folder}</h2>
          <Status pair={pair} />
          {dirty && <span className="unsaved">저장하지 않은 변경</span>}
        </div>
        <div className="pair-navigation">
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
                <label>클래스<input value={draft.class_label} onChange={(e) => field("class_label", e.target.value)} maxLength={200} placeholder="예: connector / pad" /></label>
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
                ? "변경 사항을 저장하면 GT 이력에 기록됩니다."
                : "저장된 최신 데이터입니다."}
            </span>
            <button
              type="button"
              className="button secondary"
              disabled={!dirty}
              onClick={() => setDraft(draftOf(pair))}
            >
              <Undo2 size={15} /> 되돌리기
            </button>
            <button
              className="button primary"
              disabled={!dirty || save.isPending}
            >
              {save.isPending ? (
                <Loader2 className="spin" size={16} />
              ) : (
                <Save size={16} />
              )}{" "}
              변경 저장
            </button>
          </div>
        </fieldset>
      </form>
    </>
  );
}

function AuditPage({ project }: { project: Project; notify: Notify }) {
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

function VersionsPage({
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

function Workflow({ project, pairs }: { project: Project; pairs: Pair[] }) {
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
  ];
  return (
    <>
      <div className="workflow-banner">
        <GitBranch size={26} />
        <div>
          <h2>먼저 데이터 기반을 완성합니다.</h2>
          <p>
            현재 릴리스는 데이터 준비 4단계를 지원합니다. 실제 학습 실행과 GPU
            연결은 다음 구현 단계입니다.
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
            title: "Split · Leakage",
            detail: "데이터 그룹 분리 / Probe / Group CV",
            icon: <GitBranch />,
          },
          {
            title: "Training · Experiments",
            detail: "기존 코드 연결 / Stage 1·2 / GPU Queue",
            icon: <Activity />,
          },
          {
            title: "Evaluation · Models",
            detail: "정밀도 비교 / 실패 분석 / Champion",
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

function Settings({
  project,
  refresh,
  notify,
  deleted,
}: {
  project: Project;
  refresh: () => Promise<void>;
  notify: Notify;
  deleted: () => void;
}) {
  const [name, setName] = useState(project.name);
  const [description, setDescription] = useState(project.description);
  const update = useMutation({
    mutationFn: () =>
      api(`/projects/${project.id}`, "PATCH", { name, description }),
    onSuccess: async () => {
      await refresh();
      notify("프로젝트 정보를 저장했습니다.");
    },
  });
  const remove = useMutation({
    mutationFn: () => api(`/projects/${project.id}`, "DELETE"),
    onSuccess: async () => {
      await refresh();
      deleted();
      notify("프로젝트 등록 정보를 삭제했습니다. 원본 이미지는 유지됩니다.");
    },
  });
  return (
    <>
      <section className="panel settings-panel">
        <h2>프로젝트 정보</h2>
        <form
          onSubmit={(e) => {
            e.preventDefault();
            update.mutate();
          }}
        >
          <label>
            이름
            <input
              required
              value={name}
              maxLength={120}
              onChange={(e) => setName(e.target.value)}
            />
          </label>
          <label>
            설명
            <textarea
              value={description}
              onChange={(e) => setDescription(e.target.value)}
            />
          </label>
          <label>
            데이터 경로
            <input readOnly value={project.root_directory || "연결되지 않음"} />
          </label>
          <p className="field-hint">
            다른 데이터 경로는 새 프로젝트로 연결하세요.
          </p>
          <ErrorBox error={update.error} />
          <button className="button primary" disabled={update.isPending}>
            <Save size={16} /> 정보 저장
          </button>
        </form>
      </section>
      <section className="panel settings-panel danger-zone">
        <h2>프로젝트 등록 삭제</h2>
        <p>
          이 프로젝트의 Pair, GT 이력과 데이터 버전을 삭제합니다. 원본 이미지
          파일은 삭제하지 않습니다.
          <br />
          필요한 GT와 Manifest를 먼저 내보내세요.
        </p>
        <ErrorBox error={remove.error} />
        <button
          className="button danger"
          disabled={remove.isPending}
          onClick={() => {
            if (
              window.confirm(
                `‘${project.name}’의 모든 등록 정보, GT 이력과 버전을 삭제할까요? 이 작업은 되돌릴 수 없습니다. 원본 이미지 파일은 유지됩니다.`,
              )
            )
              remove.mutate();
          }}
        >
          <Trash2 size={16} /> 프로젝트 삭제
        </button>
      </section>
    </>
  );
}
