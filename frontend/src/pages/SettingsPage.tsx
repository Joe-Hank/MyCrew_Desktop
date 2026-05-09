import { useState } from "react";
import { useLlmProviders, type LlmProvider } from "../queries/useLlmQuery";
import { useMcpServers } from "../queries/useMcpQuery";
import { usePermissions } from "../queries/useConfigQuery";
import LlmTable from "../components/settings/LlmTable";
import McpTable from "../components/settings/McpTable";
import PermissionTable from "../components/settings/PermissionTable";
import LlmEditOverlay from "../components/settings/LlmEditOverlay";
import McpEditOverlay from "../components/settings/McpEditOverlay";

type Tab = "llm" | "mcp" | "permission";

export type EditTarget =
  | { kind: "llm"; data: LlmProvider | null }
  | { kind: "mcp"; data: Record<string, unknown> | null }
  | null;

function SettingsPage() {
  const [activeTab, setActiveTab] = useState<Tab>("llm");
  const [editTarget, setEditTarget] = useState<EditTarget>(null);

  const { data: providers = [] } = useLlmProviders();
  const { data: servers = [] } = useMcpServers();
  usePermissions(); // prefetch for PermissionTable

  const tabs: { key: Tab; label: string; count: number }[] = [
    { key: "llm", label: "LLM", count: (providers as unknown[]).length },
    { key: "mcp", label: "MCP", count: (servers as unknown[]).length },
    { key: "permission", label: "系统权限", count: 0 },
  ];

  function handleNewLlm() {
    setEditTarget({ kind: "llm", data: null });
  }

  function handleEditLlm(provider: LlmProvider) {
    setEditTarget({ kind: "llm", data: provider });
  }

  function handleNewMcp() {
    setEditTarget({ kind: "mcp", data: null });
  }

  function handleEditMcp(server: Record<string, unknown>) {
    setEditTarget({ kind: "mcp", data: server });
  }

  return (
    <div className="relative flex h-full flex-col">
      {/* Tab bar */}
      <div className="flex items-center justify-between px-6 pt-4">
        {/* Pill tabs */}
        <div className="flex items-center rounded-2xl bg-zinc-200/60 p-1 dark:bg-zinc-800/60">
          {tabs.map((tab) => (
            <button
              key={tab.key}
              onClick={() => {
                setActiveTab(tab.key);
                setEditTarget(null);
              }}
              className={`rounded-xl px-4 py-2 text-sm font-semibold transition-all ${
                activeTab === tab.key
                  ? "bg-white text-blue-600 shadow dark:bg-zinc-900 dark:text-blue-400"
                  : "text-zinc-500 hover:text-zinc-700 dark:text-zinc-400 dark:hover:text-zinc-200"
              }`}
            >
              {tab.label}
              {tab.count > 0 && `（${tab.count}）`}
            </button>
          ))}
        </div>

        {/* Action button */}
        {activeTab !== "permission" && (
          <button
            onClick={activeTab === "llm" ? handleNewLlm : handleNewMcp}
            className="rounded-2xl bg-blue-500 px-5 py-2.5 text-sm font-medium text-white shadow transition-colors hover:bg-blue-600"
          >
            {activeTab === "llm" ? "LLM配置  +" : "MCP配置  +"}
          </button>
        )}
      </div>

      {/* Table content */}
      <div className="flex-1 overflow-auto px-6 pt-4">
        {activeTab === "llm" && (
          <LlmTable onEdit={handleEditLlm} />
        )}
        {activeTab === "mcp" && (
          <McpTable onEdit={handleEditMcp} />
        )}
        {activeTab === "permission" && (
          <PermissionTable />
        )}
      </div>

      {/* Edit overlay */}
      {editTarget?.kind === "llm" && (
        <LlmEditOverlay
          data={editTarget.data}
          onClose={() => setEditTarget(null)}
        />
      )}
      {editTarget?.kind === "mcp" && (
        <McpEditOverlay
          data={editTarget.data}
          onClose={() => setEditTarget(null)}
        />
      )}
    </div>
  );
}

export default SettingsPage;
