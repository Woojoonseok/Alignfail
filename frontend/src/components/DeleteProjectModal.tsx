import { useMutation } from "@tanstack/react-query";
import { Loader2, Trash2 } from "lucide-react";
import { api, type Project } from "../api";
import { ErrorBox, Modal } from "./ui";

export function DeleteProjectModal({
  project,
  close,
  deleted,
}: {
  project: Project;
  close: () => void;
  deleted: () => void;
}) {
  const remove = useMutation({
    mutationFn: () => api(`/projects/${project.id}`, "DELETE"),
    onSuccess: deleted,
  });
  return (
    <Modal
      title="프로젝트 삭제"
      close={() => {
        if (!remove.isPending) close();
      }}
    >
      <form
        onSubmit={(event) => {
          event.preventDefault();
          if (!remove.isPending) remove.mutate();
        }}
      >
        <p>
          <strong>{project.name}</strong> 프로젝트를 삭제할까요?
        </p>
        <p>
          Pair 등록 {project.pair_count}개, 클래스, GT·ROI 이력, Clean 등록
          정보와 데이터 버전이 삭제됩니다. 등록 정보는 복구할 수 없습니다.
        </p>
        <p>
          원본 이미지, 업로드한 파일, 저장된 Clean 파일과 학습 결과 파일은
          디스크에 유지됩니다. 필요한 GT와 Manifest는 삭제 전에 내보내세요.
        </p>
        <ErrorBox error={remove.error} />
        <div className="modal-actions">
          <button
            type="button"
            className="button secondary"
            disabled={remove.isPending}
            onClick={close}
          >
            취소
          </button>
          <button
            className="button danger"
            disabled={remove.isPending}
            type="submit"
          >
            {remove.isPending ? (
              <Loader2 className="spin" size={16} />
            ) : (
              <Trash2 size={16} />
            )}
            {remove.isPending ? "삭제 중…" : "프로젝트 삭제 확인"}
          </button>
        </div>
      </form>
    </Modal>
  );
}
