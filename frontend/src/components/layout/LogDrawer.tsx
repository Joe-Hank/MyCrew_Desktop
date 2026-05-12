import { useState, useCallback } from "react";
import { useAnyEvent } from "../../hooks/useEvent";
import type { WsMessage } from "../../net/ws";

const TABS = ["应用日志", "Agent 输出"] as const;

interface LogEntry {
  ts: string;
  type: string;
  message: string;
}

function LogDrawer() {
  const [expanded, setExpanded] = useState(false);
  const [activeTab, setActiveTab] = useState<string>(TABS[0]);
  const [logs, setLogs] = useState<LogEntry[]>([]);

  const handleEvent = useCallback((msg: WsMessage) => {
    if (msg.type === "ws.connected" || msg.type === "ws.disconnected" || msg.type === "pong") {
      return;
    }
    const entry: LogEntry = {
      ts: msg.ts,
      type: msg.type,
      message: (msg.payload as Record<string, unknown>)?.message as string ?? msg.type,
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
