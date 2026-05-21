import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { apiFetch } from "../net/api";

export function useStartProject() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (params: string | {
      projectId: string;
      // PM v5+ scaffold args. Required ONLY when project.scaffold_status
      // is 'pending' (or 'failed' for retry). For already-scaffolded
      // projects pass just the projectId string.
      root_parent_path?: string;
      slug?: string;
    }) => {
      const projectId = typeof params === "string" ? params : params.projectId;
      const body = typeof params === "string"
        ? undefined
        : {
            root_parent_path: params.root_parent_path,
            slug: params.slug,
          };
      return apiFetch(`/workflow/projects/${projectId}/start`, {
        method: "POST",
        body: body ? JSON.stringify(body) : undefined,
      });
    },
    onSuccess: (_d, params) => {
      const projectId = typeof params === "string" ? params : params.projectId;
      qc.invalidateQueries({ queryKey: ["project", projectId] });
      qc.invalidateQueries({ queryKey: ["projects"] });
    },
  });
}

export function usePauseProject() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (projectId: string) =>
      apiFetch(`/workflow/projects/${projectId}/pause`, { method: "POST" }),
    onSuccess: (_d, projectId) => {
      qc.invalidateQueries({ queryKey: ["project", projectId] });
      qc.invalidateQueries({ queryKey: ["projects"] });
    },
  });
}

export function useResumeProject() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (projectId: string) =>
      apiFetch(`/workflow/projects/${projectId}/resume`, { method: "POST" }),
    onSuccess: (_d, projectId) => {
      qc.invalidateQueries({ queryKey: ["project", projectId] });
      qc.invalidateQueries({ queryKey: ["projects"] });
    },
  });
}

export function useAbortProject() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ projectId, reason }: { projectId: string; reason?: string }) =>
      apiFetch(`/workflow/projects/${projectId}/abort?reason=${encodeURIComponent(reason ?? "")}`, {
        method: "POST",
      }),
    onSuccess: (_d, { projectId }) => {
      qc.invalidateQueries({ queryKey: ["project", projectId] });
      qc.invalidateQueries({ queryKey: ["projects"] });
    },
  });
}

export function useRetryTask() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({
      projectId,
      taskId,
      cleanupArtifacts = true,
    }: {
      projectId: string;
      taskId: string;
      // When false, preserves the previous run's sub/ + out.* on disk —
      // user opt-out from the retry confirm dialog. Backend default is
      // also true; the param is explicit for symmetry with the dialog.
      cleanupArtifacts?: boolean;
    }) =>
      apiFetch(
        `/workflow/projects/${projectId}/tasks/${taskId}/retry?cleanup_artifacts=${cleanupArtifacts}`,
        { method: "POST" },
      ),
    onSuccess: (_d, { projectId }) => {
      qc.invalidateQueries({ queryKey: ["project", projectId] });
    },
  });
}

/** Hard-reset a project to its initial state (all tasks → pending,
 *  artifacts + optionally produced files wiped). Used by the debug
 *  initialise button — surfaced selectively on debug projects so
 *  contributors can iterate on a Crew without manually clearing DB
 *  rows + on-disk PNGs between runs. */
export function useResetProject() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({
      projectId,
      deleteOutputFiles = false,
    }: {
      projectId: string;
      /** When true, also unlinks every file the tasks claimed in
       *  output_paths (+ companion .meta) under root_path. */
      deleteOutputFiles?: boolean;
    }) =>
      apiFetch(
        `/workflow/projects/${projectId}/reset?delete_output_files=${deleteOutputFiles}`,
        { method: "POST" },
      ),
    onSuccess: (_d, { projectId }) => {
      qc.invalidateQueries({ queryKey: ["project", projectId] });
      qc.invalidateQueries({ queryKey: ["projects"] });
    },
  });
}

export interface TaskPatch {
  title?: string;
  detail?: string;
  agent_id?: string | null;
  // PM v4: when the user picks a Crew from TaskEditModal, the patch
  // includes performer_kind='crew' + performer_id=<crew_id> + clears
  // agent_id to null so workflow_svc routes the task through the Crew
  // walker. Sending undefined leaves the column untouched (backend
  // honours exclude_unset).
  performer_kind?: "agent" | "crew" | null;
  performer_id?: string | null;
  deps?: string[];
  position_x?: number;
  position_y?: number;
}

export function useUpdateTask() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ taskId, ...body }: { taskId: string } & TaskPatch) =>
      apiFetch(`/workflow/tasks/${taskId}`, {
        method: "PUT",
        body: JSON.stringify(body),
      }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["project"] });
      qc.invalidateQueries({ queryKey: ["projects"] });
    },
  });
}

export interface TaskCreatePayload {
  project_id: string;
  title?: string;
  detail?: string;
  agent_id?: string | null;
  deps?: string[];
  kind?: string;
  position_x?: number;
  position_y?: number;
}

export function useCreateTask() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (body: TaskCreatePayload) =>
      apiFetch(`/workflow/tasks`, {
        method: "POST",
        body: JSON.stringify(body),
      }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["project"] });
      qc.invalidateQueries({ queryKey: ["projects"] });
    },
  });
}

export function useDeleteTask() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (taskId: string) =>
      apiFetch(`/workflow/tasks/${taskId}`, { method: "DELETE" }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["project"] });
      qc.invalidateQueries({ queryKey: ["projects"] });
    },
  });
}

export interface TaskIO {
  direction: string;
  structured: Record<string, unknown> | null;
  raw: string | null;
}

