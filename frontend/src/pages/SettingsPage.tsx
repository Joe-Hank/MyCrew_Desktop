import { useState } from "react";
import { useLlmProviders } from "../queries/useLlmQuery";
import { useMcpServers } from "../queries/useMcpQuery";
import { usePermissions } from "../queries/useConfigQuery";
import LlmList from "../components/settings/LlmList";
import McpList from "../components/settings/McpList";
import PermissionMatrix from "../components/settings/PermissionMatrix";

type Tab = "llm" | "mcp" | "permission";

function SettingsPage() {
  const [activeTab, setActiveTab] = useState<Tab>("llm");
  const [selectedId, setSelectedId] = useState<string | null>(null);

  const { data: providers = [] } = useLlmProviders();
  const { data: servers = [] } = useMcpServers();
  const { data: permissions = [] } = usePermissions();

  const tabs: { key: Tab; label: string; count: number }[] = [
    { key: "llm", label: "LLM", count: (providers as unknown[]).length },
    { key: "mcp", label: "MCP", count: (servers as unknown[]).length },
    { key: "permission", label: "系统权限", count: (permissions as unknown[]).length },
  ];

  return (
    <div className="flex h-full flex-col">
      <div className="flex items-center gap-1 border-b border-zinc-200 px-4 dark:border-zinc-800">
        {tabs.map((tab) => (
          <button
            key={tab.key}
            onClick={() => {
              setActiveTab(tab.key);
              setSelectedId(null);
            }}
            className={`flex items-center gap-1.5 px-4 py-3 text-sm font-medium transition-colors ${
              activeTab === tab.key
                ? "border-b-2 border-blue-500 text-blue-600 dark:text-blue-400"
                : "text-zinc-500 hover:text-zinc-700 dark:text-zinc-400 dark:hover:text-zinc-200"
            }`}
          >
            {tab.label}
            <span className="rounded-full bg-zinc-200 px-1.5 py-0.5 text-xs dark:bg-zinc-700">
              {tab.count}
            </span>
          </button>
        ))}
      </div>

      <div className="flex flex-1 overflow-hidden">
        <div className="flex-1 overflow-auto">
          {activeTab === "llm" && <LlmList onSelect={setSelectedId} />}
          {activeTab === "mcp" && <McpList onSelect={setSelectedId} />}
          {activeTab === "permission" && <PermissionMatrix />}
        </div>

        {selectedId && activeTab !== "permission" && (
          <div className="w-[38.2%] border-l border-zinc-200 bg-zinc-50 p-4 dark:border-zinc-800 dark:bg-zinc-900">
            <div className="flex items-center justify-between">
              <h3 className="text-sm font-medium">编辑</h3>
              <button
                onClick={() => setSelectedId(null)}
                className="text-xs text-zinc-400 hover:text-zinc-600"
              >
                关闭
              </button>
            </div>
            <p className="mt-4 text-xs text-zinc-400">
              编辑面板 — Phase 8 完整实现
            </p>
          </div>
        )}
      </div>
    </div>
  );
}

export default SettingsPage;
