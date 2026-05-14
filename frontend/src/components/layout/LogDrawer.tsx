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
  // agent.output — per-step output from a running task. Prefix with the
  // agent role + truncated task id so the user can tell which task is talking.
  if (type === "agent.output") {
    const role = typeof payload.agent_role === "string" ? payload.agent_role : "Agent";
    const step = payload.step != null ? `#${payload.step} ` : "";
    const tid = typeof payload.task_id === "string" ? ` · tid=${payload.task_id.slice(-6)}` : "";
    const text = typeof payload.text === "string" ? truncate(payload.text, 140) : "";
    return `[${role}] ${step}${text}${tid}`;
  }
  // plan_maker.sub_agent_io — per-stage IO trace for the Plan Maker
  // pipeline (compliance_gate / intent_classifier / create_new /
  // iterate_existing / clarify_design / modify_blueprint /
  // abort_or_restart). Lets the user watch exactly what each sub-agent
  // saw + replied across a round.
  if (type === "plan_maker.sub_agent_io") {
    const sub = typeof payload.sub_agent === "string" ? payload.sub_agent : "?";
    const inp = typeof payload.input_preview === "string"
      ? truncate(payload.input_preview, 80) : "";
    const out = typeof payload.output_preview === "string"
      ? truncate(payload.output_preview, 120) : "";
    const sid = typeof payload.session_id === "string"
      ? ` · sid=${payload.session_id.slice(-6)}` : "";
    const conf = payload.confidence != null
      ? ` (conf=${payload.confidence})` : "";
    const reason = typeof payload.reason === "string"
      ? ` reason=${truncate(payload.reason, 30)}` : "";
    return `🧠 [${sub}] ${inp ? "in=" + inp + " " : ""}→ out=${out}${conf}${reason}${sid}`;
  }
  // tool.invoked — audit row emitted by GuardedMCPTool / GuardedLocalTool.
  // status ∈ started | completed | denied | failed. Surface tool name +
  // status + duration/error so the user can scan a tool-call trace.
  if (type === "tool.invoked") {
    const tool = typeof payload.tool === "string" ? payload.tool : "?";
    const status = typeof payload.status === "string" ? payload.status : "?";
    const kind = typeof payload.kind === "string" ? `${payload.kind}/` : "";
    const perm = typeof payload.permission_kind === "string"
      ? ` perm=${payload.permission_kind}`
      : "";
    const dur = payload.duration_ms != null ? ` (${payload.duration_ms}ms)` : "";
    const err = typeof payload.error === "string" ? ` err=${truncate(payload.error, 80)}` : "";
    const reason = typeof payload.reason === "string" ? ` reason=${payload.reason}` : "";
    const glyph = status === "completed" ? "✓" : status === "denied" ? "⛔" : status === "failed" ? "✗" : "▶";
    return `${glyph} ${kind}${tool} ${status}${perm}${dur}${reason}${err}`;
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

// Event-type sets that route to each tab. "Agent 输出" focuses on task
// execution — agent output chunks + per-task lifecycle. "应用日志" gets
// everything else (project lifecycle, MCP, quota, errors, etc.).
const AGENT_TAB_EVENTS = new Set([
  "agent.output",
  "task.started",
  "task.completed",
  "task.failed",
  "task.paused",
  "task.blocked",
  "task.validation_failed",
]);

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

  const visibleLogs = logs.filter((e) =>
    activeTab === "Agent 输出"
      ? AGENT_TAB_EVENTS.has(e.type)
      : !AGENT_TAB_EVENTS.has(e.type),
  );

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
        {visibleLogs.length === 0 ? (
          <div className="text-[var(--color-ink-ghost)]">&gt;_ 日志内容...</div>
        ) : (
          visibleLogs.map((entry, i) => (
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
