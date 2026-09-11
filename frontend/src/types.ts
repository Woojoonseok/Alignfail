import type { Pair, Project } from "./api";

export type Notify = (message: string) => void;
export type PageProps = {
  project: Project;
  pairs: Pair[];
  refresh: () => Promise<void>;
  notify: Notify;
};
