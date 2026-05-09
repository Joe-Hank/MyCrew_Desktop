import { useState } from "react";

type Tab = "agents" | "crews" | "tools";

function TeamPage() {
  const [activeTab, setActiveTab] = useState<Tab>("agents");

  const tabs: { key: Tab; label: string; count: number }[] = [
    { key: "agents", label: "Agents", count: 14 },
    { key: "crews", label: "Crews", count: 2 },
    { key: "tools", label: "Tools", count: 2 },
  ];

  const buttonLabel = activeTab === "agents" ? "新建员工  +" : activeTab === "crews" ? "新建员工  +" : "Tools配置  +";

  return (
    <div className="relative flex h-full flex-col">
      {/* Tab bar */}
      <div className="flex items-center justify-between px-6 pt-4">
        <div className="flex items-center rounded-2xl bg-zinc-200/60 p-1 dark:bg-zinc-800/60">
          {tabs.map((tab) => (
            <button
              key={tab.key}
              onClick={() => setActiveTab(tab.key)}
              className={`rounded-xl px-4 py-2 text-sm font-semibold transition-all ${
                activeTab === tab.key
                  ? "bg-white text-blue-600 shadow dark:bg-zinc-900 dark:text-blue-400"
                  : "text-zinc-500 hover:text-zinc-700 dark:text-zinc-400 dark:hover:text-zinc-200"
              }`}
            >
              {tab.label}（{tab.count}）
            </button>
          ))}
        </div>

        <button className="rounded-2xl bg-blue-500 px-5 py-2.5 text-sm font-medium text-white shadow transition-colors hover:bg-blue-600">
          {buttonLabel}
        </button>
      </div>

      {/* Table content */}
      <div className="flex-1 overflow-auto px-6 pt-4">
        {activeTab === "agents" && <AgentsTable />}
        {activeTab === "crews" && <CrewsTable />}
        {activeTab === "tools" && <ToolsTable />}
      </div>
    </div>
  );
}

/* --- Agents Table --- */
const AGENT_COLS = ["名称", "模型", "思考模式", "工具", "记忆路径", "操作"] as const;

