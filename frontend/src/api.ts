export interface Project {
  id: string;
  name: string;
  description: string;
  root_directory: string;
  created_at: string;
  pair_count: number;
  enabled_count: number;
  annotated_count: number;
  issue_count: number;
  group_count: number;
}
export interface ImageRecord {
  id: string;
  file_name: string;
  file_path: string;
  role: string;
  file_hash: string | null;
  width: number | null;
  height: number | null;
  mode: string | null;
  error: string | null;
  cleanup?: Cleanup | null;
}
export interface PixelRect {
  x0: number;
  y0: number;
  x1: number;
  y1: number;
}
export interface CleanupConfig {
  source_hash: string;
  box: PixelRect | null;
  cross: PixelRect | null;
  padding: number;
  radius: number;
  cross_noise: boolean;
}
export interface Cleanup {
  id: string;
  source_hash: string;
  clean_hash: string;
  stale: boolean;
  config: { parameters: CleanupConfig };
}
export interface Pair {
  id: string;
  project_id: string;
  folder: string;
  gt_x: number | null;
  gt_y: number | null;
  gt_source: string;
  group_key: string;
  class_label: string;
  pattern_type: "A" | "B" | "unknown";
  reference_annotation: {
    id: string;
    image_hash: string;
    box: number[];
    center: number[];
    source: string;
    revision: number;
  } | null;
  tier: string;
  notes: string;
  enabled: boolean;
  exclude_reason: string;
  import_issues: string[];
  revision: number;
  updated_at: string;
  reference: ImageRecord | null;
  query: ImageRecord | null;
}
export type PairDraft = Pick<
  Pair,
  | "revision"
  | "gt_x"
  | "gt_y"
  | "group_key"
  | "class_label"
  | "pattern_type"
  | "tier"
  | "notes"
  | "enabled"
  | "exclude_reason"
>;
export interface Audit {
  checked_at: string;
  pair_count: number;
  enabled_count: number;
  errors: number;
  warnings: number;
  passed: boolean;
  scope: string;
  issues: {
    pair_id: string;
    folder: string;
    code: string;
    message: string;
    severity: string;
  }[];
  duplicates: {
    file_hash: string;
    occurrences: {
      pair_id: string;
      folder: string;
      role: string;
      group_key: string;
    }[];
  }[];
}
export interface Version {
  id: string;
  number: number;
  description: string;
  created_at: string;
  pair_count: number;
  enabled_count: number;
}
export interface History {
  id: string;
  before: { x: number | null; y: number | null };
  after: { x: number | null; y: number | null };
  reason: string;
  created_at: string;
}

export async function api<T>(
  path: string,
  method = "GET",
  data?: unknown,
): Promise<T> {
  let response: Response;
  try {
    response = await fetch(`/api${path}`, {
      method,
      headers: data === undefined ? {} : { "Content-Type": "application/json" },
      body: data === undefined ? undefined : JSON.stringify(data),
    });
  } catch {
    throw new Error(
      "서버에 연결할 수 없습니다. Backend 실행 상태를 확인하세요.",
    );
  }
  if (!response.ok) {
    const body = await response.json().catch(() => ({}));
    const detail = body.detail;
    throw new Error(
      typeof detail === "string"
        ? detail
        : Array.isArray(detail)
          ? detail.map((e: { msg: string }) => e.msg).join(" · ")
          : `요청 실패 (${response.status})`,
    );
  }
  return response.status === 204 ? (undefined as T) : response.json();
}
export const imageUrl = (image: ImageRecord, thumbnail = false) =>
  `/api/images/${image.id}?${thumbnail ? "size=160&" : ""}v=${image.file_hash ?? ""}`;
export const cleanImageUrl = (image: ImageRecord) =>
  `/api/cleanups/${image.cleanup!.id}/image`;
export const versionName = (n: number) => `v${String(n).padStart(3, "0")}`;
export const dateLabel = (date: string) =>
  new Date(date).toLocaleString("ko-KR", {
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    hour12: false,
  });
export const draftOf = (pair: Pair): PairDraft => ({
  revision: pair.revision,
  gt_x: pair.gt_x,
  gt_y: pair.gt_y,
  group_key: pair.group_key,
  class_label: pair.class_label,
  pattern_type: pair.pattern_type,
  tier: pair.tier,
  notes: pair.notes,
  enabled: pair.enabled,
  exclude_reason: pair.exclude_reason,
});
