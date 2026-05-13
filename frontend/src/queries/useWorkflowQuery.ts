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
    mutationFn: ({ projectId, taskId }: { projectId: string; taskId: string }) =>
      apiFetch(`/workflow/projects/${projectId}/tasks/${taskId}/retry`, { method: "POST" }),
    onSuccess: (_d, { projectId }) => {
      qc.invalidateQueries({ queryKey: ["project", projectId] });
    },
  });
}

export interface TaskPatch {
  title?: string;
  detail?: string;
  agent_id?: string | null;
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

export function useActiveProjects() {
  return useQuery({
    queryKey: ["activeProjects"],
    queryFn: async () => {
      const res = await apiFetch<{ projects: string[] }>("/workflow/active");
      return res.data?.projects ?? [];
    },
  });
}
