import { useCallback, useEffect, useState } from "react";

import { apiFetch } from "../net/api";
import { useEvent } from "./useEvent";

/** PM v3 — single source of truth for what the right-side debug log
 *  panel shows. Two sources merged:
 *    - GET /pm/sessions/{sid}/state on mount / sessionId change (replay
 *      for drawer reopen + page refresh)
 *    - WS `pm.log` events as the orchestrator broadcasts them
 *
 *  The hook is stateless re: session — pass the active session_id and
 *  it handles re-fetching when that changes (or clears state for null). */

export interface PMLogEntry {
  session_id: string;
  phase: string;
  role: string;
  status: string;
  ts: string;
  message: string;
  payload_preview?: unknown;
  detail?: string | null;
  error?: string | null;
}

export interface PMState {
  status: "idle" | "running" | "ready" | "failed" | "cancelled" | "interrupted";
  current_phase: string | null;
  debug_log: PMLogEntry[];
  draft_blueprint: Record<string, unknown> | null;
  completeness: "ONELINE" | "PRD" | null;
  error: string | null;
  failed_phase: string | null;
  /** PM v3.1 (2026-05-17): set on persisted-cache reload — the furthest
   *  phase that has a captured payload. Used as the resume point when
   *  the user clicks 「从断点重来」 on an 'interrupted' session and the
   *  cache doesn't carry an explicit failed_phase. */
  last_completed_phase?: string | null;
}

const EMPTY: PMState = {
  status: "idle",
  current_phase: null,
  debug_log: [],
  draft_blueprint: null,
  completeness: null,
  error: null,
  failed_phase: null,
};

export function usePmState(sessionId: string | null): {
  state: PMState;
  refetch: () => Promise<void>;
} {
  const [state, setState] = useState<PMState>(EMPTY);

  const refetch = useCallback(async () => {
    if (!sessionId) {
      setState(EMPTY);
      return;
    }
    try {
      const res = await apiFetch<PMState>(`/pm/sessions/${sessionId}/state`);
      if (res.ok && res.data) {
        setState(res.data);
      }
    } catch {
      // Best-effort — backend down, swallow and keep last state
    }
  }, [sessionId]);

  // Initial + on-sessionId-change replay
  useEffect(() => {
    void refetch();
  }, [refetch]);

  // Live append from WS
  const onLog = useCallback(
    (msg: { payload: Record<string, unknown> }) => {
      const p = msg.payload as unknown as PMLogEntry;
      if (!sessionId || p.session_id !== sessionId) return;
      setState((prev) => ({
        ...prev,
        debug_log: [...prev.debug_log, p],
        current_phase: p.phase,
        status: deriveStatus(prev.status, p.status),
        error: p.error ?? prev.error,
        failed_phase: p.status === "phase_failed" ? p.phase : prev.failed_phase,
      }));
      // When the orchestrator broadcasts the "complete" terminal log,
      // the draft_blueprint isn't in the WS payload — fetch fresh state
      // to pick it up.
      if (p.phase === "complete" && p.status === "phase_completed") {
        void refetch();
      }
    },
    [sessionId, refetch],
  );
  useEvent("pm.log", onLog);

  return { state, refetch };
}

function deriveStatus(prev: PMState["status"], logStatus: string): PMState["status"] {
  if (logStatus === "phase_failed") return "failed";
  if (logStatus === "cancelled") return "cancelled";
  if (logStatus === "started" || logStatus === "retry") return "running";
  if (logStatus === "phase_completed") {
    // Stay running unless a refetch lands a final 'ready'/'failed' status
    return prev === "failed" || prev === "cancelled" ? prev : "running";
  }
  return prev;
}
