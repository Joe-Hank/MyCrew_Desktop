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
  /** Cost per 1M input tokens, in 整数分人民币 (1800 = ¥18 / 1M).
   *  null = not set; project metrics treat 0/null as "do not charge". */
  input_price_cny_per_1m: number | null;
  /** Cost per 1M output tokens, same unit as above. */
  output_price_cny_per_1m: number | null;
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
      input_price_cny_per_1m?: number;
      output_price_cny_per_1m?: number;
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

// ── Thinking-mode capability probe ────────────────────────────────
//
// Used by both editors:
//   - LLM settings → "选模型 / 保存模型" hits this with model_id (when
//     editing an existing row) OR provider_id+model_name (when typing
//     a new one). The result drives whether the 思考模式 toggle in the
//     drawer is interactive.
//   - Team / Agent settings → when the user changes the bound LLM, the
//     drawer probes the newly-picked (provider_id, model_name) so the
//     toggle locks instantly without waiting for the next list refetch.
//
// The backend caches the result on `llm_models.supports_thinking`, so
// subsequent reads from `useLlmProviders` already reflect it.

export interface ThinkingProbeResult {
  supports_thinking: boolean;
  provider_type: string;
  model_name: string;
  cached: boolean;
}

export function useProbeThinking() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async (
      payload: { model_id: string } | { provider_id: string; model_name: string },
    ) => {
      const res = await apiFetch<ThinkingProbeResult>("/llm/probe-thinking", {
        method: "POST",
        body: JSON.stringify(payload),
      });
      return res.data!;
    },
    onSuccess: (data) => {
      // If the probe wrote back to the DB (model row exists), refresh
      // the providers list so any other surface that reads
      // supports_thinking sees the new value.
      if (data.cached) {
        qc.invalidateQueries({ queryKey: ["llm", "providers"] });
      }
    },
  });
}

// ── Quota / Token monitoring (plan §11.2) ─────────────────────────

export type QuotaDisplay = "percent" | "tokens_m" | "available" | "unavailable";

export interface ProviderQuota {
  provider_id: string;
  name: string;
  type: string;
  display: QuotaDisplay;
  value: number | null;     // for percent / tokens_m
  raw: string | null;       // human-readable extra (e.g. "¥10.00 CNY")
}

/** Polls /llm/quota every 30s (plan §11.2: "30s auto refresh"). */
export function useLlmQuota() {
  return useQuery({
    queryKey: ["llm", "quota"],
    queryFn: async () => {
      const res = await apiFetch<ProviderQuota[]>("/llm/quota");
      return res.data ?? [];
    },
    refetchInterval: 30_000,
    staleTime: 25_000,
  });
}

/** Force-refresh (manual refresh button). */
export function useRefreshLlmQuota() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async () => {
      const res = await apiFetch<ProviderQuota[]>("/llm/quota/refresh", { method: "POST" });
      return res.data ?? [];
    },
    onSuccess: (data) => {
      qc.setQueryData(["llm", "quota"], data);
    },
  });
}
