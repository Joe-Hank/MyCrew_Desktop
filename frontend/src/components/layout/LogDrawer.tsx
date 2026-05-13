import { useState, useCallback } from "react";
import { useAnyEvent } from "../../hooks/useEvent";
import { usePrefsStore, type LogTab } from "../../stores/usePrefsStore";
import type { WsMessage } from "../../net/ws";

const TABS: LogTab[] = ["应用日志", "Agent 输出"];

interface LogEntry {
  ts: string;
  type: string;
  message: string;
}

/** Build a short, human-readable preview of the payload for a single log line.
 *  Falls back to a compact JSON snippet so the line is never empty (the old
 *  behaviour printed the event type twice when no `message` field was present). */
function summarisePayload(type: string, payload: Record<string, unknown> | undefined): string {
  if (!payload) return "";
  if (typeof payload.message === "string") return payload.message;
  // inception.probe — render the checkpoint label + any extra context fields
  // so users can see exactly which Plan Maker step is running / stuck.
  if (type === "inception.probe" && typeof payload.label === "string") {
    const extra: string[] = [];
    for (const [k, v] of Object.entries(payload)) {
      if (k === "label" || k === "session_id") continue;
      extra.push(`${k}=${truncate(String(v), 80)}`);
    }
    const sid = typeof payload.session_id === "string" ? ` · sid=${payload.session_id.slice(-6)}` : "";
    return `▶ ${payload.label}${extra.length ? " (" + extra.join(", ") + ")" : ""}${sid}`;
  }
  const parts: string[] = [];
  if (typeof payload.role === "string" && typeof payload.content === "string") {
    parts.push(`${payload.role}: ${truncate(payload.content, 80)}`);
  } else if (typeof payload.text === "string") {
    parts.push(truncate(payload.text, 80));
  }
  if (typeof payload.session_id === "string") parts.push(`sid=${payload.session_id.slice(-6)}`);
  if (typeof payload.project_id === "string") parts.push(`pid=${payload.project_id.slice(-6)}`);
  if (typeof payload.task_id === "string") parts.push(`tid=${payload.task_id.slice(-6)}`);
  if (Array.isArray(payload.providers)) parts.push(`providers=${payload.providers.length}`);
  if (parts.length) return parts.join(" · ");
  // Last-resort: compact JSON, truncated.
  try {
    const s = JSON.stringify(payload);
    return truncate(s, 120);
  } catch {
    return type;
  }
}

function truncate(s: string, n: number): string {
  if (s.length <= n) return s;
  return s.slice(0, n - 1) + "…";
}

function LogDrawer() {
  const expanded = usePrefsStore((s) => s.logDrawerExpanded);
  const setExpanded = usePrefsStore((s) => s.setLogDrawerExpanded);
  const activeTab = usePrefsStore((s) => s.logDrawerActiveTab);
  const setActiveTab = usePrefsStore((s) => s.setLogDrawerActiveTab);
  const [logs, setLogs] = useState<LogEntry[]>([]);

  const handleEvent = useCallback((msg: WsMessage) => {
    if (msg.type === "ws.connected" || msg.type === "ws.disconnected" || msg.type === "pong") {
      return;
    }
    const entry: LogEntry = {
      ts: msg.ts,
      type: msg.type,
      message: summarisePayload(msg.type, msg.payload as Record<string, unknown>),
    };
    setLogs((prev) => [...prev.slice(-499), entry]);
  }, []);

  useAnyEvent(handleEvent);

  if (!expanded) {
    return (
      <div
        onClick={() => setExpanded(true)}
        className="flex h-7 cursor-pointer select-none items-center justify-between px-3 text-xs"
        style={{
          backgroundColor: "var(--color-card)",
          color: "var(--color-ink-ghost)",
          borderTop: "1px solid var(--color-border-strong)",
        }}
      >
        <span className="font-mono">&gt;_ 日志</span>
      </div>
    );
  }

  return (
    <div
      className="flex h-56 flex-col"
      style={{
        backgroundColor: "var(--color-card)",
        borderTop: "1px solid var(--color-border-strong)",
      }}
    >
      <div
        className="flex items-center justify-between px-2"
        style={{ borderBottom: "1px solid var(--color-border-soft)" }}
      >
        <div className="flex">
          {TABS.map((tab) => (
            <button
              key={tab}
              onClick={() => setActiveTab(tab)}
              className="px-4 py-1.5 text-xs transition-colors"
              style={{
                color:
                  activeTab === tab
                    ? "var(--color-ink-label)"
                    : "var(--color-ink-ghost)",
                borderBottom:
                  activeTab === tab
                    ? "2px solid var(--color-brand-500)"
                    : "2px solid transparent",
                fontWeight: activeTab === tab ? 500 : 400,
              }}
            >
              {tab}
            </button>
          ))}
        </div>
        <button
          onClick={() => setExpanded(false)}
          className="px-2 py-1 text-base"
          style={{ color: "var(--color-ink-ghost)" }}
          title="收起"
        >
          ▽
        </button>
      </div>
      <div
        className="flex-1 overflow-auto px-3 py-2 font-mono text-xs"
        style={{ color: "var(--color-ink-soft)" }}
      >
        {logs.length === 0 ? (
          <div className="text-[var(--color-ink-ghost)]">&gt;_ 日志内容...</div>
        ) : (
          logs.map((entry, i) => (
            <div key={i} className="leading-5">
              <span style={{ color: "var(--color-ink-ghost)" }}>
                {entry.ts.substring(11, 19)}
              </span>{" "}
              <span style={{ color: "var(--color-brand-500)" }}>[{entry.type}]</span>{" "}
              {entry.message}
            </div>
          ))
        )}
      </div>
    </div>
  );
}

export default LogDrawer;
