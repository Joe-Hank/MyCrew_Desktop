import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { apiFetch } from "../net/api";

export interface InceptionSession {
  id: string;
  project_id: string | null;
  llm_id: string;
  thinking_mode: boolean;
  created_at: string;
  project_name: string | null;
  is_draft: boolean;
}

export interface InceptionMessage {
  id: string;
  session_id: string;
  role: "user" | "assistant";
  content: string;
  ts: string;
}

export interface SessionDetail {
  id: string;
  project_id: string | null;
  llm_id: string;
  thinking_mode: boolean;
  messages: InceptionMessage[];
}

export interface Blueprint {
  name?: string;
  execution_kind: string;
  tasks: {
    title: string;
    detail: string;
    deps: number[];
    output_schema: Record<string, unknown>;
    kind: string;
  }[];
}

export function useInceptionSessions() {
  return useQuery({
    queryKey: ["inception", "sessions"],
    queryFn: async () => {
      const res = await apiFetch<InceptionSession[]>("/inceptions/sessions");
      return res.data ?? [];
    },
  });
}

export function useInceptionSession(sessionId: string | null) {
  return useQuery({
    queryKey: ["inception", "session", sessionId],
    queryFn: async () => {
      if (!sessionId) return null;
      const res = await apiFetch<SessionDetail>(`/inceptions/sessions/${sessionId}`);
      return res.data ?? null;
    },
    enabled: !!sessionId,
  });
}

export function useCreateInceptionSession() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (data: { llm_id: string; thinking_mode?: boolean }) =>
      apiFetch("/inceptions/sessions", { method: "POST", body: JSON.stringify(data) }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["inception"] }),
  });
}

export function useSendInceptionMessage() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ sessionId, content }: { sessionId: string; content: string }) =>
      apiFetch(`/inceptions/sessions/${sessionId}/messages`, {
        method: "POST",
        body: JSON.stringify({ content }),
      }),
    onSuccess: (_data, vars) => {
      qc.invalidateQueries({ queryKey: ["inception", "session", vars.sessionId] });
    },
  });
}

export function useFinalizeInception() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ sessionId, blueprint }: { sessionId: string; blueprint?: Blueprint }) =>
      apiFetch(`/inceptions/sessions/${sessionId}/finalize`, {
        method: "POST",
        body: JSON.stringify({ blueprint: blueprint ?? null }),
      }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["inception"] });
      qc.invalidateQueries({ queryKey: ["projects"] });
    },
  });
}