export function useTaskIO(taskId: string | null, direction: "in" | "out") {
  return useQuery({
    queryKey: ["taskIO", taskId, direction],
    queryFn: async () => {
      if (!taskId) return null;
      const res = await apiFetch<TaskIO>(`/workflow/tasks/${taskId}/io?direction=${direction}`);
      return res.data ?? null;
    },
    enabled: !!taskId,
  });
}

export interface SubIO {
  step_index: number;
  in: Record<string, unknown> | null;
  out: Record<string, unknown> | null;
  // Separate raw markdown for in vs out tabs. Pre-2026-05-17 backends
  // only wrote out.md (raw_in is null) — IO viewer falls back gracefully.
  raw_in: string | null;
  raw_out: string | null;
  /** @deprecated use raw_out — kept for old-server compatibility */
  raw: string | null;
}

export function useSubIO(taskId: string | null, stepIndex: number | null) {
  return useQuery({
    queryKey: ["subIO", taskId, stepIndex],
    queryFn: async () => {
      if (!taskId || stepIndex === null || stepIndex === undefined) return null;
      const res = await apiFetch<SubIO>(
        `/workflow/tasks/${taskId}/sub_io?step_index=${stepIndex}`,
      );
      return res.data ?? null;
    },
    enabled: !!taskId && stepIndex !== null && stepIndex !== undefined,
  });
}

export function useActiveProjects() {
  return useQuery({
    queryKey: ["activeProjects"],
    queryFn: async () => {
      const res = await apiFetch<{ projects: string[] }>("/workflow/active");
      return res.data?.projects ?? [];
    },
  });
}

export interface RequiredMcp {
  server_id: string;
  name: string;
  status: "connected" | "connecting" | "error" | "disconnected" | string;
  tools_used: string[];
  missing_tools: string[];
}

// ── PM v5+ scaffold flow (2026-05-17) ───────────────────────────────
//
// New hooks for the scaffold redesign — trigger lives on the project
// card's 「路径」 button now (not the task header start button). All
// three hooks talk to /workflow/projects/{id}/scaffold[*] routes.

export function useScaffoldProject() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (params: {
      projectId: string;
      root_parent_path: string;
      slug: string;
    }) =>
      apiFetch(`/workflow/projects/${params.projectId}/scaffold`, {
        method: "POST",
        body: JSON.stringify({
          root_parent_path: params.root_parent_path,
          slug: params.slug,
        }),
      }),
    onSuccess: (_d, params) => {
      qc.invalidateQueries({ queryKey: ["project", params.projectId] });
      qc.invalidateQueries({ queryKey: ["projects"] });
    },
  });
}

export function useRepairScaffold() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (projectId: string) =>
      apiFetch(`/workflow/projects/${projectId}/scaffold-repair`, {
        method: "POST",
      }),
    onSuccess: (_d, projectId) => {
      qc.invalidateQueries({ queryKey: ["project", projectId] });
      qc.invalidateQueries({ queryKey: ["projects"] });
    },
  });
}

export interface ScaffoldAudit {
  applicable: boolean;
  scaffold_status: string | null;
  root_path?: string;
  missing: string[];
}

/** Audit the scaffolded project root vs the 4 critical anchor paths.
 *  Used by TaskHeader's first-start gate: if missing.length > 0, the
 *  ScaffoldAuditModal pops with a 一键修复 button. */
export function useScaffoldAudit(projectId: string | undefined) {
  return useQuery({
    queryKey: ["scaffoldAudit", projectId],
    queryFn: async () => {
      if (!projectId) return null;
      const res = await apiFetch<ScaffoldAudit>(
        `/workflow/projects/${projectId}/scaffold-audit`,
      );
      return res.data ?? null;
    },
    // Re-fetch on every TaskHeader mount — cheap (just stat 4 paths).
    enabled: !!projectId,
    staleTime: 0,
  });
}

export interface FailureAnalysis {
  status: "ready" | "pending" | "not_failed";
  text: string | null;
  at: string | null;
  validation_errors?: string | null;
  last_error?: string | null;
}

/** Read the LLM-precomputed failure diagnosis for a task.
 *
 *  Backend's failure_analyzer.spawn(task_id) runs at the moment a task
 *  transitions to failed / validation_failed, writes its output to
 *  tasks.failure_analysis, then broadcasts task.failure_analyzed.
 *  TaskPage subscribes to that event and invalidates this query so the
 *  drawer flips from "分析中..." to the rendered diagnosis. */
export function useFailureAnalysis(taskId: string | null) {
  return useQuery({
    queryKey: ["failureAnalysis", taskId],
    queryFn: async () => {
      if (!taskId) return null;
      const res = await apiFetch<FailureAnalysis>(
        `/workflow/tasks/${taskId}/failure_analysis`,
      );
      return res.data ?? null;
    },
    enabled: !!taskId,
    // Short stale time so re-opening the drawer right after the WS
    // event lands always shows fresh text.
    staleTime: 1_000,
  });
}

/** Computes which MCP servers a project's tasks actually need + their
 *  current connection status. Powers the TaskHeader right-side status
 *  row + the Start button's pre-flight gate.
 *
 *  Refetched on mcp.status_changed so the chips flip green / grey as
 *  the user (or autostart) toggles connections. */
export function useRequiredMcps(projectId: string | undefined) {
  return useQuery({
    queryKey: ["workflow", "requiredMcps", projectId],
    queryFn: async () => {
      if (!projectId) return [] as RequiredMcp[];
      const res = await apiFetch<{ servers: RequiredMcp[] }>(
        `/workflow/projects/${projectId}/required-mcps`,
      );
      return res.data?.servers ?? [];
    },
    enabled: !!projectId,
  });
}
