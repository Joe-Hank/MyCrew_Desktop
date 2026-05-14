import { useState } from "react";
import { useLlmProviders, type LlmProvider } from "../queries/useLlmQuery";
import { useMcpServers } from "../queries/useMcpQuery";
import { useStorageUsage, formatBytes } from "../queries/useStorageQuery";
import { usePrefsStore, type SettingsTab } from "../stores/usePrefsStore";
import PillTabs from "../components/common/PillTabs";
import LlmTable from "../components/settings/LlmTable";
import McpTable from "../components/settings/McpTable";
import PermissionTable from "../components/settings/PermissionTable";
import SettingsEditorDrawer, { type SettingsEditorTarget } from "../components/settings/SettingsEditorDrawer";

type Tab = SettingsTab;

function SettingsPage() {
  const activeTab = usePrefsStore((s) => s.settingsActiveTab);
  const setActiveTab = usePrefsStore((s) => s.setSettingsActiveTab);
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

      {/* Footer: non-system storage usage stats */}
      <StorageFooter />

      {/* Editor drawer */}
      <SettingsEditorDrawer target={editor} onClose={() => setEditor(null)} />
    </div>
  );
}

/** Subtle gray footer showing how much non-system data is on disk —
 *  project rows + tasks + inception history + events log + output files.
 *  System config (LLM keys, MCP setup, etc.) is intentionally excluded
 *  per spec. */
function StorageFooter() {
  const { data, isLoading } = useStorageUsage();
  if (isLoading || !data) {
    return (
      <div
        className="pt-2 text-center"
        style={{ color: "#999", fontSize: "small" }}
      >
        数据占用：计算中…
      </div>
    );
  }
  const b = data.breakdown;
  return (
    <div
      className="pt-2 text-center"
      style={{ color: "#999", fontSize: "small" }}
      title={data.notes}
    >
      数据占用：{formatBytes(data.non_system_total_bytes)}
      {" · "}
      项目 {formatBytes(b.projects_and_tasks.bytes)}
      {" / 立项 "}{formatBytes(b.inception_history.bytes)}
      {" / 日志 "}{formatBytes(b.events_log.bytes)}
      {" / 输出 "}{formatBytes(b.output_files.bytes)}
    </div>
  );
}

export default SettingsPage;