function AgentsTable() {
  const rows = [
    { name: "Unity操作员", model: "Deepseek v4-Pro", thinking: true, tool: "Unity-Operator", memory: "E:\\CrewAI\\..." },
    { name: "ComfyUI专家", model: "Deepseek v4-Pro", thinking: true, tool: "ComfyUI-Operator", memory: "E:\\CrewAI\\..." },
  ];

  return (
    <div className="overflow-hidden rounded-xl border border-zinc-200 bg-white dark:border-zinc-700 dark:bg-zinc-900">
      <div className="grid grid-cols-[1.2fr_1fr_0.8fr_1.2fr_1.2fr_auto] gap-2 border-b border-zinc-200 px-4 py-3 dark:border-zinc-700">
        {AGENT_COLS.map((col) => (
          <span key={col} className="text-xs font-medium text-zinc-400">{col}</span>
        ))}
      </div>
      <div className="divide-y divide-zinc-100 dark:divide-zinc-800">
        {rows.map((r) => (
          <div key={r.name} className="group grid grid-cols-[1.2fr_1fr_0.8fr_1.2fr_1.2fr_auto] items-center gap-2 px-4 py-3 transition-colors hover:bg-zinc-50 dark:hover:bg-zinc-800/40">
            <div className="flex items-center gap-2">
              <span className="inline-flex h-7 w-7 items-center justify-center rounded-full bg-zinc-200 text-xs dark:bg-zinc-700">👤</span>
              <span className="text-sm font-medium">{r.name}</span>
            </div>
            <span className="text-xs text-zinc-600 dark:text-zinc-400">{r.model}</span>
            <span>
              <span className={`inline-block h-7 w-14 rounded-full ${r.thinking ? "bg-green-500" : "bg-zinc-300"} relative`}>
                <span className={`absolute top-0.5 h-6 w-6 rounded-full bg-white shadow transition-transform ${r.thinking ? "left-[calc(100%-1.625rem)]" : "left-0.5"}`} />
              </span>
            </span>
            <span className="text-xs text-zinc-600 dark:text-zinc-400">{r.tool}</span>
            <span className="text-xs text-zinc-600 underline dark:text-zinc-400">{r.memory}</span>
            <div className="flex items-center gap-1 opacity-0 transition-opacity group-hover:opacity-100">
              <button className="rounded-2xl border border-zinc-200 bg-white px-3 py-1 text-xs text-zinc-600 shadow-sm dark:border-zinc-600 dark:bg-zinc-800 dark:text-zinc-300">编辑</button>
              <button className="rounded-2xl bg-red-400 px-3 py-1 text-xs text-white shadow-sm">删除</button>
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}

/* --- Crews Table --- */
const CREW_COLS = ["名称", "成员", "过程控制", "操作"] as const;

function CrewsTable() {
  const rows = [
    { name: "Unity游戏制作", members: "Unity操作员,ComfyUI专家", process: "链式" },
    { name: "Unity游戏制作", members: "Unity操作员,ComfyUI专家", process: "链式" },
  ];

  return (
    <div className="overflow-hidden rounded-xl border border-zinc-200 bg-white dark:border-zinc-700 dark:bg-zinc-900">
      <div className="grid grid-cols-[1.2fr_2fr_1fr_auto] gap-2 border-b border-zinc-200 px-4 py-3 dark:border-zinc-700">
        {CREW_COLS.map((col) => (
          <span key={col} className="text-xs font-medium text-zinc-400">{col}</span>
        ))}
      </div>
      <div className="divide-y divide-zinc-100 dark:divide-zinc-800">
        {rows.map((r, i) => (
          <div key={i} className="group grid grid-cols-[1.2fr_2fr_1fr_auto] items-center gap-2 px-4 py-3 transition-colors hover:bg-zinc-50 dark:hover:bg-zinc-800/40">
            <div className="flex items-center gap-2">
              <span className="inline-flex h-7 w-7 items-center justify-center rounded-full bg-zinc-200 text-xs dark:bg-zinc-700">👥</span>
              <span className="text-sm font-medium">{r.name}</span>
            </div>
            <span className="text-xs text-zinc-600 dark:text-zinc-400">{r.members}</span>
            <div className="flex items-center rounded-2xl bg-zinc-200/60 p-0.5 dark:bg-zinc-700/60">
              <span className={`rounded-xl px-3 py-1 text-xs ${r.process === "链式" ? "bg-white shadow dark:bg-zinc-800" : ""}`}>链式</span>
              <span className={`rounded-xl px-3 py-1 text-xs ${r.process === "层式" ? "bg-white shadow dark:bg-zinc-800" : "text-zinc-400"}`}>层式</span>
            </div>
            <div className="flex items-center gap-1 opacity-0 transition-opacity group-hover:opacity-100">
              <button className="rounded-2xl border border-zinc-200 bg-white px-3 py-1 text-xs text-zinc-600 shadow-sm dark:border-zinc-600 dark:bg-zinc-800 dark:text-zinc-300">编辑</button>
              <button className="rounded-2xl bg-red-400 px-3 py-1 text-xs text-white shadow-sm">删除</button>
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}

/* --- Tools Table --- */
const TOOL_COLS = ["名称", "路径"] as const;

function ToolsTable() {
  const rows = [
    { name: "GLM", path: "E:\\CrewAI\\..." },
    { name: "Deepseek", path: "E:\\CrewAI\\..." },
  ];

  return (
    <div className="overflow-hidden rounded-xl border border-zinc-200 bg-white dark:border-zinc-700 dark:bg-zinc-900">
      <div className="grid grid-cols-[1fr_2fr] gap-2 border-b border-zinc-200 px-4 py-3 dark:border-zinc-700">
        {TOOL_COLS.map((col) => (
          <span key={col} className="text-xs font-medium text-zinc-400">{col}</span>
        ))}
      </div>
      <div className="divide-y divide-zinc-100 dark:divide-zinc-800">
        {rows.map((r, i) => (
          <div key={i} className="grid grid-cols-[1fr_2fr] items-center gap-2 px-4 py-3 transition-colors hover:bg-zinc-50 dark:hover:bg-zinc-800/40">
            <span className="text-sm">{r.name}</span>
            <span className="text-xs text-zinc-600 underline dark:text-zinc-400">{r.path}</span>
          </div>
        ))}
      </div>
    </div>
  );
}

export default TeamPage;
