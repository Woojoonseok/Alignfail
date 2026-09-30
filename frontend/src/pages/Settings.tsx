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
  deleteProject,
  importData,
}: {
  project: Project;
  refresh: () => Promise<void>;
  notify: Notify;
  deleteProject: () => void;
  importData: () => void;
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
  const normalize = useMutation({
    mutationFn: () =>
      api(`/projects/${project.id}/normalize-upload-roles`, "POST"),
    onSuccess: async () => {
      await refresh();
      notify(
        "기존 업로드를 Train=REF, Test=Query로 정리하고 저장된 십자선 중심 GT를 복구했습니다.",
      );
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
            등록한 데이터 폴더 · {project.data_directories.length}개
            <textarea
              readOnly
              value={
                project.data_directories.join("\n") ||
                "아직 가져온 폴더가 없습니다."
              }
            />
          </label>
          <button
            type="button"
            className="button secondary"
            onClick={importData}
          >
            Train 폴더 추가 · 재검색
          </button>
          <p className="field-hint">
            같은 프로젝트에 이미지 폴더를 계속 추가할 수 있습니다.
          </p>
          <button
            type="button"
            className="button secondary"
            disabled={normalize.isPending}
            onClick={() => normalize.mutate()}
          >
            기존 업로드를 Train=REF · Test=Query로 정리
          </button>
          <ErrorBox error={normalize.error} />
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
        <button className="button danger" onClick={deleteProject}>
          <Trash2 size={16} /> 프로젝트 삭제
        </button>
      </section>
    </>
  );
}
