import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { apiFetch } from "../net/api";

export interface Project {
  id: string;
  name: string;
  root_path: string | null;
  state: string;
  is_running: boolean;
  progress_pct: number;
  execution_kind: string;
  created_at: string;
  copied_from: string | null;
  /** Non-null = starred. Server sorts starred rows to the head of page 1
   *  (newest favorite first). */
  favorited_at: string | null;
  /** Timestamp of the last unstar event. Used by the server to push a
   *  just-unstarred project to the head of the non-favorites tier — same
   *  position a freshly created project would land in. */
  unfavorited_at: string | null;
  task_count?: number;
  done_count?: number;
  tasks?: Task[];
}

export interface Task {
  id: string;
  project_id: string;
  title: string;
  detail: string;
  agent_id: string | null;
  kind: string;
  output_schema: Record<string, unknown>;
  status: string;
  deps: string[];
  /** Canvas position. NULL = never been dragged; client falls back to the
   *  wave-layout coordinates for the initial render. */
  position_x?: number | null;
  position_y?: number | null;
  /** Free-text failure message (full exception / first validation error)
   *  persisted on the task row so the canvas warning badge can show a
   *  concrete reason on hover. Null for non-failed tasks. */
  last_error?: string | null;
  /** Coarse failure category, derived server-side. Values used by the
   *  hover tooltip to render a one-line Chinese hint:
   *    quota | auth | mcp | network | validation | stalled | tool | unknown */
  last_error_kind?: string | null;
  /** PM v4: which kind of performer this task is bound to. When 'crew',
   *  the canvas swaps in CanvasCrewNode and the run path takes the
   *  Crew walker (workflow_svc._run_crew). null/undefined means legacy
   *  v3 single-agent task (uses agent_id). */
  performer_kind?: "agent" | "crew" | null;
  /** ID of the bound performer (agent_id or crew_id depending on
   *  performer_kind). Mirrors agent_id when performer_kind='agent'. */
  performer_id?: string | null;
  /** PM v5 named-symbol contract. JSON string (backend stores as TEXT);
   *  IO viewer parses on demand for the 代码契约 tab. Null/undefined =
   *  non-code task (Art / Audio / pure prefab). */
  code_contract?: string | null;
}

/** PM v5: shape of the parsed code_contract column. The DB stores the
 *  JSON serialization; consumers (IoViewerDrawer / future contract
 *  inspector) parse on demand. Keep in sync with backend
 *  agents/sub_agents/_planner_models.CodeContract. */
export interface CodeContract {
  namespace?: string | null;
  files: Array<{
    path: string;
    exports: Array<{
      kind: string;  // class | interface | struct | enum | method | event | field | property
      signature: string;
    }>;
  }>;
  imports?: Array<{
    from_task_index: number;
    uses: string[];
  }>;
}

export interface ProjectPage {
  items: Project[];
  total: number;
  page: number;
  size: number;
}

export function useProjects(page = 1, size = 4) {
  return useQuery({
    queryKey: ["projects", page, size],
    queryFn: async () => {
      const res = await apiFetch<ProjectPage>(`/projects?page=${page}&size=${size}`);
      return res.data ?? { items: [], total: 0, page: 1, size: 4 };
    },
  });
}

export function useProject(projectId: string | undefined) {
  return useQuery({
    queryKey: ["project", projectId],
    queryFn: async () => {
      if (!projectId) return null;
      const res = await apiFetch<Project>(`/projects/${projectId}`);
      return res.data ?? null;
    },
    enabled: !!projectId,
  });
}

export function useCreateProject() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (data: { name: string; root_path?: string; execution_kind?: string }) =>
      apiFetch("/projects", { method: "POST", body: JSON.stringify(data) }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["projects"] }),
  });
}

export function useCloneProject() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (id: string) =>
      apiFetch(`/projects/${id}/clone`, { method: "POST" }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["projects"] }),
  });
}

export function useDeleteProject() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ id, name }: { id: string; name: string }) =>
      apiFetch(`/projects/${id}`, {
        method: "DELETE",
        body: JSON.stringify({ name }),
      }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["projects"] }),
  });
}

export function useUpdateRootPath() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ id, root_path }: { id: string; root_path: string }) =>
      apiFetch(`/projects/${id}/root-path`, {
        method: "PUT",
        body: JSON.stringify({ root_path }),
      }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["projects"] }),
  });
}

/** Toggle the star on a project. The server handles ordering so the next
 *  refetch already places the row in the right spot — no client-side
 *  reordering needed. */
export function useToggleFavorite() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ id, favorited }: { id: string; favorited: boolean }) =>
      apiFetch(`/projects/${id}/${favorited ? "favorite" : "unfavorite"}`, {
        method: "POST",
      }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["projects"] }),
  });
}

// useUpdateTask was moved to useWorkflowQuery.ts so the canvas and the
// home grid share a single canonical task-mutation hook. Import from
// "../queries/useWorkflowQuery" for any task PATCH need.
