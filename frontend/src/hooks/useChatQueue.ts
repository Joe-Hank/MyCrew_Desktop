import { useCallback, useRef, useState } from "react";

export interface PendingMsg {
  id: string;
  content: string;
}

interface ChatQueueOptions {
  /** Performs the actual LLM round-trip. Throws on real failure; AbortError is swallowed. */
  send: (content: string, signal: AbortSignal) => Promise<void>;
  /** Called once the engine returns to idle (queue drained or stopped). */
  onSettle?: () => void;
}

interface ChatQueueState {
  /** Local-only user bubbles that haven't yet been reconciled with server state. */
  pending: PendingMsg[];
  /** True while a round is in flight. UI should render the "思考中..." indicator. */
  thinking: boolean;
  /** Append a user input. Echoes locally immediately; merges into the current
   *  round if one is already in flight, otherwise kicks off a new round. */
  enqueue: (content: string) => void;
  /** Abort the current round (if any) and drop everything not yet sent.
   *  Already-displayed user bubbles are kept (they were committed to UI). */
  stop: () => void;
  /** Drop a local bubble — call after a server refetch confirms it's persisted. */
  reconcile: (ids: string[]) => void;
}

/** Single-flight chat engine. Rule:
 *  - User input is echoed immediately as a local bubble.
 *  - While a round is mid-flight, additional inputs queue (still echoed).
 *  - When the round finishes, all queued inputs are concatenated with "\n\n"
 *    into one prompt and sent as the next round.
 *  - Stop aborts the current round AND drops the pending queue.
 *
 *  This guarantees there's never more than one POST/LLM call in flight per
 *  chat panel, which is what kept user messages from being eaten before. */
export function useChatQueue({ send, onSettle }: ChatQueueOptions): ChatQueueState {
  const [pending, setPendingState] = useState<PendingMsg[]>([]);
  const [thinking, setThinking] = useState(false);

  const pendingRef = useRef<PendingMsg[]>([]);
  const runningRef = useRef(false);
  const abortRef = useRef<AbortController | null>(null);

  const setPending = useCallback((updater: (prev: PendingMsg[]) => PendingMsg[]) => {
    const next = updater(pendingRef.current);
    pendingRef.current = next;
    setPendingState(next);
  }, []);

  const runLoop = useCallback(async () => {
    if (runningRef.current) return;
    if (pendingRef.current.length === 0) return;
    runningRef.current = true;
    setThinking(true);
    try {
      while (pendingRef.current.length > 0) {
        const batch = pendingRef.current.slice();
        const combined = batch.map((p) => p.content).join("\n\n");
        const controller = new AbortController();
        abortRef.current = controller;
        try {
          await send(combined, controller.signal);
        } catch (err) {
          const name = (err as { name?: string })?.name;
          if (name === "AbortError") {
            // Stop was hit — pending queue was already cleared by stop().
            // Exit the loop without sending again.
            break;
          }
          // Real failure: drop this batch to avoid an infinite retry storm.
          const ids = new Set(batch.map((p) => p.id));
          setPending((prev) => prev.filter((p) => !ids.has(p.id)));
          // eslint-disable-next-line no-console
          console.warn("chat.send_failed", err);
          continue;
        } finally {
          abortRef.current = null;
        }
        // Success — the messages in this batch are now persisted server-side.
        // Reconciliation is handled by the caller via onSettle (typically a
        // React Query invalidate which triggers reconcile() after refetch).
        const ids = new Set(batch.map((p) => p.id));
        setPending((prev) => prev.filter((p) => !ids.has(p.id)));
      }
    } finally {
      runningRef.current = false;
      setThinking(false);
      onSettle?.();
    }
  }, [send, onSettle, setPending]);

  const enqueue = useCallback(
    (content: string) => {
      const trimmed = content.trim();
      if (!trimmed) return;
      const id = `local_${Date.now()}_${Math.random().toString(36).slice(2, 8)}`;
      setPending((prev) => [...prev, { id, content: trimmed }]);
      // Kick the loop. If a round is already in flight, runLoop is a no-op
      // and the new entry will be picked up by the loop's next iteration.
      void runLoop();
    },
    [runLoop, setPending],
  );

  const stop = useCallback(() => {
    setPending(() => []);
    abortRef.current?.abort();
  }, [setPending]);

  const reconcile = useCallback(
    (ids: string[]) => {
      if (ids.length === 0) return;
      const idSet = new Set(ids);
      setPending((prev) => prev.filter((p) => !idSet.has(p.id)));
    },
    [setPending],
  );

  return { pending, thinking, enqueue, stop, reconcile };
}
