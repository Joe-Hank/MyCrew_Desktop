import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { apiFetch } from "../net/api";

// --- Types ---

export interface Agent {
  id: string;
  role: string;
  goal: string | null;
  backstory: string | null;
  reasoning: boolean;
  max_retry: number;
  memory_enabled: boolean;
  memory_path: string | null;
  thinking_mode: boolean;
  tool_ids: string[];
  llm_id: string | null;
  is_auto_generated: boolean;
  promoted_at: string | null;
}

export interface Crew {
  id: string;
  name: string;
  process: string;
  agent_ids: string[];
  is_auto_generated: boolean;
  promoted_at: string | null;
}

export interface Tool {
  id: string;
  name: string;
  script_path: string | null;
  source: string;
  checksum: string | null;
  params_schema: Record<string, unknown>;
}

// --- Agent hooks ---

export function useAgents() {
  return useQuery({
    queryKey: ["agents"],
    queryFn: async () => {
      const res = await apiFetch<Agent[]>("/agents");
      return res.data ?? [];
    },
  });
}

export function useCreateAgent() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (data: Partial<Agent>) =>
      apiFetch("/agents", { method: "POST", body: JSON.stringify(data) }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["agents"] }),
  });
}

export function useUpdateAgent() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ id, ...data }: { id: string } & Partial<Agent>) =>
      apiFetch(`/agents/${id}`, { method: "PUT", body: JSON.stringify(data) }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["agents"] }),
  });
}

export function useDeleteAgent() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (id: string) =>
      apiFetch(`/agents/${id}`, { method: "DELETE" }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["agents"] }),
  });
}

// --- Crew hooks ---

export function useCrews() {
  return useQuery({
    queryKey: ["crews"],
    queryFn: async () => {
      const res = await apiFetch<Crew[]>("/crews");
      return res.data ?? [];
    },
  });
}

export function useCreateCrew() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (data: Partial<Crew>) =>
      apiFetch("/crews", { method: "POST", body: JSON.stringify(data) }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["crews"] }),
  });
}

export function useUpdateCrew() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ id, ...data }: { id: string } & Partial<Crew>) =>
      apiFetch(`/crews/${id}`, { method: "PUT", body: JSON.stringify(data) }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["crews"] }),
  });
}

export function useDeleteCrew() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (id: string) =>
      apiFetch(`/crews/${id}`, { method: "DELETE" }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["crews"] }),
  });
}

// --- Tool hooks ---

export function useTools() {
  return useQuery({
    queryKey: ["tools"],
    queryFn: async () => {
      const res = await apiFetch<Tool[]>("/tools");
      return res.data ?? [];
    },
  });
}

export function useCreateTool() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (data: Partial<Tool>) =>
      apiFetch("/tools", { method: "POST", body: JSON.stringify(data) }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["tools"] }),
  });
}

export function useDeleteTool() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (id: string) =>
      apiFetch(`/tools/${id}`, { method: "DELETE" }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["tools"] }),
  });
}

export function useScanTools() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: () =>
      apiFetch("/tools/scan", { method: "POST" }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["tools"] }),
  });
}
