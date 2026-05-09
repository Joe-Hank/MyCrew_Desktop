import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { apiFetch } from "../net/api";

export function useLlmProviders() {
  return useQuery({
    queryKey: ["llm", "providers"],
    queryFn: async () => {
      const res = await apiFetch<unknown[]>("/llm/providers");
      return res.data ?? [];
    },
  });
}

export function useCreateLlmProvider() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (data: { name: string; type: string; api_key_ref?: string; base_url?: string }) =>
      apiFetch("/llm/providers", { method: "POST", body: JSON.stringify(data) }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["llm", "providers"] }),
  });
}

export function useUpdateLlmProvider() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ id, ...data }: { id: string; [key: string]: unknown }) =>
      apiFetch(`/llm/providers/${id}`, { method: "PUT", body: JSON.stringify(data) }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["llm", "providers"] }),
  });
}

export function useDeleteLlmProvider() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (id: string) => apiFetch(`/llm/providers/${id}`, { method: "DELETE" }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["llm", "providers"] }),
  });
}
