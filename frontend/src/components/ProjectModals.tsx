import { useState } from "react";
import { useMutation } from "@tanstack/react-query";
import { FolderInput, Loader2, Plus, RefreshCw } from "lucide-react";
import { api, type Project } from "../api";
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
