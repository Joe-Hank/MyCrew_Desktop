import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { apiFetch } from "../net/api";

export function usePermissions() {
  return useQuery({
    queryKey: ["permissions"],
    queryFn: async () => {
      const res = await apiFetch<unknown[]>("/permissions");
      return res.data ?? [];
    },
  });
}

export function useUpdatePermissions() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (updates: { id: string; allowed: boolean }[]) =>
      apiFetch("/permissions", { method: "PUT", body: JSON.stringify(updates) }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["permissions"] }),
  });
}

export function useConfig() {
  return useQuery({
    queryKey: ["config"],
    queryFn: async () => {
      const res = await apiFetch<Record<string, string>>("/config");
      return res.data ?? {};
    },
  });
}

export function useUpdateConfig() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (data: { key: string; value: string }) =>
      apiFetch("/config", { method: "PUT", body: JSON.stringify(data) }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["config"] }),
  });
}
