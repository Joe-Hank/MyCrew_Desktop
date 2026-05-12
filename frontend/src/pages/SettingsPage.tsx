import { useState } from "react";
import { useLlmProviders, type LlmProvider } from "../queries/useLlmQuery";
import { useMcpServers } from "../queries/useMcpQuery";
import PillTabs from "../components/common/PillTabs";
import LlmTable from "../components/settings/LlmTable";
import McpTable from "../components/settings/McpTable";
import PermissionTable from "../components/settings/PermissionTable";
import SettingsEditorDrawer, { type SettingsEditorTarget } from "../components/settings/SettingsEditorDrawer";

type Tab = "llm" | "mcp" | "permission";

function SettingsPage() {
  const [activeTab, setActiveTab] = useState<Tab>("llm");
  const [editor, setEditor] = useState<SettingsEditorTarget | null>(null);

  const { data: providers = [] } = useLlmProviders();
  const { data: servers = [] } = useMcpServers();

  const tabs = [
    { key: "llm" as const, label: "LLM", count: providers.length },
    { key: "mcp" as const, label: "MCP", count: servers.length },
    { key: "permission" as const, label: "系统权限" },
  ];

  function openNew() {
    if (activeTab === "llm") setEditor({ kind: "llm", data: null });
    else if (activeTab === "mcp") setEditor({ kind: "mcp", data: null });
  }

  function editLlm(p: LlmProvider) {
    setEditor({ kind: "llm", data: p });
  }

  function editMcp(s: Record<string, unknown>) {
    setEditor({ kind: "mcp", data: s });
  }

  const newButtonLabel = activeTab === "llm" ? "LLM配置" : activeTab === "mcp" ? "MCP配置" : "";

  return (
    <div className="flex h-full flex-col px-6 pb-4 pt-4">
      {/* Tab bar */}
      <div className="mb-4 flex items-center justify-between">
        <PillTabs<Tab> tabs={tabs} active={activeTab} onChange={(k) => { setActiveTab(k); setEditor(null); }} />

        {activeTab !== "permission" && (
          <button
            onClick={openNew}
            className="flex items-center gap-1 rounded-2xl px-5 py-2 text-sm font-medium text-white shadow-sm transition-opacity hover:opacity-90"
            style={{ backgroundColor: "var(--color-brand-500)" }}
          >
            <span>{newButtonLabel}</span>
            <span className="text-base">+</span>
          </button>
        )}
      </div>

      {/* Content */}
      <div className="min-h-0 flex-1 overflow-auto">
        {activeTab === "llm" && <LlmTable onEdit={editLlm} />}
        {activeTab === "mcp" && <McpTable onEdit={editMcp} />}
        {activeTab === "permission" && <PermissionTable />}
      </div>

      {/* Editor drawer */}
      <SettingsEditorDrawer target={editor} onClose={() => setEditor(null)} />
    </div>
  );
}

export default SettingsPage;
