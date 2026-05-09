import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { apiFetch } from "../net/api";

export interface McpServerStatus {
  server_id: string;
  name: string;
  transport: string;
  status: "connected" | "connecting" | "disconnected" | "error";
  tools_count: number;
  error: string | null;
}

export interface McpStatusSummary {
  total: number;
  enabled: number;
  online: number;
  offline: number;
  servers: McpServerStatus[];
}

export function useMcpServers() {
  return useQuery({
    queryKey: ["mcp", "servers"],
    queryFn: async () => {
      const res = await apiFetch<unknown[]>("/mcp/servers");
      return res.data ?? [];
    },
  });
}

export function useMcpStatus() {
  return useQuery({
    queryKey: ["mcp", "status"],
    queryFn: async () => {
      const res = await apiFetch<McpStatusSummary>("/mcp/status");
      return res.data ?? { total: 0, enabled: 0, online: 0, offline: 0, servers: [] };
    },
    refetchInterval: 15000,
  });
}

export function useCreateMcpServer() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (data: Record<string, unknown>) =>
      apiFetch("/mcp/servers", { method: "POST", body: JSON.stringify(data) }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["mcp"] });
    },
  });
}

export function useUpdateMcpServer() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ id, ...data }: { id: string; [key: string]: unknown }) =>
      apiFetch(`/mcp/servers/${id}`, { method: "PUT", body: JSON.stringify(data) }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["mcp"] });
    },
  });
}

export function useDeleteMcpServer() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (id: string) => apiFetch(`/mcp/servers/${id}`, { method: "DELETE" }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["mcp"] });
    },
  });
}

export function useConnectMcpServer() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (id: string) =>
      apiFetch(`/mcp/servers/${id}/connect`, { method: "POST" }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["mcp"] });
    },
  });
}

export function useDisconnectMcpServer() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (id: string) =>
      apiFetch(`/mcp/servers/${id}/disconnect`, { method: "POST" }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["mcp"] });
    },
  });
}

export function useRestartMcpServer() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (id: string) =>
      apiFetch(`/mcp/servers/${id}/restart`, { method: "POST" }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["mcp"] });
    },
  });
}

export function useRefreshAllMcp() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: () => apiFetch("/mcp/refresh-all", { method: "POST" }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["mcp"] });
    },
  });
}
