import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { apiFetch } from "../net/api";

// --- Types ---

export interface LlmModel {
  id: string;
  provider_id: string;
  model_name: string;
  label: string | null;
  max_tokens: number | null;
  supports_thinking: boolean;
}

export interface LlmProvider {
  id: string;
  name: string;
  type: string;
  api_key_ref: string | null;
  base_url: string | null;
  models: LlmModel[];
}

export const LLM_TYPES = [
  { value: "openai", label: "OpenAI" },
  { value: "anthropic", label: "Anthropic" },
  { value: "qwen", label: "通义千问" },
  { value: "deepseek", label: "DeepSeek" },
  { value: "gemini", label: "Gemini" },
  { value: "ollama", label: "Ollama" },
  { value: "custom", label: "自定义" },
] as const;

// --- Provider hooks ---

export function useLlmProviders() {
  return useQuery({
    queryKey: ["llm", "providers"],
    queryFn: async () => {
      const res = await apiFetch<LlmProvider[]>("/llm/providers");
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

// --- Model hooks ---

export function useCreateLlmModel() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (data: {
      provider_id: string;
      model_name: string;
      label?: string;
      max_tokens?: number;
      supports_thinking?: boolean;
    }) => apiFetch("/llm/models", { method: "POST", body: JSON.stringify(data) }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["llm", "providers"] }),
  });
}

export function useUpdateLlmModel() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ id, ...data }: { id: string; [key: string]: unknown }) =>
      apiFetch(`/llm/models/${id}`, { method: "PUT", body: JSON.stringify(data) }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["llm", "providers"] }),
  });
}

export function useDeleteLlmModel() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (id: string) => apiFetch(`/llm/models/${id}`, { method: "DELETE" }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["llm", "providers"] }),
  });
}
