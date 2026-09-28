import { useRef, useState } from "react";
import { useMutation } from "@tanstack/react-query";
import { FolderInput, Loader2, Plus, RefreshCw } from "lucide-react";
import { api, uploadFolder, type ImportResult, type Project } from "../api";
import { ErrorBox, Modal } from "../components/ui";

export function ProjectModal({
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

export function ImportModal({
  project,
  close,
  imported,
}: {
  project: Project;
  close: () => void;
  imported: (message: string) => Promise<void>;
}) {
  const [mode, setMode] = useState<"upload" | "server">("upload");
  const [path, setPath] = useState("");
  const [files, setFiles] = useState<File[]>([]);
  const [skipped, setSkipped] = useState(0);
  const [progress, setProgress] = useState(0);
  const [selectionError, setSelectionError] = useState("");
  const [groupFoldersAsClasses, setGroupFoldersAsClasses] = useState(true);
  const picker = useRef<HTMLInputElement>(null);
  const directories = project.data_directories;
  const mutation = useMutation({
    mutationFn: () => {
      setProgress(0);
      return mode === "upload"
        ? uploadFolder(project.id, files, setProgress, groupFoldersAsClasses)
        : api<ImportResult>(`/projects/${project.id}/import`, "POST", {
            root_directory: path,
            group_folders_as_classes: groupFoldersAsClasses,
          });
    },
    onSuccess: (r) =>
      imported(
        `이미지 ${r.images}장 · 새 항목 ${r.new_pairs}개 · 재검색 ${r.updated_pairs}개 · 파일 확인 필요 ${r.invalid_pairs}개`,
      ),
  });
  const folderName = files[0]?.webkitRelativePath.split("/")[0];
  const totalBytes = files.reduce((sum, file) => sum + file.size, 0);
  return (
    <Modal
      title="이미지 폴더 가져오기"
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
        <div className="import-modes">
          <button
            type="button"
            className={`button ${mode === "upload" ? "primary" : "secondary"}`}
            disabled={mutation.isPending}
            onClick={() => {
              setMode("upload");
              mutation.reset();
            }}
          >
            내 PC 폴더 업로드
          </button>
          <button
            type="button"
            className={`button ${mode === "server" ? "primary" : "secondary"}`}
            disabled={mutation.isPending}
            onClick={() => {
              setMode("server");
              mutation.reset();
            }}
          >
            서버 경로 연결 · 재검색
          </button>
        </div>
        <p className="modal-description">
          이미지 폴더를 선택하면 하위 폴더까지 함께 가져옵니다. 일반 이미지는
          각각 Query로, REF가 있는 폴더는 REF/Query Pair로 등록합니다. REF는
          나중에 Classes에서 연결할 수 있습니다.
        </p>
        {mode === "upload" ? (
          <>
            <input
              ref={picker}
              type="file"
              hidden
              multiple
              {...{ webkitdirectory: "", directory: "" }}
              aria-label="업로드할 이미지 폴더 선택"
              disabled={mutation.isPending}
              onChange={(e) => {
                const all = Array.from(e.target.files ?? []);
                const images = all.filter((file) =>
                  /\.(png|jpe?g|bmp|tiff?|webp)$/i.test(file.name),
                );
                setFiles(images);
                setSkipped(all.length - images.length);
                setSelectionError(
                  !images.length
                    ? "선택한 폴더에 지원하는 이미지가 없습니다."
                    : images.length > 10000
                      ? "한 번에 이미지 10,000장까지 업로드할 수 있습니다."
                      : images.some((file) => file.size > 256 * 1024 ** 2) ||
                          images.reduce((sum, file) => sum + file.size, 0) >
                            4 * 1024 ** 3
                        ? "이미지당 256 MB, 폴더당 4 GB까지 업로드할 수 있습니다."
                        : "",
                );
                mutation.reset();
                e.target.value = "";
              }}
            />
            <button
              type="button"
              className="folder-upload-picker"
              disabled={mutation.isPending}
              onClick={() => picker.current?.click()}
            >
              <FolderInput size={32} />
              <strong>{folderName || "내 PC에서 폴더 선택"}</strong>
              <span>
                {files.length
                  ? `이미지 ${files.length}장 · ${(totalBytes / 1024 / 1024).toFixed(1)} MB · 클릭하여 다시 선택`
                  : "PNG · JPG · BMP · TIFF · WebP"}
              </span>
            </button>
            {skipped > 0 && (
              <p className="field-hint">
                이미지가 아닌 파일 {skipped}개는 제외했습니다.
              </p>
            )}
            <p className="field-hint">
              이미지를 이 Studio 서버의 저장 공간에 복사합니다. 기존 데이터와
              GT는 유지하며, 같은 폴더를 다시 업로드해도 별도 데이터로
              추가합니다.
            </p>
            {mutation.isPending && (
              <div className="upload-progress" role="status">
                <progress
                  max={100}
                  value={progress}
                  aria-label="폴더 업로드 진행률"
                />
                <span>
                  {progress < 100
                    ? `이미지 업로드 중… ${progress}%`
                    : "업로드 완료 · 이미지 검사 및 등록 중…"}
                </span>
              </div>
            )}
            <ErrorBox error={selectionError} />
          </>
        ) : (
          <>
            <label>
              서버에서 접근 가능한 폴더 경로
              <input
                required
                value={path}
                disabled={mutation.isPending}
                placeholder="/mnt/d/images"
                onChange={(e) => setPath(e.target.value)}
              />
            </label>
            <p className="field-hint">
              WSL 예: D:\Dada → /mnt/d/Dada. 경로 연결은 원본을 복사하지
              않습니다.
            </p>
            {!!directories.length && (
              <label>
                등록한 폴더 재검색
                <select
                  value={directories.includes(path) ? path : ""}
                  disabled={mutation.isPending}
                  onChange={(e) => setPath(e.target.value)}
                >
                  <option value="">폴더 선택…</option>
                  {directories.map((directory) => (
                    <option key={directory} value={directory}>
                      {directory}
                    </option>
                  ))}
                </select>
              </label>
            )}
            {directories.includes(path) && (
              <div className="notice">
                <RefreshCw size={16} />
                <span>
                  이 폴더만 재검색합니다. 변경된 Query의 GT는 초기화하고 이전
                  좌표는 이력에 보관합니다.
                </span>
              </div>
            )}
          </>
        )}
        <label className="import-class-option">
          <input
            type="checkbox"
            checked={groupFoldersAsClasses}
            disabled={mutation.isPending}
            onChange={(e) => setGroupFoldersAsClasses(e.target.checked)}
          />
          Group / Group_ 폴더를 하나의 클래스로 자동 지정
        </label>
        <p className="field-hint">
          예: Group/폴더1, 폴더2, 폴더3 → 모두 Group 클래스.
          하위 REF/Query 쌍과 일반 이미지에 함께 적용하며, 이미 지정한 클래스는 유지합니다.
        </p>
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
            disabled={
              mutation.isPending ||
              (mode === "upload"
                ? !files.length || !!selectionError
                : !path.trim())
            }
          >
            {mutation.isPending ? (
              <Loader2 size={16} className="spin" />
            ) : (
              <FolderInput size={16} />
            )}
            {mutation.isPending
              ? "가져오는 중…"
              : mode === "upload"
                ? "선택한 폴더 업로드"
                : "폴더 검사 · 등록"}
          </button>
        </div>
      </form>
    </Modal>
  );
}
