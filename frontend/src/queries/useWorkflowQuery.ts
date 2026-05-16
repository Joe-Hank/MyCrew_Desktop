import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { apiFetch } from "../net/api";

export function useStartProject() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (projectId: string) =>
      apiFetch(`/workflow/projects/${projectId}/start`, { method: "POST" }),
    onSuccess: (_d, projectId) => {
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
