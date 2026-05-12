import { useEffect, useState } from "react";
import { wsClient } from "../../net/ws";
import { useEvent } from "../../hooks/useEvent";

interface PromptOption {
  value: string;
  label: string;
}

interface PromptRequest {
  request_id: string;
  project_id?: string;
  task_id?: string;
  title?: string;
  type: "choice" | "text" | "confirm";
  options?: PromptOption[];
  hint?: string;
}

/**
 * Global listener for `prompt.request` events from the InteractionPort.
 * Renders a modal letting the user choose / type / confirm; sends
 * `prompt.response` with the same `request_id` when the user acts.
 */
function PromptModal() {
  const [current, setCurrent] = useState<PromptRequest | null>(null);
  const [textValue, setTextValue] = useState("");

  useEvent("prompt.request", (msg) => {
    const payload = msg.payload as unknown as PromptRequest;
    if (!payload?.request_id) return;
    setCurrent(payload);
    setTextValue("");
  });

  // Auto-clear if the WS disconnects (avoid orphaned modal)
  useEffect(() => {
    const off = wsClient.on("ws.disconnected", () => setCurrent(null));
    return off;
  }, []);

  function respond(value: unknown) {
    if (!current) return;
    wsClient.send("prompt.response", {
      request_id: current.request_id,
      value,
    });
    setCurrent(null);
  }

  if (!current) return null;

  const ctxLine = [current.project_id && `项目 ${current.project_id.slice(-6)}`,
                   current.task_id && `任务 ${current.task_id.slice(-6)}`]
    .filter(Boolean)
    .join(" · ");

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center"
      style={{ backgroundColor: "rgba(0,0,0,0.35)" }}
    >
      <div
        className="w-full max-w-md rounded-2xl bg-white p-5 shadow-2xl"
        style={{ border: "1px solid var(--color-border-soft)" }}
      >
        <h2 className="mb-1 text-base font-semibold" style={{ color: "var(--color-ink-strong)" }}>
          {current.title || "需要你的确认"}
        </h2>
        {ctxLine && (
          <p className="mb-4 text-xs" style={{ color: "var(--color-ink-faint)" }}>
            {ctxLine}
          </p>
        )}

        {current.type === "choice" && (
          <div className="space-y-2">
            {(current.options ?? []).map((opt) => (
              <button
                key={opt.value}
                onClick={() => respond(opt.value)}
                className="block w-full rounded-lg px-4 py-2.5 text-left text-sm transition-colors"
                style={{
                  backgroundColor: "var(--color-surface-alt)",
                  color: "var(--color-ink-soft)",
                }}
              >
                {opt.label}
              </button>
            ))}
          </div>
        )}

        {current.type === "text" && (
          <>
            {current.hint && (
              <p className="mb-2 text-xs" style={{ color: "var(--color-ink-muted)" }}>
                {current.hint}
              </p>
            )}
            <textarea
              value={textValue}
              onChange={(e) => setTextValue(e.target.value)}
              rows={4}
              className="w-full resize-none rounded-lg bg-zinc-50 px-3 py-2 text-sm outline-none"
              placeholder="输入回答..."
              autoFocus
            />
            <div className="mt-4 flex justify-end gap-2">
              <button
                onClick={() => respond("")}
                className="rounded-lg bg-white px-4 py-2 text-sm"
                style={{ border: "1px solid var(--color-border-soft)", color: "var(--color-ink-label)" }}
              >
                取消
              </button>
              <button
                onClick={() => respond(textValue)}
                className="rounded-lg px-4 py-2 text-sm text-white"
                style={{ backgroundColor: "var(--color-brand-500)" }}
              >
                提交
              </button>
            </div>
          </>
        )}

        {current.type === "confirm" && (
          <div className="mt-4 flex justify-end gap-2">
            <button
              onClick={() => respond(false)}
              className="rounded-lg bg-white px-4 py-2 text-sm"
              style={{ border: "1px solid var(--color-border-soft)", color: "var(--color-ink-label)" }}
            >
              拒绝
            </button>
            <button
              onClick={() => respond(true)}
              className="rounded-lg px-4 py-2 text-sm text-white"
              style={{ backgroundColor: "var(--color-brand-500)" }}
            >
              允许
            </button>
          </div>
        )}
      </div>
    </div>
  );
}

export default PromptModal;
