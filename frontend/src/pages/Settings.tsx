import { useState } from "react";
import { useMutation } from "@tanstack/react-query";
import { Save, Trash2 } from "lucide-react";
import { api, type Project } from "../api";
import type { Notify } from "../types";
import { ErrorBox } from "../components/ui";

export function Settings({
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
