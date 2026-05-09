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
  const [lastLine, setLastLine] = useState("就绪");

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
    setLastLine(`[${msg.type}] ${entry.message}`);
  }, []);

  useAnyEvent(handleEvent);

  if (!expanded) {
    return (
      <div
        className="h-8 flex items-center justify-between border-t border-zinc-200 bg-zinc-100 px-3 text-xs text-zinc-500 cursor-pointer select-none dark:border-zinc-800 dark:bg-zinc-900 dark:text-zinc-400"
        onClick={() => setExpanded(true)}
      >
        <span className="truncate">{lastLine}</span>
        <span className="ml-2 shrink-0">▲</span>
      </div>
    );
  }

  return (
    <div className="flex h-48 flex-col border-t border-zinc-200 bg-zinc-100 dark:border-zinc-800 dark:bg-zinc-900">
      <div className="flex items-center justify-between border-b border-zinc-200 px-2 dark:border-zinc-800">
        <div className="flex gap-1">
          {TABS.map((tab) => (
            <button
              key={tab}
              onClick={() => setActiveTab(tab)}
              className={`px-3 py-1.5 text-xs font-medium transition-colors ${
                activeTab === tab
                  ? "border-b-2 border-blue-500 text-blue-600 dark:text-blue-400"
                  : "text-zinc-500 hover:text-zinc-700 dark:text-zinc-400 dark:hover:text-zinc-200"
              }`}
            >
              {tab}
            </button>
          ))}
        </div>
        <button
          onClick={() => setExpanded(false)}
          className="px-2 py-1 text-xs text-zinc-400 hover:text-zinc-600 dark:hover:text-zinc-200"
        >
          ▼ 收起
        </button>
      </div>
      <div className="flex-1 overflow-auto p-2 font-mono text-xs text-zinc-600 dark:text-zinc-300">
        {logs.length === 0 ? (
          <div className="flex h-full items-center justify-center text-zinc-400">暂无日志</div>
        ) : (
          logs.map((entry, i) => (
            <div key={i} className="leading-5">
              <span className="text-zinc-400">{entry.ts.substring(11, 19)}</span>{" "}
              <span className="text-blue-500">[{entry.type}]</span>{" "}
              {entry.message}
            </div>
          ))
        )}
      </div>
    </div>
  );
}

export default LogDrawer;
