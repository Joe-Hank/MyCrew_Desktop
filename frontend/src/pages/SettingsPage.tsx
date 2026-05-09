import { useState } from "react";
import { useLlmProviders, type LlmProvider } from "../queries/useLlmQuery";
import { useMcpServers } from "../queries/useMcpQuery";
import { usePermissions } from "../queries/useConfigQuery";
import LlmList from "../components/settings/LlmList";
import McpList from "../components/settings/McpList";
import PermissionMatrix from "../components/settings/PermissionMatrix";
import EditorDrawer, { type SettingsEditorTarget } from "../components/settings/EditorDrawer";
import DefaultLlmSelector from "../components/settings/DefaultLlmSelector";

type Tab = "llm" | "mcp" | "permission";

function SettingsPage() {
  const [activeTab, setActiveTab] = useState<Tab>("llm");
  const [editor, setEditor] = useState<SettingsEditorTarget | null>(null);

  const { data: providers = [] } = useLlmProviders();
  const { data: servers = [] } = useMcpServers();
  const { data: permissions = [] } = usePermissions();

  const tabs: { key: Tab; label: string; count: number }[] = [
    { key: "llm", label: "LLM", count: (providers as unknown[]).length },
    { key: "mcp", label: "MCP", count: (servers as unknown[]).length },
    { key: "permission", label: "系统权限", count: (permissions as unknown[]).length },
  ];

  function handleSelectLlm(id: string) {
    const provider = (providers as LlmProvider[]).find((p) => p.id === id);
    setEditor({ kind: "llm", data: provider ?? null });
  }

  function handleSelectMcp(id: string) {
    const server = (servers as Record<string, unknown>[]).find(
      (s) => (s.id as string) === id
    );
    setEditor({ kind: "mcp", data: server ?? null });
  }

  function handleNew() {
    if (activeTab === "llm") {
      setEditor({ kind: "llm", data: null });
    } else if (activeTab === "mcp") {
      setEditor({ kind: "mcp", data: null });
    }
  }

  return (
    <div className="flex h-full flex-col">
      {/* Tab bar + new button */}
      <div className="flex items-center justify-between border-b border-zinc-200 px-4 dark:border-zinc-800">
        <div className="flex items-center gap-1">
          {tabs.map((tab) => (
            <button
              key={tab.key}
              onClick={() => {
                setActiveTab(tab.key);
                setEditor(null);
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

        {activeTab !== "permission" && (
          <button
            onClick={handleNew}
            className="rounded bg-blue-500 px-3 py-1.5 text-xs font-medium text-white transition-colors hover:bg-blue-600"
          >
            + 新建
          </button>
        )}
      </div>

      {/* Default LLM selectors (only on LLM tab) */}
      {activeTab === "llm" && (
        <DefaultLlmSelector providers={providers as LlmProvider[]} />
      )}

      {/* Content area */}
      <div className="flex flex-1 overflow-hidden">
        <div className={`flex-1 overflow-auto ${editor ? "border-r border-zinc-200 dark:border-zinc-700" : ""}`}>
          {activeTab === "llm" && <LlmList onSelect={handleSelectLlm} />}
          {activeTab === "mcp" && <McpList onSelect={handleSelectMcp} />}
          {activeTab === "permission" && <PermissionMatrix />}
        </div>

        {editor && (
          <div className="w-[320px] shrink-0">
            <EditorDrawer target={editor} onClose={() => setEditor(null)} />
          </div>
        )}
      </div>
    </div>
  );
}

export default SettingsPage;
