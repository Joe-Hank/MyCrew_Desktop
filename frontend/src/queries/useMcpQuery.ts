import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { apiFetch } from "../net/api";

export function useMcpServers() {
  return useQuery({
    queryKey: ["mcp", "servers"],
    queryFn: async () => {
      const res = await apiFetch<unknown[]>("/mcp/servers");
      return res.data ?? [];
    },
  });
}

export function useCreateMcpServer() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (data: Record<string, unknown>) =>
      apiFetch("/mcp/servers", { method: "POST", body: JSON.stringify(data) }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["mcp", "servers"] }),
  });
}

export function useUpdateMcpServer() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ id, ...data }: { id: string; [key: string]: unknown }) =>
      apiFetch(`/mcp/servers/${id}`, { method: "PUT", body: JSON.stringify(data) }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["mcp", "servers"] }),
  });
}

export function useDeleteMcpServer() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (id: string) => apiFetch(`/mcp/servers/${id}`, { method: "DELETE" }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["mcp", "servers"] }),
  });
}
