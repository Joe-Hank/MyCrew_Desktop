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
