import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { apiFetch } from "../net/api";

// ── Templates (Strategy C, 2026-05-16) ─────────────────────────
// Catalogue of MCP server presets — figma / notion / tavily / unity /
// blender / git / comfyui / custom. Frontend reads this once to drive
// the create/edit form: each template declares its required fields
// (label / type / placeholder), and the backend assembles command/args
// /url/env_ref from {template_id, template_values} on save.

export interface McpTemplateField {
  key: string;
  label: string;
  type: "text" | "password" | "number" | "path" | "url";
  required?: boolean;
  placeholder?: string;
  description?: string;
  default?: unknown;
}

export interface McpTemplate {
  id: string;
  name: string;
  description: string;
  transport: "stdio" | "http";
  command?: string | null;
  args_template?: string[];
  url_template?: string | null;
  env_template?: Record<string, string>;
  fields: McpTemplateField[];
}

export function useMcpTemplates() {
  return useQuery({
    queryKey: ["mcp", "templates"],
    queryFn: async () => {
      const res = await apiFetch<{ templates: McpTemplate[] }>(
        "/mcp/templates",
      );
      return res.data?.templates ?? [];
    },
    // Templates are static for the life of the backend process; cache
    // for the whole session so the picker is instant.
    staleTime: Infinity,
  });
}

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
