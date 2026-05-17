import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { apiFetch } from "../net/api";

export interface InceptionSession {
  id: string;
  project_id: string | null;
  llm_id: string;
  thinking_mode: boolean;
  created_at: string;
  last_activity_at: string | null;
  title: string | null;
  title_resolved: string;           // title || project_name || `会话 <id 后6>`
  project_name: string | null;
  preview: string;                  // first user message, ≤ 80 chars
  is_draft: boolean;
}

export interface InceptionSessionListResult {
  items: InceptionSession[];
  total: number;
  offset: number;
  limit: number;
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
    /** Legacy single-agent assignment (PM v3 / setup tasks / iterate
     *  flow). When `performer_kind === "agent"`, this mirrors
     *  `performer_id` so workflow_svc fallbacks and the team page still
     *  find a row. NULL for Crew tasks. */
    agent_id?: string | null;
    /** PM v4: 'agent' (single agent) or 'crew' (head → executor → QA
     *  chain). Filled by Phase 5 (planner_orchestrator
     *  ._assemble_draft_blueprint) and round-tripped through
     *  pmState.draft_blueprint without modification. The task draft
     *  preview reads this to show "Crew: Art Crew" vs "Agent: …". */
    performer_kind?: "agent" | "crew" | null;
    /** ID of the assigned performer (agent_id or crew_id depending on
     *  kind). For Crew tasks this is the only field carrying the
     *  identity — the legacy `agent_id` column is null. */
    performer_id?: string | null;
  }[];
}

interface ListSessionsParams {
  q?: string;
  limit?: number;
  offset?: number;
}

export function useInceptionSessions(params: ListSessionsParams = {}) {
  const q = (params.q ?? "").trim();
  const limit = params.limit ?? 10;
  const offset = params.offset ?? 0;
  return useQuery({
    queryKey: ["inception", "sessions", { q, limit, offset }],
    queryFn: async () => {
      const url = `/inceptions/sessions?` + new URLSearchParams({
        ...(q ? { q } : {}),
        limit: String(limit),
        offset: String(offset),
      }).toString();
      const res = await apiFetch<InceptionSessionListResult>(url);
      return res.data ?? { items: [], total: 0, offset, limit };
    },
  });
}

export function useDeleteInceptionSession() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (sessionId: string) =>
      apiFetch(`/inceptions/sessions/${sessionId}`, { method: "DELETE" }),
    onSuccess: () =>
      qc.invalidateQueries({ queryKey: ["inception", "sessions"] }),
  });
}

export function useRenameInceptionSession() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ id, title }: { id: string; title: string }) =>
      apiFetch(`/inceptions/sessions/${id}`, {
        method: "PATCH",
        body: JSON.stringify({ title }),
      }),
    onSuccess: () =>
      qc.invalidateQueries({ queryKey: ["inception", "sessions"] }),
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
    mutationFn: (data: {
      llm_id: string;
      mode?: "create" | "iterate";
      parent_project_id?: string;
      template_id?: string;
    }) =>
      apiFetch("/inceptions/sessions", { method: "POST", body: JSON.stringify(data) }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["inception"] }),
  });
}

/** Streaming variant — backend emits `inception.delta` per LLM token via WS,
 *  then `inception.message` with the full assistant text at the end.
 *  Subscribe to those events in the component to render token-by-token.
 *
 *  Pass an AbortSignal in the mutation variables to support a user "Stop"
 *  button — aborting the fetch disconnects the client, FastAPI cancels the
 *  task, and the in-flight LLM call is cancelled too.
 *
 *  NOTE: no `onMutate` optimistic update. The chat-queue hook owns the
 *  pending-bubble lifecycle (the round is single-flight, the user-side
 *  echo is rendered from `useChatQueue.pending`). Adding an optimistic
 *  insert here too caused the "message appears twice" bug. We `await`
 *  the invalidation in onSuccess so mutateAsync only resolves once the
 *  cache holds the freshly-fetched server messages — eliminating the
 *  gap where the pending bubble has been cleared but the persisted
 *  message hasn't arrived yet. */
// No request-side timeout — Plan Maker rounds with a slow LLM (DeepSeek pro,
// long context) can take several minutes; cutting them off mid-flight loses
// work that's already been done server-side. Use 0 to opt out of the
// apiFetch internal timer; the user retains control via the chat queue's
// Stop button (which aborts the fetch via AbortController).
const PLAN_MAKER_TIMEOUT_MS = 0;

export function useStreamInceptionMessage() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({
      sessionId,
      content,
      signal,
    }: { sessionId: string; content: string; signal?: AbortSignal }) =>
      apiFetch(`/inceptions/sessions/${sessionId}/messages/stream`, {
        method: "POST",
        body: JSON.stringify({ content }),
        signal,
        timeoutMs: PLAN_MAKER_TIMEOUT_MS,
      }),
    onSuccess: async (_data, vars) => {
      await qc.invalidateQueries({ queryKey: ["inception", "session", vars.sessionId] });
    },
  });
}

export function useSendInceptionMessage() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ sessionId, content }: { sessionId: string; content: string }) =>
      apiFetch(`/inceptions/sessions/${sessionId}/messages`, {
        method: "POST",
        body: JSON.stringify({ content }),
        timeoutMs: PLAN_MAKER_TIMEOUT_MS,
      }),
    // Optimistic update: the LLM round-trip can take many seconds, so
    // immediately reflect the user's message in the cache. Otherwise the
    // user's own typed text doesn't appear in the chat until the AI replies.
    onMutate: async ({ sessionId, content }) => {
      const key = ["inception", "session", sessionId];
      await qc.cancelQueries({ queryKey: key });
      const prev = qc.getQueryData<SessionDetail | null>(key);

      const optimisticMsg: InceptionMessage = {
        id: `__pending_${Date.now()}`,
        session_id: sessionId,
        role: "user",
        content,
        ts: new Date().toISOString(),
      };

      if (prev) {
        qc.setQueryData<SessionDetail>(key, {
          ...prev,
          messages: [...prev.messages, optimisticMsg],
        });
      }

      return { prev };
    },
    onError: (_err, vars, ctx) => {
      // Roll back on failure so the user sees their message didn't actually send
      if (ctx?.prev !== undefined) {
        qc.setQueryData(["inception", "session", vars.sessionId], ctx.prev);
      }
    },
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
